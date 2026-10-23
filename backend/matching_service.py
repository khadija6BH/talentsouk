"""Explainable local matching service for candidate profiles and demo offers."""

import re


MATCH_WEIGHTS = {
    "skills": 30,
    "experience": 20,
    "education": 15,
    "location": 10,
    "keywords": 25,
}

PROFILE_SECTIONS = (
    "summary", "education", "experience", "skills", "projects",
    "certifications", "languages",
)


def _contains(text, phrase):
    if not text or not phrase:
        return False
    parts = re.split(r"\s+", phrase.strip())
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(part) for part in parts) + r"(?!\w)"
    return re.search(pattern, text, re.IGNORECASE) is not None


def _terms_in(text, terms):
    return [term for term in terms if _contains(text, term)]


def _offer_keywords(offer, requirements):
    title_words = [
        word for word in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", offer.get("title", ""), re.IGNORECASE)
        if word.casefold() not in {"intern", "internship", "junior", "senior"}
    ]
    title_phrases = [
        " ".join(title_words[index:index + 2])
        for index in range(len(title_words) - 1)
    ]
    return list(dict.fromkeys([*requirements, *title_phrases]))


def _location_matches(candidate_location, company):
    candidate_location = str(candidate_location or "").strip().casefold()
    if not candidate_location:
        return None

    company_location = " ".join(
        str(company.get(field) or "") for field in ("area", "address")
    ).casefold()
    if not company_location:
        return False
    if candidate_location in company_location or company_location in candidate_location:
        return True

    ignored_words = {"the", "and", "near", "area", "zone", "rue", "avenue", "lot"}
    candidate_words = {
        word for word in re.findall(r"[a-z0-9]+", candidate_location)
        if len(word) > 2 and word not in ignored_words
    }
    company_words = {
        word for word in re.findall(r"[a-z0-9]+", company_location)
        if len(word) > 2 and word not in ignored_words
    }
    return bool(candidate_words & company_words)


def match_candidate_to_offer(candidate, company, offer):
    """Return score, evidence lists, factor scores, and a neutral explanation."""
    requirements = list(dict.fromkeys(
        str(term).strip() for term in offer.get("requirements", []) if str(term).strip()
    ))
    offer_keywords = _offer_keywords(offer, requirements)
    skill_text = str(candidate.get("skills") or "")
    experience_text = str(candidate.get("experience") or "")
    education_text = str(candidate.get("education") or "")
    all_profile_text = " ".join(
        str(candidate.get(section) or "") for section in PROFILE_SECTIONS
    )

    strong_matches = _terms_in(skill_text, requirements)
    missing_skills = [term for term in requirements if term not in strong_matches]
    experience_matches = _terms_in(experience_text, requirements)
    education_matches = _terms_in(education_text, requirements)
    matching_keywords = _terms_in(all_profile_text, offer_keywords)
    location_match = _location_matches(candidate.get("target_location") or candidate.get("location"), company)

    denominator = len(requirements)
    factor_scores = {
        "skills": round(len(strong_matches) / denominator * 100) if denominator else 0,
        "experience": round(len(experience_matches) / denominator * 100) if denominator else 0,
        "education": round(len(education_matches) / denominator * 100) if denominator else 0,
        "location": 100 if location_match is True else 0,
        "keywords": round(len(matching_keywords) / len(offer_keywords) * 100) if offer_keywords else 0,
    }
    score = round(sum(
        factor_scores[factor] * weight / 100
        for factor, weight in MATCH_WEIGHTS.items()
    ))

    if location_match is None:
        location_note = "No candidate location was provided, so location overlap could not be assessed."
    elif location_match:
        location_note = "The candidate location overlaps the company location."
    else:
        location_note = "The candidate location does not overlap the company location."

    explanation = (
        f"{len(strong_matches)} of {denominator} listed offer requirements appear in candidate skills; "
        f"{len(experience_matches)} appear in experience and "
        f"{len(education_matches)} appear in education. {location_note} "
        f"{len(matching_keywords)} of {len(offer_keywords)} offer requirements/title phrases appear somewhere in the saved CV profile."
    )
    return {
        "score": score,
        "match_score": score,
        "company_id": company["id"],
        "company_name": company["name"],
        "offer_id": offer["id"],
        "offer_title": offer["title"],
        "requirements": requirements,
        "offer_keywords": offer_keywords,
        "strong_matches": strong_matches,
        "missing_skills": missing_skills,
        "matching_keywords": matching_keywords,
        "experience_matches": experience_matches,
        "education_matches": education_matches,
        "location_match": location_match,
        "factor_scores": factor_scores,
        "explanation": explanation,
    }


def match_company_offers(candidate, company, offers):
    """Score every supplied offer for one company and return the highest result."""
    company_offers = [offer for offer in offers if offer["company_id"] == company["id"]]
    matches = [match_candidate_to_offer(candidate, company, offer) for offer in company_offers]
    return max(matches, key=lambda result: result["score"]) if matches else None