"""Private operations data. No request bodies, IPs, passwords or CV contents."""
from datetime import datetime, timedelta, timezone
import hashlib
import uuid

from backend.database import get_db_connection


SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_members (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS account_activity (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 last_seen TEXT NOT NULL, last_login TEXT, login_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS admin_daily_metrics (
 day TEXT PRIMARY KEY, logins INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS admin_page_metrics (
 day TEXT NOT NULL, endpoint TEXT NOT NULL, hits INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(day,endpoint));
CREATE TABLE IF NOT EXISTS support_tickets (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, message TEXT NOT NULL, category TEXT NOT NULL,
 reference TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
 reply TEXT NOT NULL DEFAULT '', internal_note TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_support_owner ON support_tickets(user_id,created_at);
CREATE TABLE IF NOT EXISTS admin_incidents (
 id TEXT PRIMARY KEY, route TEXT NOT NULL, error_type TEXT NOT NULL,
 status_code INTEGER NOT NULL, occurrences INTEGER NOT NULL DEFAULT 1,
 first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, reference TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'open', internal_note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS admin_audit (
 id TEXT PRIMARY KEY, actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
 action TEXT NOT NULL, target_id TEXT NOT NULL, created_at TEXT NOT NULL);
"""


def now_text():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def ensure_schema(conn):
    conn.executescript(SCHEMA)


def rows(conn, query, params=()):
    return [dict(row) for row in conn.execute(query, params)]


def member(user_id):
    if not user_id:
        return False
    conn = get_db_connection()
    try:
        return conn.execute('SELECT user_id FROM admin_members WHERE user_id=?', (user_id,)).fetchone() is not None
    finally:
        conn.close()


def record_activity(user_id, login=False, endpoint=None, consent=False):
    now = now_text()
    threshold = (datetime.now(timezone.utc) - timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db_connection()
    try:
        previous = conn.execute('SELECT last_seen FROM account_activity WHERE user_id=?', (user_id,)).fetchone()
        if login or not previous or previous['last_seen'] < threshold:
            conn.execute('''INSERT INTO account_activity(user_id,last_seen,last_login,login_count)
                VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET last_seen=excluded.last_seen,
                last_login=COALESCE(excluded.last_login,account_activity.last_login),
                login_count=account_activity.login_count+excluded.login_count''',
                (user_id, now, now if login else None, int(login)))
        if login:
            conn.execute('''INSERT INTO admin_daily_metrics(day,logins) VALUES(?,1)
                ON CONFLICT(day) DO UPDATE SET logins=admin_daily_metrics.logins+1''', (now[:10],))
        if consent and endpoint:
            conn.execute('''INSERT INTO admin_page_metrics(day,endpoint,hits) VALUES(?,?,1)
                ON CONFLICT(day,endpoint) DO UPDATE SET hits=admin_page_metrics.hits+1''', (now[:10], endpoint))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime('%Y-%m-%d')
        # Prune bounded aggregates when a login occurs, not on every request.
        if login:
            conn.execute('DELETE FROM admin_page_metrics WHERE day<?', (cutoff,))
            conn.execute('DELETE FROM admin_daily_metrics WHERE day<?', (cutoff,))
        conn.commit()
    finally:
        conn.close()


def record_incident(route, error_type, status_code, reference):
    now = now_text()
    fingerprint = hashlib.sha256(f'{route}|{error_type}|{status_code}'.encode()).hexdigest()[:24]
    conn = get_db_connection()
    try:
        conn.execute('''INSERT INTO admin_incidents
            (id,route,error_type,status_code,first_seen,last_seen,reference)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            occurrences=admin_incidents.occurrences+1,last_seen=excluded.last_seen,
            reference=excluded.reference,status='open' ''',
            (fingerprint, route, error_type, status_code, now, now, reference))
        conn.commit()
    finally:
        conn.close()


def create_ticket(user_id, title, message, category, reference=''):
    title, message, reference = title.strip(), message.strip(), reference.strip()
    if not 3 <= len(title) <= 150 or not 10 <= len(message) <= 3000:
        raise ValueError('Use a title of 3–150 characters and a description of 10–3000 characters.')
    if category not in {'account', 'cv', 'email', 'bug', 'other'} or len(reference) > 80:
        raise ValueError('Choose a valid category and a reference of at most 80 characters.')
    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        count = conn.execute('SELECT COUNT(*) FROM support_tickets WHERE user_id=? AND created_at>=?', (user_id, since)).fetchone()[0]
        if count >= 5:
            raise ValueError('You can submit up to five reports per hour. Please try later.')
        ticket_id, now = uuid.uuid4().hex, now_text()
        conn.execute('''INSERT INTO support_tickets(id,user_id,title,message,category,reference,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?)''', (ticket_id, user_id, title, message, category, reference, now, now))
        conn.commit()
        return ticket_id
    finally:
        conn.close()


def my_tickets(user_id):
    conn = get_db_connection()
    try:
        return rows(conn, '''SELECT id,title,message,category,reference,status,reply,created_at,updated_at
            FROM support_tickets WHERE user_id=? ORDER BY created_at DESC LIMIT 50''', (user_id,))
    finally:
        conn.close()


def update_ticket(actor, ticket_id, status, reply, note):
    if status not in {'open', 'in_progress', 'resolved'} or len(reply) > 3000 or len(note) > 2000:
        raise ValueError('Choose a valid status. Replies are limited to 3000 characters; notes to 2000.')
    conn = get_db_connection()
    try:
        cursor = conn.execute('UPDATE support_tickets SET status=?,reply=?,internal_note=?,updated_at=? WHERE id=?',
                              (status, reply.strip(), note.strip(), now_text(), ticket_id))
        if cursor.rowcount != 1:
            raise LookupError('Report not found.')
        audit(conn, actor, 'ticket.' + status, ticket_id)
        conn.commit()
    finally:
        conn.close()


def update_incident(actor, incident_id, status, note):
    if status not in {'open', 'resolved'} or len(note) > 2000:
        raise ValueError('Choose a valid incident status and a note of at most 2000 characters.')
    conn = get_db_connection()
    try:
        cursor = conn.execute('UPDATE admin_incidents SET status=?,internal_note=? WHERE id=?', (status, note.strip(), incident_id))
        if cursor.rowcount != 1:
            raise LookupError('Incident not found.')
        audit(conn, actor, 'incident.' + status, incident_id)
        conn.commit()
    finally:
        conn.close()


def audit(conn, actor, action, target):
    conn.execute('INSERT INTO admin_audit(id,actor_id,action,target_id,created_at) VALUES(?,?,?,?,?)',
                 (uuid.uuid4().hex, actor, action, target, now_text()))


def dashboard(search='', page=1, status='all', days=14):
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days - 1)).strftime('%Y-%m-%d')
    active_since = (now - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db_connection()
    try:
        summary = {}
        for key, sql, params in [
            ('users', 'SELECT COUNT(*) FROM users', ()),
            ('verified', "SELECT COUNT(*) FROM users WHERE verified_email=email AND verified_email<>''", ()),
            ('new_users', 'SELECT COUNT(*) FROM users WHERE created_at>=?', (since,)),
            ('active_users', 'SELECT COUNT(*) FROM account_activity WHERE last_seen>=?', (active_since,)),
            ('logins', 'SELECT COALESCE(SUM(logins),0) FROM admin_daily_metrics WHERE day>=?', (since,)),
            ('open_tickets', "SELECT COUNT(*) FROM support_tickets WHERE status<>'resolved'", ()),
            ('open_incidents', "SELECT COUNT(*) FROM admin_incidents WHERE status='open'", ()),
            ('applications', 'SELECT COUNT(*) FROM applications', ()),
            ('offers', 'SELECT COUNT(*) FROM offers', ())]:
            summary[key] = conn.execute(sql, params).fetchone()[0]
        pattern = '%' + search[:120].lower() + '%'
        where = 'LOWER(u.full_name) LIKE ? OR LOWER(u.email) LIKE ?'
        total = conn.execute('SELECT COUNT(*) FROM users u WHERE '+where, (pattern, pattern)).fetchone()[0]
        accounts = rows(conn, '''SELECT u.id,u.full_name,u.email,u.created_at,
            CASE WHEN u.verified_email=u.email AND u.verified_email<>'' THEN 1 ELSE 0 END AS verified,
            a.last_seen,a.last_login,COALESCE(a.login_count,0) AS login_count,
            CASE WHEN m.user_id IS NULL THEN 0 ELSE 1 END AS is_admin
            FROM users u LEFT JOIN account_activity a ON a.user_id=u.id
            LEFT JOIN admin_members m ON m.user_id=u.id WHERE '''+where+
            ' ORDER BY u.created_at DESC,u.id DESC LIMIT 25 OFFSET ?', (pattern, pattern, (page-1)*25))
        ticket_where, params = ('', ()) if status == 'all' else (' WHERE t.status=?', (status,))
        tickets = rows(conn, '''SELECT t.*,u.full_name,u.email FROM support_tickets t
            JOIN users u ON u.id=t.user_id'''+ticket_where+' ORDER BY t.updated_at DESC LIMIT 50', params)
        incidents = rows(conn, 'SELECT * FROM admin_incidents ORDER BY last_seen DESC LIMIT 50')
        signups = {str(r['day']): r['count'] for r in rows(conn, '''SELECT SUBSTR(CAST(created_at AS TEXT),1,10) AS day,
            COUNT(*) AS count FROM users WHERE created_at>=? GROUP BY SUBSTR(CAST(created_at AS TEXT),1,10)''', (since,))}
        logins = {r['day']: r['logins'] for r in rows(conn, 'SELECT day,logins FROM admin_daily_metrics WHERE day>=?', (since,))}
        trend = []
        for offset in range(days-1, -1, -1):
            day = (now - timedelta(days=offset)).strftime('%Y-%m-%d')
            trend.append({'day': day, 'signups': signups.get(day, 0), 'logins': logins.get(day, 0)})
        peak = max([1] + [max(d['signups'], d['logins']) for d in trend])
        pages = rows(conn, '''SELECT endpoint,SUM(hits) AS hits FROM admin_page_metrics
            WHERE day>=? GROUP BY endpoint ORDER BY hits DESC LIMIT 10''', (since,))
        history = rows(conn, '''SELECT a.action,a.target_id,a.created_at,u.full_name FROM admin_audit a
            LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.created_at DESC LIMIT 20''')
        return dict(summary=summary, accounts=accounts, total=total, tickets=tickets, incidents=incidents,
                    trend=trend, peak=peak, pages=pages, history=history, days=days)
    finally:
        conn.close()
