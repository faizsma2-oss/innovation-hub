"""Screening: every request gets a route, a transparent priority and a PROPOSED next decision
before a person sees it.

Priority uses a weighted rubric. Each criterion is scored 0–5 with a reason. UNKNOWN IS NOT
ZERO: unknown criteria are left out and the weights re-balanced, and confidence shows how
much of the rubric was actually known. Feasibility is a separate label, so easy projects
don't crowd out valuable but less understood problems.

Only two clear-cut policy criteria decline automatically (not a request; weakens a safety or
security control), and never when the employee asked for an innovation review. Those always
get a human decision.
"""
import json
import re

from .. import db
from ..intake import rules, search
from ..intake.brain import LABELS, QUESTIONS, get_brain
from ..models import INNOVATION_ROUTES, ROUTES, ROUTINE_ROUTES

VERSION = "screening-rules v2"

# PROPOSED demo rubric. Adjust the weights with the innovation team.
WEIGHTS = {"business_impact": 0.35, "frequency_reach": 0.25, "alignment": 0.20, "experimentation": 0.20}
CRITERION_NAMES = {
    "business_impact": "Potential business impact",
    "frequency_reach": "Frequency and reach",
    "alignment": "Alignment with agreed business priorities",
    "experimentation": "Need for innovation or experimentation",
}
# PROPOSED demo priorities. Replace with the team's agreed list.
BUSINESS_PRIORITIES = {
    "Reliability and uptime": r"\b(uptime|downtime|outages?|reliab\w*|faults?|failures?|alarms?|cooling)\b",
    "Energy and water efficiency": r"\b(energy|power usage|PUE|water|kwh|efficien\w*)\b",
    "Safety and security": r"\b(safety|hazards?|risks?|security)\b",
    "Speed and productivity": r"\b(manual(ly)?|hours?|delays?|slow|paperwork|reports?|re-?enter|by hand)\b",
    "Cost": r"\b(cost|costs|aed|spend|budget|savings?)\b",
}
BLOCKED = r"\b(blocked|waiting (for|on) (approval|data|access)|no access to (the )?data|not allowed|vendor lock)\b"

# The written decline criteria. Reviewers pick from the same list.
CRITERIA = {
    "not_a_request": {
        "name": "Not a valid request", "auto": True,
        "message": "This doesn't describe a work problem, so it has been closed. If that's a mistake, "
                   "ask for a human review and add more detail.",
    },
    "policy": {
        "name": "Would weaken a safety or security control", "auto": True,
        "message": "We can't take this forward as described, because it would weaken a safety or security "
                   "control. If you think it has been misread, ask for a human review.",
    },
    "duplicate": {
        "name": "Duplicate of an existing request", "auto": False,
        "message": "Thanks. This is already being looked at as {ref}, so we've linked your request to it.",
    },
    "out_of_scope": {
        "name": "Outside innovation scope", "auto": False,
        "message": "This is best handled by {team}. It has been routed to them.",
    },
    "low_value": {
        "name": "Low expected value right now", "auto": False,
        "message": "Thanks for raising this. Based on what we know about its impact and reach, we're not taking it "
                   "forward right now. If the impact grows, please submit it again with numbers.",
    },
    "other": {"name": "Other (explain in the message)", "auto": False, "message": ""},
}
# Which criteria may be applied without a person. Set to an empty set to turn auto-decline off.
AUTO_DECLINE = {code for code, criterion in CRITERIA.items() if criterion["auto"]}


# ── The rubric ───────────────────────────────────────────────────────────────

def score_criteria(record: dict) -> dict:
    text = full_text(record)
    impact = record.get("impact")
    if rules.is_quantified(impact):
        business = (4, f"Quantified by the employee: \"{impact}\" (estimate, not verified)")
    elif impact and re.search(r"\b(minor|small|slight|little|annoy\w*|not (a )?big)\b", impact, re.IGNORECASE):
        business = (1, "The employee describes the impact as minor")
    elif impact and re.search(r"\b(risk|outage|downtime|safety|failure|incident)\b", impact, re.IGNORECASE):
        business = (4, "Describes an operational risk")
    elif impact:
        business = (3, "Impact described but not quantified")
    else:
        business = (None, "Impact unknown")

    frequency = rules.frequency_score(record.get("frequency") or text)
    reach = rules.reach_score(record.get("people_affected"))
    known = [value for value in (frequency, reach) if value is not None]
    frequency_reach = (round(sum(known) / len(known), 1) if known else None,
                       f"Frequency {frequency if frequency is not None else 'unknown'}/5 · "
                       f"reach {reach if reach is not None else 'unknown'}/5")

    priorities = [name for name, pattern in BUSINESS_PRIORITIES.items() if re.search(pattern, text, re.IGNORECASE)]
    alignment = ((min(5, 2 + len(priorities)), "Links to: " + ", ".join(priorities)) if priorities
                 else (None, "No link to an agreed priority found: reviewer to judge"))

    signals = set(rules.innovation_signals(text))
    if record.get("route") in ROUTINE_ROUTES and record.get("innovation_track") == "none":
        experimentation = (0, "Standard request: no experimentation needed")
    elif "needs_experimentation" in signals:
        experimentation = (4, "May need a pilot or a comparison of approaches")
    elif signals & {"recurring_effort", "persistent_failure"}:
        experimentation = (3, "Existing processes keep failing to fix it")
    else:
        experimentation = (None, "Unclear whether a new approach is needed")

    scored = {"business_impact": business, "frequency_reach": frequency_reach,
              "alignment": alignment, "experimentation": experimentation}
    return {name: {"value": value, "reason": reason, "weight": WEIGHTS[name], "name": CRITERION_NAMES[name]}
            for name, (value, reason) in scored.items()}


def compute_priority(criteria: dict) -> dict:
    """Weighted score 0–100 over KNOWN criteria only, plus how much of the rubric was known."""
    known = {name: c for name, c in criteria.items() if c["value"] is not None}
    known_weight = sum(c["weight"] for c in known.values())
    score = round(sum(c["weight"] * c["value"] for c in known.values()) / known_weight * 20) if known else None
    confidence = "high" if known_weight >= 0.8 else "medium" if known_weight >= 0.55 else "low"
    return {"score": score, "confidence": confidence, "known_weight": round(known_weight, 2),
            "unknown": [c["name"] for c in criteria.values() if c["value"] is None], "criteria": criteria}


def feasibility(record: dict, priority: dict) -> str:
    if re.search(BLOCKED, full_text(record), re.IGNORECASE):
        return "blocked"
    enough = record.get("current_process") and record.get("impact") and (
        record.get("frequency") or record.get("people_affected"))
    return "ready_to_investigate" if enough and priority["confidence"] != "low" else "needs_discovery"


def suggested_owner(record: dict) -> str:
    route = record.get("route")
    if route == "process_owner_innovation":
        department = record.get("department")
        return f"{department} process owner" if department and department != "Not specified" else "Process owner (to confirm)"
    if route == "innovation_screening":
        return "Innovation team, with an operations sponsor"
    if route == "human_triage" or route is None:
        return "To be decided in triage"
    return ROUTES[route]


def next_step(record: dict, label: str, owner: str, missing: list) -> str:
    if record.get("innovation_track") == "none":
        return (f"{owner} handles today's request. No innovation action." if record.get("route") in ROUTINE_ROUTES
                else "A person chooses the right owner.")
    if label == "blocked":
        return "Resolve the blocker before investigating."
    if label == "ready_to_investigate":
        return f"Discovery conversation with the employee and the {owner}. Vendor research only after that."
    return "Short discovery to fill the gaps: " + ", ".join(missing[:3]) + "."


# ── The recommendation ───────────────────────────────────────────────────────

def recommend(conn, record: dict, priority: dict) -> dict:
    text = full_text(record)
    requested = record.get("innovation_track") == "employee_requested"

    if record["linked_to"] and not requested:
        return {"decision": "none", "confidence": "high", "reason": f"Linked to {record['linked_to']}; "
                "it is considered together with that opportunity."}
    if rules.is_not_a_request(record["description"]):
        return decline("not_a_request", "high", "The description doesn't describe a work problem.", requested)
    if rules.weakens_control(text):
        return decline("policy", "high", "Asks to disable, bypass or skip a safety or security control.", requested)

    if record.get("innovation_track") == "none":
        route = record.get("route")
        if route in ROUTINE_ROUTES:
            return {"decision": "route", "confidence": "high",
                    "reason": f"Routine request for {ROUTES[route]}; no innovation potential found."}
        return {"decision": "triage", "confidence": "low",
                "reason": "No clear owner and no innovation signal. A person should choose where it goes."}

    similar = search.find_similar_submission(conn, text, exclude_pk=db.parse_pk(record["id"]))
    if similar:
        return {"decision": "link", "confidence": "medium", "link_to": similar["id"],
                "reason": f"Very similar to {similar['id']} \"{similar['title']}\" ({similar['status']}). "
                          "Link them into one opportunity, keeping both records."}

    score, confidence = priority["score"], priority["confidence"]
    if "instruction_attempt" in (record.get("brief") or {}).get("flags", []):
        return {"decision": "ask", "confidence": "low",
                "reason": "The employee's messages contained instructions to the assistant. A person should "
                          "check what is genuinely known before ranking it.",
                "suggested_question": "Could you describe the problem and its impact in your own words?"}
    missing_question = next((QUESTIONS[field] for field in QUESTIONS if not record.get(field)), None)
    if score is None or confidence == "low":
        return {"decision": "ask", "confidence": "low",
                "reason": f"Too little is known to rank it ({', '.join(priority['unknown']) or 'details'} unknown).",
                "suggested_question": missing_question or "Can you tell us more about the impact?"}
    if score >= 60:
        return {"decision": "accept", "confidence": confidence,
                "reason": f"Strong opportunity: priority {score}/100 with {confidence} confidence."}
    if score < 35:
        return decline("low_value", confidence, f"Priority {score}/100: limited impact or reach on what we know.",
                       requested)
    return {"decision": "ask", "confidence": confidence,
            "reason": f"Priority {score}/100: worth a closer look before deciding.",
            "suggested_question": missing_question or "How does this connect to the team's current priorities?"}


def decline(code: str, confidence: str, reason: str, requested: bool, **fill) -> dict:
    message = CRITERIA[code]["message"]
    return {"decision": "decline", "reason_code": code, "criterion": CRITERIA[code]["name"],
            "confidence": confidence, "reason": reason,
            "suggested_message": message.format(**fill) if fill else message,
            # Employee-requested reviews always get a human decision.
            "auto": code in AUTO_DECLINE and not requested}


# ── Running it ───────────────────────────────────────────────────────────────

def screen(conn, submission_id: str, allow_auto: bool = True) -> dict:
    """Route (if not routed yet), brief, prioritise and recommend. Applies a recommendation
    straight away only when it's an automatic policy decline."""
    record = db.get_submission(conn, submission_id)
    pk = db.parse_pk(submission_id)

    if record["route"] is None and not record["linked_to"]:  # form submissions and samples
        route, reason = rules.classify_route(full_text(record))
        if route == "incident":
            route, reason = "human_triage", "Mentions an incident; a person should check it"
        signals = rules.innovation_signals(full_text(record))
        track = record["innovation_track"]
        if track == "none" and (route in INNOVATION_ROUTES or (signals and route not in ROUTINE_ROUTES)):
            track = "screening"
        status = "Routed" if route in ROUTINE_ROUTES and record["status"] == "Submitted" else record["status"]
        conn.execute("UPDATE submissions SET route = ?, route_reason = ?, initial_route = ?, innovation_track = ?,"
                     " status = ? WHERE pk = ?", (route, reason, route, track, status, pk))
        record = db.get_submission(conn, submission_id)

    brief = record["brief"] or get_brain().write_brief(record, {
        "unknown": [field for field in QUESTIONS if not record.get(field)],
        "notes": ["Submitted without the intake assistant"],
        "checked": [], "related": [], "previous_attempts": [], "flags": []})

    criteria = score_criteria(record)
    for name, old in (brief.get("priority") or {}).get("criteria", {}).items():
        if old.get("corrected_by"):  # a reviewer's correction always wins
            criteria[name] = old
    priority = compute_priority(criteria)
    label = feasibility(record, priority) if record["feasibility"] is None or not brief.get("feasibility_set_by") \
        else record["feasibility"]
    owner = suggested_owner(record)
    brief.update(
        priority=priority,
        routing={"route": record["route"], "label": ROUTES.get(record["route"] or "", "Linked"),
                 "reason": record["route_reason"], "innovation_track": record["innovation_track"],
                 "signals": [rules.SIGNAL_LABELS[s] for s in rules.innovation_signals(full_text(record))]},
        feasibility=label,
        suggested_owner=owner,
        next_step=next_step(record, label, owner, [LABELS[f] for f in QUESTIONS if not record.get(f)]),
    )
    conn.execute("UPDATE submissions SET brief_json = ?, score = ?, feasibility = ? WHERE pk = ?",
                 (json.dumps(brief), priority["score"], label, pk))

    recommendation = recommend(conn, record, priority) | {"status": "PROPOSED", "generated_by": VERSION}
    applied = allow_auto and recommendation.get("auto") and record["status"] in ("Submitted", "Routed")
    recommendation["auto_applied"] = bool(applied)
    conn.execute("UPDATE submissions SET recommendation_json = ? WHERE pk = ?", (json.dumps(recommendation), pk))
    conn.execute("INSERT INTO agent_runs (workflow, session_id, prompt_version, model, input_text, output_json,"
                 " created_at) VALUES ('screening', NULL, ?, 'rules', ?, ?, ?)",
                 (VERSION, submission_id, json.dumps(recommendation), db.now()))
    db.add_event(conn, pk, "screening", "screened", record["status"], record["status"],
                 f"Route: {ROUTES.get(record['route'] or '', 'linked')}. Recommends {recommendation['decision']}: "
                 f"{recommendation['reason']}")

    if applied:
        conn.execute("UPDATE submissions SET status = 'Declined', decision_reason = ?, decision_message = ?,"
                     " decided_by = 'screening-policy' WHERE pk = ?",
                     (recommendation["reason_code"], recommendation["suggested_message"], pk))
        db.add_event(conn, pk, "screening-policy", "auto_declined", record["status"], "Declined",
                     recommendation["criterion"])
    return recommendation


def screen_unscreened():
    """Run at startup, so older records and the samples get routes and recommendations too."""
    with db.connect() as conn:
        rows = conn.execute("SELECT pk FROM submissions WHERE recommendation_json IS NULL"
                            " OR route IS NULL AND status != 'Linked'").fetchall()
        for row in rows:
            screen(conn, f"SUB-{row['pk']:04d}", allow_auto=False)


def full_text(record: dict) -> str:
    return " ".join(filter(None, [record.get(field) for field in
                                  ("title", "description", "current_process", "frequency", "people_affected",
                                   "impact", "tried_already", "desired_outcome")]))
