"""Local CV optimization logic using real SQLite offers."""

from copy import deepcopy
from datetime import datetime, timezone
import re

from backend.database import get_all_offers_from_db


PROFILE_FIELDS = (
    "summary", "education", "experience", "skills", "projects",
    "certifications", "languages",
)


def get_offers(companies=None):
    """Return the real offers currently stored in SQLite."""
    return get_all_offers_from_db()


def _contains_keyword(text, keyword):
    pattern = r"(?<!\w)" + r"\s+".join(
        re.escape(part) for part in keyword.split()
    ) + r"(?!\w)"
    return re.search(pattern, text, re.IGNORECASE) is not None


def _ordered_skills(skills_text, requirements):
    skills = [
        part.strip()
        for part in re.split(r"[\n,;]+", skills_text)
        if part.strip()
    ]

    matched = [
        skill
        for requirement in requirements
        for skill in skills
        if _contains_keyword(skill, requirement)
    ]

    prioritized = list(dict.fromkeys(matched))
    remaining = [skill for skill in skills if skill not in prioritized]

    return "\n".join(prioritized + remaining)


def optimize_cv(profile, company, offer):
    """Score explicit offer keywords and reorder existing skills."""

    source_text = " ".join(
        str(profile.get(field, "")) for field in PROFILE_FIELDS
    )

    requirements = offer.get("requirements", [])

    if isinstance(requirements, str):
        requirements = [
            part.strip()
            for part in re.split(r"[\n,;]+", requirements)
            if part.strip()
        ]

    existing = [
        keyword
        for keyword in requirements
        if _contains_keyword(source_text, keyword)
    ]

    missing = [
        keyword
        for keyword in requirements
        if keyword not in existing
    ]

    optimized_profile = deepcopy(profile)

    optimized_profile["skills"] = _ordered_skills(
        str(profile.get("skills", "")),
        requirements,
    )

    match_percent = (
        round((len(existing) / len(requirements)) * 100)
        if requirements
        else 0
    )

    return {
        "profile": optimized_profile,
        "template": "Modern",
        "company_id": company["id"],
        "company_name": company["name"],
        "offer_id": offer["id"],
        "offer_title": offer["title"],
        "requirements": requirements,
        "existing_keywords": existing,
        "missing_keywords": missing,
        "recommended_keywords": missing,
        "match_percent": match_percent,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds"),
    }
