"""Add account appearance storage without changing existing preferences."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent/'.env')
from backend.database import get_db_connection,uses_postgres

def migrate():
    conn=get_db_connection()
    try:
        if uses_postgres():
            conn.raw.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS appearance_json TEXT NOT NULL DEFAULT '{}'")
        else:
            columns={row['name'] for row in conn.execute('PRAGMA table_info(user_settings)')}
            if 'appearance_json' not in columns:
                conn.execute("ALTER TABLE user_settings ADD COLUMN appearance_json TEXT NOT NULL DEFAULT '{}'")
        conn.commit()
    finally:
        conn.close()

if __name__=='__main__':
    migrate()
    print('Account appearance storage ready.')
