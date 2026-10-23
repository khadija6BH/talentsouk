"""Back up the offer catalog, archive legacy entries and import recent API rows.

No offers are deleted: existing application references remain intact. Only
items explicitly returned by Jooble for Marrakech with dates in the last 30
days become active. Absence from a partial API page is not called expiration.
"""
import sys,json
from pathlib import Path
from datetime import datetime,timezone
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));load_dotenv(ROOT/'.env',override=True)


def run():
    import psycopg
    from backend.database import get_db_connection,uses_postgres
    from backend.job_sources import fetch_offers
    from backend.offer_lifecycle import recent_offer,activate_offer
    from backend.market_sync import MarketSync,normalized_name
    from backend.opportunity_radar import LocalOfferSync
    from backend.radar_watch import alert_preferences,notify_new_offers
    from backend.offer_cleaning import canonical_url
    assert uses_postgres(),'Refusing to clean a SQLite fallback.'
    rows=[]
    for page in range(1,4):
        values,_=fetch_offers('jooble','ma',location='Marrakech',page=page)
        rows.extend(values)
        if not values:break
    unique={canonical_url(row['url']):row for row in rows if recent_offer(row)}
    rows=list(unique.values())
    if not rows:raise ValueError('No recent API offers returned; original catalog was not changed.')
    backup=ROOT/'backups'/('catalog-before-cleanup-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True,exist_ok=False)
    prefs=alert_preferences()
    conn=get_db_connection()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            # Explicit migration; runtime compatibility layer does not rewrite DDL.
            conn.raw.execute('''CREATE TABLE IF NOT EXISTS offer_catalog_status (
                offer_id BIGINT PRIMARY KEY REFERENCES offers(id),is_active BIGINT NOT NULL DEFAULT 0 CHECK(is_active IN (0,1)),
                verified_at TEXT NOT NULL DEFAULT '',reason TEXT NOT NULL DEFAULT '')''')
            conn.raw.execute('ALTER TABLE offer_catalog_status ENABLE ROW LEVEL SECURITY')
            conn.raw.execute('CREATE INDEX IF NOT EXISTS idx_offer_catalog_active ON offer_catalog_status(is_active,offer_id)')
            tables=['offers','offer_sync_metadata','offer_alerts','companies','opportunity_refreshes']
            for table in tables:
                payload=[dict(r) for r in conn.execute('SELECT * FROM '+table)]
                (backup/(table+'.json')).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
            prior=conn.raw.execute('SELECT * FROM offer_catalog_status').fetchall()
            (backup/'previous_catalog_status.json').write_text(json.dumps(prior,default=str),encoding='utf-8')
            old_ids={r[0] for r in conn.execute('SELECT id FROM offers')}
            conn.execute('''INSERT INTO offer_catalog_status(offer_id,is_active,reason)
                SELECT id,0,'legacy_not_recently_reconfirmed' FROM offers WHERE 1=1
                ON CONFLICT(offer_id) DO UPDATE SET is_active=0,reason='legacy_not_recently_reconfirmed' ''')
            sync=LocalOfferSync(conn); new=[]
            for row in rows:
                matches=sync.company_index.get(('name',normalized_name(row['company_name'])),set())
                if len(matches)>1:raise ValueError('Ambiguous company; nothing was changed.')
                company_id=next(iter(matches),None)
                if company_id is None:company_id=sync.company({'name':row['company_name'],'area':row['location'],'has_offer':1})
                values=dict(row,company_id=company_id)
                offer_id=sync.offer(values)
                conn.execute("INSERT INTO offer_sync_metadata(offer_id,adapter) VALUES(?,'jooble') ON CONFLICT(offer_id) DO UPDATE SET last_checked=CURRENT_TIMESTAMP,adapter='jooble'",(offer_id,))
                activate_offer(conn,offer_id)
                if offer_id not in old_ids:new.append(dict(values,id=offer_id));old_ids.add(offer_id)
            notify_new_offers(conn,new,prefs)
            conn.execute('UPDATE companies SET has_offer=CASE WHEN id IN (SELECT company_id FROM offers WHERE id IN (SELECT offer_id FROM offer_catalog_status WHERE is_active=1)) THEN 1 ELSE 0 END')
            conn.execute("INSERT INTO opportunity_refreshes(created_count,updated_count,provider,country) VALUES(?,?,'jooble','ma')",(sync.created['offers'],sync.updated['offers']))
            active=conn.execute('SELECT COUNT(*) FROM offer_catalog_status WHERE is_active=1').fetchone()[0]
            archived=conn.execute('SELECT COUNT(*) FROM offer_catalog_status WHERE is_active=0').fetchone()[0]
            notifications=conn.execute("SELECT COUNT(*) FROM notifications WHERE kind='opportunity'").fetchone()[0]
        result={'backend':'PostgreSQL','active_recent_marrakech':active,'archived_preserved':archived,
                'fresh_api_rows':len(rows),'newly_inserted':sync.created['offers'],
                'notification_count_after':notifications,'backup':str(backup.resolve()),'offers_deleted':0}
        (backup/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
    finally:conn.close()


if __name__=='__main__':run()
