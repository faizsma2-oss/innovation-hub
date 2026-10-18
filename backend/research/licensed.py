"""Tools Khazna already licenses, and the rule that every set of solution options includes one built on them.

Why: before buying new software, check whether something already paid for does the job. That avoids
licence cost and months of security review and procurement.

  - The team keeps the list (name, what it's good for, assumed or confirmed by IT).
  - The Research AI must build at least one option on these tools and say which ones it uses.
  - The code removes any tool name that isn't on the list, and adds the option itself if the AI left it
    out. The ranking is unchanged: no bonus points, the option competes on its scores like the others.
"""
from ..intake.search import tokens

SETTING = "licensed_tools"
STATUSES = ("assumed", "confirmed")

# Typical Microsoft 365 tools in an enterprise licence. Marked "assumed": confirm with Khazna IT.
DEFAULT_TOOLS = [
    {"name": "Power Automate", "good_for": "Automated workflows and approvals between Microsoft 365 apps and other systems; "
     "scheduled jobs; moving data between spreadsheets, email and lists",
     "keywords": ["approval", "automate", "automatic", "email", "workflow", "chase", "copy", "retype", "combine", "manual"]},
    {"name": "Power BI", "good_for": "Dashboards and reports that refresh automatically from several data sources",
     "keywords": ["report", "dashboard", "capacity", "combine", "kpi", "chart", "readings", "trend"]},
    {"name": "Microsoft Forms", "good_for": "Simple digital forms and checklists on a phone or tablet instead of paper",
     "keywords": ["paper", "form", "clipboard", "checklist", "inspection", "survey", "readings"]},
    {"name": "Power Apps", "good_for": "Small custom apps for field work, data capture and tracking, without full development",
     "keywords": ["tablet", "app", "field", "capture", "technician", "walk", "clipboard", "tracking"]},
    {"name": "SharePoint Lists", "good_for": "Shared trackers and registers with history, owners and permissions",
     "keywords": ["tracker", "register", "records", "list", "out of date", "database", "status", "spreadsheet"]},
    {"name": "Microsoft Teams", "good_for": "Notifications, channels and approvals where people already work",
     "keywords": ["notify", "alert", "message", "chat", "handover", "shift"]},
    {"name": "Excel with Office Scripts", "good_for": "Automating repeated spreadsheet steps such as imports and clean-up",
     "keywords": ["excel", "spreadsheet", "import", "export", "file", "retype", "csv"]},
    {"name": "Microsoft Planner", "good_for": "Task lists with owners and due dates for a team",
     "keywords": ["task", "follow up", "owner", "due", "actions"]},
]


def load(conn) -> list[dict]:
    from .. import db
    return db.get_setting(conn, SETTING) or [t | {"status": "assumed"} for t in DEFAULT_TOOLS]


def save(conn, tools: list[dict]):
    from .. import db
    db.set_setting(conn, SETTING, tools)


def for_ai(tools: list[dict]) -> list[dict]:
    return [{"name": t["name"], "good_for": t["good_for"], "licence": t["status"]} for t in tools]


def best_matches(text: str, tools: list[dict], count: int = 2) -> list[str]:
    """The tools whose keywords (or description words) appear most in the problem. Plain keyword matching."""
    lowered, words = (text or "").lower(), tokens(text)
    scored = []
    for position, tool in enumerate(tools):
        keywords = tool.get("keywords") or sorted(tokens(tool["good_for"]))
        hits = sum(1 for k in keywords if (k in lowered if " " in k else k in words or k in lowered))
        scored.append((-hits, position, tool["name"]))
    return [name for _, _, name in sorted(scored)[:count]]


def keep_known(names, tools: list[dict]) -> list[str]:
    """Only names on the list (matched without caring about case), in the list's own spelling."""
    known = {t["name"].lower(): t["name"] for t in tools}
    result = []
    for name in names or []:
        match = known.get(str(name).strip().lower())
        if match and match not in result:
            result.append(match)
    return result


def guarantee(options: list[dict], tools: list[dict], problem_text: str) -> list[dict]:
    """Make sure at least one option is built on licensed tools. Returns the options (possibly one more)."""
    if not tools:
        return options
    for option in options:
        option["uses_existing_tools"] = keep_known(option.get("uses_existing_tools"), tools)
    if any(option["uses_existing_tools"] for option in options):
        return options
    used = best_matches(problem_text, tools)
    free = next(letter for letter in "ABCDEF" if letter not in {o["id"] for o in options})
    reason = "Generic estimate from the rules; confirm in research"
    options.append({
        "id": free, "title": "Build on tools Khazna already licenses",
        "summary": f"Solve it with {' and '.join(used)}, which Khazna already pays for, before buying anything new.",
        "how_it_helps": "Removes the repeated work inside systems that are already approved, secured and supported.",
        "scores": {key: {"value": value, "reason": reason} for key, value in
                   dict(effectiveness=3, time_to_value=4, cost=4, risk=4, fit=4, evidence=3).items()},
        "pros": ["No new licence or procurement", "Already approved by security and IT", "Familiar to staff"],
        "cons": ["May not cover every need of a dedicated tool", "Someone has to build and maintain it"],
        "assumptions": [f"{name} is licensed and available to this team" for name in used],
        "open_questions": [f"Can {used[0]} reach the data this process uses?", "Who would build and own it?"],
        "uses_existing_tools": used, "added_by_rules": True})
    return options
