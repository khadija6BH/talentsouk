"""SQLite-backed company access for TALENTSOUK."""

from backend.database import get_all_companies_from_db, get_company_from_db
from backend.company_catalog import attach_domains


def get_all_companies():
    return [attach_domains(company) for company in get_all_companies_from_db()]


def get_company(company_id):
    company=get_company_from_db(company_id)
    return attach_domains(company) if company else None
