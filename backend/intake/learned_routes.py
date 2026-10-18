"""Routing rules learned from the team's corrections, approved by a person.

  1. Corrections are grouped by "moved from X to Y".
  2. Words (stems) shared by at least MIN_SUPPORT corrected requests in a group are candidates.
  3. Each candidate is replayed on every past routed request (uncorrected ones count as correct): "word → Y"
     must fix at least MIN_SUPPORT and break none (a request containing the word whose correct route wasn't Y).
  4. A person approves or dismisses. Approved rules route new requests after the incident check, before
     the built-in patterns, and can be removed.
Plain code: routing has to be instant and the same every time.
"""
from . import rules
from .search import stems

SETTING, DISMISSED = "learned_routing_rules", "dismissed_routing_suggestions"
MIN_SUPPORT = 2


def load(conn) -> list[dict]:
    from .. import db
    return db.get_setting(conn, SETTING) or []


def classify(conn, text: str, allow_incident: bool = True) -> tuple[str, str]:
    """Incident first (always), then approved learned rules, then the built-in rules."""
    if allow_incident and rules.is_safety_concern(text):
        return "incident", "Describes a possible active incident"
    learned = load(conn)
    if learned:
        words = stems({"text": text})["text"]
        for rule in learned:
            if rule["term"] in words:
                return rule["route"], f"Learned rule: “{rule['word']}” goes to this team (approved by {rule['approved_by']})"
    return rules.classify_route(text, allow_incident=False)


def full_text(row) -> str:
    return " ".join(filter(None, [row[k] for k in ("title", "description", "current_process", "impact")]))


def suggestions(conn) -> list[dict]:
    """Candidate rules from repeated corrections, each with its evidence and replay result."""
    from .. import db
    # Replayed on every routed request: one the team never corrected counts as correctly routed.
    reviewed = [dict(r) for r in conn.execute("SELECT * FROM submissions WHERE initial_route IS NOT NULL AND route IS NOT NULL")]
    corrected = [r for r in reviewed if r["route"] != r["initial_route"]]
    if len(corrected) < MIN_SUPPORT:
        return []
    found = stems({r["pk"]: full_text(r) for r in reviewed})
    reasons = {row["submission_pk"]: row["details"] for row in conn.execute(
        "SELECT submission_pk, details FROM submission_events WHERE event = 'rerouted' ORDER BY pk")}
    taken = {r["term"] for r in load(conn)}
    dismissed = set(db.get_setting(conn, DISMISSED) or [])
    groups = {}
    for r in corrected:
        groups.setdefault((r["initial_route"], r["route"]), []).append(r)
    result = []
    for (source, target), group in groups.items():
        if len(group) < MIN_SUPPORT:
            continue
        counts = {}
        for r in group:
            for term in found[r["pk"]]:
                counts[term] = counts.get(term, 0) + 1
        candidates = []
        for term, support in counts.items():
            if support < MIN_SUPPORT or len(term) < 4 or term in taken or f"{term}->{target}" in dismissed:
                continue
            hits = [r for r in reviewed if term in found[r["pk"]]]
            fixes = [r for r in hits if r["route"] == target and r["initial_route"] != target]
            breaks = [r for r in hits if r["route"] != target]
            if len(fixes) >= MIN_SUPPORT and not breaks:
                candidates.append((len(fixes), -len(hits), term, fixes))
        for fixes_count, _, term, fixes in sorted(candidates, reverse=True)[:3]:
            word = example_word(term, [full_text(r) for r in fixes])
            result.append({"key": f"{term}->{target}", "term": term, "word": word, "from": source, "route": target,
                           "fixes": fixes_count, "breaks": 0, "replayed_on": len(reviewed),
                           "requests": [{"id": f"SUB-{r['pk']:04d}", "title": r["title"], "reason": reasons.get(r["pk"])}
                                        for r in fixes]})
    return sorted(result, key=lambda s: -s["fixes"])


def example_word(term: str, texts: list[str]) -> str:
    """The word as people actually wrote it (the stem 'turnstil' shows as 'turnstile')."""
    import re
    for text in texts:
        for word in re.findall(r"[A-Za-z]+", text):
            if word.lower().startswith(term):
                return word.lower()
    return term
