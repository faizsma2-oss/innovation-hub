"""Fictional example requests at every stage of the lifecycle, so a new demo sandbox shows the
later screens (solution options, suppliers, pilot, business case, handover, benefits, lessons,
portfolio and weekly report) without walking the whole pipeline first.

Each example is built through the same route functions a reviewer's clicks reach, with the
scripted assistants only: seeding never calls Claude or the web (llm.scripted_only), so a new
sandbox stays fast. Every title starts with "Example:" and every record is submitted by
"example-employee", so they never appear as the demo employee's own requests.
"""
from datetime import timedelta

from . import db, llm
from .meetings import calendar
from .reports import routes as reports
from .research import evaluation, evaluation_routes as ev, pilot_routes as pilot, routes as research, suppliers
from .review import routes as review, screening
from .scale import routes as scale

EXAMPLE_USER = "example-employee"

# The topics avoid the words of the demo's three chat examples (reports, inspections, combining
# systems), so a visitor's chat is still linked to SUB-0001, never to one of these.
REQUESTS = {
    "choose": {
        "title": "Example: Contractor access requests wait days for approval",
        "department": "Security",
        "description": "Contractor access requests travel through email chains between three approvers, so "
                       "contractors often arrive before their access card is ready.",
        "current_process": "Email chain between the host, security and the site manager; should be one approval step.",
        "people_affected": "Hosts and the security desk at 3 fictional sites",
        "impact": "About 5 hours a week chasing approvals, and contractors waiting at the gate",
    },
    "research": {
        "title": "Example: Chiller alarms are acknowledged one at a time",
        "department": "Engineering",
        "description": "Overnight engineers acknowledge each chiller alarm separately, even when one fault "
                       "triggers dozens of related alarms.",
        "current_process": "Every alarm is opened and acknowledged in the BMS; related alarms should be grouped.",
        "people_affected": "The overnight engineering shift at 2 fictional sites",
        "impact": "About 4 hours a week, and real faults get buried under repeat alarms",
    },
    "pilot": {
        "title": "Example: Cooling tower water readings are logged on paper",
        "department": "Facilities",
        "description": "Technicians write cooling tower water readings on paper clipboards and type them "
                       "into a spreadsheet at the end of the shift.",
        "current_process": "Paper clipboard, then typed into a spreadsheet; readings should be captured once on a tablet.",
        "people_affected": "Facilities technicians at 2 fictional sites",
        "impact": "About 3 hours a week of retyping, and missed readings are noticed late",
    },
    "scaling": {
        "title": "Example: UPS battery test results are retyped into the asset tool",
        "department": "Engineering",
        "description": "Battery test results come out of the test kit as a file, and engineers retype each "
                       "value into the asset management tool.",
        "current_process": "Export from the test kit, retype into the asset tool; the file should import directly.",
        "people_affected": "Electrical engineers at 3 fictional sites",
        "impact": "About 6 hours a week, plus typing mistakes in battery health records",
    },
    "operation": {
        "title": "Example: Rack power readings are collected by walking the floor",
        "department": "Operations",
        "description": "Twice a day an operator walks the data hall noting rack power readings from each PDU "
                       "display, then types them into a capacity sheet.",
        "current_process": "Walk the hall with a clipboard, then type up; readings should flow from the PDUs automatically.",
        "people_affected": "Operations shift at 3 fictional sites",
        "impact": "About 7 hours a week, and capacity alerts arrive half a day late",
    },
    "stopped": {
        "title": "Example: Fibre patch records go out of date",
        "department": "IT",
        "description": "Fibre patching changes are recorded in a cabling database after the work, and the "
                       "records often lag behind what is actually patched.",
        "current_process": "Technician updates the cabling database after each change; records should update as patching happens.",
        "people_affected": "Network technicians at 2 fictional sites",
        "impact": "About 3 hours a week tracing cables, and occasional patching mistakes",
    },
}


def seed():
    """Add the examples once. Safe to call again: it does nothing if they are already there."""
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM submissions WHERE submitted_by = ?", (EXAMPLE_USER,)).fetchone():
            return
    token = llm.scripted_only.set(True)
    try:
        build()
    finally:
        llm.scripted_only.reset(token)


# Each pilot's two agreed metrics: (metric, unit, target, baseline values, pilot values). Lower is better.
PILOTS = {
    "pilot": [("Minutes per reading round", "minutes", 15, (45, 42, 48), (14, 12)),
              ("Missed readings per week", "readings", 1, (4, 5, 3), (1, 0))],
    "scaling": [("Hours retyping per week", "hours", 2, (6, 6.5, 5.5), (1.5, 1.8, 1.6)),
                ("Typing errors per week", "errors", 1, (4, 3, 5), (0, 1, 0))],
    "operation": [("Hours collecting readings per week", "hours", 2, (7, 7.5, 6.5), (1.2, 1.0, 1.4)),
                  ("Hours until a capacity alert", "hours", 1, (12, 10, 14), (0.5, 0.3, 0.4))],
    "stopped": [("Hours tracing cables per week", "hours", 1, (3, 4.5, 2.5), (3.2, 3.6, 3.1)),
                ("Patching mistakes per month", "mistakes", 0.5, (2, 1, 3), (2, 2, 1))],
}


def build():
    today = calendar.today()
    day = lambda offset: (today + timedelta(days=offset)).isoformat()

    choose = accepted("choose")
    research.propose_solutions(choose, research.OptionsIn())

    in_research = researching("research")
    research.research_suppliers(in_research, research.SupplierSetupIn(**supplier_setup()))
    found = db_record(in_research)["research"]["suppliers"]["suppliers"]
    research.shortlist_suppliers(in_research, research.ShortlistIn(
        names=[s["name"] for s in found[:2]], note="Example shortlist: the two closest fits."))
    ev.prepare(in_research, ev.SupplierIn(supplier=found[0]["name"]))

    running = pilot_running("pilot", day)
    log_pilot(running, "pilot", "pilot", day)                   # 2 of the 3 points needed: still running
    pilot.add_observation(running, pilot.ObservationIn(
        text="Example observation: technicians found the tablet form quicker after the first week."))

    scaling = scaled("scaling", day)
    scale.business_case(scaling, scale.CaseIn(**business_case(
        ("hours_retyping_per_week", 150, 52), ("typing_errors_per_week", 200, 52))))

    live = scaled("operation", day)
    scale.business_case(live, scale.CaseIn(**business_case(("hours_collecting_readings_per_week", 150, 52))))
    scale.management_decision(live, scale.DecisionIn(decision="approve", reason="Example: pays back within a year"))
    for index in range(len(db_record(live)["research"]["scale"]["rollout"]["handover"])):
        scale.handover_item(live, scale.ItemIn(index=index, done=True))
    scale.handover(live, scale.HandoverIn(business_owner="Example Owner (Operations)", handover_date=day(-100)))
    scale.benefits_checkin(live, scale.CheckinIn(
        index=0, values={"hours_collecting_readings_per_week": 1.6, "hours_until_a_capacity_alert": 0.5},
        note="Example 3-month check-in: the saving has mostly held."))
    scale.draft_lesson(live)
    scale.publish_lesson(live, scale.LessonIn(
        title="Example: automatic rack power readings",
        summary="Fictional example. PDU readings now flow into the capacity sheet automatically, "
                "so nobody walks the hall to collect them.",
        keywords=["rack power readings", "pdu readings"]))

    stopped = pilot_running("stopped", day)
    log_pilot(stopped, "stopped", "pilot", day)
    pilot.evaluate_pilot(stopped)
    pilot.decide(stopped, pilot.DecisionIn(decision="stop", reason="Example: no clear change from the baseline"))
    scale.draft_lesson(stopped)
    scale.publish_lesson(stopped, scale.LessonIn(
        title="Example: fibre patch tracking pilot (stopped)",
        summary="Fictional example. Scanning labels during patching did not change how often records lagged; "
                "the delay came from change approvals, not from data entry.",
        keywords=["fibre patch records", "patching records"]))

    reports.weekly_report()


# ── The steps, in the order a reviewer would take them ──────────────────────

def accepted(key: str) -> str:
    with db.connect() as conn:
        values = {field: None for field in ("current_process", "people_affected", "frequency", "impact",
                                            "tried_already", "desired_outcome", "suggested_solution")}
        sid = db.insert_submission(conn, values | REQUESTS[key], EXAMPLE_USER)
        screening.screen(conn, sid, allow_auto=False, use_ai=False)
    review.review(sid, review.ReviewIn(decision="accept", message="Example: accepted for discovery"))
    return sid


def researching(key: str) -> str:
    sid = accepted(key)
    research.propose_solutions(sid, research.OptionsIn())
    research.select_solution(sid, research.SelectIn(option_id="B", reason="Example: uses tools already in place"))
    return sid


def pilot_running(key: str, day) -> str:
    sid = researching(key)
    research.research_suppliers(sid, research.SupplierSetupIn(**supplier_setup()))
    partner = db_record(sid)["research"]["suppliers"]["suppliers"][0]["name"]
    research.shortlist_suppliers(sid, research.ShortlistIn(names=[partner]))
    for item in evaluation.CHECKLIST:
        if item["required"]:
            ev.update_checklist(sid, ev.ChecklistIn(supplier=partner, item=item["key"], status="passed",
                                                    owner="Example Reviewer"))
    ev.choose_pilot_partner(sid, ev.PartnerIn(supplier=partner, reason="Example: passed every required check"))
    pilot.agree_setup(sid, pilot.SetupIn(
        criteria=[{"metric": metric, "unit": unit, "direction": "lower_better", "target": target}
                  for metric, unit, target, _, _ in PILOTS[key]],
        owner="Example Pilot Owner", start_date=day(-30), end_date=day(30)))
    log_pilot(sid, key, "baseline", day)
    pilot.start_pilot(sid)
    return sid


def scaled(key: str, day) -> str:
    sid = pilot_running(key, day)
    log_pilot(sid, key, "pilot", day)
    pilot.evaluate_pilot(sid)
    pilot.decide(sid, pilot.DecisionIn(decision="scale", reason="Example: both targets met"))
    return sid


def log_pilot(sid: str, key: str, phase: str, day):
    """Baseline readings 6 to 4 weeks ago, pilot readings in the last 3 weeks, a week apart."""
    for metric, _, _, baseline, piloted in PILOTS[key]:
        values, start = (baseline, -42) if phase == "baseline" else (piloted, -20)
        for offset, value in enumerate(values):
            pilot.log_measurement(sid, pilot.MeasurementIn(metric=pilot.key_for(metric), phase=phase, value=value,
                                                           date=day(start + offset * 7)))


def supplier_setup() -> dict:
    setup = suppliers.default_setup()
    setup["factors"] = [{k: f[k] for k in ("key", "name", "description", "importance")} for f in setup["factors"]]
    return setup


def business_case(*benefits) -> dict:
    """Fictional figures: AED per unit saved, periods per year, across 3 sites."""
    return {"currency": "AED",
            "one_off": [{"item": "Example: setup and integration", "amount": 40000}],
            "yearly": [{"item": "Example: licences and support", "amount": 10000}],
            "benefits": [{"metric_key": key, "value_per_unit": value, "periods_per_year": periods, "multiplier": 3}
                         for key, value, periods in benefits]}


def db_record(sid: str) -> dict:
    with db.connect() as conn:
        return db.get_submission(conn, sid)


if __name__ == "__main__":   # add the examples to the local database: python -m backend.examples
    db.init_db()
    screening.screen_unscreened()
    seed()
    print("Example requests added (or already there).")
