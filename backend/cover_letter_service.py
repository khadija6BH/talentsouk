"""Local cover-letter generation logic, isolated for future AI integration."""

from datetime import date
import re


def _as_lines(value):
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[\n,;]+", str(value or "")) if part.strip()]


def _contains_keyword(text, keyword):
    parts = re.escape(keyword).split(r"\ ")
    pattern = r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)"
    return re.search(pattern, text, re.IGNORECASE) is not None


def generate_cover_letter(candidate, company, position, offer):
    """Generate an editable professional draft without inventing qualifications."""
    name = str(candidate.get("full_name") or "Candidate").strip()
    email = str(candidate.get("email") or "").strip()
    phone = str(candidate.get("phone") or "").strip()
    location = str(candidate.get("location") or "").strip()
    skills = _as_lines(candidate.get("skills", ""))
    requirements = offer.get("requirements", [])
    relevant_skills = [
        skill for skill in skills
        if any(_contains_keyword(skill, requirement) for requirement in requirements)
    ]
    experience = str(candidate.get("experience") or "").strip()
    experience_lines = [line.strip() for line in experience.splitlines() if line.strip()]
    relevant_experience = [
        line for line in experience_lines
        if any(_contains_keyword(line, requirement) for requirement in requirements)
    ]
    experience_to_include = "\n".join(relevant_experience) or experience
    summary = str(candidate.get("summary") or "").strip()
    company_name = str(company.get("name") or "the organization").strip()
    description = str(company.get("description") or "").strip()
    area = str(company.get("area") or "").strip()

    contact = [value for value in (email, phone, location) if value]
    recipient = [company_name]
    if company.get("address"):
        recipient.append(str(company["address"]))
    elif area:
        recipient.append(area)

    paragraphs = [
        f"I am writing to apply for the {position} position at {company_name}."
    ]
    if description:
        detail = description.rstrip(".")
        if detail.lower().startswith("a "):
            article, detail = "a", detail[2:]
        elif detail.lower().startswith("an "):
            article, detail = "an", detail[3:]
        else:
            article = "an" if detail[:1].lower() in "aeiou" else "a"
        paragraphs.append(
            f"I am interested in the opportunity at {company_name}, "
            f"{article} {detail[0].lower() + detail[1:]}."
        )
    if summary:
        paragraphs.append(f"My background, as outlined in my CV, is: {summary}")
    if relevant_skills:
        paragraphs.append(
            "The relevant skills I have listed in my CV include "
            f"{', '.join(relevant_skills)}."
        )
    if experience_to_include:
        paragraphs.append(f"My experience includes: {experience_to_include}")
    paragraphs.append(
        "Thank you for considering my application. I would welcome the opportunity "
        "to discuss how my background aligns with the position."
    )

    lines = [date.today().strftime("%B %d, %Y"), "", name]
    lines.extend(contact)
    lines.extend(["", *recipient, "", f"Subject: Application for {position}", "", "Dear Hiring Team,", ""])
    for paragraph in paragraphs:
        lines.extend([paragraph, ""])
    lines.extend(["Sincerely,", name])
    return "\n".join(lines).strip()
