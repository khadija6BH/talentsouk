"""Final guarded cutover: freeze SQLite, verify snapshot, import, select backend.

Stop Flask/background workers before running. No source data is deleted. An
existing talentsouk cloud schema is never overwritten. Keep a fresh backup.
"""
import argparse
import json
import os
import sqlite3
from pathlib import Path

from dotenv import dotenv_values, set_key

from backup_before_supabase import digest, quote
from import_supabase import migrate, table_digest

ROOT = Path(__file__).resolve().parents[1]


def cutover(backup):
    settings = dotenv_values(ROOT / '.env')
    storage = Path(os.environ.get('STORAGE_ROOT') or settings.get('STORAGE_ROOT') or ROOT).resolve()
    manifest = json.loads((backup / 'manifest.json').read_text(encoding='utf-8'))
    with sqlite3.connect(storage / 'database.db', timeout=15) as live:
        # Any SQLite writer must finish before this lock is acquired. None can
        # change the database while it is compared/imported and the backend flips.
        live.execute('BEGIN EXCLUSIVE')
        try:
            with sqlite3.connect((backup / 'database.db').resolve().as_uri() + '?mode=ro', uri=True) as snapshot:
                for table, meta in manifest['tables'].items():
                    original = live.execute('SELECT * FROM ' + quote(table)).fetchall()
                    saved = snapshot.execute('SELECT * FROM ' + quote(table)).fetchall()
                    if table_digest(original, meta['columns']) != table_digest(saved, meta['columns']):
                        raise ValueError('SQLite changed since backup; take a fresh backup before cutover.')
            saved_uploads = {item['path']: item for item in manifest['files'] if item['path'].startswith('uploads/')}
            current = {path.relative_to(storage).as_posix() for path in (storage / 'uploads').rglob('*') if path.is_file()}
            if current != set(saved_uploads):
                raise ValueError('Uploads changed since backup; take a fresh backup.')
            for name, meta in saved_uploads.items():
                if digest(storage / name) != meta['sha256']:
                    raise ValueError('An upload changed since backup; take a fresh backup.')
            migrate(backup, apply=True, schema='talentsouk')
            set_key(str(ROOT / '.env'), 'DATABASE_SCHEMA', 'talentsouk')
            set_key(str(ROOT / '.env'), 'DATABASE_BACKEND', 'postgres')
            result = {'backend': 'postgres', 'schema': 'talentsouk', 'source_preserved': True,
                      'backup': str(backup.resolve()), 'restart_required': True}
            (backup / 'cutover.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result))
        finally:
            live.rollback()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--backup', required=True, type=Path)
    cutover(parser.parse_args().backup)
