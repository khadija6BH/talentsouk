"""Local CSV adapter and transactional opportunity refresh."""
import csv
from urllib.parse import urlparse
from backend.database import get_db_connection
from backend.market_sync import MarketSync, normalized_name


class LocalOfferSync(MarketSync):
    @staticmethod
    def offer_keys(row):
        # A source URL identifies an individual announcement. Distinct links
        # may legitimately repeat the same job title, company and date.
        keys = MarketSync.offer_keys(row)
        url_keys = [key for key in keys if key[0] == 'url']
        return url_keys or keys


def ensure_radar_schema(conn):
    from backend.offer_lifecycle import ensure_catalog_schema
    ensure_catalog_schema(conn)
    from backend.radar_watch import ensure_watch_schema
    ensure_watch_schema(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS offer_sync_metadata (offer_id INTEGER PRIMARY KEY REFERENCES offers(id), first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, last_checked TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, adapter TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS opportunity_refreshes (id INTEGER PRIMARY KEY, checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, created_count INTEGER NOT NULL, updated_count INTEGER NOT NULL)")
    columns={row[1] for row in conn.execute('PRAGMA table_info(opportunity_refreshes)')}
    for name,default in [('provider','local_csv'),('country','')]:
        if name not in columns:
            conn.execute("ALTER TABLE opportunity_refreshes ADD COLUMN "+name+" TEXT NOT NULL DEFAULT '"+default+"'")


def refresh_external_offers(provider,country,keyword='',location=''):
    from backend.job_sources import fetch_offers, JobSourceError
    # Network work precedes the write transaction.
    rows,skipped=fetch_offers(provider,country,keyword,location or 'Marrakech')
    from backend.offer_lifecycle import recent_offer,activate_offer,expire_offers,ensure_catalog_schema
    domestic=[row for row in rows if recent_offer(row)]
    skipped+=len(rows)-len(domestic)
    rows=domestic
    from backend.radar_watch import alert_preferences,notify_new_offers
    preferences=alert_preferences()
    conn=get_db_connection()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            ensure_catalog_schema(conn)
            expire_offers(conn)
            sync=LocalOfferSync(conn)
            existing_ids={r[0] for r in conn.execute('SELECT id FROM offers')}
            new_offers=[]
            for row in rows:
                matches=sync.company_index.get(('name',normalized_name(row['company_name'])),set())
                if len(matches)>1: raise JobSourceError('A company has ambiguous duplicates. No offers were changed.')
                company_id=next(iter(matches),None)
                if company_id is None:
                    company_id=sync.company({'name':row['company_name'],'area':row['location'],'has_offer':1})
                values=dict(row,company_id=company_id)
                offer_id=sync.offer(values)
                if offer_id not in existing_ids:
                    new_offers.append(dict(values,id=offer_id));existing_ids.add(offer_id)
                conn.execute("INSERT INTO offer_sync_metadata(offer_id,adapter) VALUES(?,?) ON CONFLICT(offer_id) DO UPDATE SET last_checked=CURRENT_TIMESTAMP,adapter=excluded.adapter",(offer_id,provider))
                activate_offer(conn,offer_id)
                conn.execute('UPDATE companies SET has_offer=1 WHERE id=?',(company_id,))
            notify_new_offers(conn,new_offers,preferences)
            result={'created':sync.created['offers'],'updated':sync.updated['offers'],'skipped':skipped}
            conn.execute('INSERT INTO opportunity_refreshes(created_count,updated_count,provider,country) VALUES(?,?,?,?)',(result['created'],result['updated'],provider,country))
        return result
    finally:
        conn.close()


def refresh_local_offers(path):
    with open(path, encoding='utf-8-sig', newline='') as file:
        reader = csv.DictReader(file)
        required = {'poste', 'entreprise', 'source', 'url', 'localisation', 'type_contrat', 'date_publication', 'description'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('The local offers file has missing columns. No offers were changed.')
        rows = list(reader)
    if not rows:
        raise ValueError('The local offers file is empty. No offers were changed.')
    conn = get_db_connection()
    try:
        with conn:
            ensure_radar_schema(conn)
            conn.execute('BEGIN IMMEDIATE')
            sync = LocalOfferSync(conn)
            for row in rows:
                title = (row['poste'] or '').strip()
                company = (row['entreprise'] or '').strip()
                if not title or not company:
                    raise ValueError('An offer is missing its title or company. No offers were changed.')
                from backend.company_catalog import in_morocco
                if not in_morocco({'area':row.get('localisation')}):
                    continue
                matches = sync.company_index.get(('name', normalized_name(company)), set())
                if len(matches) > 1:
                    raise ValueError('A company has ambiguous duplicates. No offers were changed.')
                company_id = next(iter(matches), None)
                offer_id = sync.offer({'company_id': company_id, 'company_name': company, 'title': title,
                    'source': (row['source'] or '').strip(), 'url': (row['url'] or '').strip(),
                    'location': (row['localisation'] or '').strip(), 'offer_type': (row['type_contrat'] or '').strip(),
                    'publication_date': (row['date_publication'] or '').strip(), 'description': (row['description'] or '').strip()})
                conn.execute("INSERT INTO offer_sync_metadata(offer_id,adapter) VALUES(?, 'local_csv') ON CONFLICT(offer_id) DO UPDATE SET last_checked=CURRENT_TIMESTAMP,adapter=excluded.adapter", (offer_id,))
                if company_id:
                    conn.execute('UPDATE companies SET has_offer=1 WHERE id=?', (company_id,))
            result = {'created': sync.created['offers'], 'updated': sync.updated['offers']}
            conn.execute('INSERT INTO opportunity_refreshes(created_count,updated_count) VALUES(?,?)', (result['created'], result['updated']))
        return result
    finally:
        conn.close()


def radar_data():
    conn = get_db_connection()
    try:
        offers = [dict(row) for row in conn.execute("SELECT o.*, m.first_seen,m.last_checked FROM offers o LEFT JOIN offer_sync_metadata m ON m.offer_id=o.id WHERE o.id IN (SELECT offer_id FROM offer_catalog_status WHERE is_active=1 AND verified_at>=datetime('now','-7 days')) ORDER BY COALESCE(m.first_seen,'') DESC,o.id DESC")]
        from backend.offer_lifecycle import recent_offer
        offers=[offer for offer in offers if recent_offer(offer)]
        last = conn.execute('SELECT * FROM opportunity_refreshes ORDER BY id DESC LIMIT 1').fetchone()
        for offer in offers:
            offer['safe_url'] = offer['url'] if urlparse(offer['url'] or '').scheme in {'http', 'https'} else None
        return offers, dict(last) if last else None
    finally:
        conn.close()
