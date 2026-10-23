"""Read-only SQLite snapshot plus verified uploads/config backup. No cloud writes."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def backup(destination):
    settings = dotenv_values(ROOT / '.env')
    storage = Path(os.environ.get('STORAGE_ROOT') or settings.get('STORAGE_ROOT') or ROOT).resolve()
    source_path = storage / 'database.db'
    if not source_path.is_file():
        raise FileNotFoundError('SQLite database not found; no empty database will be created.')
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'storage_root': str(storage), 'status': 'in_progress', 'files': [], 'tables': {}}
    manifest_path = destination / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    try:
        with sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True) as source:
            with sqlite3.connect(destination / 'database.db') as target:
                source.backup(target)
        with sqlite3.connect((destination / 'database.db').as_uri() + '?mode=ro', uri=True) as db:
            integrity = [row[0] for row in db.execute('PRAGMA integrity_check')]
            if integrity != ['ok']:
                raise RuntimeError('Backup integrity check failed')
            manifest['integrity_check'] = integrity
            manifest['foreign_key_issues'] = db.execute('PRAGMA foreign_key_check').fetchall()
            schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name").fetchall()
            (destination / 'schema.sql').write_text('\n\n'.join(row[3] + ';' for row in schema), encoding='utf-8')
            for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                manifest['tables'][name] = {
                    'rows': db.execute('SELECT COUNT(*) FROM ' + quote(name)).fetchone()[0],
                    'columns': db.execute('PRAGMA table_info(' + quote(name) + ')').fetchall(),
                    'foreign_keys': db.execute('PRAGMA foreign_key_list(' + quote(name) + ')').fetchall(),
                    'indexes': db.execute('PRAGMA index_list(' + quote(name) + ')').fetchall(),
                }
        uploads = storage / 'uploads'
        manifest['uploads_directory_present'] = uploads.is_dir()
        paths = list(uploads.rglob('*')) if uploads.is_dir() else []
        pairs = [(path, destination / 'uploads' / path.relative_to(uploads)) for path in paths if path.is_file()]
        for name in ('.env', '.env.example', 'requirements.txt', 'requirements-dev.txt'):
            if (ROOT / name).is_file():
                pairs.append((ROOT / name, destination / 'config' / name))
        for source, target in pairs:
            before = digest(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            after = digest(source)
            if before != after or digest(target) != before:
                raise RuntimeError('A file changed during backup; retry while the app is stopped.')
            manifest['files'].append({'path': target.relative_to(destination).as_posix(), 'bytes': target.stat().st_size, 'sha256': before})
        # Recheck the upload inventory so concurrent additions/deletions are detected.
        if {p.relative_to(uploads) for p in paths if p.is_file()} != {p.relative_to(uploads) for p in uploads.rglob('*') if p.is_file()}:
            raise RuntimeError('Upload inventory changed during backup; retry while the app is stopped.')
        manifest['database_sha256'] = digest(destination / 'database.db')
        manifest['status'] = 'verified'
        manifest['consistency_note'] = 'SQLite is a consistent snapshot. Stop app writes for the final database/files cutover snapshot.'
    except Exception:
        manifest['status'] = 'failed'
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'backup': str(destination), 'status': manifest['status'],
                      'tables': len(manifest['tables']), 'rows': sum(t['rows'] for t in manifest['tables'].values()),
                      'uploads': sum(f['path'].startswith('uploads/') for f in manifest['files']),
                      'foreign_key_issues': len(manifest['foreign_key_issues'])}))
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, default=ROOT.parents[1] / 'migration_backups' / ('before-supabase-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')))
    backup(parser.parse_args().destination)
