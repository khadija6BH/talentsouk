from pathlib import Path
from datetime import datetime
from contextlib import closing
import sqlite3
import re
import unicodedata

from backend.market_sync import MarketSync


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "database.db"
DATA_DIR = BASE_DIR / "data"

COMPANIES_FILE = DATA_DIR / "entreprises_Marrakech_FINAL.csv"
JOBS_FILE = DATA_DIR / "all_jobs_marrakech (2).csv"

BACKUP_DIR = DATA_DIR / "backups"


# ============================================================
# HELPERS
# ============================================================

def clean(value):
    if value is None:
        return ""

    if pd.isna(value):
        return ""

    return str(value).strip()


def normalize_name(value):
    """
    Normalisation prudente uniquement.
    Pas de fuzzy matching.
    """
    value = clean(value)

    value = unicodedata.normalize(
        "NFKD",
        value
    ).encode(
        "ascii",
        "ignore"
    ).decode(
        "ascii"
    )

    value = value.lower()

    value = re.sub(r"[^a-z0-9]+", "", value)

    return value


def table_exists(conn, table_name):
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name=?
        """,
        (table_name,)
    ).fetchone()

    return row is not None


def columns_of(conn, table_name):
    return [
        row[1]
        for row in conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    ]


def main():
    global pd
    import pandas as pd
    # ============================================================
    # VALIDATION
    # ============================================================

    print("=" * 70)
    print("TALENTSOUK - REAL DATA IMPORT")
    print("=" * 70)

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Database introuvable: {DB_PATH}"
        )

    if not COMPANIES_FILE.exists():
        raise FileNotFoundError(
            f"CSV entreprises introuvable: {COMPANIES_FILE}"
        )

    if not JOBS_FILE.exists():
        raise FileNotFoundError(
            f"CSV introuvable: {JOBS_FILE}"
        )


    # ============================================================
    # BACKUP
    # ============================================================

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    backup_path = (
        BACKUP_DIR /
        f"TalentSouk_before_real_import_{timestamp}.db"
    )

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as source_db, closing(sqlite3.connect(backup_path)) as backup_db:
        source_db.backup(backup_db)

    print()
    print(f"[OK] Backup created:")
    print(f"     {backup_path}")


    # ============================================================
    # LOAD DATA
    # ============================================================

    print()
    print("[1/6] Loading Excel...")

    companies_df = pd.read_csv(
        COMPANIES_FILE
    )

    print(f"      Companies found: {len(companies_df)}")

    print()
    print("[2/6] Loading CSV...")

    jobs_df = pd.read_csv(
        JOBS_FILE
    )

    print(f"      Jobs found: {len(jobs_df)}")


    # ============================================================
    # BASIC VALIDATION
    # ============================================================

    required_company_columns = [
        "nom",
        "categorie",
        "adresse",
        "ville",
        "telephone",
        "telephone_international",
        "email",
        "site_web",
        "google_maps_url",
        "rating",
        "nombre_avis",
        "latitude",
        "longitude",
        "business_status",
    ]

    required_job_columns = [
        "source",
        "poste",
        "entreprise",
        "localisation",
        "type_contrat",
        "date_publication",
        "description",
        "url",
    ]

    missing_company = [
        c for c in required_company_columns
        if c not in companies_df.columns
    ]

    missing_job = [
        c for c in required_job_columns
        if c not in jobs_df.columns
    ]

    if missing_company:
        raise ValueError(
            f"Colonnes Excel manquantes: {missing_company}"
        )

    if missing_job:
        raise ValueError(
            f"Colonnes CSV manquantes: {missing_job}"
        )


    # ============================================================
    # OPEN DATABASE
    # ============================================================

    print()
    print("[3/6] Inspecting SQLite database...")

    conn = sqlite3.connect(DB_PATH)

    conn.execute("PRAGMA foreign_keys = ON")

    print("      Tables:")

    tables = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        ORDER BY name
        """
    ).fetchall()

    for table in tables:
        print(f"        - {table[0]}")


    if not table_exists(conn, "companies"):
        conn.close()
        raise RuntimeError(
            "La table 'companies' n'existe pas."
        )

    if not table_exists(conn, "offers"):
        conn.close()
        raise RuntimeError(
            "La table 'offers' n'existe pas."
        )


    print()
    print("      companies columns:")
    print("       ", columns_of(conn, "companies"))

    print()
    print("      offers columns:")
    print("       ", columns_of(conn, "offers"))


    # ============================================================
    # PREPARE COMPANY MATCHING
    # ============================================================

    print()
    print("[4/6] Preparing safe company matching...")

    # Excel = source principale des entreprises
    excel_company_map = {}

    for _, row in companies_df.iterrows():

        original_name = clean(row["nom"])

        if not original_name:
            continue

        normalized = normalize_name(original_name)

        if normalized:
            # Première occurrence uniquement
            if normalized not in excel_company_map:
                excel_company_map[normalized] = row


    # ============================================================
    # PREPARE OFFER MATCHES
    # ============================================================

    matched_jobs = 0
    unmatched_jobs = 0

    job_company_matches = {}

    for company_name in jobs_df["entreprise"].dropna().unique():

        normalized = normalize_name(company_name)

        if normalized in excel_company_map:
            job_company_matches[company_name] = "MATCH"
        else:
            job_company_matches[company_name] = None


    for company_name in jobs_df["entreprise"].dropna():

        if job_company_matches.get(company_name) == "MATCH":
            matched_jobs += 1
        else:
            unmatched_jobs += 1


    print()
    print(f"      Exact normalized company matches: {matched_jobs}")
    print(f"      Unmatched job companies: {unmatched_jobs}")


    # ============================================================
    # IMPORTANT:
    # We don't force fuzzy matching.
    #
    # Existing applications / users / CRM tables are preserved.
    #
    # Companies and offers are updated incrementally.
    # Missing rows and personal references are retained.
    # ============================================================

    print()
    print("[5/6] Importing real companies and offers...")


    try:

        conn.execute("BEGIN IMMEDIATE")

        # --------------------------------------------------------
        # Clear only fake/company/offer data
        # --------------------------------------------------------

        market_sync = MarketSync(conn)
        # Preserve records absent from this batch and every referenced ID.


        # --------------------------------------------------------
        # Add useful metadata columns to companies if absent
        # --------------------------------------------------------

        company_columns = columns_of(conn, "companies")

        extra_company_columns = {
            "google_maps_url": "TEXT",
            "rating": "REAL",
            "review_count": "INTEGER",
            "business_status": "TEXT",
            "data_source": "TEXT",
        }

        for column, sql_type in extra_company_columns.items():

            if column not in company_columns:

                conn.execute(
                    f"ALTER TABLE companies ADD COLUMN {column} {sql_type}"
                )


        # --------------------------------------------------------
        # Add useful metadata columns to offers if absent
        # --------------------------------------------------------

        offer_columns = columns_of(conn, "offers")

        extra_offer_columns = {
            "source": "TEXT",
            "url": "TEXT",
            "location": "TEXT",
            "publication_date": "TEXT",
            "company_name": "TEXT",
        }

        for column, sql_type in extra_offer_columns.items():

            if column not in offer_columns:

                conn.execute(
                    f"ALTER TABLE offers ADD COLUMN {column} {sql_type}"
                )


        # --------------------------------------------------------
        # Insert companies
        # --------------------------------------------------------

        # --------------------------------------------------------
        # Protection contre les colonnes NOT NULL (review_count, rating...)
        # --------------------------------------------------------

        COMPANY_INSERT_COLUMNS = [
            "name", "category", "area", "address", "email", "phone",
            "website", "description", "lat", "lng", "has_offer",
            "google_maps_url", "rating", "review_count",
            "business_status", "data_source",
        ]

        company_id_by_normalized_name = {key[1]: next(iter(ids)) for key, ids in market_sync.company_index.items() if len(ids) == 1}

        inserted_companies = 0

        for _, row in companies_df.iterrows():

            name = clean(row["nom"])

            if not name:
                continue

            category = (
                clean(row["categorie"])
                or clean(row["categorie_type"])
                or "Other"
            )

            area = clean(row["ville"])

            address = clean(row["adresse"])

            phone = (
                clean(row["telephone_international"])
                or clean(row["telephone"])
            )

            website = clean(row["site_web"])

            # Email trouvé par le scraping (vide si absent)
            email = clean(row["email"]).lower()

            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                email = ""

            # Excel has very few descriptions,
            # so we don't invent one.
            description = clean(row["description"])

            lat = row["latitude"]
            lng = row["longitude"]

            if pd.isna(lat):
                lat = None

            if pd.isna(lng):
                lng = None

            rating = row["rating"]

            if pd.isna(rating):
                rating = None

            review_count = row["nombre_avis"]

            if pd.isna(review_count):
                review_count = None

            business_status = clean(
                row["business_status"]
            )

            google_maps_url = clean(
                row["google_maps_url"]
            )

            # Temporary value.
            # It will be recalculated after offers are imported.
            has_offer = 0

            company_id = market_sync.company(dict(zip(COMPANY_INSERT_COLUMNS, (
                name, category, area, address, email, phone, website, description, lat, lng,
                has_offer, google_maps_url, rating, review_count, business_status,
                "entreprises_Marrakech_FINAL.csv",
            ))))

            normalized = normalize_name(name)

            if normalized:
                company_id_by_normalized_name[
                    normalized
                ] = company_id

            inserted_companies += 1


        # --------------------------------------------------------
        # Insert offers
        # --------------------------------------------------------

        inserted_offers = 0
        linked_offers = 0
        unmatched_offers = 0

        for _, row in jobs_df.iterrows():

            job_company_name = clean(
                row["entreprise"]
            )

            normalized_company = normalize_name(
                job_company_name
            )

            company_id = company_id_by_normalized_name.get(
                normalized_company
            )

            if company_id:
                linked_offers += 1
            else:
                unmatched_offers += 1

            title = clean(row["poste"])

            offer_type = (
                clean(row["type_contrat"])
                or "Non précisé"
            )

            description = clean(
                row["description"]
            )

            source = clean(
                row["source"]
            )

            url = clean(
                row["url"]
            )

            location = clean(
                row["localisation"]
            )

            publication_date = clean(
                row["date_publication"]
            )

            market_sync.offer({
                "company_id": company_id, "title": title, "offer_type": offer_type,
                "requirements": "", "description": description, "source": source,
                "url": url, "location": location, "publication_date": publication_date,
                "company_name": job_company_name,
            })

            inserted_offers += 1


        # --------------------------------------------------------
        # Recalculate has_offer
        # --------------------------------------------------------

        conn.execute(
            """
            UPDATE companies
            SET has_offer = 0
            """
        )

        conn.execute(
            """
            UPDATE companies
            SET has_offer = 1
            WHERE id IN (
                SELECT DISTINCT company_id
                FROM offers
                WHERE company_id IS NOT NULL
            )
            """
        )


        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Foreign key validation failed; import rolled back.")
        conn.commit()
        print("Created:", market_sync.created, "Updated:", market_sync.updated)


    except Exception:

        conn.rollback()

        print()
        print("[ERROR] Import failed.")
        print("       Database rollback executed.")
        print(f"       Backup available at:")
        print(f"       {backup_path}")

        conn.close()

        raise


    # ============================================================
    # FINAL REPORT
    # ============================================================

    print()
    print("[6/6] Final verification...")

    company_count = conn.execute(
        "SELECT COUNT(*) FROM companies"
    ).fetchone()[0]

    offer_count = conn.execute(
        "SELECT COUNT(*) FROM offers"
    ).fetchone()[0]

    companies_with_offers = conn.execute(
        """
        SELECT COUNT(*)
        FROM companies
        WHERE has_offer = 1
        """
    ).fetchone()[0]

    offers_linked = conn.execute(
        """
        SELECT COUNT(*)
        FROM offers
        WHERE company_id IS NOT NULL
        """
    ).fetchone()[0]

    offers_unmatched = conn.execute(
        """
        SELECT COUNT(*)
        FROM offers
        WHERE company_id IS NULL
        """
    ).fetchone()[0]


    conn.close()


    print()
    print("=" * 70)
    print("IMPORT FINISHED")
    print("=" * 70)

    print(f"Companies imported       : {company_count}")
    print(f"Offers imported           : {offer_count}")
    print(f"Companies with offers     : {companies_with_offers}")
    print(f"Offers linked             : {offers_linked}")
    print(f"Offers unmatched          : {offers_unmatched}")

    print()
    print("Backup:")
    print(backup_path)

    print()
    print("IMPORTANT:")
    print("- No fuzzy matching was used.")
    print("- No fake company was matched to another company.")
    print("- Users / applications / CRM / CV data were preserved.")
    print("=" * 70)


if __name__ == "__main__":
    main()
