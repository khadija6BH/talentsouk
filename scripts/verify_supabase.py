"""Read-only comparison of the live PostgreSQL schema against its snapshot."""
import argparse
import json
import sqlite3
from pathlib import Path

import psycopg
from psycopg import sql
from dotenv import dotenv_values

from backup_before_supabase import digest, quote
from import_supabase import table_digest

ROOT = Path(__file__).resolve().parents[1]


def verify(backup):
    settings = dotenv_values(ROOT / '.env')
    manifest = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
    if digest(backup / 'database.db') != manifest['database_sha256']:
        raise ValueError('Backup checksum mismatch')
    schema = settings.get('DATABASE_SCHEMA', 'talentsouk')
    with psycopg.connect(settings['DATABASE_URL'], connect_timeout=15, sslmode='require',
                         options='-c default_transaction_read_only=on') as target:
        target.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
        target.execute('SET LOCAL extra_float_digits=3')
        with sqlite3.connect((backup / 'database.db').resolve().as_uri() + '?mode=ro', uri=True) as source:
            for table, meta in manifest['tables'].items():
                before = source.execute('SELECT * FROM ' + quote(table)).fetchall()
                after = target.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(table))).fetchall()
                if table_digest(before, meta['columns']) != table_digest(after, meta['columns']):
                    raise ValueError('Data differs from the snapshot in ' + table)
        rls = target.execute("SELECT COUNT(*),COUNT(*) FILTER (WHERE c.relrowsecurity) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relkind='r'", (schema,)).fetchone()
        browser_access = target.execute("SELECT has_schema_privilege('anon',%s,'USAGE'),has_schema_privilege('authenticated',%s,'USAGE')", (schema,schema)).fetchone()
        constraints = target.execute("SELECT COUNT(*) FILTER (WHERE k.convalidated),COUNT(*) FILTER (WHERE NOT k.convalidated) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND k.contype='f'", (schema,)).fetchone()
        assert rls == (len(manifest['tables']), len(manifest['tables']))
        assert browser_access == (False, False)
        assert constraints[1] == len({(r[0],r[3]) for r in manifest['foreign_key_issues']})
    storage = Path(settings.get('STORAGE_ROOT') or ROOT).resolve()
    uploads = [item for item in manifest['files'] if item['path'].startswith('uploads/')]
    for item in uploads:
        if digest(storage / item['path']) != item['sha256']:
            raise ValueError('An upload differs from its snapshot')
    result = {'backend': settings.get('DATABASE_BACKEND'), 'schema': schema,
              'tables': len(manifest['tables']), 'rows': sum(t['rows'] for t in manifest['tables'].values()),
              'all_record_values_match': True, 'uploads_verified': len(uploads),
              'rls_enabled_on_all_tables': True, 'browser_schema_access': False,
              'validated_foreign_keys': constraints[0], 'historical_foreign_keys_pending_validation': constraints[1]}
    (backup / 'final-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup', type=Path, required=True)
    verify(parser.parse_args().backup)
