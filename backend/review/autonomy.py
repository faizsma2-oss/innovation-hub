"""Earned autonomy: how often people agree with the AI's recommendations, per decision area, and whether the
evidence is strong enough to *propose* giving the AI more room. Nothing here switches anything on.

  status, by a fixed rule:
    always_human  - areas that commit money or end work (pilot decisions): agreement shown for learning only
    automated     - already automatic (policy declines): watched through how often appeals overturn them
    too_few       - fewer than MIN_DECISIONS decisions
    keep          - agreement under AGREEMENT, or an override among the last RECENT decisions
    ready         - enough decisions, high agreement, no recent override: evidence for management to decide
Plain code: the AI is what's being measured, so it plays no part in the measuring.
"""
import json

from fastapi import APIRouter

from .. import db

router = APIRouter(tags=["autonomy"])

MIN_DECISIONS, AGREEMENT, RECENT = 20, 0.9, 10

AREAS = {
    "routing": ("Routing", "Where each request goes (IT, HR, facilities, innovation screening…)",
                "Send routine requests straight to the department, with a weekly spot-check of a sample."),
    "screening": ("Screening recommendation", "Accept, ask, decline or link for innovation requests",
                  "Accept strong opportunities automatically; a person still reviews each one within a week."),
    "policy_declines": ("Policy declines", "Clear-cut declines applied automatically, with a right to appeal",
                        "Already automatic. Stays that way while appeals rarely overturn it."),
    "options": ("Solution option ranking", "Whether the team picks the top-ranked approach",
                "Pre-select the top-ranked option; the team can still change it with a reason."),
    "suppliers": ("Supplier ranking", "Whether the shortlist includes the top-ranked supplier",
                  "Pre-fill the shortlist with the top two suppliers; the team confirms."),
    "pilots": ("Pilot decisions", "Scale, extend, revise or stop after the evaluation",
               "Always a person's decision: it commits money or ends work."),
}
ALWAYS_HUMAN, AUTOMATED = {"pilots"}, {"policy_declines"}


@router.get("/api/autonomy")
def autonomy():
    with db.connect() as conn:
        decisions = collect(conn)
    return {"thresholds": {"min_decisions": MIN_DECISIONS, "agreement": AGREEMENT, "recent": RECENT},
            "areas": [summarise(key, decisions[key]) for key in AREAS]}


def collect(conn) -> dict:
    """Every recorded AI recommendation and what people did, oldest first: {area: [(agreed, override_note)]}."""
    found = {key: [] for key in AREAS}
    rerouted = {row["submission_pk"]: row["details"] for row in conn.execute(
        "SELECT submission_pk, details FROM submission_events WHERE event = 'rerouted' ORDER BY pk")}
    auto = {row[0] for row in conn.execute("SELECT submission_pk FROM submission_events WHERE event = 'auto_declined'")}
    for row in conn.execute("SELECT * FROM submissions ORDER BY pk"):
        sid = f"SUB-{row['pk']:04d}"
        if row["initial_route"] and (row["review_outcome"] or row["pk"] in rerouted):
            same = row["route"] == row["initial_route"]
            found["routing"].append((same, None if same else f"{sid}: {rerouted.get(row['pk'], 'route changed')}"))
        if row["review_outcome"] in ("agreed", "overrode"):
            recommendation = json.loads(row["recommendation_json"] or "{}")
            decided = {"Declined": "decline", "Linked": "link"}.get(row["status"], "accept")   # later stages followed an accept
            note = (f"{sid}: recommended {recommendation.get('decision', '?')}, the reviewer chose {decided}"
                    + (f": “{row['decision_message']}”" if row["decision_message"] else ""))
            found["screening"].append((row["review_outcome"] == "agreed", None if row["review_outcome"] == "agreed" else note))
        if row["pk"] in auto:
            overturned = row["review_outcome"] == "overturned_auto"
            found["policy_declines"].append((not overturned, f"{sid}: overturned on appeal" if overturned else None))
        research = json.loads(row["research_json"]) if row["research_json"] else {}
        if "agreed_with_top_rank" in research:
            agreed = research["agreed_with_top_rank"]
            found["options"].append((agreed, None if agreed else
                                     f"{sid}: chose #{research.get('selected_rank')} “{(research.get('selected_option') or {}).get('title')}”: “{research.get('reason')}”"))
        run = research.get("suppliers") or {}
        if run.get("shortlist") and run.get("suppliers"):
            top = next((s["name"] for s in run["suppliers"] if s.get("rank") == 1), None)
            agreed = top in run["shortlist"]["names"]
            found["suppliers"].append((agreed, None if agreed else
                                       f"{sid}: left out top-ranked {top}" + (f": “{run['shortlist']['note']}”" if run["shortlist"].get("note") else "")))
        for decision in (research.get("pilot") or {}).get("decisions") or []:
            agreed = decision.get("agreed_with_recommendation")
            found["pilots"].append((agreed, None if agreed else
                                    f"{sid}: recommended {decision.get('recommended')}, decided {decision['decision']}: “{decision['reason']}”"))
    return found


def summarise(key: str, items: list) -> dict:
    name, what, unlock = AREAS[key]
    total, agreed = len(items), sum(1 for ok, _ in items if ok)
    recent = items[-RECENT:]
    rate = round(agreed / total, 2) if total else None
    recent_rate = round(sum(1 for ok, _ in recent if ok) / len(recent), 2) if recent else None
    if key in ALWAYS_HUMAN:
        status, why = "always_human", "Commits money or ends work, so a person always decides."
    elif key in AUTOMATED:
        status = "automated" if rate is None or rate >= AGREEMENT else "keep"
        why = ("No automatic declines yet." if not total else "Automatic, and appeals rarely overturn it."
               if status == "automated" else f"Appeals overturned {total - agreed} of {total}: review the policy rules.")
    elif total < MIN_DECISIONS:
        status, why = "too_few", f"{total} of {MIN_DECISIONS} decisions needed before judging."
    elif rate < AGREEMENT:
        status, why = "keep", f"People agreed {round(rate * 100)}% of the time; the bar is {round(AGREEMENT * 100)}%."
    elif any(not ok for ok, _ in recent):
        status, why = "keep", f"An override among the last {RECENT} decisions: wait until it's clear again."
    else:
        status, why = "ready", (f"{total} decisions, {round(rate * 100)}% agreement, no override in the last {RECENT}. "
                                "Evidence for management to decide; nothing changes automatically.")
    return {"key": key, "name": name, "what": what, "more_autonomy": unlock, "decisions": total, "agreed": agreed,
            "agreement": rate, "recent_agreement": recent_rate, "status": status, "why": why,
            "overrides": [note for ok, note in reversed(items) if not ok][:3]}
