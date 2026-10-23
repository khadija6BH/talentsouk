"""Written-answer coaching and comparisons without invented candidate achievements."""
import re
from backend.skill_gap_service import SKILLS, _contains


def question_guide(question):
    kind = question.get("type")
    if kind == "behavioral":
        return {"framework": "STAR", "steps": ["Situation: describe one real context.", "Task: state your own responsibility.", "Action: explain what you personally did.", "Result: give the outcome you can demonstrate."],
                "starter": "Situation: [real context]\nTask: [my responsibility]\nAction: [what I did]\nResult: [actual outcome]"}
    if kind == "technical":
        return {"framework": "Explain → Apply → Verify", "steps": ["Explain the concept in simple words.", "Describe a real use or say honestly that you are still learning.", "Explain how you would test the solution and handle a limitation."],
                "starter": "Concept: [my explanation]\nApplication: [real example or learning approach]\nVerification: [how I would test it]"}
    return {"framework": "Present → Evidence → Fit", "steps": ["Answer the question directly in one sentence.", "Support it with a real project, course or experience.", "Connect that evidence to the role and company."],
            "starter": "Direct answer: [my point]\nEvidence: [real example]\nRole connection: [why it matters here]"}


def enrich_answer_coaching(item, suggested=None):
    answer = item.get("answer") or ""
    guide = question_guide(item)
    steps = []
    for metric, message in (("clarity", "Replace vague statements with a precise example."),
                            ("structure", "Use a short opening, evidence, and a concluding point."),
                            ("relevance", "Answer the actual question before adding background.")):
        if item.get(metric, 0) < 60:
            steps.append(message)
    if item.get("star") is not None and item["star"] < 60:
        steps.append("Complete each STAR part with real information; labels alone are not evidence.")
    if not steps:
        steps.append("Keep the structure and verify that every claim is supported by your experience.")
    draft = guide["starter"] if not answer.strip() else "Your original evidence:\n" + answer + "\n\nReorganize it using this framework:\n" + guide["starter"]
    kind = "guided_outline"
    changes = steps
    if isinstance(suggested, dict) and answer.strip():
        rewrite, reasons = suggested.get("improved_answer"), suggested.get("improvement_notes")
        original_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", answer))
        if (isinstance(rewrite, str) and 0 < len(rewrite.strip()) <= 4000
                and set(re.findall(r"\d+(?:[.,]\d+)?", rewrite)) <= original_numbers
                and {skill for skill, _ in SKILLS if _contains(rewrite, skill)} <= {skill for skill, _ in SKILLS if _contains(answer, skill)}
                and isinstance(reasons, list) and 0 < len(reasons) <= 5
                and all(isinstance(reason, str) and 0 < len(reason.strip()) <= 400 for reason in reasons)):
            draft, changes, kind = rewrite.strip(), [reason.strip() for reason in reasons], "ai_rewrite"
    skill = str(item.get("skill") or "")
    terms = [skill] if skill and re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", answer, re.I) else []
    item.update({"improved_answer": draft, "improved_answer_kind": kind, "improvement_notes": changes,
                 "guide": guide, "technical_terms": terms if item.get("type") == "technical" else [],
                 "rewrite_notice": "Practice draft: check every claim and replace brackets with your own evidence."})
    return item


def interview_progress(history):
    completed = [row for row in reversed(history) if row.get("completed_at")]
    comparable = []
    for row in completed:
        evaluation = row.get("evaluation")
        if isinstance(evaluation, dict) and evaluation.get("rubric_version"):
            comparable.append(row)
    comparisons = []
    for current in comparable:
        prior = next((row for row in reversed(comparable[:comparable.index(current)])
            if row.get("company_id") == current.get("company_id") and row.get("position") == current.get("position")
            and row.get("questions") == current.get("questions")
            and row["evaluation"].get("source") == current["evaluation"].get("source")
            and row["evaluation"].get("rubric_version") == current["evaluation"].get("rubric_version")
            and (row.get("practice_context") or {}).get("mode", "standard") == (current.get("practice_context") or {}).get("mode", "standard")), None)
        if prior:
            comparisons.append({"previous_id": prior["id"], "current_id": current["id"], "position": current["position"],
                "before": prior["score"], "after": current["score"], "delta": current["score"] - prior["score"],
                "source": current["evaluation"]["source"], "date": current["completed_at"]})
    return {"completed_count": len(completed), "comparisons": list(reversed(comparisons))[:8]}
