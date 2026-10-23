"""Read-only Supabase connectivity check. Never prints credentials or raw errors."""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def check():
    # Read the file directly so a stale process environment cannot mask an edit.
    url = dotenv_values(ROOT / '.env').get('DATABASE_URL', '')
    if not url:
        return {'ok': False, 'reason': 'DATABASE_URL is missing in .env'}
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {'postgres', 'postgresql'} or not parsed.hostname or not parsed.username or not parsed.password:
            return {'ok': False, 'reason': 'Incomplete PostgreSQL URI'}
        if parsed.fragment or any(char in parsed.password for char in '@/[]'):
            return {'ok': False, 'reason': 'Password contains unencoded reserved URI characters. Copy the Connect URI and percent-encode the password.'}
        if '[YOUR-PASSWORD]' in url:
            return {'ok': False, 'reason': 'Replace the password placeholder with the database password'}
        # Access port here so malformed values are rejected without printing them.
        parsed.port
    except ValueError:
        return {'ok': False, 'reason': 'Malformed DATABASE_URL; copy it again from the project Connect panel'}
    try:
        with psycopg.connect(url, connect_timeout=15, sslmode='require',
                             options='-c default_transaction_read_only=on -c statement_timeout=15000') as db:
            tls = db.execute('SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()').fetchone()[0]
            schema_exists = db.execute("SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name='talentsouk')").fetchone()[0]
            table_count = db.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'").fetchone()[0]
            return {'ok': True, 'ssl': tls, 'app_schema_exists': schema_exists, 'public_table_count': table_count,
                    'mode': 'read_only; no schema or records changed'}
    except psycopg.Error as error:
        detail = str(error).lower()  # Inspect locally; never log or return raw errors.
        if 'password authentication failed' in detail or error.sqlstate == '28P01':
            reason = 'Authentication refused. Verify the project database password and exact pooler username; an API key cannot replace the database password.'
        elif 'tenant or user not found' in detail:
            reason = 'Pooler project or username not found. Copy the exact Session pooler URI from Connect.'
        elif 'timeout' in detail or 'timed out' in detail:
            reason = 'Network timeout. Check project availability and network access.'
        elif 'resolve' in detail or 'getaddrinfo' in detail:
            reason = 'Database hostname could not be resolved. Check network access and the copied hostname.'
        else:
            reason = 'Connection failed. Review the project Connect settings and database availability.'
        return {'ok': False, 'reason': reason}


if __name__ == '__main__':
    result = check()
    print(json.dumps(result, ensure_ascii=True))
    sys.exit(0 if result['ok'] else 1)
