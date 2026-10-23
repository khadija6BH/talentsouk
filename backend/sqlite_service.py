from datetime import datetime
"""SQLite query and persistence services for TalentSouk."""

from backend.career_dna_service import get_unified_candidate_profile

import json
import os
import re
from backend.application_status import APPLICATION_STATUSES, normalize_application_status, application_counts

from backend.database import (
    get_all_companies_from_db,
    get_company_from_db,
    get_all_offers_from_db,
    get_offers_for_company_from_db,
    get_cv_builder_data,
    get_db_connection,
    get_user_by_id,
    uses_postgres,
)


def get_companies():
    return get_all_companies_from_db()


def get_jobs():
    return get_all_offers_from_db()


def fetch_companies_for_api(limit=100, offset=0):
    companies = get_all_companies_from_db()
    return companies[offset:offset + limit]


def query_companies_for_api(
    query="",
    city="",
    category="",
    has_email=None,
    min_score=None,
    limit=100,
    offset=0,
):
    from backend.company_catalog import attach_domains
    companies = [attach_domains(company) for company in get_all_companies_from_db()]

    query = (query or "").strip().lower()
    city = (city or "").strip().lower()
    category = (category or "").strip().lower()

    if query:
        companies = [
            c for c in companies
            if query in (c.get("name") or "").lower()
            or query in (c.get("category") or "").lower()
            or query in (c.get("address") or "").lower()
            or query in (c.get("area") or "").lower()
        ]

    if city:
        companies = [
            c for c in companies
            if city in (c.get("area") or "").lower()
            or city in (c.get("address") or "").lower()
        ]

    if category:
        companies = [
            c for c in companies
            if any(category in domain.lower() for domain in c.get("domains",[]))
        ]

    if has_email is True:
        companies = [
            c for c in companies
            if (c.get("email") or "").strip()
        ]
    elif has_email is False:
        companies = [
            c for c in companies
            if not (c.get("email") or "").strip()
        ]

    if min_score is not None:
        # SQLite real data does not have an AI score.
        # Keep compatibility without inventing a score.
        try:
            minimum = float(min_score)
            if minimum > 0:
                companies = []
        except (TypeError, ValueError):
            pass

    total = len(companies)
    companies = companies[offset:offset + limit]

    return {
        "items": companies,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def fetch_jobs_for_api(limit=100, offset=0):
    jobs = get_all_offers_from_db()

    items = []

    for job in jobs[offset:offset + limit]:
        items.append({
            "id": job["id"],
            "title": job["title"],
            "company_name": job["company_name"],
            "location": job["location"],
            "source": job["source"],
            "contract_type": job["contract_type"],
            "publication_date": job["publication_date"],
            "description": job["description"],
            "url": job["url"],
        })

    return items


def query_jobs_for_api(
    query="",
    location="",
    source="",
    contract_type="",
    company_id=None,
    limit=100,
    offset=0,
):
    jobs = get_all_offers_from_db()

    query = (query or "").strip().lower()
    location = (location or "").strip().lower()
    source = (source or "").strip().lower()
    contract_type = (contract_type or "").strip().lower()

    if query:
        jobs = [
            job for job in jobs
            if query in (job.get("title") or "").lower()
            or query in (job.get("company_name") or "").lower()
            or query in (job.get("description") or "").lower()
        ]

    if location:
        jobs = [
            job for job in jobs
            if location in (job.get("location") or "").lower()
        ]

    if source:
        jobs = [
            job for job in jobs
            if source in (job.get("source") or "").lower()
        ]

    if contract_type:
        jobs = [
            job for job in jobs
            if contract_type in (job.get("contract_type") or "").lower()
        ]

    if company_id is not None:
        jobs = [job for job in jobs if job.get("company_id") == company_id]

    total = len(jobs)

    items = []
    for job in jobs[offset:offset + limit]:
        items.append({
            "id": job["id"],
            "title": job["title"],
            "company_name": job["company_name"],
            "location": job["location"],
            "source": job["source"],
            "contract_type": job["contract_type"],
            "publication_date": job["publication_date"],
            "description": job["description"],
            "url": job["url"],
        })

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def fetch_contacts_for_api(company_id=None):
    conn = get_db_connection()

    try:
        if company_id is not None:
            rows = conn.execute(
                """
                SELECT
                    id,
                    company_id,
                    contact_type,
                    email,
                    phone,
                    source,
                    is_verified,
                    created_at
                FROM company_contacts
                WHERE company_id = ?
                ORDER BY id DESC
                """,
                (company_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    id,
                    company_id,
                    contact_type,
                    email,
                    phone,
                    source,
                    is_verified,
                    created_at
                FROM company_contacts
                ORDER BY id DESC
                """
            ).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()


def get_job_offer_for_application(application):
    """Return the real offer associated with an application when possible."""

    if application is None:
        return None

    if isinstance(application, dict):
        offer_id = application.get("offer_id") or application.get("job_id")
    else:
        offer_id = application

    if offer_id is None:
        return None

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM offers WHERE id = ?",
            (int(offer_id),)
        ).fetchone()

        if row is None:
            return None

        return {
            "id": row["id"],
            "company_id": row["company_id"],
            "company_name": row["company_name"],
            "title": row["title"],
            "requirements": row["requirements"],
            "category": row["offer_type"],
            "description": row["description"],
            "location": row["location"],
            "contract_type": row["offer_type"],
            "published_at": row["publication_date"],
            "publication_date": row["publication_date"],
            "url": row["url"],
            "source": row["source"],
        }
    finally:
        conn.close()


def fetch_dashboard_stats(user_id=None):
    """Dashboard statistics based only on real local SQLite data."""

    conn = get_db_connection()

    try:
        total_companies = conn.execute(
            "SELECT COUNT(*) AS count FROM companies"
        ).fetchone()["count"]

        published_offers = get_all_offers_from_db()
        total_jobs_offers = len(published_offers)

        companies_with_contact_email = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM companies
            WHERE TRIM(COALESCE(email, '')) <> ''
            """
        ).fetchone()["count"]

        rows = conn.execute("SELECT status FROM applications" + (" WHERE user_id = ?" if user_id is not None else ""), (user_id,) if user_id is not None else ()).fetchall()
        counts = application_counts(rows)
        total_applications = len(rows)
        wishlist = counts["Wishlist"]
        contacted = applied = sum(counts[status] for status in ("Sent", "Replied", "Interview", "Accepted", "Rejected"))
        replied = counts["Replied"] + counts["Interview"] + counts["Accepted"]
        interviews = counts["Interview"] + counts["Accepted"]
        response_rate = round((replied / contacted) * 100, 1) if contacted else 0

        technology_domains = {
            "AI": ("artificial intelligence", "machine learning", "deep learning", "intelligence artificielle", " ia "),
            "Data Analysis": ("data analyst", "data analysis", "business intelligence", "power bi", "tableau"),
            "Data Science": ("data scientist", "data science", "science des données", "big data"),
            "Software Development": ("software developer", "software engineer", "développeur logiciel", "java", ".net"),
            "Web Development": ("web developer", "développeur web", "frontend", "front-end", "backend", "back-end", "full stack"),
            "Cybersecurity": ("cybersecurity", "cyber security", "cybersécurité", "security engineer", "soc analyst"),
            "Cloud Computing": ("cloud", "aws", "azure", "devops", "kubernetes"),
            "Networking": ("network engineer", "network administrator", "réseau", "networking", "cisco"),
        }
        technology_market = {domain: 0 for domain in technology_domains}
        offer_rows = published_offers
        for row in offer_rows:
            searchable = " " + " ".join(
                str(row[field] or "") for field in ("title", "description", "requirements")
            ).casefold() + " "
            for domain, keywords in technology_domains.items():
                if any(keyword.casefold() in searchable for keyword in keywords):
                    technology_market[domain] += 1

        current_month = datetime.now()
        month_keys = []
        for months_ago in range(5, -1, -1):
            absolute_month = current_month.year * 12 + current_month.month - 1 - months_ago
            month_keys.append(f"{absolute_month // 12:04d}-{absolute_month % 12 + 1:02d}")
        trend_params = () if user_id is None else (user_id,)
        trend_where = "" if user_id is None else "WHERE user_id = ?"
        trend_rows = conn.execute(
            f"""
            SELECT SUBSTR(created_at, 1, 7) AS month, COUNT(*) AS count
            FROM applications {trend_where}
            GROUP BY SUBSTR(created_at, 1, 7)
            """,
            trend_params,
        ).fetchall()
        trend_counts = {row["month"]: row["count"] for row in trend_rows}

        return {
            "total_companies": total_companies,
            "companies_with_contact_email": companies_with_contact_email,
            "total_jobs_offers": total_jobs_offers,
            "total_applications": total_applications,
            "contacted_companies": contacted,
            "replied_applications_contacts": replied,
            "interviews": interviews,
            "response_rate": response_rate,
            "technology_market": technology_market,
            "application_trend": [
                {"month": month, "count": trend_counts.get(month, 0)}
                for month in month_keys
            ],

            "status_counts": counts,
            "funnel_method": "Stage reached: Interview includes Accepted; Replied includes Interview and Accepted. Rejected has no inferred prior reply.",
            "funnel": {
                "Discovered": total_companies,
                "Contacted": contacted,
                "Wishlist": wishlist,
                "Applied": applied,
                "Replied": replied,
                "Interview": interviews,
            },
        }

    finally:
        conn.close()

def connection_status():
    postgres = uses_postgres()
    conn = None
    try:
        conn = get_db_connection()
        conn.execute('SELECT 1').fetchone()
        ok = True
    except Exception:
        ok = False  # Never include connection errors or credentials in a public response.
    finally:
        if conn is not None:
            conn.close()
    return {'ok': ok, 'connected': ok, 'provider': 'PostgreSQL' if postgres else 'SQLite',
            'database': os.environ.get('DATABASE_SCHEMA', 'talentsouk') if postgres else 'database.db'}


def fetch_ai_context(job_id, user_id):
    """Build AI helper input from the logged-in user's local SQLite data."""
    offer = get_job_offer_for_application(job_id)
    if offer is None:
        raise LookupError("Job offer not found")

    company = (
        get_company_from_db(offer["company_id"])
        if offer.get("company_id") is not None
        else None
    )
    if company is None:
        company = {
            "id": offer.get("company_id"),
            "name": offer.get("company_name") or "Company",
            "area": offer.get("location") or "",
            "address": offer.get("location") or "",
            "description": "",
            "email": "",
        }

    profile = get_unified_candidate_profile(user_id)

    requirements = offer.get("requirements")
    if isinstance(requirements, str):
        try:
            requirements = json.loads(requirements or "[]")
        except json.JSONDecodeError:
            requirements = re.split(r"[\n,;]+", requirements)
    requirements = [
        str(value).strip() for value in (requirements or []) if str(value).strip()
    ]
    offer["requirements"] = requirements

    skill_names = [
        value.strip()
        for value in re.split(r"[\n,;]+", str(profile.get("skills") or ""))
        if value.strip()
    ]
    candidate_skills = [
        {"id": name.casefold(), "name": name, "category": "", "level": None}
        for name in skill_names
    ]
    required_skills = [
        {"id": name.casefold(), "name": name, "category": "", "required": True}
        for name in requirements
    ]
    return {
        "profile": profile,
        "company": company,
        "offer": offer,
        "candidate_skills": candidate_skills,
        "required_skills": required_skills,
        "source": "SQLite",
    }


# ============================================================
# APPLICATIONS + CRM
# ============================================================

def _ensure_sqlite_schema():
    """Add required SQLite columns/tables without deleting existing data."""
    conn = get_db_connection()

    try:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(applications)").fetchall()
        }

        if "job_id" not in columns:
            conn.execute("ALTER TABLE applications ADD COLUMN job_id INTEGER")

        if "profile_id" not in columns:
            conn.execute("ALTER TABLE applications ADD COLUMN profile_id TEXT")

        if "application_message" not in columns:
            conn.execute(
                "ALTER TABLE applications ADD COLUMN application_message TEXT NOT NULL DEFAULT ''"
            )
        for column in ("gmail_message_id", "sent_at", "recipient_email"):
            if column not in columns:
                conn.execute(
                    f"ALTER TABLE applications ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS crm (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                company_id INTEGER NOT NULL,
                contact_email TEXT,
                status TEXT NOT NULL DEFAULT 'Draft',
                last_contact_date TEXT,
                next_followup_date TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)
        crm_columns = {row["name"] for row in conn.execute("PRAGMA table_info(crm)").fetchall()}
        if "application_id" not in crm_columns:
            conn.execute("ALTER TABLE crm ADD COLUMN application_id INTEGER")

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_crm_company
            ON crm(company_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_crm_user
            ON crm(user_id)
        """)

        conn.commit()

    finally:
        conn.close()


def get_default_profile_id():
    """Use the currently available local user as the default profile."""
    try:
        conn = get_db_connection()
        row = conn.execute(
            "SELECT id FROM users ORDER BY id LIMIT 1"
        ).fetchone()
        conn.close()

        if row:
            return str(row["id"])

    except Exception:
        return ""

    return ""


def _profile_to_user_id(profile_id):
    """Convert local profile id to local user id."""
    if profile_id is None:
        return None

    value = str(profile_id).strip()

    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def _application_to_api(row):
    """Normalize a local application for the existing frontend."""
    item = dict(row)

    company_id = item.get("company_id")
    company = get_company_from_db(company_id) if company_id is not None else None

    offer_id = item.get("job_id")

    offer = None
    if offer_id is not None:
        offers = get_all_offers_from_db()
        offer = next(
            (x for x in offers if x["id"] == offer_id),
            None,
        )

    return {
        "id": item.get("id"),
        "profile_id": item.get("profile_id"),
        "user_id": item.get("user_id"),
        "company_id": company_id,
        "job_id": offer_id,
        "offer_id": offer_id,
        "company_name": (
            offer["company_name"]
            if offer and offer.get("company_id") is None
            else company["name"] if company
            else offer["company_name"] if offer
            else ""
        ),
        "position": item.get("position") or (
            offer["title"] if offer else ""
        ),
        "title": item.get("position") or (
            offer["title"] if offer else ""
        ),
        "status": normalize_application_status(item.get("status")),
        "contact_email": item.get("contact_email"),
        "last_contact_date": item.get("last_contact_date"),
        "applied_at": item.get("applied_at"),
        "notes": item.get("notes") or "",
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "cv_used": item.get("cv_used"),
        "cover_letter_used": item.get("cover_letter_used"),
        "application_message": item.get("application_message") or "",
        "gmail_message_id": item.get("gmail_message_id") or "",
        "sent_at": item.get("sent_at") or "",
        "recipient_email": item.get("recipient_email") or "",
        "url": offer["url"] if offer else "",
        "source": offer["source"] if offer else "",
    }


def fetch_applications_for_api(user_id=None):
    _ensure_sqlite_schema()

    if user_id is None:
        return []

    conn = get_db_connection()

    try:
        rows = conn.execute("""
            SELECT *
            FROM applications
            WHERE user_id = ?
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
        """, (user_id,)).fetchall()

        return [
            _application_to_api(row)
            for row in rows
        ]

    finally:
        conn.close()


def create_tracked_application(values, notes=""):
    """Create or update a user's tracked application in SQLite."""

    _ensure_sqlite_schema()

    user_id = values.get("user_id")
    company_id = values.get("company_id")
    job_id = values.get("job_id")

    if user_id is None:
        raise ValueError("user_id is required")
    if company_id is None:
        raise ValueError("company_id is required")
    profile_id = str(values.get("profile_id") or user_id)

    conn = get_db_connection()

    try:
        # Serialize the duplicate check and write so two Apply requests cannot
        # create two rows for the same user and offer.
        conn.execute("BEGIN IMMEDIATE")

        company = conn.execute(
            "SELECT id FROM companies WHERE id = ?",
            (company_id,),
        ).fetchone()
        if company is None:
            raise ValueError("Company not found")

        offer = None
        if job_id is not None:
            offer_row = conn.execute(
                "SELECT * FROM offers WHERE id = ?",
                (job_id,),
            ).fetchone()
            if offer_row is None:
                raise ValueError("Job offer not found")

            offer = dict(offer_row)
            if offer.get("company_id") is not None and offer["company_id"] != company_id:
                raise ValueError("The job offer does not belong to the selected company")
            position = str(offer.get("title") or "").strip()
            if not position:
                raise ValueError("Job offer title is missing")
        else:
            position = str(values.get("position") or "Spontaneous internship/PFE application").strip()
            if not position:
                raise ValueError("position is required")

        now = datetime.now().astimezone().isoformat()

        status = normalize_application_status(values.get("status"))
        applied_at = str(values.get("applied_at") or "")
        if not applied_at and status.casefold() == "applied":
            applied_at = now

        if job_id is not None:
            existing = conn.execute(
                "SELECT * FROM applications WHERE user_id = ? AND job_id = ? ORDER BY id LIMIT 1",
                (user_id, job_id),
            ).fetchone()
        else:
            existing = conn.execute(
                """
                SELECT * FROM applications
                WHERE user_id = ? AND company_id = ? AND job_id IS NULL
                  AND lower(position) = lower(?)
                ORDER BY id LIMIT 1
                """,
                (user_id, company_id, position),
            ).fetchone()

        cv_used = str(values.get("cv_used") or "")
        cover_letter_used = str(values.get("cover_letter_used") or "")
        application_message = str(values.get("application_message") or "")
        if existing is not None:
            if values.get('preserve_sent_cv') and normalize_application_status(existing['status']) not in {'Draft','Wishlist'}:
                raise ValueError('This application has already progressed. Its saved CV cannot be replaced.')
            previous_status = existing["status"] or "Draft"
            existing_notes = existing["notes"] or ""
            conn.execute("""
                UPDATE applications
                SET company_id = ?, profile_id = ?, position = ?, status = ?,
                    applied_at = ?, updated_at = ?, notes = ?, cv_used = ?, cover_letter_used = ?,
                    application_message = ?
                WHERE id = ? AND user_id = ?
            """, (
                company_id,
                profile_id,
                position,
                status,
                applied_at or existing["applied_at"] or "",
                now,
                notes if notes else existing_notes,
                cv_used or existing["cv_used"] or "",
                cover_letter_used or existing["cover_letter_used"] or "",
                application_message or existing["application_message"] or "",
                existing["id"],
                user_id,
            ))
            if status != previous_status:
                conn.execute(
                    """
                    INSERT INTO application_history
                        (user_id, application_id, event_type, description)
                    VALUES (?, ?, 'Status changed', ?)
                    """,
                    (user_id, existing["id"], f"{previous_status} → {status}"),
                )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM applications WHERE id = ? AND user_id = ?",
                (existing["id"], user_id),
            ).fetchone()
            return _application_to_api(row)

        cursor = conn.execute("""
            INSERT INTO applications (
                user_id,
                company_id,
                position,
                contact_email,
                status,
                last_contact_date,
                notes,
                created_at,
                applied_at,
                updated_at,
                job_id,
                profile_id,
                cv_used,
                cover_letter_used,
                application_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            company_id,
            position,
            "",
            status,
            "",
            notes or "",
            now,
            applied_at or "",
            now,
            job_id,
            profile_id,
            cv_used,
            cover_letter_used,
            application_message,
        ))
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

        row = conn.execute(
            "SELECT * FROM applications WHERE id = ? AND user_id = ?",
            (application_id, user_id),
        ).fetchone()

        return _application_to_api(row)

    finally:
        conn.close()


def update_tracked_application(application_id, user_id, fields, notes=None):
    _ensure_sqlite_schema()

    conn = get_db_connection()

    try:
        existing = conn.execute(
            "SELECT * FROM applications WHERE id = ? AND user_id = ?",
            (application_id, user_id),
        ).fetchone()

        if not existing:
            return None

        updates = []
        params = []

        if "company_id" in fields:
            updates.append("company_id = ?")
            params.append(fields["company_id"])

        if "job_id" in fields:
            updates.append("job_id = ?")

            params.append(fields["job_id"])

            offer = conn.execute(
                "SELECT title FROM offers WHERE id = ?",
                (fields["job_id"],),
            ).fetchone()

            if offer:
                updates.append("position = ?")
                params.append(offer["title"])

        if "status" in fields:
            updates.append("status = ?")
            params.append(fields["status"])

        if "applied_at" in fields:
            updates.append("applied_at = ?")
            params.append(fields["applied_at"])

        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        updates.append("updated_at = ?")
        params.append(datetime.now().astimezone().isoformat())

        if not updates:
            return _application_to_api(existing)

        params.extend((application_id, user_id))

        conn.execute(
            f"""
            UPDATE applications
            SET {", ".join(updates)}
            WHERE id = ? AND user_id = ?
            """,
            params,
        )

        if "status" in fields and fields["status"] != (existing["status"] or "Draft"):
            conn.execute(
                """
                INSERT INTO application_history
                    (user_id, application_id, event_type, description)
                VALUES (?, ?, 'Status changed', ?)
                """,
                (
                    user_id, application_id,
                    f"{existing['status'] or 'Draft'} → {fields['status']}",
                ),
            )

        conn.commit()

        row = conn.execute(
            "SELECT * FROM applications WHERE id = ? AND user_id = ?",
            (application_id, user_id),
        ).fetchone()

        return _application_to_api(row)

    finally:
        conn.close()


def delete_tracked_application(application_id, user_id):
    _ensure_sqlite_schema()

    conn = get_db_connection()

    try:
        cursor = conn.execute(
            "DELETE FROM applications WHERE id = ? AND user_id = ?",
            (application_id, user_id),
        )

        conn.commit()

        return cursor.rowcount > 0

    finally:
        conn.close()


# ============================================================
# CRM
# ============================================================

def _crm_to_api(row):
    if not row:
        return None

    item = dict(row)

    company = get_company_from_db(item["company_id"])

    return {
        "id": item["id"],
        "application_id": item.get("application_id"),
        "user_id": item.get("user_id"),
        "company_id": item["company_id"],
        "company_name": company["name"] if company else "Company removed from catalog",
        "category": company["category"] if company else "Archived",
        "read_only": not bool(company),
        "contact_email": item.get("contact_email"),
        "email": item.get("contact_email"),
        "status": normalize_application_status(item.get("status")),
        "last_contact_date": item.get("last_contact_date"),
        "next_followup_date": item.get("next_followup_date"),
        "notes": item.get("notes") or "",
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


def fetch_crm_for_api(user_id=None):
    _ensure_sqlite_schema()

    if user_id is None:
        return []

    conn = get_db_connection()

    try:
        conn.execute(
            """
            INSERT INTO crm (
                user_id, company_id, application_id, contact_email, status,
                last_contact_date, notes, created_at, updated_at
            )
            SELECT a.user_id, a.company_id, a.id,
                   COALESCE(NULLIF(a.recipient_email, ''), NULLIF(a.contact_email, '')),
                   a.status, NULLIF(a.last_contact_date, ''), a.notes,
                   a.created_at, a.updated_at
            FROM applications AS a
            JOIN companies AS c ON c.id=a.company_id
            WHERE a.user_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM crm WHERE crm.user_id = a.user_id
                    AND crm.application_id = a.id
              )
            """,
            (user_id,),
        )
        conn.commit()
        rows = conn.execute("""
            SELECT *
            FROM crm
            WHERE user_id = ?
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
        """, (user_id,)).fetchall()

        records=[_crm_to_api(row) for row in rows]
        # Removed catalog entries must not break synchronization or erase personal history.
        archived=conn.execute("""
            SELECT a.* FROM applications a
            LEFT JOIN companies c ON c.id=a.company_id
            WHERE a.user_id=? AND c.id IS NULL
              AND NOT EXISTS(SELECT 1 FROM crm WHERE crm.user_id=a.user_id AND crm.application_id=a.id)
            ORDER BY a.created_at DESC,a.id DESC
        """,(user_id,)).fetchall()
        for row in archived:
            records.append(dict(id="archived-"+str(row["id"]),application_id=row["id"],
                user_id=user_id,company_id=row["company_id"],company_name="Company removed from catalog",
                category="Archived",read_only=True,position=row["position"],
                contact_email=row["contact_email"],email=row["contact_email"],
                status=normalize_application_status(row["status"]),last_contact_date=row["last_contact_date"],
                next_followup_date=None,notes=row["notes"] or "",created_at=row["created_at"],updated_at=row["updated_at"]))
        return records

    finally:
        conn.close()


def create_crm_record(values):
    _ensure_sqlite_schema()

    conn = get_db_connection()

    try:
        user_id = values.get("user_id")
        if user_id is None:
            raise ValueError("user_id is required")

        now = datetime.now().astimezone().isoformat()

        application_cursor = conn.execute(
            """
            INSERT INTO applications (
                user_id, company_id, position, contact_email, status,
                last_contact_date, notes, created_at, updated_at
            ) VALUES (?, ?, 'General application', ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, values["company_id"], values.get("contact_email") or "",
                values.get("status", "Draft"), values.get("last_contact_date") or "",
                values.get("notes", ""), now, now,
            ),
        )
        cursor = conn.execute("""
            INSERT INTO crm (
                user_id,
                company_id,
                application_id,
                contact_email,
                status,
                last_contact_date,
                next_followup_date,
                notes,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            values["company_id"],
            application_cursor.lastrowid,
            values.get("contact_email"),
            values.get("status", "Draft"),
            values.get("last_contact_date"),
            values.get("next_followup_date"),
            values.get("notes", ""),
            now,
            now,
        ))

        record_id = cursor.lastrowid
        conn.commit()

        row = conn.execute(
            "SELECT * FROM crm WHERE id = ?",
            (record_id,),
        ).fetchone()

        return _crm_to_api(row)

    finally:
        conn.close()


def update_crm_record(record_id, user_id, values):
    _ensure_sqlite_schema()

    conn = get_db_connection()

    try:
        existing = conn.execute(
            "SELECT * FROM crm WHERE id = ? AND user_id = ?",
            (record_id, user_id),
        ).fetchone()

        if not existing:
            return None

        allowed = {
            "company_id",
            "contact_email",
            "status",
            "last_contact_date",
            "next_followup_date",
            "notes",
            "updated_at",
        }

        updates = []
        params = []

        for key, value in values.items():
            if key in allowed:
                updates.append(f"{key} = ?")
                params.append(value)

        if not updates:
            return _crm_to_api(existing)

        params.extend((record_id, user_id))

        conn.execute(
            f"""
            UPDATE crm
            SET {", ".join(updates)}
            WHERE id = ? AND user_id = ?
            """,
            params,
        )

        application_id = existing["application_id"] if "application_id" in existing.keys() else None
        if application_id:
            mirrored = {key: value for key, value in values.items() if key in {"contact_email", "status", "last_contact_date", "notes"}}
            if mirrored:
                assignments = [f"{key} = ?" for key in mirrored]
                assignments.append("updated_at = CURRENT_TIMESTAMP")
                conn.execute(
                    f"UPDATE applications SET {', '.join(assignments)} WHERE id = ? AND user_id = ?",
                    [*mirrored.values(), application_id, user_id],
                )

        conn.commit()

        row = conn.execute(
            "SELECT * FROM crm WHERE id = ? AND user_id = ?",
            (record_id, user_id),
        ).fetchone()

        return _crm_to_api(row)

    finally:
        conn.close()


def delete_crm_record(record_id, user_id):
    _ensure_sqlite_schema()

    conn = get_db_connection()

    try:
        existing = conn.execute(
            "SELECT application_id FROM crm WHERE id = ? AND user_id = ?",
            (record_id, user_id),
        ).fetchone()
        cursor = conn.execute(
            "DELETE FROM crm WHERE id = ? AND user_id = ?",
            (record_id, user_id),
        )
        if existing and existing["application_id"]:
            conn.execute(
                "DELETE FROM applications WHERE id = ? AND user_id = ?",
                (existing["application_id"], user_id),
            )

        conn.commit()

        return cursor.rowcount > 0

    finally:
        conn.close()


# Make sure the SQLite schema exists when this module is loaded.
_ensure_sqlite_schema()













