"""
TalentSouk — SQLite data layer.

TASK 1 — LOGIN + REGISTER
Minimal local authentication storage. One `users` table for now;
more tables will be added as later tasks need them.
"""

import json
import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", PROJECT_ROOT)).resolve()
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
DB_PATH = STORAGE_ROOT / "database.db"


def uses_postgres():
    # DB_PATH is an existing explicit SQLite override used by isolated tests and
    # maintenance callers. Honour it instead of directing those writes to cloud.
    return (os.environ.get('DATABASE_BACKEND', 'sqlite').lower() == 'postgres'
            and Path(DB_PATH).resolve() == (STORAGE_ROOT / 'database.db').resolve())


def get_db_connection():
    """Open the selected backend, keeping explicit SQLite path overrides local."""
    if uses_postgres():
        from backend.postgres import Connection
        url = os.environ.get('DATABASE_URL', '').strip()
        if not url:
            raise RuntimeError('DATABASE_URL is required when DATABASE_BACKEND=postgres')
        return Connection(url, os.environ.get('DATABASE_SCHEMA', 'talentsouk'))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables if they don't exist yet. Safe to call on every startup."""
    conn = get_db_connection()
    if uses_postgres():
        # PostgreSQL schema/data migrations are explicit and transactional. Do
        # not rerun legacy SQLite data rewrites on an imported production copy.
        required = {'users', 'cvs', 'applications', 'cv_builder_data', 'companies',
                    'offers', 'company_contacts', 'crm', 'gmail_credentials',
                    'notifications', 'notification_mail_queue', 'notification_mail_state',
                    'reminders', 'application_history', 'application_email_attempts',
                    'password_reset_tokens', 'user_settings', 'company_search_history',
                    'interview_sessions', 'interview_schedules', 'career_dna_profiles',
                    'skill_learning_progress', 'cv_versions', 'offer_sync_metadata',
                    'opportunity_refreshes', 'public_job_feed_cache', 'radar_watch_state',
                    'radar_source_checks', 'offer_alerts', 'career_plans', 'career_tasks',
                    'proof_projects', 'network_contacts', 'network_interactions',
                    'network_followup_alerts', 'career_scenarios', 'skill_practice_attempts',
                    'email_verification_codes', 'admin_members', 'account_activity',
                    'admin_daily_metrics', 'admin_page_metrics', 'support_tickets',
                    'admin_incidents', 'admin_audit'}
        try:
            found = {row[0] for row in conn.execute(
                'SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname=?',
                (os.environ.get('DATABASE_SCHEMA', 'talentsouk'),))}
            if required - found:
                raise RuntimeError('The PostgreSQL schema is incomplete. Run the verified migration before starting Flask.')
        finally:
            conn.close()
        return
    from backend.opportunity_radar import ensure_radar_schema
    ensure_radar_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    user_columns = {column["name"] for column in conn.execute("PRAGMA table_info(users)")}
    if "preferred_language" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN preferred_language TEXT NOT NULL DEFAULT 'en'")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cvs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            file_extension TEXT NOT NULL,
            mime_type TEXT NOT NULL DEFAULT '',
            file_size INTEGER NOT NULL DEFAULT 0,
            content_sha256 TEXT NOT NULL DEFAULT '',
            extracted_text TEXT NOT NULL DEFAULT '',
            extraction_status TEXT NOT NULL DEFAULT 'pending',
            page_count INTEGER,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )
    cv_columns = {
        column["name"] for column in conn.execute("PRAGMA table_info(cvs)")
    }
    cv_column_migrations = {
        "mime_type": "TEXT NOT NULL DEFAULT ''",
        "file_size": "INTEGER NOT NULL DEFAULT 0",
        "content_sha256": "TEXT NOT NULL DEFAULT ''",
        "extracted_text": "TEXT NOT NULL DEFAULT ''",
        "extraction_status": "TEXT NOT NULL DEFAULT 'pending'",
        "page_count": "INTEGER",
    }
    for column, definition in cv_column_migrations.items():
        if column not in cv_columns:
            conn.execute(f"ALTER TABLE cvs ADD COLUMN {column} {definition}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            position TEXT NOT NULL,
            contact_email TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Draft',
            last_contact_date TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            applied_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    application_columns = {
        column["name"] for column in conn.execute("PRAGMA table_info(applications)")
    }
    if "applied_at" not in application_columns:
        conn.execute(
            "ALTER TABLE applications ADD COLUMN applied_at TEXT NOT NULL DEFAULT ''"
        )
    if "updated_at" not in application_columns:
        conn.execute(
            "ALTER TABLE applications ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
        )
    for column in (
        "cv_used", "cover_letter_used", "application_message",
        "gmail_message_id", "sent_at", "recipient_email",
    ):
        if column not in application_columns:
            conn.execute(f"ALTER TABLE applications ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gmail_credentials (
            user_id INTEGER PRIMARY KEY,
            token_encrypted TEXT NOT NULL,
            expires_at TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL,
            account_email TEXT NOT NULL DEFAULT '',
            email_verified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    gmail_columns = {column["name"] for column in conn.execute("PRAGMA table_info(gmail_credentials)")}
    if "account_email" not in gmail_columns:
        conn.execute("ALTER TABLE gmail_credentials ADD COLUMN account_email TEXT NOT NULL DEFAULT ''")
    if "email_verified" not in gmail_columns:
        conn.execute("ALTER TABLE gmail_credentials ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        """
        UPDATE applications SET applied_at = created_at
        WHERE applied_at = '' AND status IN (
            'Sent', 'Replied', 'Interview', 'Accepted', 'Rejected'
        )
        """
    )
    conn.execute(
        "UPDATE applications SET updated_at = created_at WHERE updated_at = ''"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cv_builder_data (
            user_id INTEGER PRIMARY KEY,
            profiles_json TEXT NOT NULL DEFAULT '{}',
            templates_json TEXT NOT NULL DEFAULT '{}',
            optimized_json TEXT NOT NULL DEFAULT '',
            optimized_source TEXT NOT NULL DEFAULT 'manual',
            career_objective TEXT NOT NULL DEFAULT '',
            profile_photo_filename TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    cv_builder_columns = {
        column["name"] for column in conn.execute("PRAGMA table_info(cv_builder_data)")
    }
    for column in (
        "career_objective", "profile_photo_filename", "target_position", "career_field",
        "target_location", "target_skills", "career_goal", "education_level",
        "experience_level",
    ):
        if column not in cv_builder_columns:
            conn.execute(
                f"ALTER TABLE cv_builder_data ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
            )
    from backend.email_verification import ensure_verification_schema
    ensure_verification_schema(conn)
    from backend.skill_practice_service import ensure_practice_schema
    ensure_practice_schema(conn)
    from backend.twin_service import ensure_twin_schema
    ensure_twin_schema(conn)
    from backend.networking_service import ensure_network_schema
    ensure_network_schema(conn)
    from backend.portfolio_service import ensure_portfolio_schema
    ensure_portfolio_schema(conn)
    from backend.copilot_service import ensure_copilot_schema
    ensure_copilot_schema(conn)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            application_id INTEGER NOT NULL, due_date TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            kind TEXT NOT NULL, title TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '', is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS application_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            application_id INTEGER NOT NULL, event_type TEXT NOT NULL,
            description TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS application_email_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            application_id INTEGER,
            recipient_email TEXT NOT NULL DEFAULT '',
            cv_filename TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL CHECK(status IN ('sent', 'failed')),
            error_message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_application_email_attempts_user_created
            ON application_email_attempts(user_id, created_at);
        CREATE TABLE IF NOT EXISTS cv_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            optimized_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            origin TEXT NOT NULL DEFAULT 'optimization',
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_cv_versions_user ON cv_versions(user_id,id DESC);
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_hash
            ON password_reset_tokens(token_hash);
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user
            ON password_reset_tokens(user_id, created_at);
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            email_notifications INTEGER NOT NULL DEFAULT 1,
            ai_suggestions INTEGER NOT NULL DEFAULT 1,
            notification_frequency TEXT NOT NULL DEFAULT 'daily',
            ai_provider TEXT NOT NULL DEFAULT 'gemini',
            ai_model TEXT NOT NULL DEFAULT 'gemini-3.5-flash-lite',
            profile_visibility TEXT NOT NULL DEFAULT 'private',
            analytics_enabled INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS company_search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            query TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_company_search_history_user_created
            ON company_search_history(user_id, created_at);
        CREATE TABLE IF NOT EXISTS interview_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            application_id INTEGER,
            company_id INTEGER NOT NULL,
            position TEXT NOT NULL,
            questions_json TEXT NOT NULL DEFAULT '[]',
            answers_json TEXT NOT NULL DEFAULT '[]',
            score INTEGER,
            weak_skills_json TEXT NOT NULL DEFAULT '[]',
            feedback TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_interview_sessions_user_created
            ON interview_sessions(user_id, created_at);
        CREATE TABLE IF NOT EXISTS interview_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            application_id INTEGER,
            company_id INTEGER NOT NULL,
            offer_id INTEGER,
            position TEXT NOT NULL,
            interview_date TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_interview_schedules_user_date
            ON interview_schedules(user_id, interview_date);
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS career_dna_profiles (
            user_id INTEGER PRIMARY KEY,
            overrides_json TEXT NOT NULL DEFAULT '{}',
            reviews_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""CREATE TABLE IF NOT EXISTS skill_learning_progress (
        user_id INTEGER NOT NULL, skill TEXT NOT NULL, action_index INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'planned', notes TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(user_id, skill, action_index),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    interview_columns = {row["name"] for row in conn.execute("PRAGMA table_info(interview_sessions)")}
    for column in ("practice_context_json", "evaluation_json"):
        if column not in interview_columns:
            conn.execute("ALTER TABLE interview_sessions ADD COLUMN " + column + " TEXT NOT NULL DEFAULT '{}'")
    columns = list(conn.execute("PRAGMA table_info(interview_sessions)"))
    if any(col["name"] == "application_id" and col["notnull"] for col in columns):
        schema = conn.execute("SELECT sql FROM sqlite_master WHERE name='interview_sessions'").fetchone()[0]
        schema = schema.replace("interview_sessions", "interview_sessions_migrating", 1).replace("application_id INTEGER NOT NULL", "application_id INTEGER")
        conn.execute("BEGIN")
        try:
            conn.execute(schema)
            conn.execute("INSERT INTO interview_sessions_migrating SELECT * FROM interview_sessions")
            conn.execute("DROP TABLE interview_sessions")
            conn.execute("ALTER TABLE interview_sessions_migrating RENAME TO interview_sessions")
            conn.execute("CREATE INDEX idx_interview_sessions_user_created ON interview_sessions(user_id, created_at)")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    from backend.notification_mail import ensure_mail_schema
    ensure_mail_schema(conn)
    settings_columns = {
        column["name"] for column in conn.execute("PRAGMA table_info(user_settings)")
    }
    if "ai_model" not in settings_columns:
        conn.execute(
            "ALTER TABLE user_settings ADD COLUMN ai_model TEXT NOT NULL DEFAULT 'gemini-3.5-flash-lite'"
        )
    if 'appearance_json' not in settings_columns:
        conn.execute("ALTER TABLE user_settings ADD COLUMN appearance_json TEXT NOT NULL DEFAULT '{}'")
    schedule_columns = {column["name"] for column in conn.execute("PRAGMA table_info(interview_schedules)")}
    if "application_id" not in schedule_columns:
        conn.execute("ALTER TABLE interview_schedules ADD COLUMN application_id INTEGER")
    # Preserve the latest pre-history snapshot once, without inventing older versions.
    conn.execute("""INSERT INTO cv_versions(user_id,source,optimized_json,created_at,origin)
        SELECT user_id,optimized_source,optimized_json,COALESCE(CAST(updated_at AS TEXT),CURRENT_TIMESTAMP),'legacy'
        FROM cv_builder_data WHERE optimized_json IS NOT NULL AND optimized_json<>''
        AND NOT EXISTS(SELECT 1 FROM cv_versions WHERE cv_versions.user_id=cv_builder_data.user_id)""")

    from backend.admin_service import ensure_schema
    ensure_schema(conn)

    conn.commit()
    conn.close()


def get_user_by_email(email):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return user


def create_interview_session(user_id, application_id, company_id, position, questions, practice_context=None):
    conn = get_db_connection()
    cursor = conn.execute(
        """INSERT INTO interview_sessions
           (user_id, application_id, company_id, position, questions_json, practice_context_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, application_id, company_id, position, json.dumps(questions, ensure_ascii=False), json.dumps(practice_context or {}, ensure_ascii=False)),
    )
    conn.commit()
    session_id = cursor.lastrowid
    conn.close()
    return session_id


def complete_interview_session(user_id, session_id, answers, score, weak_skills, feedback, evaluation=None):
    conn = get_db_connection()
    cursor = conn.execute(
        """UPDATE interview_sessions SET answers_json=?, score=?, weak_skills_json=?,
           feedback=?, evaluation_json=?, completed_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND (completed_at IS NULL OR completed_at='')""",
        (json.dumps(answers, ensure_ascii=False), int(score),
         json.dumps(weak_skills, ensure_ascii=False), feedback, json.dumps(evaluation or {}, ensure_ascii=False), session_id, user_id),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount == 1


def get_interview_sessions(user_id):
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM interview_sessions WHERE user_id=? ORDER BY created_at DESC, id DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    results = []
    for row in rows:
        item = dict(row)
        for source, target in (("questions_json", "questions"), ("answers_json", "answers"), ("weak_skills_json", "weak_skills"), ("practice_context_json", "practice_context"), ("evaluation_json", "evaluation")):
            try:
                item[target] = json.loads(item.pop(source) or "[]")
            except (TypeError, ValueError):
                item[target] = []
        results.append(item)
    return results


def get_interview_session(user_id, session_id):
    return next((item for item in get_interview_sessions(user_id) if item["id"] == session_id), None)


def get_interview_weak_skills(user_id, position=None):
    counts = {}
    seen = set()
    for item in get_interview_sessions(user_id):
        if not item.get("completed_at"):
            continue
        if position and str(item.get("position") or "").casefold() != str(position).casefold():
            continue
        focus = (item.get("company_id"), str(item.get("position") or "").casefold())
        if focus in seen:
            continue
        seen.add(focus)
        for skill in item.get("weak_skills", []):
            name = str(skill).strip()
            if name:
                counts[name] = counts.get(name, 0) + 1
    return counts


def create_interview_schedule(user_id, application_id, company_id, offer_id, position, interview_date, notes=""):
    conn = get_db_connection()
    cursor = conn.execute(
        """INSERT INTO interview_schedules
           (user_id, application_id, company_id, offer_id, position, interview_date, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, application_id, company_id, offer_id, position, interview_date, notes),
    )
    conn.commit()
    schedule_id = cursor.lastrowid
    conn.close()
    return schedule_id


def get_interview_schedules(user_id):
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM interview_schedules WHERE user_id=? ORDER BY interview_date, id",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_interview_schedule(user_id, schedule_id):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM interview_schedules WHERE id=? AND user_id=?",
        (schedule_id, user_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_interview_schedule(user_id, schedule_id):
    conn = get_db_connection()
    cursor = conn.execute("DELETE FROM interview_schedules WHERE id=? AND user_id=?", (schedule_id, user_id))
    conn.commit()
    conn.close()
    return cursor.rowcount == 1


def get_user_by_id(user_id):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return user


def update_user_language(user_id, language):
    if language not in {"ar", "fr", "en"}:
        return False
    conn = get_db_connection()
    cursor = conn.execute(
        "UPDATE users SET preferred_language = ? WHERE id = ?",
        (language, user_id),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount == 1


def update_user_profile(user_id, full_name, email):
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET full_name = ?, verified_email=CASE WHEN email=? THEN verified_email ELSE '' END, email_verification_required=CASE WHEN email=? THEN email_verification_required ELSE 1 END, email = ? WHERE id = ?",
            (full_name, email, email, email, user_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return False
    conn.close()
    return True


def get_user_settings(user_id):
    defaults = {
        "user_id": user_id,
        "email_notifications": 1,
        "ai_suggestions": 1,
        "notification_frequency": "daily",
        "ai_provider": "gemini",
        "ai_model": "gemini-3.5-flash-lite",
        "profile_visibility": "private",
        "analytics_enabled": 0,
    }
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else defaults


def save_user_settings(user_id, values):
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO user_settings (
            user_id, email_notifications, ai_suggestions, notification_frequency,
            ai_provider, ai_model, profile_visibility, analytics_enabled, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            email_notifications=excluded.email_notifications,
            ai_suggestions=excluded.ai_suggestions,
            notification_frequency=excluded.notification_frequency,
            ai_provider=excluded.ai_provider,
            ai_model=excluded.ai_model,
            profile_visibility=excluded.profile_visibility,
            analytics_enabled=excluded.analytics_enabled,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            user_id, int(values["email_notifications"]), int(values["ai_suggestions"]),
            values["notification_frequency"], values["ai_provider"],
            values.get("ai_model", "gemini-3.5-flash-lite"),
            values["profile_visibility"], int(values["analytics_enabled"]),
        ),
    )
    conn.commit()
    conn.close()


def delete_user_account(user_id):
    conn = get_db_connection()
    cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount == 1


def save_company_search(user_id, query):
    query = str(query or "").strip()[:120]
    if len(query) < 2:
        return
    conn = get_db_connection()
    previous = conn.execute(
        "SELECT query FROM company_search_history WHERE user_id=? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if previous is None or previous["query"].casefold() != query.casefold():
        conn.execute(
            "INSERT INTO company_search_history(user_id, query) VALUES(?, ?)",
            (user_id, query),
        )
        conn.execute(
            "DELETE FROM company_search_history WHERE user_id=? AND id NOT IN "
            "(SELECT id FROM company_search_history WHERE user_id=? ORDER BY id DESC LIMIT 30)",
            (user_id, user_id),
        )
        conn.commit()
    conn.close()


def get_company_search_history(user_id, limit=10):
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT query FROM company_search_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [row["query"] for row in rows]


def update_user_password(user_id, password_hash):
    conn = get_db_connection()
    cursor = conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (password_hash, user_id),
    )
    conn.commit()
    conn.close()
    return cursor.rowcount == 1


def create_user(full_name, email, password_hash):
    conn = get_db_connection()
    cursor = conn.execute(
        "INSERT INTO users (full_name, email, password_hash, email_verification_required) VALUES (?, ?, ?, 1)",
        (full_name, email, password_hash),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    return user_id


def create_password_reset_token(user_id, token_hash, expires_at):
    """Store a reset hash; older delivered codes remain usable until expiry."""
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
        (user_id, token_hash, expires_at),
    )
    conn.commit()
    conn.close()


def password_reset_token_is_valid(token_hash):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT id FROM password_reset_tokens "
        "WHERE token_hash = ? AND used_at IS NULL AND expires_at > CURRENT_TIMESTAMP",
        (token_hash,),
    ).fetchone()
    conn.close()
    return row is not None


def reset_password_with_token(token_hash, password_hash):
    """Atomically consume a valid token and update its user's password."""
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        token = conn.execute(
            "SELECT id, user_id FROM password_reset_tokens "
            "WHERE token_hash = ? AND used_at IS NULL AND expires_at > CURRENT_TIMESTAMP",
            (token_hash,),
        ).fetchone()
        if token is None:
            conn.rollback()
            return False
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, token["user_id"]),
        )
        conn.execute(
            "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP WHERE user_id = ? AND used_at IS NULL",
            (token["user_id"],),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def reset_password_with_code(email, code_hash, password_hash):
    """Atomically consume a valid one-time code belonging to the supplied email."""
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        token = conn.execute(
            """
            SELECT password_reset_tokens.id, password_reset_tokens.user_id
            FROM password_reset_tokens
            JOIN users ON users.id = password_reset_tokens.user_id
            WHERE users.email = ? AND password_reset_tokens.token_hash = ?
              AND password_reset_tokens.used_at IS NULL
              AND password_reset_tokens.expires_at > CURRENT_TIMESTAMP
            """,
            (email, code_hash),
        ).fetchone()
        if token is None:
            conn.rollback()
            return False
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, token["user_id"]),
        )
        conn.execute(
            "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP WHERE user_id = ? AND used_at IS NULL",
            (token["user_id"],),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_initials(full_name):
    """Return up to 2 uppercase initials from a full name, for avatar badges."""
    parts = [p for p in full_name.strip().split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()


# ---------------------------------------------------------------------------
# TASK 6 — CV UPLOAD + SKILL GAP
# One active CV per user for now (uploading again replaces it). The actual
# file lives on disk under UPLOAD_FOLDER (see app.py); this table only
# tracks the metadata needed to display, download, or delete it.
# ---------------------------------------------------------------------------

def get_cv_for_user(user_id):
    conn = get_db_connection()
    cv = conn.execute("SELECT * FROM cvs WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return cv


def save_cv(
    user_id,
    original_filename,
    stored_filename,
    file_extension,
    mime_type,
    file_size,
    content_sha256,
    extracted_text,
    extraction_status,
    page_count=None,
):
    """Insert or replace one user's CV metadata and extracted content."""
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO cvs (
            user_id, original_filename, stored_filename, file_extension,
            mime_type, file_size, content_sha256, extracted_text,
            extraction_status, page_count, uploaded_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            original_filename = excluded.original_filename,
            stored_filename = excluded.stored_filename,
            file_extension = excluded.file_extension,
            mime_type = excluded.mime_type,
            file_size = excluded.file_size,
            content_sha256 = excluded.content_sha256,
            extracted_text = excluded.extracted_text,
            extraction_status = excluded.extraction_status,
            page_count = excluded.page_count,
            uploaded_at = CURRENT_TIMESTAMP
        """,
        (
            user_id, original_filename, stored_filename, file_extension,
            mime_type, file_size, content_sha256, extracted_text,
            extraction_status, page_count,
        ),
    )
    conn.commit()
    conn.close()


def delete_cv(user_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM cvs WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def count_recent_application_attempts(user_id):
    conn = get_db_connection()
    count = conn.execute(
        """
        SELECT COUNT(*) FROM application_email_attempts
        WHERE user_id = ? AND created_at >= datetime('now', '-1 hour')
        """,
        (user_id,),
    ).fetchone()[0]
    conn.close()
    return count


def log_application_email_attempt(
    user_id, company_id, recipient_email, cv_filename, status,
    error_message="", application_id=None,
):
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO application_email_attempts
            (user_id, company_id, application_id, recipient_email,
             cv_filename, status, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id, company_id, application_id, recipient_email,
            cv_filename, status, error_message,
        ),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# TASK 8 — APPLICATION TRACKER / CRM
# Company details remain in companies_data.py; this table stores only the
# user's relationship with a company and the application pipeline details.
# ---------------------------------------------------------------------------

def get_applications_for_user(user_id):
    conn = get_db_connection()
    applications = conn.execute(
        "SELECT * FROM applications WHERE user_id = ? ORDER BY created_at DESC, id DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return applications


def get_application_for_user(user_id, application_id):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM applications WHERE id = ? AND user_id = ?",
        (application_id, user_id),
    ).fetchone()
    conn.close()
    return row


def get_gmail_credentials(user_id):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM gmail_credentials WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row


def save_gmail_credentials(
    user_id, token_encrypted, expires_at, scope, account_email=None, email_verified=None
):
    conn = get_db_connection()
    existing = conn.execute(
        "SELECT account_email, email_verified FROM gmail_credentials WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if account_email is None:
        account_email = existing["account_email"] if existing else ""
    if email_verified is None:
        email_verified = bool(existing["email_verified"]) if existing else False
    conn.execute(
        """
        INSERT INTO gmail_credentials (
            user_id, token_encrypted, expires_at, scope, account_email, email_verified
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            token_encrypted = excluded.token_encrypted,
            expires_at = excluded.expires_at,
            scope = excluded.scope,
            account_email = excluded.account_email,
            email_verified = excluded.email_verified,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, token_encrypted, expires_at, scope, account_email, int(email_verified)),
    )
    conn.commit()
    conn.close()


def delete_gmail_credentials(user_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM gmail_credentials WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def mark_application_sent(user_id, application_id, message_id, recipient_email):
    conn = get_db_connection()
    existing = conn.execute(
        "SELECT status FROM applications WHERE id = ? AND user_id = ?",
        (application_id, user_id),
    ).fetchone()
    if existing is None:
        conn.close()
        return None
    conn.execute(
        """
        UPDATE applications
        SET status = 'Sent', gmail_message_id = ?, recipient_email = ?,
            sent_at = CURRENT_TIMESTAMP, applied_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
        """,
        (message_id, recipient_email, application_id, user_id),
    )
    if existing["status"] != "Sent":
        conn.execute(
            """
            INSERT INTO application_history
                (user_id, application_id, event_type, description)
            VALUES (?, ?, 'Status changed', ?)
            """,
            (
                user_id, application_id,
                f"{existing['status'] or 'Draft'} → Sent; Gmail message ID {message_id}",
            ),
        )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM applications WHERE id = ? AND user_id = ?",
        (application_id, user_id),
    ).fetchone()
    conn.close()
    return row


def create_application(user_id, company_id, position, contact_email, status,
                       last_contact_date, notes):
    conn = get_db_connection()
    cursor = conn.execute(
        """
        INSERT INTO applications
            (user_id, company_id, position, contact_email, status, last_contact_date, notes, applied_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CASE WHEN ? IN (
            'Sent', 'Replied', 'Interview', 'Accepted', 'Rejected'
        ) THEN CURRENT_TIMESTAMP ELSE '' END)
        """,
        (user_id, company_id, position, contact_email, status, last_contact_date, notes, status),
    )
    application_id = cursor.lastrowid
    conn.execute(
        """
        INSERT INTO application_history
            (user_id, application_id, event_type, description)
        VALUES (?, ?, 'Status set', ?)
        """,
        (user_id, application_id, f"Initial status: {status}"),
    )
    conn.commit()
    application = conn.execute(
        "SELECT * FROM applications WHERE id = ? AND user_id = ?",
        (application_id, user_id),
    ).fetchone()
    conn.close()
    return application


def update_application(user_id, application_id, fields):
    allowed_fields = {
        "position", "contact_email", "status", "last_contact_date", "notes", "cv_used", "cover_letter_used"
    }
    updates = {key: value for key, value in fields.items() if key in allowed_fields}
    if not updates:
        return None

    conn = get_db_connection()
    existing = conn.execute(
        "SELECT status FROM applications WHERE id = ? AND user_id = ?",
        (application_id, user_id),
    ).fetchone()
    if existing is None:
        conn.close()
        return None
    assignments = [f"{key} = ?" for key in updates]
    assignments.append("updated_at = CURRENT_TIMESTAMP")
    if updates.get("status") in {"Sent", "Replied", "Interview", "Accepted", "Rejected"}:
        assignments.append(
            "applied_at = CASE WHEN applied_at = '' THEN CURRENT_TIMESTAMP ELSE applied_at END"
        )
    values = list(updates.values()) + [application_id, user_id]
    conn.execute(
        f"UPDATE applications SET {', '.join(assignments)} WHERE id = ? AND user_id = ?",
        values,
    )
    if "status" in updates and updates["status"] != existing["status"]:
        conn.execute(
            """
            INSERT INTO application_history
                (user_id, application_id, event_type, description)
            VALUES (?, ?, 'Status changed', ?)
            """,
            (
                user_id, application_id,
                f"{existing['status'] or 'Draft'} → {updates['status']}",
            ),
        )
    application = conn.execute(
        "SELECT * FROM applications WHERE id = ? AND user_id = ?",
        (application_id, user_id),
    ).fetchone()
    conn.commit()
    conn.close()
    return application


def find_application(user_id, company_id, position):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM applications WHERE user_id=? AND company_id=? AND lower(position)=lower(?)", (user_id, company_id, position)).fetchone()
    conn.close()
    return row


def add_history(user_id, application_id, event_type, description):
    conn = get_db_connection()
    conn.execute("INSERT INTO application_history(user_id, application_id, event_type, description) VALUES(?,?,?,?)", (user_id, application_id, event_type, description))
    conn.commit(); conn.close()


def get_history(user_id, application_id=None):
    conn = get_db_connection()
    sql = "SELECT * FROM application_history WHERE user_id=?"
    args = [user_id]
    if application_id is not None:
        sql += " AND application_id=?"; args.append(application_id)
    rows = conn.execute(sql + " ORDER BY created_at DESC, id DESC", args).fetchall()
    conn.close(); return rows


def get_reminders(user_id):
    conn = get_db_connection()
    rows = conn.execute("SELECT r.*, a.company_id, a.position FROM reminders r JOIN applications a ON a.id=r.application_id WHERE r.user_id=? ORDER BY r.completed, r.due_date", (user_id,)).fetchall()
    conn.close(); return rows


def create_reminder(user_id, application_id, due_date):
    conn = get_db_connection()
    cursor = conn.execute("INSERT INTO reminders(user_id, application_id, due_date) SELECT ?,id,? FROM applications WHERE id=? AND user_id=?", (user_id, due_date, application_id, user_id))
    conn.commit(); reminder_id = cursor.lastrowid if cursor.rowcount else None; conn.close(); return reminder_id


def update_reminder(user_id, reminder_id, action):
    conn = get_db_connection()
    if action == "delete": conn.execute("DELETE FROM reminders WHERE id=? AND user_id=?", (reminder_id, user_id))
    else: conn.execute("UPDATE reminders SET completed=1 WHERE id=? AND user_id=?", (reminder_id, user_id))
    conn.commit(); conn.close()


def create_notification(user_id, kind, title, message="", url=""):
    conn = get_db_connection(); conn.execute("INSERT INTO notifications(user_id,kind,title,message,url) VALUES(?,?,?,?,?)", (user_id,kind,title,message,url)); conn.commit(); conn.close()


def get_notifications(user_id):
    from backend.notification_events import emit_due_reminders
    from backend.radar_watch import sync_matching_notifications
    sync_matching_notifications(user_id)
    emit_due_reminders(user_id=user_id)
    conn = get_db_connection(); rows = conn.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT 30", (user_id,)).fetchall(); conn.close(); return rows


def notification_action(user_id, notification_id, action):
    conn = get_db_connection()
    if action == "clear": conn.execute("DELETE FROM notifications WHERE user_id=?", (user_id,))
    elif action == "read_all": conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user_id,))
    else: conn.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (notification_id,user_id))
    conn.commit(); conn.close()


# ---------------------------------------------------------------------------
# TASK 9 — CV BUILDER / OPTIMIZER
# The uploaded original remains in `cvs`; this row stores editable profiles
# and a distinct generated optimized version.
# ---------------------------------------------------------------------------

def get_cv_builder_data(user_id):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM cv_builder_data WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return {
            "profiles": {}, "templates": {}, "optimized": None,
            "optimized_source": "manual", "career_objective": "",
            "profile_photo_filename": "",
            "target_position": "", "career_field": "", "target_location": "", "target_skills": "",
            "career_goal": "", "education_level": "", "experience_level": "",
        }
    try:
        profiles = json.loads(row["profiles_json"])
        templates = json.loads(row["templates_json"])
        optimized = json.loads(row["optimized_json"]) if row["optimized_json"] else None
    except (TypeError, json.JSONDecodeError):
        profiles, templates, optimized = {}, {}, None
    return {
        "profiles": profiles if isinstance(profiles, dict) else {},
        "templates": templates if isinstance(templates, dict) else {},
        "optimized": optimized if isinstance(optimized, dict) else None,
        "optimized_source": row["optimized_source"],
        "career_objective": row["career_objective"],
        "profile_photo_filename": row["profile_photo_filename"],
        "target_position": row["target_position"],
        "career_field": row["career_field"],
        "target_location": row["target_location"],
        "target_skills": row["target_skills"],
        "career_goal": row["career_goal"],
        "education_level": row["education_level"],
        "experience_level": row["experience_level"],
    }


def save_cv_profile(user_id, source, profile, template):
    data = get_cv_builder_data(user_id)
    profiles = data["profiles"]
    templates = data["templates"]
    profiles[source] = profile
    templates[source] = template
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO cv_builder_data (user_id, profiles_json, templates_json, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            profiles_json = excluded.profiles_json,
            templates_json = excluded.templates_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, json.dumps(profiles), json.dumps(templates)),
    )
    conn.commit()
    conn.close()


def save_candidate_profile_metadata(
    user_id, career_objective, profile_photo_filename, target_position="",
    career_field="", target_location="", target_skills="", career_goal="",
    education_level="", experience_level="",
):
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO cv_builder_data
            (user_id, career_objective, profile_photo_filename, target_position, career_field,
             target_location, target_skills, career_goal, education_level, experience_level, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            career_objective = excluded.career_objective,
            profile_photo_filename = excluded.profile_photo_filename,
            target_position = excluded.target_position,
            career_field = excluded.career_field,
            target_location = excluded.target_location,
            target_skills = excluded.target_skills,
            career_goal = excluded.career_goal,
            education_level = excluded.education_level,
            experience_level = excluded.experience_level,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, career_objective, profile_photo_filename, target_position, career_field,
         target_location, target_skills, career_goal, education_level, experience_level),
    )
    conn.commit()
    conn.close()


def save_optimized_cv(user_id, source, optimized):
    conn = get_db_connection()
    try:
        with conn:
            cursor = conn.execute("INSERT INTO cv_versions(user_id,source,optimized_json) VALUES(?,?,?)",
                                  (user_id, source, json.dumps(optimized, ensure_ascii=False)))
            version_id = cursor.lastrowid
            snapshot = {**optimized, 'version_id': version_id}
            conn.execute('UPDATE cv_versions SET optimized_json=? WHERE id=?', (json.dumps(snapshot,ensure_ascii=False),version_id))
            conn.execute("""INSERT INTO cv_builder_data(user_id,optimized_json,optimized_source,updated_at)
                VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET
                optimized_json=excluded.optimized_json,optimized_source=excluded.optimized_source,
                updated_at=CURRENT_TIMESTAMP""", (user_id,json.dumps(snapshot,ensure_ascii=False),source))
        return version_id
    finally:
        conn.close()


def get_cv_versions(user_id):
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM cv_versions WHERE user_id=? ORDER BY id DESC",(user_id,)).fetchall()
    conn.close()
    result=[]
    for row in rows:
        item=dict(row)
        try:
            item['optimized']=json.loads(item.pop('optimized_json'))
        except (ValueError, TypeError):
            continue
        result.append(item)
    return result


def get_cv_version(user_id, version_id):
    conn=get_db_connection()
    row=conn.execute("SELECT * FROM cv_versions WHERE user_id=? AND id=?",(user_id,version_id)).fetchone()
    conn.close()
    if row is None:
        return None
    item=dict(row)
    try:
        item['optimized']=json.loads(item.pop('optimized_json'))
    except (ValueError,TypeError):
        return None
    return item


# ============================================================
# REAL LOCAL COMPANIES / OFFERS
# ============================================================

def get_all_companies_from_db():
    conn = get_db_connection()
    try:
        rows = conn.execute("""
            SELECT
                id,
                name,
                category,
                area,
                address,
                email,
                phone,
                website,
                description,
                lat,
                lng,
                has_offer,
                status,
                notes,
                google_maps_url,
                rating,
                review_count,
                business_status,
                data_source
            FROM companies
            ORDER BY name COLLATE NOCASE
        """).fetchall()

        return [
            {
                "id": row["id"],
                "name": row["name"],
                "category": row["category"],
                "area": row["area"],
                "address": row["address"],
                "email": row["email"],
                "phone": row["phone"] or "",
                "website": row["website"],
                "description": row["description"],
                "lat": row["lat"],
                "lng": row["lng"],
                "has_offer": bool(row["has_offer"]),
                "status": row["status"],
                "notes": row["notes"],
                "google_maps_url": row["google_maps_url"],
                "rating": row["rating"],
                "review_count": row["review_count"],
                "business_status": row["business_status"],
                "data_source": row["data_source"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_company_from_db(company_id):
    conn = get_db_connection()
    try:
        row = conn.execute("""
            SELECT
                id,
                name,
                category,
                area,
                address,
                email,
                phone,
                website,
                description,
                lat,
                lng,
                has_offer,
                status,
                notes,
                google_maps_url,
                rating,
                review_count,
                business_status,
                data_source
            FROM companies
            WHERE id = ?
        """, (company_id,)).fetchone()

        if not row:
            return None

        return {
            "id": row["id"],
            "name": row["name"],
            "category": row["category"],
            "area": row["area"],
            "address": row["address"],
            "email": row["email"],
            "phone": row["phone"] or "",
            "website": row["website"],
            "description": row["description"],
            "lat": row["lat"],
            "lng": row["lng"],
            "has_offer": bool(row["has_offer"]),
            "status": row["status"],
            "notes": row["notes"],
            "google_maps_url": row["google_maps_url"],
            "rating": row["rating"],
            "review_count": row["review_count"],
            "business_status": row["business_status"],
            "data_source": row["data_source"],
        }
    finally:
        conn.close()


def update_company_status(company_id, status):
    """Persist an existing Companies-page tracking status."""
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "UPDATE companies SET status = ? WHERE id = ?",
            (status, company_id),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def get_all_offers_from_db():
    conn = get_db_connection()
    try:
        rows = conn.execute("""
            SELECT
                id,
                company_id,
                company_name,
                title,
                offer_type,
                requirements,
                description,
                location,
                publication_date,
                url,
                source
            FROM offers
            WHERE id IN (SELECT offer_id FROM offer_catalog_status WHERE is_active=1 AND verified_at>=datetime('now','-7 days'))
            ORDER BY id DESC
        """).fetchall()

        import json

        result = []

        for row in rows:
            from backend.offer_lifecycle import recent_offer
            if not recent_offer(dict(row)):
                continue
            try:
                requirements = json.loads(row["requirements"] or "[]")
            except Exception:
                requirements = []

            result.append({
                "id": row["id"],
                "company_id": row["company_id"],
                "company_name": row["company_name"],
                "title": row["title"],
                "requirements": requirements,
                "category": row["offer_type"],
                "description": row["description"],
                "location": row["location"],
                "contract_type": row["offer_type"],
                "published_at": row["publication_date"],
                "publication_date": row["publication_date"],
                "url": row["url"],
                "source": row["source"],
            })

        return result
    finally:
        conn.close()


def get_offers_for_company_from_db(company_id):
    conn = get_db_connection()
    try:
        rows = conn.execute("""
            SELECT
                id,
                company_id,
                company_name,
                title,
                offer_type,
                requirements,
                description,
                location,
                publication_date,
                url,
                source
            FROM offers
            WHERE company_id = ?
              AND id IN (SELECT offer_id FROM offer_catalog_status WHERE is_active=1 AND verified_at>=datetime('now','-7 days'))
            ORDER BY id DESC
        """, (company_id,)).fetchall()

        import json

        result = []

        for row in rows:
            from backend.offer_lifecycle import recent_offer
            if not recent_offer(dict(row)):
                continue
            try:
                requirements = json.loads(row["requirements"] or "[]")
            except Exception:
                requirements = []

            result.append({
                "id": row["id"],
                "company_id": row["company_id"],
                "company_name": row["company_name"],
                "title": row["title"],
                "requirements": requirements,
                "category": row["offer_type"],
                "description": row["description"],
                "location": row["location"],
                "contract_type": row["offer_type"],
                "published_at": row["publication_date"],
                "publication_date": row["publication_date"],
                "url": row["url"],
                "source": row["source"],
            })

        return result
    finally:
        conn.close()
