"""Per-user, self-reported completion of learning actions, separate from CV evidence."""
from backend.database import get_db_connection


def get_learning_progress(user_id):
    conn = get_db_connection()
    try:
        return { (row["skill"], row["action_index"]): dict(row)
            for row in conn.execute("SELECT * FROM skill_learning_progress WHERE user_id=?", (user_id,)) }
    finally:
        conn.close()


def save_learning_progress(user_id, skill, action_index, status, notes=""):
    if (not isinstance(skill, str) or not skill.strip() or len(skill) > 120
            or type(action_index) is not int or action_index not in range(3)
            or not isinstance(status, str) or status not in {"planned", "in_progress", "completed"}
            or not isinstance(notes, str) or len(notes) > 1000):
        raise ValueError("Choose a skill, an action and a valid progress status; notes are limited to 1000 characters.")
    conn = get_db_connection()
    try:
        conn.execute("""INSERT INTO skill_learning_progress(user_id,skill,action_index,status,notes)
            VALUES(?,?,?,?,?) ON CONFLICT(user_id,skill,action_index) DO UPDATE SET
            status=excluded.status,notes=excluded.notes,updated_at=CURRENT_TIMESTAMP""",
            (user_id,skill.strip().casefold(),action_index,status,notes.strip()))
        conn.commit()
    finally:
        conn.close()


def attach_learning_progress(analysis, user_id):
    records = get_learning_progress(user_id)
    completed = total = 0
    for step in analysis["technical_roadmap"] + analysis["soft_roadmap"]:
        step["tasks"] = []
        for index, action in enumerate(step["actions"]):
            record = records.get((step["skill"].casefold(), index), {})
            task = {"index": index, "text": action, "status": record.get("status", "planned"), "notes": record.get("notes", "")}
            step["tasks"].append(task)
            completed += task["status"] == "completed"
            total += 1
    analysis["learning_progress"] = {"completed": completed, "total": total}
    return analysis


def learning_plan(skill, category, soft=False):
    if soft:
        actions = [f"Practice {skill}: write a clear opening and one supporting example.",
                   "Write a STAR example from your real experience and identify your own contribution.",
                   "Repeat the same interview questions; review one improvement and one remaining weakness."]
        return {"actions": actions, "resources": [{"title": "STAR worksheet and beginner guide", "url": "/interview-helper#beginner-guide"}]}
    projects = {
        "Programming": "Build a small command-line task tracker: validate inputs, save entries and test edge cases.",
        "Web": "Build a responsive task list with a form, empty state and accessible keyboard controls.",
        "Data & AI": "Analyze a small public or synthetic dataset: clean missing values, answer three questions and explain limitations.",
        "Cloud & DevOps": "Package a small sample service, document setup and verify a reproducible deployment locally.",
        "Cybersecurity & Networks": "Use a local practice lab you control: document a threat, test a protection and record the result.",
    }
    project = projects.get(category, f"Build a small demonstration using {skill}; document setup, inputs, outputs and limitations.")
    resource = {"Python": ("Python tutorial (basic programming assumed)", "https://docs.python.org/3/tutorial/"),
                "SQL": ("SQLite SQL reference", "https://www.sqlite.org/lang.html"),
                "React": ("React Quick Start", "https://react.dev/learn")}.get(skill)
    resources = [{"title": resource[0], "url": resource[1]}] if resource else []
    if not resources and category == "Web":
        resources = [{"title": "MDN web learning guide", "url": "https://developer.mozilla.org/en-US/docs/Learn_web_development"}]
    resources.append({"title": "Project validation checklist", "url": "/skill-gap#learning-checklist"})
    return {"actions": [f"Learn {skill}: explain its purpose, demonstrate one basic operation and describe a limitation.",
                         f"Use {skill} in this exercise: {project}",
                         "Verify the result with three test cases; save your evidence and describe it in your own words before updating the CV."],
            "resources": resources}
