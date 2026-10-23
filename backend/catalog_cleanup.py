"""Explicit, backed-up cleanup of non-Moroccan catalog records."""
from datetime import datetime
import sqlite3
from pathlib import Path
from backend.company_catalog import in_morocco

def clean_catalog(conn):
    conn.row_factory=sqlite3.Row
    previous_issues=set(map(tuple,conn.execute('PRAGMA foreign_key_check')))
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('CREATE TEMP TABLE removed_companies(id INTEGER PRIMARY KEY)')
        companies=[dict(r) for r in conn.execute('SELECT * FROM companies')]
        ids=[c['id'] for c in companies if not in_morocco(c)]
        conn.executemany('INSERT INTO removed_companies VALUES(?)',[(i,) for i in ids])
        conn.execute('CREATE TEMP TABLE removed_offers(id INTEGER PRIMARY KEY)')
        offers=[dict(r) for r in conn.execute('SELECT * FROM offers')]
        offer_ids=[o['id'] for o in offers if o.get('company_id') in set(ids) or not in_morocco({'area':o.get('location')})]
        conn.executemany('INSERT INTO removed_offers VALUES(?)',[(i,) for i in offer_ids])
        # Personal history remains available, with obsolete catalog links detached.
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('applications','interview_sessions','interview_schedules','network_contacts','proof_projects'):
            if table not in tables:continue
            columns={r[1]:r for r in conn.execute('PRAGMA table_info('+table+')')}
            for column,temp in (('company_id','removed_companies'),('offer_id','removed_offers'),('job_id','removed_offers')):
                if column not in columns:continue
                value=0 if columns[column][3] else None
                conn.execute('UPDATE '+table+' SET '+column+'=? WHERE '+column+' IN (SELECT id FROM '+temp+')',(value,))
        conn.execute('DELETE FROM offer_sync_metadata WHERE offer_id IN (SELECT id FROM removed_offers)')
        conn.execute('DELETE FROM offer_alerts WHERE offer_id IN (SELECT id FROM removed_offers)')
        # Notifications pointing to removed offers must not offer broken links.
        conn.execute("DELETE FROM notifications WHERE url IN (SELECT '/opportunities/'||id FROM removed_offers)")
        conn.execute('DELETE FROM offers WHERE id IN (SELECT id FROM removed_offers)')
        conn.execute('DELETE FROM companies WHERE id IN (SELECT id FROM removed_companies)')
        conn.execute('UPDATE companies SET has_offer=EXISTS(SELECT 1 FROM offers WHERE offers.company_id=companies.id)')
        if set(map(tuple,conn.execute('PRAGMA foreign_key_check')))-previous_issues:raise ValueError('Catalog cleanup failed integrity check')
        conn.execute('DROP TABLE removed_offers');conn.execute('DROP TABLE removed_companies')
    return dict(companies=len(ids),offers=len(offer_ids))

def backup_and_clean(db_path):
    db_path=Path(db_path)
    backup=db_path.parent/'backups'/('before-morocco-cleanup-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.db')
    backup.parent.mkdir(exist_ok=True)
    conn=sqlite3.connect(db_path);conn.execute('PRAGMA foreign_keys=ON')
    try:
        with sqlite3.connect(backup) as target:conn.backup(target)
        return clean_catalog(conn),backup
    finally:conn.close()
