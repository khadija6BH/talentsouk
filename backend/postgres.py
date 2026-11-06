"""PostgreSQL storage with the row/transaction contract used by existing services.

Only the application's known SQLite syntax is adapted. Unknown schema DDL fails
explicitly: production tables must be created by the reviewed migration first.
"""
import re
import os
import atexit
import sqlite3
import weakref
from threading import Lock
from datetime import date, datetime

import psycopg
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool, NullConnectionPool, PoolTimeout
import sqlparse

UTC_TEXT = "to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"
POOLS = {}
POOL_LOCK = Lock()


def release(pool, raw):
    try:
        if not raw.closed and raw.info.transaction_status != TransactionStatus.IDLE:
            raw.rollback()
    finally:
        pool.putconn(raw)


class Row:
    def __init__(self, names, values):
        self.names = names
        self.values = tuple(v.isoformat(sep=' ') if isinstance(v, datetime)
                            else v.isoformat() if isinstance(v, date) else v for v in values)

    def keys(self):
        return self.names

    def __getitem__(self, key):
        return self.values[self.names.index(key)] if isinstance(key, str) else self.values[key]

    def __iter__(self):
        return iter(self.values)

    def __len__(self):
        return len(self.values)


class Result:
    def __init__(self, rows=(), names=(), rowcount=-1, lastrowid=None):
        self.rows = iter(Row(tuple(names), row) for row in rows)
        self.description = [(name, None, None, None, None, None, None) for name in names]
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self):
        return next(self.rows, None)

    def fetchall(self):
        return list(self.rows)

    def __iter__(self):
        return self.rows


def parameters(query):
    """Translate positional markers while leaving quoted question marks alone."""
    output, quoted, i = [], None, 0
    while i < len(query):
        char = query[i]
        if quoted:
            output.append(char)
            if char == quoted:
                if i + 1 < len(query) and query[i + 1] == quoted:
                    output.append(query[i + 1]); i += 1
                else:
                    quoted = None
        elif char in "'\"":
            quoted = char; output.append(char)
        elif char == '?':
            output.append('%s')
        else:
            output.append(char)
        i += 1
    # psycopg parses percent signs even in literals when parameters are supplied.
    return ''.join(output).replace('%', '%%').replace('%%s', '%s')


def dialect(query, timestamp_expression=UTC_TEXT):
    query = re.sub(r'\b([\w.]+)\s+COLLATE\s+NOCASE\b', r'LOWER(\1)', query, flags=re.I)
    query = re.sub(r'\bLIKE\b', 'ILIKE', query, flags=re.I)
    # SQLite date() returns NULL for empty values; keep text keys for calendars.
    query = re.sub(r'\bdate\(\s*([\w.]+)\s*\)', r"NULLIF(SUBSTR(CAST(\1 AS TEXT),1,10),'')", query, flags=re.I)
    query = re.sub(r"datetime\(\s*'now'\s*,\s*'([+-]?\d+)\s+(hour|minute|day)s?'\s*\)",
                   lambda m: "to_char((CURRENT_TIMESTAMP AT TIME ZONE 'UTC') + INTERVAL '" + m[1] + ' ' + m[2] + "', 'YYYY-MM-DD HH24:MI:SS')", query, flags=re.I)
    query = re.sub(r"datetime\(\s*\?\s*,\s*'unixepoch'\s*,\s*'(-?\d+) days?'\s*\)",
                   lambda m: "to_char((to_timestamp(?) AT TIME ZONE 'UTC') + INTERVAL '" + m[1] + " days', 'YYYY-MM-DD HH24:MI:SS')", query, flags=re.I)
    query = re.sub(r'\bCURRENT_TIMESTAMP\b(?!\s+AT TIME)', timestamp_expression, query, flags=re.I)
    query = re.sub(r'\bsqlite_master\b', "(SELECT tablename AS name,'table' AS type,NULL::text AS sql FROM pg_tables WHERE schemaname=current_schema()) AS sqlite_master", query, flags=re.I)
    return query


class Connection:
    def __init__(self, url, schema='talentsouk'):
        if not re.fullmatch(r'[a-z_][a-z0-9_]*', schema):
            raise ValueError('Invalid PostgreSQL schema')
        key = (os.getpid(), url, schema)
        try:
            with POOL_LOCK:
                if key not in POOLS:
                    def configure(raw):
                        raw.execute('SET search_path TO ' + schema)
                        raw.execute("SET TIME ZONE 'UTC'")
                        raw.execute('SET extra_float_digits=3')
                        raw.execute("SET statement_timeout='30s'")
                    # Frozen serverless instances must not pin idle Supabase
                    # session-pooler slots (the free pool is shared by instances).
                    serverless = os.environ.get('VERCEL') == '1'
                    pool_type = NullConnectionPool if serverless else ConnectionPool
                    pool = pool_type(url, kwargs={'sslmode': 'require', 'connect_timeout': 15,
                        'autocommit': True, 'prepare_threshold': None}, min_size=0, max_size=2 if serverless else 5,
                        timeout=20, configure=configure, open=True)
                    atexit.register(pool.close)
                    POOLS[key] = (pool, {})
                self.pool, self.metadata = POOLS[key]
            self.raw = self.pool.getconn()
            self.finalizer = weakref.finalize(self, release, self.pool, self.raw)
        except (psycopg.Error, PoolTimeout):
            raise RuntimeError('PostgreSQL connection failed. Check the private server DATABASE_URL.') from None

    @property
    def in_transaction(self):
        return self.raw.info.transaction_status != TransactionStatus.IDLE

    def table_info(self, table):
        if table not in self.metadata:
            cursor = self.raw.execute("""
                SELECT a.attnum-1 AS cid,a.attname AS name,
                    CASE a.atttypid::regtype::text WHEN 'bigint' THEN 'INTEGER'
                         WHEN 'double precision' THEN 'REAL' WHEN 'timestamp without time zone' THEN 'TIMESTAMP'
                         ELSE upper(a.atttypid::regtype::text) END AS type,
                    a.attnotnull::int AS notnull,pg_get_expr(d.adbin,d.adrelid) AS dflt_value,
                    COALESCE((SELECT k.ord::int FROM pg_constraint p,
                        unnest(p.conkey) WITH ORDINALITY AS k(num,ord)
                        WHERE p.conrelid=a.attrelid AND p.contype='p' AND k.num=a.attnum),0) AS pk
                FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                JOIN pg_namespace n ON n.oid=c.relnamespace
                LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
                WHERE n.nspname=current_schema() AND c.relname=%s AND a.attnum>0 AND NOT a.attisdropped
                ORDER BY a.attnum
            """, (table,))
            self.metadata[table] = cursor.fetchall()
        return self.metadata[table]

    def execute(self, query, params=()):
        if not self.finalizer.alive:
            raise sqlite3.ProgrammingError('Cannot operate on a closed connection.')
        query = query.strip().rstrip(';')
        pragma = re.fullmatch(r'PRAGMA\s+(\w+)\s*(?:\(\s*["\']?(\w+)["\']?\s*\)|=.*)?', query, re.I)
        if pragma:
            kind, table = pragma[1].lower(), pragma[2]
            if kind == 'foreign_keys':
                return Result()
            if kind == 'table_info':
                return Result(self.table_info(table), ('cid', 'name', 'type', 'notnull', 'dflt_value', 'pk'))
            if kind == 'foreign_key_list':
                cursor = self.raw.execute("""SELECT k.oid::bigint, x.ord-1, parent.relname, ca.attname, pa.attname,
                    'NO ACTION','NO ACTION','NONE'
                    FROM pg_constraint k JOIN pg_class child ON child.oid=k.conrelid
                    JOIN pg_namespace n ON n.oid=child.relnamespace
                    JOIN pg_class parent ON parent.oid=k.confrelid
                    CROSS JOIN LATERAL unnest(k.conkey,k.confkey) WITH ORDINALITY AS x(c,p,ord)
                    JOIN pg_attribute ca ON ca.attrelid=child.oid AND ca.attnum=x.c
                    JOIN pg_attribute pa ON pa.attrelid=parent.oid AND pa.attnum=x.p
                    WHERE k.contype='f' AND n.nspname=current_schema() AND child.relname=%s""", (table,))
                return Result(cursor.fetchall(), ('id','seq','table','from','to','on_update','on_delete','match'))
            raise NotImplementedError('Unsupported PostgreSQL schema inspection: ' + kind)
        if re.fullmatch(r'BEGIN(?: IMMEDIATE)?', query, re.I):
            if not self.in_transaction:
                self.raw.execute('BEGIN')
            if query.upper().endswith('IMMEDIATE'):
                # Preserve serialization for verification counters and watcher
                # leases. The lock is released by commit/rollback, never kept
                # on a pooled session after the transaction ends.
                self.raw.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema()),hashtext('immediate'))")
            return Result()
        create = re.match(r'CREATE TABLE IF NOT EXISTS\s+["\']?(\w+)', query, re.I)
        if create:
            if self.table_info(create[1]):
                return Result()
            raise RuntimeError('Missing PostgreSQL table ' + create[1] + '; apply a reviewed schema migration first.')
        if re.match(r'CREATE TRIGGER IF NOT EXISTS\s+queue_notification_mail\b', query, re.I):
            exists = self.raw.execute("SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND t.tgname='queue_notification_mail'").fetchone()
            if exists:
                return Result()
            raise RuntimeError('Notification trigger is missing; run the schema migration.')
        if re.match(r'(CREATE|ALTER|DROP)\s+(TABLE|TRIGGER)', query, re.I):
            raise RuntimeError('Run schema migrations explicitly before changing PostgreSQL tables.')
        write_table = re.match(r'(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE)\s+["\']?(\w+)', query, re.I)
        timestamp_expression = UTC_TEXT
        if write_table and any(col[2] == 'TIMESTAMP' for col in self.table_info(write_table[1])):
            timestamp_expression = "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')"
        query = dialect(query, timestamp_expression)
        inserted = re.match(r'INSERT(?:\s+OR\s+(IGNORE|REPLACE))?\s+INTO\s+["\']?(\w+)', query, re.I)
        identity = None
        if inserted:
            mode, table = inserted.groups()
            query = re.sub(r'^INSERT\s+OR\s+(IGNORE|REPLACE)', 'INSERT', query, flags=re.I)
            info = self.table_info(table)
            pks = [col[1] for col in info if col[5]]
            if mode and mode.upper() == 'IGNORE':
                query += ' ON CONFLICT DO NOTHING'
            elif mode and mode.upper() == 'REPLACE':
                if not pks:
                    raise ValueError('Replacement needs an explicit conflict key')
                fields = [col[1] for col in info if col[1] not in pks]
                query += ' ON CONFLICT (' + ','.join(pks) + ') DO UPDATE SET ' + ','.join(f'{c}=EXCLUDED.{c}' for c in fields)
            if len(pks) == 1 and not re.search(r'\bRETURNING\b', query, re.I):
                identity = pks[0]
                query += ' RETURNING "' + identity + '"'
        if re.match(r'(INSERT|UPDATE|DELETE|CREATE)\b', query, re.I) and not self.in_transaction:
            self.raw.execute('BEGIN')
        try:
            cursor = self.raw.execute(parameters(query) if params else query, tuple(params) if params else None)
        except psycopg.IntegrityError:
            raise sqlite3.IntegrityError('PostgreSQL rejected a duplicate value or invalid relationship.') from None
        names = tuple(col.name for col in cursor.description) if cursor.description else ()
        rows = cursor.fetchall() if cursor.description else []
        lastrowid = rows[-1][0] if identity and rows else None
        return Result(() if identity else rows, () if identity else names, cursor.rowcount, lastrowid)

    def executescript(self, script):
        for query in sqlparse.split(script):
            self.execute(query)
        return Result()

    def executemany(self, query, parameters_list):
        total = 0
        for params in parameters_list:
            total += max(0,self.execute(query,params).rowcount)
        return Result(rowcount=total)

    def commit(self):
        if self.in_transaction:
            self.raw.execute('COMMIT')

    def rollback(self):
        if self.in_transaction:
            self.raw.execute('ROLLBACK')

    def close(self):
        self.finalizer()

    def __enter__(self):
        if not self.in_transaction:
            self.raw.execute('BEGIN')
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.rollback() if exc_type else self.commit()
