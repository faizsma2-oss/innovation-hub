"""Live check of the meetings workflow with Claude, on a throwaway database.

Uses Zoho (a real supplier from the earlier live supplier search), finds its official contact
channels on the web, plans a meeting, schedules it, and debriefs a sample meeting note.
Costs real money (roughly $0.30–0.60). Run from the project folder:
    python scripts/live_meetings_check.py
"""
import json
import os
import sqlite3
import sys
import tempfile
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)
os.environ["HUB_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "meetings.db")
os.environ.pop("HUB_BRAIN", None)

from fastapi.testclient import TestClient  # noqa: E402

from backend import db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.research import suppliers  # noqa: E402

SUPPLIER = "Zoho Corporation"
setup = suppliers.default_setup()
setup["factors"] = [{k: f[k] for k in ("key", "name", "description", "importance")} for f in setup["factors"]]
for factor in setup["factors"]:
    if factor["key"] == "data_residency":
        factor["importance"] = "must"
zoho = {"name": SUPPLIER, "website": "https://www.zoho.com", "headquarters": "Chennai, India (regional HQ Dubai)",
        "uae_presence": "Office in Dubai Media City; data centres in Dubai and Abu Dhabi",
        "offering": "Zoho Sheet Data Connection and Zoho Analytics scheduled imports",
        "findings": {f["key"]: {"rating": None, "finding": "Not found.", "evidence": "not found", "sources": [],
                                "must_have_met": "unknown"} for f in setup["factors"]},
        "cost": {"published_price": "Price on request", "price_is_published": False, "estimate": None,
                 "relative": "unknown", "sources": []},
        "questions_for_supplier": ["Confirm in writing that Zoho Sheet and Zoho Analytics run in the UAE data centres.",
                                   "What are paid plan and Zoho Analytics prices?"]}
suppliers.rank([zoho], setup)

NOTES = """Teams call with Zoho, 3 November. Attendees: Sara (Operations), Omar (IT), Rania from Zoho's Dubai partner team.
Rania demoed Zoho Sheet Data Connection pulling from two of our three tools; the third has no export API, so it would need a CSV drop.
She confirmed Zoho Sheet and Analytics data for UAE customers is hosted in the Dubai data centre and said she will send written confirmation.
Pricing for Analytics depends on users; she will send a quote for 15 users.
Omar raised SSO; Rania said Azure AD SSO is supported on paid plans.
Agreed: Sara will send three sample weekly exports by 6 November. Rania will send the data residency letter and the quote.
Someone needs to check the CSV workaround with the tool owner. Next call to be arranged after the quote arrives."""

with TestClient(app) as client:
    record = client.post("/api/submissions", json={
        "title": "Weekly reports are combined by hand", "department": "Operations",
        "description": "Every week, we manually combine reports from several systems.",
        "current_process": "We copy numbers from three tools into one spreadsheet; it should update automatically.",
        "frequency": "Every week", "people_affected": "The reporting team and site managers at 3 sites",
        "impact": "About 6 hours a week, and errors slip in"}).json()
    sid = record["id"]
    research = {"status": "Research started", "selected_option": {"id": "B", "rank": 1, "usefulness": 78,
                "title": "Spreadsheet-level automated data import", "summary": "Refresh the sheet from source exports."},
                "plan": {}, "suppliers": {"setup": setup, "suppliers": [zoho], "shortlist": {"names": [SUPPLIER]}}}
    with db.connect() as conn:
        conn.execute("UPDATE submissions SET status = 'Research', research_json = ? WHERE pk = ?",
                     (json.dumps(research), db.parse_pk(sid)))

    t = time.monotonic()
    found = client.post(f"/api/submissions/{sid}/contacts/find", json={"supplier": SUPPLIER}).json()
    print(f"CONTACTS ({time.monotonic() - t:.0f}s, {found.get('searches', 0)} searches, ${found.get('cost_usd', 0)}) · {found['generated_by']}")
    if found.get("error"):
        print("  ERROR (fell back to examples):", found["error"])
    print("  ", found["summary"])
    for c in found["contacts"]:
        print(f"  #{c['rank']}{' BEST' if c['best'] else ''}  {c['label']}: {c['value']}  [{c['region']}]  {c['note']}")
        print(f"       source: {c['source_url']}" + (f"  ⚠ {c['flags']}" if c["flags"] else ""))

    email = next((c["value"] for c in found["contacts"] if "@" in c["value"]), None)
    t = time.monotonic()
    meeting = client.post("/api/meetings", json={"submission_id": sid, "supplier": SUPPLIER, "contact": email,
                                                 "proposed_slots": ["2026-11-03T10:00", "2026-11-04T14:00"],
                                                 "internal_attendees": "Sara (Operations), Omar (IT)"}).json()
    print(f"\nPLAN ({time.monotonic() - t:.0f}s) · {meeting['plan']['generated_by']}")
    for item in meeting["plan"]["agenda"]:
        print(f"   - {item['item']} ({item['minutes']} min)")
    print("   Subject:", meeting["plan"]["email_subject"])
    print("   " + meeting["plan"]["email_body"].replace("\n", "\n   "))
    print("   flags:", meeting["plan"]["flags"])

    client.post(f"/api/meetings/{meeting['id']}/sent")
    client.post(f"/api/meetings/{meeting['id']}/schedule", json={"start_at": "2026-11-03T10:00", "duration_min": 45,
                                                               "teams_link": "https://teams.microsoft.com/l/meetup-join/example"})
    t = time.monotonic()
    held = client.post(f"/api/meetings/{meeting['id']}/debrief", json={"notes": NOTES}).json()
    d = held["debrief"]
    print(f"\nDEBRIEF ({time.monotonic() - t:.0f}s) · {d['generated_by']}")
    print("   Summary:", d["summary"])
    print("   Decisions:", d["decisions"])
    print("   Actions:")
    for a in held["actions"]:
        print(f"     - {a['action']} | owner: {a['owner']} | due: {a['due'] or '—'} (written: {a['due_text']})")
    print("   Next steps:")
    for s in d["next_steps"]:
        print(f"     - {s['step']}  ({s['why']})")
    print("   Risks:", d["risks"])
    print("   Comparison updates:", [(u["factor_key"], u["rating"], u["must_have_met"]) for u in d["factor_updates"]])
    print("   Follow-up subject:", d["follow_up_subject"], "| flags:", d["flags"])
    print("   " + d["follow_up_body"].replace("\n", "\n   "))

    reminders = client.get("/api/reminders").json()
    print("\nREMINDERS:", [r["text"] for r in reminders["items"]])

    conn = sqlite3.connect(os.environ["HUB_DB_PATH"])
    print("\nCOST BY STEP:")
    total = 0
    for workflow, cost, fallback in conn.execute(
            "SELECT workflow, cost_usd, fallback_used FROM agent_runs WHERE workflow LIKE 'supplier_contacts'"
            " OR workflow LIKE 'meeting%'"):
        total += cost or 0
        print(f"  {workflow:18} ${cost or 0:.4f}{'  FALLBACK' if fallback else ''}")
    print(f"  {'total':18} ${total:.4f}")
