"""The brain: the part of the assistant that uses judgement.

Every brain offers the same two methods, so the workflow doesn't care which one is plugged in:
  step(...)        - understand the latest message (extract facts), then choose and word the
                     next question, or decide there's enough
  write_brief(...) - summarise the request for whoever receives it

MockBrain does this with fixed rules, so everything works without an API key.
ClaudeBrain (claude_brain.py) does it with Claude, and falls back to MockBrain on any problem.
get_brain() picks one: Claude when ANTHROPIC_API_KEY is set, unless HUB_BRAIN=mock.
"""
from ..llm import claude_enabled
from . import rules

# One question at a time, in order of value. The assistant aims for 2–4 follow-ups.
QUESTIONS = {
    "current_process": "What happens today, and what should happen instead?",
    "frequency": "How often does it happen?",
    "people_affected": "Who, or which locations, does it affect?",
    "impact": "What time, cost, delay or risk does it create?",
    "tried_already": "What have you already tried?",
}
# When someone starts from a technology ("I saw a robot…"), first ask which problem it solves.
TECHNOLOGY_FIRST_QUESTION = "Which problem at work would it help with? What happens today, and what should happen instead?"

LABELS = {
    "title": "Title", "description": "Problem", "department": "Department",
    "current_process": "Today, and what should happen instead", "frequency": "How often",
    "people_affected": "Who or which locations", "impact": "Time, cost, delay or risk",
    "tried_already": "Already tried", "desired_outcome": "Desired outcome", "suggested_solution": "Suggested solution",
}


class MockBrain:
    name = "mock-brain"
    version = "mock-v2"

    def extract(self, text: str) -> dict:
        found = {}
        if frequency := rules.find_frequency(text):
            found["frequency"] = frequency
        if people := rules.find_people(text):
            found["people_affected"] = people
        if impact := rules.find_quantified_impact(text):
            found["impact"] = impact
        return found

    def next_question(self, draft: dict, unknown: list, asked: list) -> str | None:
        """The next field to ask about, or None when there's enough to hand over."""
        reach_known = draft.get("frequency") or draft.get("people_affected")
        if len(asked) >= 2 and draft.get("current_process") and draft.get("impact") and reach_known:
            return None
        for field in QUESTIONS:
            if not draft.get(field) and field not in unknown and field not in asked:
                return field
        return None

    def question(self, field: str, technology_first: bool = False) -> str:
        if field == "current_process" and technology_first:
            return TECHNOLOGY_FIRST_QUESTION
        return QUESTIONS[field]

    def step(self, text: str | None, draft: dict, unknown: list, asked: list,
             technology_first: bool = False, meter: list | None = None) -> dict:
        extracted = self.extract(text) if text else {}
        merged = draft | {field: value for field, value in extracted.items()
                          if not draft.get(field) and field not in asked}
        field = self.next_question(merged, unknown, asked)
        return {"extracted": extracted, "next_field": field,
                "question": self.question(field, technology_first) if field else None}

    def write_brief(self, draft: dict, context: dict, meter: list | None = None) -> dict:
        """The handover brief. Facts, estimates and missing evidence are kept apart."""
        facts, estimates = [], []
        for field in ("current_process", "frequency", "people_affected", "impact", "tried_already"):
            value = draft.get(field)
            if not value:
                continue
            if rules.is_quantified(value):
                estimates.append(f"{LABELS[field]}: {value} (employee estimate, not verified)")
            else:
                facts.append(f"{LABELS[field]}: {value} (employee-stated)")
        missing = [LABELS[field] for field in QUESTIONS if not draft.get(field)]
        previous = ([f"Employee tried: {draft['tried_already']}"] if draft.get("tried_already") else []) \
            + context.get("previous_attempts", [])
        return {
            "status": "PROPOSED",
            "generated_by": f"{self.name} {self.version}",
            "problem": draft["description"],
            "today_and_desired": draft.get("current_process"),
            "affected": draft.get("people_affected"),
            "frequency": draft.get("frequency"),
            "impact": draft.get("impact"),
            "existing_solutions_checked": context.get("checked", []),
            "previous_attempts": previous,
            "related": context.get("related", []),
            "evidence": {"facts": facts, "estimates": estimates, "missing": missing},
            "unknown": [LABELS[field] for field in context.get("unknown", [])],
            "notes": context.get("notes", []),
            "flags": context.get("flags", []),
        }


MOCK = MockBrain()
_claude = None


def get_brain():
    """Claude when an API key is available (and HUB_BRAIN isn't 'mock'); otherwise the scripted brain."""
    global _claude
    if not claude_enabled():
        return MOCK
    if _claude is None:
        from .claude_brain import ClaudeBrain
        _claude = ClaudeBrain(fallback=MOCK)
    return _claude
