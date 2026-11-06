"""Local CSV adapter and transactional opportunity refresh."""
import csv
import re
from urllib.parse import urlparse
from backend.database import get_db_connection
from backend.market_sync import MarketSync, normalized_name


class LocalOfferSync(MarketSync):
    def __init__(self, connection):
        super().__init__(connection)
        self.duplicate_offer_ids = {}
        reviews = {row[0]: row[1] for row in connection.execute('SELECT offer_id,status FROM admin_offer_reviews')}
        for key, identifiers in list(self.offer_index.items()):
            if key[0] != 'url' or len(identifiers) < 2:
                continue
            parsed = urlparse(key[1])
            host = (parsed.hostname or '').lower()
            if not (host == 'jooble.org' or host.endswith('.jooble.org')) or not re.fullmatch(r'/(?:desc|jdp)/-?\d+',parsed.path):
                continue
            # A rejection/archive applies to the source announcement, including
            # tracking URL aliases. Never choose a new alias to bypass review.
            blocked = sorted(i for i in identifiers if reviews.get(i) in {'rejected','archived'})
            approved = sorted(i for i in identifiers if reviews.get(i) == 'approved')
            target = (blocked or approved or sorted(identifiers))[0]
            self.offer_index[key] = {target}
            self.duplicate_offer_ids.update({i: target for i in identifiers if i != target})

    @staticmethod
    def offer_keys(row):
        # A source URL identifies an individual announcement. Distinct links
        # may legitimately repeat the same job title, company and date.
        keys = MarketSync.offer_keys(row)
        from backend.offer_cleaning import canonical_url
        url_keys = [('url',canonical_url(key[1])) for key in keys if key[0] == 'url']
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


def refresh_external_offers(provider,country,keyword='',location='', *, pages=1):
    from backend.job_sources import fetch_offers, fetch_offer_pages
    # Network work precedes the write transaction.
    if pages == 1:
        rows,skipped=fetch_offers(provider,country,keyword,location or 'Marrakech')
    else:
        rows,skipped=fetch_offer_pages(provider,country,keyword,location or 'Marrakech',pages=pages)
    return import_external_offers(provider,country,rows,skipped)


def import_external_offers(provider,country,rows,skipped=0, *, notify=True):
    """Persist the fetched response without spending another source request."""
    from backend.job_sources import JobSourceError, HTML_PROVIDERS
    from backend.offer_lifecycle import recent_offer,activate_offer,expire_offers,ensure_catalog_schema
    domestic=[row for row in rows if recent_offer(row)]
    skipped+=len(rows)-len(domestic)
    rows=domestic
    from backend.radar_watch import alert_preferences,notify_new_offers
    preferences=alert_preferences() if notify else []
    conn=get_db_connection()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            ensure_catalog_schema(conn)
            expire_offers(conn)
            sync=LocalOfferSync(conn)
            existing_ids={r[0] for r in conn.execute('SELECT id FROM offers')}
            new_offers=[]
            checked_ids=set()
            for row in rows:
                matches=sync.company_index.get(('name',normalized_name(row['company_name'])),set())
                if len(matches)>1:
                    if provider in HTML_PROVIDERS:
                        skipped += 1
                        continue
                    raise JobSourceError('A company has ambiguous duplicates. No offers were changed.')
                company_id=next(iter(matches),None)
                if company_id is None:
                    company_id=sync.company({'name':row['company_name'],'area':row['location'],'has_offer':1})
                values=dict(row,company_id=company_id)
                offer_id=sync.offer(values)
                checked_ids.add(offer_id)
                if offer_id not in existing_ids:
                    new_offers.append(dict(values,id=offer_id));existing_ids.add(offer_id)
                conn.execute("INSERT INTO offer_sync_metadata(offer_id,adapter) VALUES(?,?) ON CONFLICT(offer_id) DO UPDATE SET last_checked=CURRENT_TIMESTAMP,adapter=excluded.adapter",(offer_id,provider))
                activate_offer(conn,offer_id,reason='recent_public_jobposting' if provider in HTML_PROVIDERS else 'recent_api_response')
                conn.execute('UPDATE companies SET has_offer=1 WHERE id=?',(company_id,))
            duplicates = [identifier for identifier,target in sync.duplicate_offer_ids.items() if target in checked_ids]
            for start in range(0,len(duplicates),400):
                batch = duplicates[start:start+400]
                conn.execute("UPDATE offer_catalog_status SET is_active=0,reason='duplicate_source_url' WHERE offer_id IN (" + ','.join('?' for _ in batch) + ')',tuple(batch))
            review_blocks = {r[0] for r in conn.execute("SELECT offer_id FROM admin_offer_reviews WHERE status IN ('pending','rejected','archived')")}
            hidden = sorted(checked_ids & review_blocks)
            for start in range(0,len(hidden),400):
                batch=hidden[start:start+400]
                conn.execute("UPDATE offer_catalog_status SET is_active=0,reason='review_required' WHERE offer_id IN (" + ','.join('?' for _ in batch) + ')',tuple(batch))
            if notify:
                notify_new_offers(conn,[o for o in new_offers if o['id'] not in review_blocks],preferences)
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
