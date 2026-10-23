"""
TalentSouk — Skill Gap Analysis demo data.

TASK 6 — CV UPLOAD + SKILL GAP
This is local demo/static data, not a real CV parser or AI service. It is
"connected" to the uploaded CV only in the sense that the Skill Gap tab
only renders once a CV exists for the user — the numbers themselves are
fixed demo values for every user for now.

Structured as a plain function returning a dict so a future task (e.g. the
AI Matching service in a later task) can replace get_skill_gap_analysis()
with a real, per-user analysis without touching the template.
"""

SKILLS = [
    {"name": "Python", "category": "Technical", "current": 85, "required": 70},
    {"name": "SQL", "category": "Technical", "current": 60, "required": 75},
    {"name": "JavaScript", "category": "Technical", "current": 40, "required": 65},
    {"name": "Data Analysis", "category": "Technical", "current": 55, "required": 80},
    {"name": "Cloud / DevOps", "category": "Technical", "current": 20, "required": 60},
    {"name": "Communication", "category": "Soft skill", "current": 75, "required": 70},
    {"name": "Project Management", "category": "Soft skill", "current": 50, "required": 65},
    {"name": "UI / UX Design", "category": "Technical", "current": 10, "required": 50},
]

ROADMAP = [
    {
        "skill": "UI / UX Design",
        "action": "Complete a UI/UX fundamentals course and build one portfolio mockup in Figma.",
        "duration": "3 weeks",
    },
    {
        "skill": "Cloud / DevOps",
        "action": "Learn Docker basics and deploy a small app to a free-tier cloud host.",
        "duration": "4 weeks",
    },
    {
        "skill": "JavaScript",
        "action": "Build two small projects using modern JavaScript (ES6+) and async/await.",
        "duration": "3 weeks",
    },
    {
        "skill": "Data Analysis",
        "action": "Practice data cleaning and visualization with Pandas on a public dataset.",
        "duration": "3 weeks",
    },
    {
        "skill": "SQL",
        "action": "Review joins, indexing, and query optimization with practice exercises.",
        "duration": "2 weeks",
    },
    {
        "skill": "Project Management",
        "action": "Take a short Agile/Scrum fundamentals course and apply it to a personal project.",
        "duration": "2 weeks",
    },
]


def _status_for(current, required):
    if current >= required:
        return "Strong"
    gap = required - current
    if current == 0 or gap >= 35:
        return "Missing"
    return "Weak"


def get_skill_gap_analysis():
    skills = []
    total_gap = 0
    gap_count = 0

    for s in SKILLS:
        gap = max(s["required"] - s["current"], 0)
        gap_percent = round((gap / s["required"]) * 100) if s["required"] else 0
        status = _status_for(s["current"], s["required"])
        skills.append({
            **s,
            "gap": gap,
            "gap_percent": gap_percent,
            "status": status,
        })
        if gap > 0:
            total_gap += gap_percent
            gap_count += 1

    average_gap_percent = round(total_gap / gap_count) if gap_count else 0
    overall_match_percent = 100 - average_gap_percent
    weak_or_missing = [s for s in skills if s["status"] in ("Weak", "Missing")]

    return {
        "skills": skills,
        "overall_match_percent": overall_match_percent,
        "average_gap_percent": average_gap_percent,
        "weak_or_missing_count": len(weak_or_missing),
        "roadmap": ROADMAP,
    }