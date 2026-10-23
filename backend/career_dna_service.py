"""Reviewable candidate evidence shared by career tools, independent of AI providers."""
import json
import re
from backend.database import get_db_connection, get_cv_builder_data, get_cv_for_user, get_user_by_id
from backend.cv_service import extract_profile_fields
from backend.skill_gap_service import SKILLS, SOFT_SKILLS, _contains

FIELD_LABELS = {
    "full_name": "Full name", "job_title": "Current professional title", "email": "Email",
    "phone": "Phone", "location": "Current location", "summary": "Professional summary",
    "skills": "Skills you can demonstrate", "experience": "Experience", "education": "Education",
    "projects": "Projects", "certifications": "Certifications", "languages": "Languages",
    "linkedin": "LinkedIn", "github": "GitHub", "interests": "Professional interests",
}
SOURCE_LABELS = {"account": "Account", "manual": "Created CV", "uploaded": "Uploaded CV",
                 "extracted": "CV extraction — review needed", "correction": "Your correction", "empty": "Not provided"}


def _state(user_id):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM career_dna_profiles WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return {}, {}
        return json.loads(row["overrides_json"]), json.loads(row["reviews_json"])
    finally:
        conn.close()


def get_career_dna(user_id):
    builder = get_cv_builder_data(user_id)
    profiles = builder["profiles"]
    cv = get_cv_for_user(user_id)
    extracted = extract_profile_fields(cv["extracted_text"]) if cv and cv["extracted_text"] else {}
    user = get_user_by_id(user_id)
    account = dict(user) if user else {}
    overrides, reviews = _state(user_id)
    fields, profile = [], {}
    for key, label in FIELD_LABELS.items():
        value, source = "", "empty"
        for origin, data in (("manual", profiles.get("manual") or {}), ("uploaded", profiles.get("uploaded") or {}),
                             ("extracted", extracted), ("account", account if key in {"full_name", "email"} else {})):
            if str(data.get(key) or "").strip():
                value, source = str(data[key]).strip(), origin
                if origin == "uploaded" and value == str(extracted.get(key) or "").strip():
                    source = "extracted"
                break
        if key in overrides:
            value, source = overrides[key], "correction"
        profile[key] = value
        fields.append({"key": key, "label": label, "value": value, "source": source,
                       "source_label": SOURCE_LABELS[source], "overridden": key in overrides})

    skills = {}
    def add(name, field):
        name = name.strip()
        if not name:
            return
        canonical = next((skill for skill, _ in SKILLS if skill.casefold() == name.casefold()), name)
        entry = skills.setdefault(canonical.casefold(), {"name": canonical, "sources": [], "evidence": [],
            "kind": "soft" if canonical in SOFT_SKILLS else "technical"})
        if field["source_label"] not in entry["sources"]:
            entry["sources"].append(field["source_label"])
        if field["label"] not in entry["evidence"]:
            entry["evidence"].append(field["label"])
        if field["source"] != "extracted":
            entry["documented"] = True

    for field in fields:
        if field["key"] == "skills":
            for name in re.split(r"[,;\n•]+", field["value"]):
                add(name, field)
        elif field["key"] in {"summary", "experience", "education", "projects", "certifications", "languages"}:
            for skill, _ in SKILLS:
                if _contains(field["value"], skill):
                    add(skill, field)
    for key, entry in skills.items():
        entry["status"] = reviews.get(key, "documented" if entry.get("documented") else "pending")
        entry["included"] = entry["status"] in {"documented", "confirmed"}
        entry.pop("documented", None)

    # Excluded detections must not re-enter analyses through another section or raw CV text.
    excluded = [entry["name"] for entry in skills.values() if not entry["included"]]
    for key in profile:
        if key in {"summary", "skills", "experience", "education", "projects", "certifications", "languages"}:
            for name in excluded:
                parts = [re.escape(part) for part in re.split(r"[\s./-]+", name) if part]
                pattern = r"(?<!\w)" + r"[\s./-]*".join(parts) + r"(?!\w)"
                profile[key] = re.sub(pattern, "", profile[key], flags=re.I)
    profile["skills"] = ", ".join(entry["name"] for entry in skills.values() if entry["included"])
    # Preferences remain separate from factual evidence. No target skill is inserted into skills.
    goals = {key: builder.get(key) or "" for key in ("target_position", "career_field", "target_location",
        "target_skills", "career_goal", "career_objective", "education_level", "experience_level")}
    profile.update({key: goals[key] for key in ("target_position", "career_field", "career_goal", "target_location")})
    profile["id"] = str(user_id)
    return {"profile": profile, "fields": fields, "skills": sorted(skills.values(), key=lambda item: item["name"].casefold()),
            "goals": goals, "included_count": sum(item["included"] for item in skills.values()),
            "pending_count": sum(item["status"] == "pending" for item in skills.values())}


def get_unified_candidate_profile(user_id):
    return get_career_dna(user_id)["profile"]


def save_career_dna(user_id, payload):
    if not isinstance(payload, dict):
        raise ValueError("Provide a valid profile update.")
    overrides, reviews = _state(user_id)
    current = get_career_dna(user_id)
    if payload.get("reset") is True:
        overrides, reviews = {}, {}
    else:
        changes = payload.get("fields", {})
        decisions = payload.get("reviews", {})
        resets = payload.get("reset_fields", [])
        if not isinstance(changes, dict) or not isinstance(decisions, dict) or not isinstance(resets, list):
            raise ValueError("Invalid profile update.")
        for key in resets:
            if not isinstance(key, str) or key not in FIELD_LABELS:
                raise ValueError("Unknown profile field.")
            overrides.pop(key, None)
        values = {field["key"]: field["value"] for field in current["fields"]}
        for key, value in changes.items():
            if key not in FIELD_LABELS or not isinstance(value, str) or len(value) > 12000:
                raise ValueError("Use known text fields, up to 12000 characters each.")
            value = value.strip()
            if value != values[key]:
                overrides[key] = value
        names = {entry["name"].casefold() for entry in current["skills"]}
        for name, status in decisions.items():
            if not isinstance(name, str) or name.casefold() not in names or not isinstance(status, str) or status not in {"confirmed", "rejected", "auto"}:
                raise ValueError("Choose a detected skill and a valid review decision.")
            if status == "auto":
                reviews.pop(name.casefold(), None)
            else:
                reviews[name.casefold()] = status
    conn = get_db_connection()
    try:
        conn.execute("""INSERT INTO career_dna_profiles(user_id, overrides_json, reviews_json)
            VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET overrides_json=excluded.overrides_json,
            reviews_json=excluded.reviews_json, updated_at=CURRENT_TIMESTAMP""",
            (user_id, json.dumps(overrides), json.dumps(reviews)))
        conn.commit()
    finally:
        conn.close()
    return get_career_dna(user_id)
