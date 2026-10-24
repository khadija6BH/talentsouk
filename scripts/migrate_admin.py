"""Add operations tables and explicitly grant an existing account admin access."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / '.env')
from backend.database import get_db_connection, uses_postgres
from backend.admin_service import SCHEMA, ensure_schema, now_text, audit


def migrate(admin_email=None):
    conn = get_db_connection()
    try:
        if uses_postgres():
            # Explicit additive migration; the ordinary data layer rejects DDL.
            conn.raw.execute('BEGIN')
            for statement in SCHEMA.split(';'):
                if statement.strip():
                    conn.raw.execute(statement)
            # Browser Supabase keys must never read operations/account records.
            for table in ('admin_members','account_activity','admin_daily_metrics',
                          'admin_page_metrics','support_tickets','admin_incidents','admin_audit'):
                conn.raw.execute('ALTER TABLE ' + table + ' ENABLE ROW LEVEL SECURITY')
        else:
            ensure_schema(conn)
        if admin_email:
            user = conn.execute('SELECT id FROM users WHERE LOWER(email)=?', (admin_email.strip().lower(),)).fetchone()
            if not user:
                raise ValueError('The requested admin account does not exist. Register it in the app first.')
            # Membership never bypasses verified-email authentication.
            changed = conn.execute('INSERT INTO admin_members(user_id,created_at) VALUES(?,?) ON CONFLICT(user_id) DO NOTHING', (user['id'], now_text()))
            if changed.rowcount:
                audit(conn, user['id'], 'admin.grant', str(user['id']))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--admin-email')
    arguments = parser.parse_args()
    migrate(arguments.admin_email)
    print('Operations schema ready. Admin membership configured.' if arguments.admin_email else 'Operations schema ready. No admin membership changed.')
