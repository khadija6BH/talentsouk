"""Evidence-based skill-gap analysis using saved CVs and SQLite market data."""

from backend.learning_service import learning_plan

from collections import Counter
import re


SKILL_GROUPS = {
    "Programming": ["Python", "Java", "JavaScript", "TypeScript", "PHP", "C++", "C#", "Ruby", "Kotlin", "Swift"],
    "Web": ["HTML", "CSS", "React", "Angular", "Vue.js", "Node.js", "Django", "Flask", "Laravel", "Spring"],
    "Data & AI": ["SQL", "Data Analysis", "Data Science", "Machine Learning", "Deep Learning", "Pandas", "Power BI", "Tableau", "Excel"],
    "Cloud & DevOps": ["AWS", "Azure", "Google Cloud", "Docker", "Kubernetes", "Git", "Linux", "CI/CD", "DevOps"],
    "Cybersecurity & Networks": ["Cybersecurity", "Network Security", "Networking", "Cisco", "Firewall", "Penetration Testing"],
    "Civil engineering & construction": ["AutoCAD", "Revit", "BIM", "Civil Engineering", "Structural Analysis", "Quantity Surveying", "Construction Management", "Site Safety"],
    "Professional": ["Communication", "Project Management", "Agile", "Scrum", "Leadership", "Problem Solving", "Teamwork", "English", "French"],
}

SKILLS = [(skill, group) for group, skills in SKILL_GROUPS.items() for skill in skills]
SOFT_SKILLS = {"Communication", "Project Management", "Agile", "Scrum", "Leadership", "Problem Solving", "Teamwork", "Motivation", "Adaptability", "Organization", "Active Listening"}


def _contains(text, phrase):
    parts = [re.escape(part) for part in re.split(r"[\s./-]+", phrase) if part]
    return bool(parts) and re.search(r"(?<!\w)" + r"[\s./-]*".join(parts) + r"(?!\w)", text, re.I) is not None


def _offer_text(offer):
    requirements = offer.get("requirements") or []
    if isinstance(requirements, str):
        requirements = requirements.replace(";", ",").split(",")
    return " ".join([
        str(offer.get("title") or ""), str(offer.get("description") or ""),
        str(offer.get("category") or ""), " ".join(map(str, requirements)),
    ])


def analyze_market_skill_gap(profile, offers, companies, field="any", interview_gaps=None, target_offer=None):
    """Compare documented CV evidence with skills found in real market records."""
    profile = dict(profile or {})
    cv_text = " ".join(str(profile.get(key) or "") for key in (
        "skills", "summary", "experience", "education", "projects",
        "certifications", "languages", "cv_text",
    ))
    field_terms = {
        "civil_engineering": ("génie civil", "genie civil", "civil engineering", "structural", "géotechnique", "topographie"),
        "construction": ("construction", "btp", "bâtiment", "batiment", "travaux publics", "chantier"),
        "software": ("software", "developer", "web", "programming", "it"),
        "ai_data": ("data", "ai", "machine learning", "analyst", "intelligence"),
        "cybersecurity": ("security", "cyber", "network", "cisco"),
        "cloud": ("cloud", "devops", "infrastructure", "system"),
    }
    filters = field_terms.get(field, ())
    selected_offers = [offer for offer in offers if not filters or any(term in _offer_text(offer).casefold() for term in filters)]
    if target_offer is not None:
        selected_offers = [target_offer]
    analyzed_companies = [] if target_offer is not None else [company for company in companies if not filters or any(term in " ".join(str(company.get(key) or "") for key in ("name", "category", "description")).casefold() for term in filters)]
    skill_catalog = list(SKILLS)
    if target_offer is not None:
        requirements = target_offer.get("requirements") or []
        if isinstance(requirements, str):
            requirements = [value.strip() for value in re.split(r"[,;\n]+", requirements) if value.strip()]
        for requirement in requirements:
            requirement = str(requirement).strip()
            if 0 < len(requirement) <= 120 and not any(_contains(requirement, skill) for skill, _ in SKILLS):
                if not any(skill.casefold() == requirement.casefold() for skill, _ in skill_catalog):
                    skill_catalog.append((requirement, "Offer requirement"))

    demand = Counter()
    sources = Counter()
    for offer in selected_offers:
        text = _offer_text(offer)
        for skill, _group in skill_catalog:
            if _contains(text, skill):
                demand[skill] += 1
                sources[skill] += 1
    for company in analyzed_companies:
        text = " ".join(str(company.get(key) or "") for key in ("name", "category", "description"))
        if filters and not any(term in text.casefold() for term in filters):
            continue
        for skill, _group in skill_catalog:
            if _contains(text, skill):
                demand[skill] += 1
                sources[skill] += 1

    documented = {skill for skill, _group in skill_catalog if _contains(cv_text, skill)}
    ranked = sorted(demand, key=lambda skill: (-demand[skill], skill.casefold()))
    if target_offer is None:
        ranked = ranked[:16]
    # Keep documented skills visible even when current records do not mention them.
    for skill in sorted(documented):
        if target_offer is None and skill not in ranked and len(ranked) < 16:
            ranked.append(skill)
    max_demand = max((demand[skill] for skill in ranked), default=1)
    group_lookup = dict(skill_catalog)
    rows = [{
        "name": skill,
        "category": group_lookup[skill],
        "documented": skill in documented,
        "demand_count": demand[skill],
        "demand_percent": round(demand[skill] / max_demand * 100) if demand[skill] else 0,
        "source_count": sources[skill],
        "kind": "soft" if skill in SOFT_SKILLS else "technical",
    } for skill in ranked]
    interview_gaps = dict(interview_gaps or {})
    for skill, count in sorted(interview_gaps.items(), key=lambda item: (-item[1], item[0].casefold())):
        existing_row = next((row for row in rows if row["name"].casefold() == skill.casefold()), None)
        if existing_row:
            existing_row["interview_gap_count"] = count
        else:
            rows.append({"name": skill, "category": group_lookup.get(skill, "Interview practice"), "documented": _contains(cv_text, skill), "demand_count": 0, "demand_percent": 0, "source_count": 0, "interview_gap_count": count, "kind": "soft" if skill in SOFT_SKILLS or skill in {"Motivation", "Adaptability", "Organization"} else "technical"})
    missing = [row for row in rows if row.get("interview_gap_count") or (not row["documented"] and row["demand_count"])]
    present = [row for row in rows if row["documented"]]
    market_skills = [row for row in rows if row["demand_count"]]
    coverage = round(len([row for row in market_skills if row["documented"]]) / len(market_skills) * 100) if market_skills else 0
    missing.sort(key=lambda row: (-row.get("interview_gap_count", 0), -row["demand_count"], row["name"].casefold()))
    def make_roadmap(gaps):
        return [{"skill": row["name"], "category": row["category"],
            "priority": "High" if index < 3 else "Medium",
            "reason": (f"Practice focus in {row.get('interview_gap_count', 0)} interview(s), not a proficiency assessment. " if row.get("interview_gap_count") else "") + f"Detected in {row['demand_count']} selected market record(s).",
            **learning_plan(row["name"], row["category"], row["kind"] == "soft")}
            for index, row in enumerate(gaps[:6])]
    roadmap = make_roadmap(missing)
    technical_skills = [row for row in rows if row["kind"] == "technical"]
    soft_skills = [row for row in rows if row["kind"] == "soft"]
    technical_missing = [row for row in missing if row["kind"] == "technical"]
    soft_missing = [row for row in missing if row["kind"] == "soft"]
    technical_roadmap = make_roadmap(technical_missing)
    soft_roadmap = make_roadmap(soft_missing)
    return {
        "coverage": coverage,
        "documented_count": len(present),
        "missing_count": len(missing),
        "offers_analyzed": len(selected_offers),
        "companies_analyzed": len(analyzed_companies),
        "skills": rows,
        "present": present,
        "missing": missing,
        "roadmap": roadmap,
        "technical_skills": technical_skills,
        "soft_skills": soft_skills,
        "technical_missing": technical_missing,
        "soft_missing": soft_missing,
        "technical_roadmap": technical_roadmap,
        "soft_roadmap": soft_roadmap,
        "technical_coverage": round(len([row for row in technical_skills if row["documented"] and row["demand_count"]]) / len([row for row in technical_skills if row["demand_count"]]) * 100) if any(row["demand_count"] for row in technical_skills) else 0,
        "soft_coverage": round(len([row for row in soft_skills if row["documented"] and (row["demand_count"] or row.get("interview_gap_count")) and not row.get("interview_gap_count")]) / len([row for row in soft_skills if row["demand_count"] or row.get("interview_gap_count")]) * 100) if any(row["demand_count"] or row.get("interview_gap_count") for row in soft_skills) else 0,
        "field": field,
        "target_offer": target_offer,
        "has_cv_evidence": bool(cv_text.strip()),
    }
