"""Live check of the Research AI with Claude, on a throwaway database.

Accepts the recurring reporting case, asks Claude for ranked solution options, selects the
top-ranked one, and prints the options, ranking, research plan and cost.
Costs real money (roughly $0.10–0.20). Run from the project folder:
    python scripts/live_research_check.py
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
os.environ["HUB_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "research.db")
os.environ.pop("HUB_BRAIN", None)

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

with TestClient(app) as client:
    print("Brain:", client.get("/api/health").json()["brain"])
    record = client.post("/api/submissions", json={
        "title": "Weekly reports are combined by hand", "department": "Operations",
        "description": "Every week, we manually combine reports from several systems.",
        "current_process": "We copy numbers from three tools into one spreadsheet; it should update automatically.",
        "frequency": "Every week", "people_affected": "The reporting team and site managers at 3 sites",
        "impact": "About 6 hours a week, and errors slip in",
        "tried_already": "We tried a shared template but it still needs copying."}).json()
    sid = record["id"]
    client.post(f"/api/submissions/{sid}/review", json={"decision": "accept"})

    started = time.monotonic()
    solutions = client.post(f"/api/submissions/{sid}/solutions", json={}).json()["solutions"]
    print(f"\nOptions took {time.monotonic() - started:.0f}s · {solutions['generated_by']}\n")
    print("COMPARISON:", solutions["comparison"], "\n")
    for o in solutions["options"]:
        print(f"#{o['rank']}  {o['title']}  — usefulness {o['usefulness']}")
        print("    ", o["summary"])
        print("     scores:", ", ".join(f"{k} {v['value']}" for k, v in o["scores"].items()))
        print("     + " + "\n     + ".join(o["pros"]))
        print("     - " + "\n     - ".join(o["cons"]))
        if o.get("unverified_figures"):
            print("     ! unverified figures:", o["unverified_figures"])
        print()

    top = solutions["options"][0]
    started = time.monotonic()
    research = client.post(f"/api/submissions/{sid}/solutions/select",
                           json={"option_id": top["id"], "reason": "Highest usefulness; fits our systems"}).json()
    print(f"Selected #{top['rank']} {top['title']} → status {research['status']} "
          f"(plan took {time.monotonic() - started:.0f}s)\n")
    print("RESEARCH PLAN:", json.dumps({k: v for k, v in research["research"]["plan"].items()}, indent=2))

    conn = sqlite3.connect(os.environ["HUB_DB_PATH"])
    print("\nCOST BY STEP:")
    total = 0
    for workflow, model, cost, fallback in conn.execute(
            "SELECT workflow, model, cost_usd, fallback_used FROM agent_runs WHERE workflow != 'screening'"):
        total += cost or 0
        print(f"  {workflow:18} {model:18} ${cost or 0:.4f}{'  FALLBACK' if fallback else ''}")
    print(f"  {'total':18} {'':18} ${total:.4f}  (plus the brief summary written on submission)")
