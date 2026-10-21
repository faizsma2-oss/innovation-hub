"""Research API: solution options for an accepted request, the team's selection, and then
supplier research for the chosen option.

  Accepted ── Research AI proposes ranked options (PROPOSED) ── team may ask again with feedback
           └─ team selects one option, with a reason ──▶ Research (plan drafted)
  Research ── team answers the setup questions (factors, weights, where, prices)
           └─ Research AI searches the web and compares suppliers ── team shortlists
"""
import json
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from .. import db
from ..models import SubmissionOut
from ..review.routes import DEMO_REVIEWER, load
from . import licensed, reuse, suppliers
from .researcher import CRITERIA, get_researcher, problem_facts, rank

router = APIRouter(tags=["research"])


class OptionsIn(BaseModel):
    feedback: str | None = Field(default=None, max_length=1000)  # "ask again" with what to change


class SelectIn(BaseModel):
    option_id: str = Field(min_length=1, max_length=2)
    reason: str = Field(min_length=1, max_length=1000)


class ToolIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    good_for: str = Field(min_length=3, max_length=300)
    status: Literal["assumed", "confirmed"] = "assumed"


class ToolsIn(BaseModel):
    tools: list[ToolIn] = Field(max_length=30)


@router.get("/api/research/licensed-tools")
def licensed_tools():
    with db.connect() as conn:
        return licensed.load(conn)


@router.put("/api/research/licensed-tools")
def save_licensed_tools(body: ToolsIn):
    with db.connect() as conn:
        keywords = {t["name"].lower(): t.get("keywords") for t in licensed.load(conn)}
        names = [t.name.strip().lower() for t in body.tools]
        if len(set(names)) != len(names):
            raise HTTPException(422, "Each tool should be listed once")
        tools = [{"name": t.name.strip(), "good_for": t.good_for.strip(), "status": t.status,
                  **({"keywords": keywords[t.name.strip().lower()]} if keywords.get(t.name.strip().lower()) else {})}
                 for t in body.tools]
        licensed.save(conn, tools)
        return tools


@router.get("/api/research/criteria")
def research_criteria():
    return [{"key": key, "name": name, "weight": weight} for key, (name, weight) in CRITERIA.items()]


@router.post("/api/submissions/{submission_id}/solutions", response_model=SubmissionOut)
def propose_solutions(submission_id: str, body: OptionsIn):
    with db.connect() as conn:
        record = load(conn, submission_id)
        if record["status"] != "Accepted":
            raise HTTPException(409, "Solution options are prepared only for accepted requests")
        researcher, meter = get_researcher(), []
        tools = licensed.load(conn)
        result = researcher.options(record, body.feedback, meter, licensed_tools=tools)
        # Rule, in code: one option is always built on tools Khazna already licenses.
        text = " ".join(str(value) for value in problem_facts(record).values() if value)
        result["options"] = rank(licensed.guarantee(result["options"], tools, text))
        result["licensed_tools"] = licensed.for_ai(tools)
        previous = record.get("solutions") or {}
        solutions = result | {
            "status": "PROPOSED",
            "round": previous.get("round", 0) + 1,
            "feedback": body.feedback,
            "weights": {key: weight for key, (_, weight) in CRITERIA.items()},
        }
        pk = db.parse_pk(submission_id)
        conn.execute("UPDATE submissions SET solutions_json = ? WHERE pk = ?", (json.dumps(solutions), pk))
        log_run(conn, "solution_options", submission_id, researcher, meter, solutions)
        titles = "; ".join(f"{o['rank']}. {o['title']} ({o['usefulness']})" for o in solutions["options"])
        db.add_event(conn, pk, "research-ai", "options_proposed", None, None,
                     (f"Round {solutions['round']} after feedback: {body.feedback}. " if body.feedback else "") + titles)
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/solutions/evidence", response_model=SubmissionOut)
def check_option_evidence(submission_id: str):
    """On request: check each option's real-world evidence on the web, then re-rank with the verified scores."""
    from .. import budget, llm
    from . import evidence
    with db.connect() as conn:
        record = load(conn, submission_id)
        solutions = record.get("solutions") or {}
        if record["status"] != "Accepted" or not solutions.get("options"):
            raise HTTPException(409, "Check the evidence once options are prepared, before one is selected")
        meter = []
        try:
            checked = evidence.check_evidence(record, solutions["options"], meter)
        except evidence.Unavailable:
            reason = budget.status().get("blocked") or "The AI assistant isn't switched on here."
            raise HTTPException(409, f"{reason} The web check needs it, so nothing changed.")
        except (llm.LLMError, KeyError, TypeError) as error:
            raise HTTPException(502, f"The web check didn't work ({str(error)[:150]}), so nothing changed. Try again later.")
        for option in solutions["options"]:
            result = checked["options"][option["id"]]
            before = option["scores"]["evidence"]["value"]
            if result["score"]:
                option["scores"]["evidence"] = {"value": result["score"], "reason": f"Web check: {result['reason']}"}
            option["evidence_check"] = result | {"before": before, "after": option["scores"]["evidence"]["value"]}
        rank(solutions["options"])
        solutions["evidence_check"] = {k: checked[k] for k in ("summary", "sources_retrieved", "generated_by")} | {
            "checked_at": db.now(), "cost_usd": round(sum(m.get("cost_usd", 0) for m in meter), 4)}
        pk = db.parse_pk(submission_id)
        conn.execute("UPDATE submissions SET solutions_json = ? WHERE pk = ?", (json.dumps(solutions), pk))
        log_run(conn, "option_evidence", submission_id, type("Checker", (), {"name": "claude", "version": evidence.VERSION}),
                meter, {"sources": checked["sources_retrieved"]})
        db.add_event(conn, pk, "research-ai", "options_evidence_checked", None, None,
                     "; ".join(f"{o['title']}: evidence {o['evidence_check']['before']} → {o['evidence_check']['after']}"
                               f" ({len(o['evidence_check']['findings'])} sources)" for o in solutions["options"]))
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/solutions/select", response_model=SubmissionOut)
def select_solution(submission_id: str, body: SelectIn):
    with db.connect() as conn:
        record = load(conn, submission_id)
        if record["status"] != "Accepted":
            raise HTTPException(409, "Only an accepted request with options can start research")
        options = (record.get("solutions") or {}).get("options", [])
        option = next((o for o in options if o["id"] == body.option_id), None)
        if option is None:
            raise HTTPException(422, "Choose one of the proposed options")
        researcher, meter = get_researcher(), []
        plan = researcher.plan(record, option, meter)
        research = {
            "status": "Research started",
            "selected_option": option,
            "selected_rank": option["rank"],
            "agreed_with_top_rank": option["rank"] == 1,
            "reason": body.reason.strip(),
            "selected_by": DEMO_REVIEWER,
            "started_at": db.now(),
            "plan": plan,
        }
        pk = db.parse_pk(submission_id)
        conn.execute("UPDATE submissions SET status = 'Research', research_json = ? WHERE pk = ?",
                     (json.dumps(research), pk))
        log_run(conn, "research_plan", submission_id, researcher, meter, research)
        db.add_event(conn, pk, DEMO_REVIEWER, "option_selected", "Accepted", "Research",
                     f"Option {option['id']} \"{option['title']}\" (ranked {option['rank']}): {body.reason.strip()}")
        return db.get_submission(conn, submission_id)


def log_run(conn, workflow: str, submission_id: str, researcher, meter: list, output: dict):
    last = meter[-1] if meter else {"brain": researcher.name, "version": researcher.version}
    conn.execute("INSERT INTO agent_runs (workflow, session_id, prompt_version, model, input_text, output_json,"
                 " created_at, input_tokens, output_tokens, cost_usd, fallback_used)"
                 " VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (workflow, last["version"], last["brain"], submission_id, json.dumps(output | {"calls": meter}),
                  db.now(), sum(m.get("input_tokens", 0) for m in meter), sum(m.get("output_tokens", 0) for m in meter),
                  round(sum(m.get("cost_usd", 0) for m in meter), 5), int(any(m.get("fallback") for m in meter))))


# ── Supplier research (after an option is chosen) ────────────────────────────

class FactorIn(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    importance: Literal["must", "high", "medium", "low"]


class SupplierSetupIn(BaseModel):
    factors: list[FactorIn] = Field(min_length=1, max_length=15)
    geography: Literal["uae_first", "uae_gcc", "global"]
    cost_policy: Literal["published_only", "estimates", "relative"]
    supplier_count: int = Field(ge=3, le=6)
    notes: str = Field(default="", max_length=1000)
    reuse: list[str] = Field(default_factory=list, max_length=5)   # earlier requests whose suppliers to reuse
    web_search: bool = True                                          # False: reuse only, no new search, no cost

    @model_validator(mode="after")
    def check(self):
        if len({f.key for f in self.factors}) != len(self.factors):
            raise ValueError("Each factor needs a different name")
        if not any(f.importance != "must" for f in self.factors):
            raise ValueError("Choose at least one factor that isn't a must-have, so suppliers can be ranked")
        if not self.web_search and not self.reuse:
            raise ValueError("Search the web, reuse earlier research, or both")
        if any(not re.fullmatch(r"SUB-\d{4}", sid) for sid in self.reuse):
            raise ValueError("Reuse earlier research by request number, e.g. SUB-0005")
        return self


class ShortlistIn(BaseModel):
    names: list[str] = Field(min_length=1, max_length=6)
    note: str = Field(default="", max_length=1000)


SETUP_KEY = "supplier_setup_defaults"


@router.get("/api/research/supplier-setup")
def supplier_setup():
    """The questions asked before every supplier search, pre-filled with the last answers used."""
    with db.connect() as conn:
        defaults = db.get_setting(conn, SETUP_KEY) or suppliers.default_setup()
    return {"library": suppliers.FACTOR_LIBRARY, "geography": suppliers.GEOGRAPHY,
            "cost_policy": suppliers.COST_POLICY, "defaults": defaults}


@router.post("/api/submissions/{submission_id}/suppliers/suggest-factors")
def suggest_factors(submission_id: str):
    with db.connect() as conn:
        record = in_research(conn, submission_id)
        researcher, meter = suppliers.get_supplier_researcher(), []
        factors = researcher.suggest_factors(record, record["research"]["selected_option"], meter)
        log_run(conn, "supplier_factors", submission_id, researcher, meter, {"factors": factors})
    return [f | {"key": suppliers.slug(f["name"])} for f in factors]


@router.get("/api/submissions/{submission_id}/suppliers/earlier")
def earlier_research(submission_id: str):
    """Supplier comparisons from other requests with a similar chosen approach."""
    with db.connect() as conn:
        record = in_research(conn, submission_id)
        return reuse.earlier_runs(conn, db.parse_pk(submission_id), record["research"])


@router.post("/api/submissions/{submission_id}/suppliers", response_model=SubmissionOut)
def research_suppliers(submission_id: str, body: SupplierSetupIn):
    setup = body.model_dump(exclude={"reuse", "web_search"})
    with db.connect() as conn:
        record = in_research(conn, submission_id)
        db.set_setting(conn, SETUP_KEY, setup)   # remembered to pre-fill the next run
        offered = {run["submission_id"] for run in reuse.earlier_runs(conn, db.parse_pk(submission_id), record["research"])}
        if not set(body.reuse) <= offered:
            raise HTTPException(422, "Reuse only earlier research offered for this request")
        researcher, meter = suppliers.get_supplier_researcher(), []
        if body.web_search:
            result = researcher.research(record, record["research"]["selected_option"], setup, meter)
        else:
            result = {"suppliers": [], "summary": "Reused earlier research only: no new web search.", "searches": 0,
                      "sources_retrieved": 0, "gaps": [], "generated_by": "reuse"}
        if body.reuse:
            reused = reuse.reused_suppliers(conn, body.reuse, setup)
            result["suppliers"] = suppliers.rank(reuse.merge(result["suppliers"], reused), setup)
            result["reused_from"] = body.reuse
            db.add_event(conn, db.parse_pk(submission_id), DEMO_REVIEWER, "suppliers_reused", None, None,
                         f"{len(reused)} suppliers reused from {', '.join(body.reuse)}"
                         + ("" if body.web_search else " without a new web search"))
        research = record["research"]
        previous = research.get("suppliers") or {}
        research["suppliers"] = result | {"status": "PROPOSED", "setup": setup, "round": previous.get("round", 0) + 1,
                                          "run_at": db.now(), "shortlist": None,
                                          "cost_usd": round(sum(m.get("cost_usd", 0) for m in meter), 4)}
        pk = db.parse_pk(submission_id)
        conn.execute("UPDATE submissions SET research_json = ? WHERE pk = ?", (json.dumps(research), pk))
        log_run(conn, "supplier_research", submission_id, researcher, meter, {"suppliers": len(result["suppliers"])})
        db.add_event(conn, pk, "research-ai", "suppliers_found", None, None,
                     f"{len(result['suppliers'])} suppliers compared on {len(setup['factors'])} factors "
                     f"({setup['geography']}, {setup['cost_policy']}): "
                     + "; ".join(f"{s['rank']}. {s['name']}" for s in result["suppliers"]))
        return db.get_submission(conn, submission_id)


@router.post("/api/submissions/{submission_id}/suppliers/shortlist", response_model=SubmissionOut)
def shortlist_suppliers(submission_id: str, body: ShortlistIn):
    with db.connect() as conn:
        record = in_research(conn, submission_id)
        found = (record["research"].get("suppliers") or {}).get("suppliers", [])
        names = {s["name"] for s in found}
        if not found or not set(body.names) <= names:
            raise HTTPException(422, "Shortlist suppliers from the latest comparison")
        research = record["research"]
        research["suppliers"]["shortlist"] = {"names": body.names, "note": body.note.strip(),
                                              "by": DEMO_REVIEWER, "at": db.now()}
        pk = db.parse_pk(submission_id)
        conn.execute("UPDATE submissions SET research_json = ? WHERE pk = ?", (json.dumps(research), pk))
        db.add_event(conn, pk, DEMO_REVIEWER, "suppliers_shortlisted", None, None,
                     ", ".join(body.names) + (f": {body.note.strip()}" if body.note.strip() else ""))
        return db.get_submission(conn, submission_id)


def in_research(conn, submission_id: str) -> dict:
    record = load(conn, submission_id)
    if record["status"] != "Research":
        raise HTTPException(409, "Supplier research starts after a solution option is chosen")
    return record
