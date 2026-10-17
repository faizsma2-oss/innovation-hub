"""Live check of supplier research with Claude and web search, on a throwaway database.

To save money it skips the option step: the request is put straight into Research with the
"Spreadsheet-level automated data import" option from the earlier live check.
Costs real money (roughly $0.30–0.80). Run from the project folder:
    python scripts/live_supplier_check.py
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
os.environ["HUB_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "suppliers.db")
os.environ.pop("HUB_BRAIN", None)

from fastapi.testclient import TestClient  # noqa: E402

from backend import db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.research import suppliers  # noqa: E402

OPTION = {
    "id": "B", "rank": 1, "usefulness": 78, "title": "Spreadsheet-level automated data import",
    "summary": "Use the built-in data connection or import features of the spreadsheet environment (or scheduled "
               "exports from the three tools into a shared folder) so the consolidated sheet refreshes from source "
               "exports instead of manual copying.",
    "how_it_helps": "Removes the weekly manual copying while staying in the spreadsheet the team already uses.",
    "assumptions": ["The three tools can export data or offer a connector"],
}

with TestClient(app) as client:
    record = client.post("/api/submissions", json={
        "title": "Weekly reports are combined by hand", "department": "Operations",
        "description": "Every week, we manually combine reports from several systems.",
        "current_process": "We copy numbers from three tools into one spreadsheet; it should update automatically.",
        "frequency": "Every week", "people_affected": "The reporting team and site managers at 3 sites",
        "impact": "About 6 hours a week, and errors slip in"}).json()
    sid = record["id"]
    with db.connect() as conn:
        research = {"status": "Research started", "selected_option": OPTION, "selected_rank": 1,
                    "agreed_with_top_rank": True, "reason": "Live check", "selected_by": "live-check",
                    "started_at": db.now(), "plan": {}}
        conn.execute("UPDATE submissions SET status = 'Research', research_json = ? WHERE pk = ?",
                     (json.dumps(research), db.parse_pk(sid)))

    setup = suppliers.default_setup()
    setup["factors"] = [{k: f[k] for k in ("key", "name", "description", "importance")} for f in setup["factors"]]
    for factor in setup["factors"]:
        if factor["key"] == "data_residency":
            factor["importance"] = "must"
    setup |= {"geography": "uae_first", "cost_policy": "published_only", "supplier_count": 4}

    started = time.monotonic()
    response = client.post(f"/api/submissions/{sid}/suppliers", json=setup)
    elapsed = time.monotonic() - started
    result = response.json()["research"]["suppliers"]

    print(f"Took {elapsed:.0f}s · {result['generated_by']} · {result['searches']} web searches · "
          f"{result['sources_retrieved']} sources retrieved · ${result['cost_usd']}")
    if result.get("error"):
        print("ERROR (fell back to examples):", result["error"])
    print("\nSUMMARY:", result["summary"])
    if result["gaps"]:
        print("GAPS:", *result["gaps"], sep="\n  - ")
    names = {f["key"]: f["name"] for f in setup["factors"]}
    for s in result["suppliers"]:
        print(f"\n#{s['rank']}  {s['name']}  — fit {s['fit_score']} ({s['confidence']} confidence) · {s['eligibility']}")
        print(f"    {s['headquarters']} · UAE: {s['uae_presence']} · {s['website']}")
        print(f"    Offers: {s['offering']}")
        cost = s["cost"]
        print(f"    Cost: {cost['published_price']}" + (f"  {cost['sources']}" if cost["sources"] else ""))
        for key, item in s["findings"].items():
            rating = item["rating"] or "?"
            must = f" must-have: {item['must_have_met']}" if key == "data_residency" else ""
            print(f"    - {names[key]}: {rating}/5{must} [{item['evidence']}] {item['finding'][:140]}")
            for url in item["sources"]:
                print(f"        {url}")
        if s["questions_for_supplier"]:
            print("    Ask them:", "; ".join(s["questions_for_supplier"][:3]))

    conn = sqlite3.connect(os.environ["HUB_DB_PATH"])
    print("\nCOST BY STEP:")
    for workflow, cost, fallback, calls in conn.execute(
            "SELECT workflow, cost_usd, fallback_used, output_json FROM agent_runs WHERE workflow = 'supplier_research'"):
        for call in json.loads(calls)["calls"]:
            print(f"  {call.get('brain')}: in {call.get('input_tokens', 0):,} tok, out {call.get('output_tokens', 0):,} tok, "
                  f"{call.get('web_searches', 0)} searches, ${call.get('cost_usd', 0):.4f}{'  FALLBACK' if call.get('fallback') else ''}")
        print(f"  total: ${cost:.4f}")
