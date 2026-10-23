"""Durable notification mail queue; SMTP runs outside SQLite transactions."""
import logging
import time
from backend.database import get_db_connection, get_user_settings
from backend.smtp_service import smtp_configured, send_notification_email


def ensure_mail_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS notification_mail_queue (
        notification_id INTEGER PRIMARY KEY REFERENCES notifications(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        retry_at INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS notification_mail_state (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        last_sent INTEGER NOT NULL DEFAULT 0, lease_until INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS queue_notification_mail AFTER INSERT ON notifications
        BEGIN INSERT INTO notification_mail_queue(notification_id,user_id) VALUES(NEW.id,NEW.user_id); END""")


def deliver_pending(now=None):
    now = int(time.time()) if now is None else int(now)
    if not smtp_configured(): return 0
    conn = get_db_connection()
    delivered = 0
    processed = 0
    try:
        users = [row[0] for row in conn.execute("SELECT DISTINCT user_id FROM notification_mail_queue WHERE state='pending' AND retry_at<=? ORDER BY user_id", (now,))]
        for uid in users:
            if processed >= 10: break
            settings = get_user_settings(uid)
            frequency = settings['notification_frequency']
            if not settings['email_notifications'] or frequency == 'off':
                with conn: conn.execute("UPDATE notification_mail_queue SET state='skipped' WHERE user_id=? AND state='pending'", (uid,))
                continue
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                user = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
                if not user or not user['verified_email'] or user['verified_email'] != user['email']: continue
                conn.execute('INSERT OR IGNORE INTO notification_mail_state(user_id) VALUES(?)', (uid,))
                state = conn.execute('SELECT * FROM notification_mail_state WHERE user_id=?', (uid,)).fetchone()
                interval = {'instant':0, 'daily':86400, 'weekly':604800}.get(frequency, 86400)
                if state['lease_until'] > now or (state['last_sent'] and now-state['last_sent'] < interval): continue
                conn.execute("UPDATE notification_mail_queue SET state='expired' WHERE user_id=? AND state='pending' AND notification_id IN (SELECT id FROM notifications WHERE created_at < datetime(?, 'unixepoch', '-7 days'))", (uid,now))
                rows = [dict(row) for row in conn.execute("SELECT n.* FROM notifications n JOIN notification_mail_queue q ON q.notification_id=n.id WHERE q.user_id=? AND q.state='pending' AND q.retry_at<=? ORDER BY n.id LIMIT 50", (uid,now))]
                if not rows: continue
                ids = [row['id'] for row in rows]
                conn.execute('UPDATE notification_mail_state SET lease_until=? WHERE user_id=?', (now+300,uid))
                conn.executemany('UPDATE notification_mail_queue SET attempts=attempts+1,retry_at=? WHERE notification_id=?', [(now+300,nid) for nid in ids])
            processed += 1
            try:
                send_notification_email(recipient=user['email'], notifications=rows)
            except Exception:
                logging.getLogger(__name__).warning('Notification email delivery unavailable; queued for retry')
                with conn:
                    conn.executemany("UPDATE notification_mail_queue SET state=CASE WHEN attempts>=5 THEN 'failed' ELSE 'pending' END,retry_at=? WHERE notification_id=?", [(now+900,nid) for nid in ids])
                    conn.execute('UPDATE notification_mail_state SET lease_until=0 WHERE user_id=?',(uid,))
                continue
            with conn:
                conn.executemany("UPDATE notification_mail_queue SET state='sent' WHERE notification_id=?",[(nid,) for nid in ids])
                conn.execute('UPDATE notification_mail_state SET last_sent=?,lease_until=0 WHERE user_id=?',(now,uid))
            delivered += len(rows)
    finally: conn.close()
    return delivered
