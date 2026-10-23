"""Email ownership challenges. No plaintext codes are persisted or logged."""
import hashlib,hmac,secrets,time
from backend.database import get_db_connection
from backend.smtp_service import send_verification_email


def ensure_verification_schema(conn):
    columns={r['name'] for r in conn.execute('PRAGMA table_info(users)')}
    if 'verified_email' not in columns:conn.execute("ALTER TABLE users ADD COLUMN verified_email TEXT NOT NULL DEFAULT ''")
    if 'email_verification_required' not in columns:conn.execute('ALTER TABLE users ADD COLUMN email_verification_required INTEGER NOT NULL DEFAULT 0')
    conn.execute("""CREATE TABLE IF NOT EXISTS email_verification_codes (
      user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,email TEXT NOT NULL,
      code_hash TEXT NOT NULL,expires INTEGER NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
      sent_at INTEGER NOT NULL,window_start INTEGER NOT NULL,sends INTEGER NOT NULL)""")


def verified(user):
    return bool(user and user['verified_email'] and user['verified_email']==user['email'])


def require_verification(user_id):
    conn=get_db_connection()
    try:
        with conn:conn.execute('UPDATE users SET email_verification_required=1 WHERE id=?',(user_id,))
    finally:conn.close()


def send_code(user_id,now=None):
    now=int(time.time()) if now is None else now
    conn=get_db_connection();code=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
    hashed=hashlib.sha256(code.encode()).hexdigest()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            user=conn.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
            if not user or verified(user):raise ValueError('This email is already verified or the account is unavailable.')
            previous=conn.execute('SELECT * FROM email_verification_codes WHERE user_id=?',(user_id,)).fetchone()
            if previous and now-previous['sent_at']<60:raise ValueError('Please wait 60 seconds before requesting another code.')
            recent=previous and now-previous['window_start']<3600
            if recent and previous['sends']>=5:raise ValueError('Too many codes requested. Try again in an hour.')
            start=previous['window_start'] if recent else now
            sends=previous['sends']+1 if recent else 1
            conn.execute('INSERT OR REPLACE INTO email_verification_codes VALUES(?,?,?,?,?,?,?,?)',(user_id,user['email'],hashed,now+600,0,now,start,sends))
            conn.execute('UPDATE users SET email_verification_required=1 WHERE id=?',(user_id,))
        try:send_verification_email(recipient=user['email'],code=code)
        except Exception:
            with conn:conn.execute("UPDATE email_verification_codes SET code_hash='',expires=0 WHERE user_id=? AND code_hash=?",(user_id,hashed))
            raise
    finally:conn.close()


def confirm_code(user_id,code,now=None):
    now=int(time.time()) if now is None else now
    value=str(code or '').strip().upper()
    hashed=hashlib.sha256(value.encode()).hexdigest()
    conn=get_db_connection()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM email_verification_codes WHERE user_id=?',(user_id,)).fetchone()
            user=conn.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
            if not row or not user or row['email']!=user['email'] or row['expires']<=now or row['attempts']>=5 or not row['code_hash']:return False
            conn.execute('UPDATE email_verification_codes SET attempts=attempts+1 WHERE user_id=?',(user_id,))
            if len(value)!=8 or not hmac.compare_digest(row['code_hash'],hashed):return False
            conn.execute('UPDATE users SET verified_email=email,email_verification_required=1 WHERE id=?',(user_id,))
            conn.execute("UPDATE email_verification_codes SET code_hash='',expires=0 WHERE user_id=?",(user_id,))
            return True
    finally:conn.close()
