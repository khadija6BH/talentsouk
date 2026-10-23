"""Generate reminder events atomically and publish product announcements."""
from datetime import date
from backend.database import get_db_connection


def emit_due_reminders(today=None, user_id=None):
    today = (today or date.today()).isoformat()
    conn = get_db_connection()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            rows = conn.execute("""SELECT r.*, a.position FROM reminders r
                JOIN applications a ON a.id=r.application_id AND a.user_id=r.user_id
                WHERE r.completed=0 AND r.due_date<=?
                AND (CAST(? AS INTEGER) IS NULL OR r.user_id=?)
                AND NOT EXISTS (SELECT 1 FROM application_history h
                    WHERE h.user_id=r.user_id AND h.application_id=r.application_id
                    AND h.event_type='reminder_due:' || r.id)""",
                (today, user_id, user_id)).fetchall()
            for row in rows:
                message = 'Your follow-up for '+row['position']+' is due on '+row['due_date']+'.'
                conn.execute("INSERT INTO notifications(user_id,kind,title,message,url) VALUES(?,'reminder',?,?,?)",
                             (row['user_id'], 'Application follow-up reminder', message, '/applications'))
                conn.execute("INSERT INTO application_history(user_id,application_id,event_type,description) VALUES(?,?,?,?)",
                             (row['user_id'], row['application_id'], 'reminder_due:'+str(row['id']), message))
            return len(rows)
    finally:
        conn.close()


def publish_update(title, message, url='/dashboard'):
    """Explicit operator action: announce an update to current users via both channels."""
    if not title.strip() or not message.strip():
        raise ValueError('Provide an update title and message.')
    if not url.startswith('/') or url.startswith('//') or '\\' in url:
        raise ValueError('Use an internal application link.')
    conn = get_db_connection()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            # Repeating the same announcement does not resend it.
            return conn.execute("""INSERT INTO notifications(user_id,kind,title,message,url)
                SELECT u.id,'update',?,?,? FROM users u WHERE NOT EXISTS
                (SELECT 1 FROM notifications n WHERE n.user_id=u.id AND n.kind='update'
                 AND n.title=? AND n.message=? AND n.url=?)""",
                (title, message, url, title, message, url)).rowcount
    finally:
        conn.close()


if __name__ == '__main__':
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description='Publish a TalentSouk product update notification.')
    parser.add_argument('--title', required=True)
    parser.add_argument('--message', required=True)
    parser.add_argument('--url', default='/dashboard')
    args = parser.parse_args()
    print('Notifications created:', publish_update(args.title, args.message, args.url))
