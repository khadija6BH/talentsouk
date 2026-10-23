"""Import a verified snapshot into a fresh private schema, atomically.

Default is rollback-only. Existing orphan references are preserved and reported;
only the corresponding foreign keys are added NOT VALID for historical rows.
New writes still enforce those foreign keys. No existing cloud schema is dropped.
"""
import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql
from dotenv import dotenv_values

from backup_before_supabase import digest, quote

ROOT = Path(__file__).resolve().parents[1]


def canonical(values, columns):
    output = []
    for value, column in zip(values, columns):
        if value is not None and column[2].upper() == 'TIMESTAMP':
            if isinstance(value, str):
                value = datetime.fromisoformat(value)
            value = value.isoformat(sep=' ')
        if isinstance(value, (bytes, memoryview)):
            value = {'bytes_hex': bytes(value).hex()}
        output.append(value)
    return json.dumps(output, ensure_ascii=False, separators=(',', ':'))


def table_digest(rows, columns):
    records = sorted(canonical(row, columns) for row in rows)
    return hashlib.sha256('\n'.join(records).encode('utf-8')).hexdigest()


def migrate(backup, apply=False, schema='talentsouk'):
    if not re.fullmatch(r'talentsouk(?:_[a-z0-9_]+)?', schema):
        raise ValueError('Use an isolated talentsouk schema name')
    manifest = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
    prepared = backup / 'postgres-preparation'
    readiness = json.loads((prepared / 'readiness.json').read_text(encoding='utf-8'))
    if manifest['status'] != 'verified' or digest(backup / 'database.db') != manifest['database_sha256']:
        raise ValueError('Snapshot verification failed')
    url = dotenv_values(ROOT / '.env').get('DATABASE_URL')
    if not url:
        raise ValueError('DATABASE_URL is missing')
    # DDL preparation uses semicolons inside PL/pgSQL functions. Use the SQL lexer.
    from sqlparse import split, format as sql_format
    ddl = (prepared / 'schema.postgres.sql').read_text(encoding='utf-8')
    ddl = re.sub(r'\btalentsouk\b', schema, ddl)
    foreign_sql = {item['sql'] for item in readiness['foreign_keys']}
    deferred = []
    known_broken = {(row[0], row[3]) for row in manifest['foreign_key_issues']}
    counts = {}
    with sqlite3.connect((backup / 'database.db').resolve().as_uri() + '?mode=ro', uri=True) as source:
        with psycopg.connect(url, connect_timeout=15, sslmode='require', autocommit=True, prepare_threshold=None) as target:
            target.execute('BEGIN')
            try:
                target.execute("SET LOCAL statement_timeout='120s'")
                target.execute('SET LOCAL extra_float_digits=3')
                for statement in split(ddl):
                    statement = sql_format(statement, strip_comments=True).strip()
                    if statement in {'BEGIN;', 'COMMIT;'}:
                        continue
                    if statement in foreign_sql or statement.startswith('CREATE FUNCTION ') or statement.startswith('CREATE TRIGGER '):
                        deferred.append(statement)
                    else:
                        target.execute(statement)
                sequences = dict(source.execute('SELECT name,seq FROM sqlite_sequence'))
                for table, meta in manifest['tables'].items():
                    columns = meta['columns']
                    names = [col[1] for col in columns]
                    records = source.execute('SELECT * FROM ' + quote(table)).fetchall()
                    copy_query = sql.SQL('COPY {} ({}) FROM STDIN').format(sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, names)))
                    with target.cursor().copy(copy_query) as copy:
                        for record in records:
                            copy.write_row(record)
                    actual = target.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(table))).fetchall()
                    if len(actual) != meta['rows'] or table_digest(actual, columns) != table_digest(records, columns):
                        by_id = {r[0]: r for r in actual}
                        differences = set()
                        for record in records:
                            other = by_id.get(record[0])
                            if other is not None:
                                for idx, (left, right) in enumerate(zip(record, other)):
                                    if canonical([left], [columns[idx]]) != canonical([right], [columns[idx]]):
                                        differences.add((names[idx], type(left).__name__, type(right).__name__))
                        print(json.dumps({'comparison_differences': sorted(differences)}))
                        raise ValueError('Record comparison failed for ' + table)
                    counts[table] = len(actual)
                    for column in readiness['identities'][table]:
                        maximum = max([r[names.index(column)] for r in records if r[names.index(column)] is not None] + [0, sequences.get(table, 0)])
                        sequence = target.execute('SELECT pg_get_serial_sequence(%s,%s)', (table, column)).fetchone()[0]
                        target.execute('SELECT setval(%s::regclass,%s,%s)', (sequence, max(1, maximum), maximum > 0))
                for statement in deferred:
                    match = next((item for item in readiness['foreign_keys'] if item['sql'] == statement), None)
                    if match and (match['table'], int(match['name'].rsplit('_', 1)[1])) in known_broken:
                        statement = statement.rstrip(';') + ' NOT VALID;'
                    target.execute(statement)
                invalid = target.execute("SELECT c.relname,k.conname FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND NOT k.convalidated ORDER BY 1,2", (schema,)).fetchall()
                if len(invalid) != len(known_broken):
                    raise ValueError('Unexpected unvalidated relationships')
                # Snapshot rows are untouched, including the three historical orphans.
                result = {'mode': 'applied' if apply else 'dry_run_rolled_back', 'schema': schema, 'tables': len(counts),
                          'rows': sum(counts.values()), 'per_table': counts, 'record_comparison': 'all_values_match',
                          'historical_orphan_rows': manifest['foreign_key_issues'], 'unvalidated_constraints': invalid}
                target.execute('COMMIT' if apply else 'ROLLBACK')
            except Exception:
                target.execute('ROLLBACK')
                raise
    report = prepared / (schema + ('-import-verified.json' if apply else '-dry-run-verified.json'))
    report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'per_table'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--schema', default='talentsouk')
    args = parser.parse_args()
    try:
        migrate(args.backup, args.apply, args.schema)
    except psycopg.Error as error:
        # Connection errors may contain credentials: only SQLSTATE/category is safe.
        print(json.dumps({'ok': False, 'error_type': type(error).__name__, 'sqlstate': error.sqlstate,
                          'schema_change': 'rolled_back_or_not_started'}))
        raise SystemExit(1)
