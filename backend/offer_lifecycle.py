"""Archive old catalog entries without deleting application references."""
from datetime import datetime, timezone, timedelta
import re
from backend.offer_cleaning import marrakech_location

MAX_AGE_DAYS = 30


def recent_offer(row, now=None):
    if not marrakech_location(row.get('location')):
        return False
    try:
        raw = str(row.get('publication_date') or '').strip().replace('Z','+00:00')
        raw = re.sub(r'(\.\d{6})\d+',r'\1',raw)  # Jooble sends 7 fractional digits; Python 3.10 accepts 6.
        published = datetime.fromisoformat(raw)
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
    except (ValueError,TypeError):
        return False
    now = now or datetime.now(timezone.utc)
    return now-timedelta(days=MAX_AGE_DAYS) <= published <= now+timedelta(days=1)


def ensure_catalog_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS offer_catalog_status (
        offer_id INTEGER PRIMARY KEY REFERENCES offers(id),
        is_active INTEGER NOT NULL DEFAULT 0,
        verified_at TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '')''')

    conn.execute("""CREATE TABLE IF NOT EXISTS admin_offer_reviews (
        offer_id INTEGER PRIMARY KEY REFERENCES offers(id) ON DELETE CASCADE,
        status TEXT NOT NULL DEFAULT 'pending', note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL)""")


def activate_offer(conn, offer_id):
    conn.execute('''INSERT INTO offer_catalog_status(offer_id,is_active,verified_at,reason)
        VALUES(?,1,CURRENT_TIMESTAMP,'recent_api_response') ON CONFLICT(offer_id)
        DO UPDATE SET is_active=1,verified_at=CURRENT_TIMESTAMP,reason='recent_api_response' ''',(offer_id,))


def expire_offers(conn):
    cutoff=(datetime.now(timezone.utc)-timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    rows=[dict(r) for r in conn.execute('''SELECT o.*,s.verified_at FROM offers o
        JOIN offer_catalog_status s ON s.offer_id=o.id WHERE s.is_active=1''')]
    expired = [row['id'] for row in rows
               if not recent_offer(row) or row['verified_at'] < cutoff]
    # A remote PostgreSQL round trip per archived offer can exceed a serverless
    # request's duration. Keep parameter batches below SQLite's common limit.
    for start in range(0, len(expired), 400):
        batch = expired[start:start + 400]
        conn.execute("UPDATE offer_catalog_status SET is_active=0,reason='age_or_verification_window_exceeded' WHERE offer_id IN ("
                     + ','.join('?' for _ in batch) + ')', tuple(batch))
