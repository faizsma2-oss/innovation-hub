"""Guardrails, routing and scoring rules in plain code.

Unlike the brain, these never guess, and they run on every message whichever brain is
plugged in. Anything that must ALWAYS happen (incident escalation, status protection,
routing to the right owner) lives here, not in a prompt.
"""
import re


def _any(patterns, text):
    return any(re.search(pattern, text or "", re.IGNORECASE) for pattern in patterns)


# 1. Incidents: these always trigger the incident question, even mid-conversation.
INCIDENT = [r"\bsmoke\b", r"\bfire\b", r"burning smell", r"\binjur(ed|y|ies)\b", r"electric(al)? (shock|hazard)",
            r"\bsparks?\b", r"\bflood(ed|ing)?\b", r"water leak", r"\bbreach(ed)?\b", r"\bhacked\b",
            r"ransomware", r"\bintruder\b", r"unauthori[sz]ed access", r"security incident",
            r"cooling (failure|has failed|is down)", r"chillers? (has |have )?(failed|tripped|down)",
            r"power (outage|failure|is down)", r"\boverheating\b"]


def is_safety_concern(text: str) -> bool:
    return _any(INCIDENT, text)


# 2. Attempts to steer the assistant. Flagged for the reviewer; they can never change a status,
#    because no tool exists that could.
INSTRUCTION_ATTEMPTS = [r"ignore (all |your |previous |the |my )*(rules|instructions)",
                        r"mark (this|it) (as )?(approved|accepted)", r"\bapprove (this|it)\b",
                        r"set (the )?(status|priority|score)", r"you are now"]


def looks_like_instruction_attempt(text: str) -> bool:
    return _any(INSTRUCTION_ATTEMPTS, text)


# 2b. Requests that would weaken a safety or security control. Declined by policy.
WEAKENS_CONTROL = [r"\b(disable|turn off|switch off|bypass|skip|remove|get rid of)\b.{0,40}\b(safety|security|"
                   r"access control|fire (alarm|suppression|system)s?|cctv|badge checks?|lockout|interlocks?|"
                   r"inspections?|permits? to work)\b"]


def weakens_control(text: str) -> bool:
    return _any(WEAKENS_CONTROL, text)


# 2c. Text that isn't a request at all: tests, keyboard mashing, a single word.
def is_not_a_request(text: str) -> bool:
    words = re.findall(r"[a-zA-Z]+", text or "")
    if re.match(r"^\s*(test(ing)?|hello|hi|asdf+|qwerty|lorem ipsum|xxx+|\.+)\W*$", text or "", re.IGNORECASE):
        return True
    return len(words) < 3


# 3. Routing: where a request goes FIRST. Checked in this order; the first match wins.
#    Proposed routes, to be validated with Khazna's real department owners.
ROUTINE_PATTERNS = {
    "it_support": [r"\bpasswords?\b", r"\blaptops?\b", r"won'?t (start|turn on|boot)", r"\bprinters?\b", r"\bvpn\b",
                   r"can'?t log ?in", r"cannot log ?in", r"email (is )?not working", r"account (is )?locked",
                   r"(can'?t|cannot|no) access (to )?(the |my )?\w*\s?(system|software|application|app|tool|account|drive|folder)",
                   r"software (install|licen[cs]e)"],
    "hr": [r"\bpayslip\b", r"\bsalary\b", r"\bpayroll\b", r"annual leave", r"leave (balance|request)", r"\bvisa\b",
           r"medical insurance", r"(hr|employee) polic(y|ies)"],
    "facilities_procurement": [r"\b(faulty|broken)\b", r"\bneeds? (a )?(repair|replacing|replacement)\b",
                               r"\brepair(ed)?\b", r"\breplace (the|a|our)\b",
                               r"\b(purchase|buy|order) (a|an|new|more|some)\b", r"\bleaking tap\b"],
}
RECURRING = [r"\b(every|each)\s+(week|day|shift|month|night|morning)\b", r"\b(daily|weekly|monthly)\b",
             r"\bmanual(ly)?\b", r"\bby hand\b", r"\bre-?(enter|type|key)", r"\bcop(y|ies|ied|ying)\b.{0,30}\binto\b",
             r"\b(combine|merge|consolidate|reconcile)\b", r"\brepeat(ed|edly|s)?\b", r"\bagain and again\b",
             r"\bkeeps? (happening|failing|breaking)\b", r"\bover and over\b", r"\brecurring\b",
             r"\b(several|multiple|different|many) (systems|spreadsheets|tools|sources)\b", r"\bspreadsheets?\b",
             r"\bpaperwork\b"]
NEW_TECHNOLOGY = [r"\brobots?\b", r"\bdrones?\b", r"\bAI\b", r"artificial intelligence", r"machine learning",
                  r"digital twin", r"computer vision", r"\bIoT\b", r"new technology", r"\bi saw\b",
                  r"\bautomat(e|ed|ion)\b", r"\bpredictive\b", r"earlier detection"]


def classify_route(text: str, allow_incident: bool = True) -> tuple[str, str]:
    """Return (route, reason). Urgency first, then routine owners, then innovation.
    allow_incident=False once the employee has confirmed it isn't an active emergency."""
    if allow_incident and is_safety_concern(text):
        return "incident", "Describes a possible active incident"
    for route, patterns in ROUTINE_PATTERNS.items():
        if _any(patterns, text):
            return route, "Matches a routine request this department handles"
    if _any(RECURRING, text):
        return "process_owner_innovation", "Recurring manual work, repeated errors or fragmented data"
    if _any(NEW_TECHNOLOGY, text):
        return "innovation_screening", "New technology or a substantially different way of working"
    return "human_triage", "Unclear: a person should choose the right owner"


# 4. Innovation signals: a request deserves innovation screening when it describes a meaningful
#    unmet need AND at least one of these applies.
SIGNALS = {
    "recurring_effort": RECURRING[:9],
    "wider_impact": [r"\b(several|multiple|all|every|many|other) (sites?|teams?|halls?|locations?|departments?|shifts?)\b",
                     r"\bwhole (site|team|company)\b", r"\beveryone\b", r"\b\d{2,} (people|staff|engineers|technicians|operators)\b"],
    "measurable_improvement": [r"\b(energy|water|cost|costs|downtime|outages?|PUE|kwh|aed|delay|delays|quality|"
                               r"reliability|uptime|errors?)\b", r"\d+\s*(hours?|hrs?|minutes?|days?|%)"],
    "needs_experimentation": NEW_TECHNOLOGY + [r"\b(pilot|trial|assess|compare|evaluate|experiment)\b"],
    "persistent_failure": [r"\brepeatedly\b", r"\bkeeps? (happening|failing|breaking)\b", r"\bstill\b",
                           r"\bevery time\b", r"\bagain\b", r"\bnever (works|fixed)\b"],
}
SIGNAL_LABELS = {
    "recurring_effort": "Recurring effort",
    "wider_impact": "Wider impact",
    "measurable_improvement": "Measurable improvement",
    "needs_experimentation": "Needs experimentation",
    "persistent_failure": "Persistent failure",
}


def innovation_signals(text: str) -> list[str]:
    return [name for name, patterns in SIGNALS.items() if _any(patterns, text)]


def is_meaningful_need(text: str) -> bool:
    return len(re.findall(r"[a-zA-Z]+", text or "")) >= 6


# 5. Understanding short answers.
def is_dont_know(text: str) -> bool:
    return bool(re.match(r"^\s*(i\s+)?(don'?t|do not)\s+know|^\s*(not sure|no idea|idk|skip|unknown|n/?a|no clue)\b",
                         text, re.IGNORECASE))


def yes_or_no(text: str) -> str | None:
    if re.match(r"^\s*(yes|yeah|yep|y|sure|ok(ay)?|correct|it does|that works)\b", text, re.IGNORECASE):
        return "yes"
    if re.match(r"^\s*(no|nope|n|not really|it doesn'?t)\b", text, re.IGNORECASE):
        return "no"
    return None


# 6. Pulling simple facts out of free text.
FREQUENCY = [
    (r"\b(every|each)\s+(shift|night|day|morning|hour)\b|\bdaily\b|\bhourly\b|\beveryday\b"
     r"|several times a day|\bconstantly\b|all the time", 5, "Happens at least daily"),
    (r"\bweekly\b|\b(every|each|once a|twice a|several times a)\s+week\b", 3, "Happens weekly"),
    (r"\bmonthly\b|\b(every|each|once a)\s+month\b", 2, "Happens monthly"),
    (r"\b(quarterly|yearly|annually|rarely)\b|\b(every|once a)\s+(quarter|year)\b", 1, "Happens rarely"),
]
PEOPLE = (r"\b(\d+|several|multiple|all|many)\s+(people|persons|engineers|technicians|staff|employees|colleagues|"
          r"operators|team members|users|sites|halls|locations|teams)\b")
EVERYONE = r"\b(everyone|all staff|whole (team|site|company))\b"
QUANTIFIED = r"\d+\s*(hours?|hrs?|minutes?|mins?|days?|aed|dhs|dirhams?|usd|%)|\b(aed|usd|\$)\s*\d+"


def find_frequency(text: str) -> str | None:
    for pattern, _, _ in FREQUENCY:
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def find_people(text: str) -> str | None:
    match = re.search(PEOPLE, text or "", re.IGNORECASE) or re.search(EVERYONE, text or "", re.IGNORECASE)
    return match.group(0) if match else None


def find_quantified_impact(text: str) -> str | None:
    """The sentence that contains a number with a unit, like '3 hours a week'."""
    for sentence in re.split(r"(?<=[.!?])\s+", text or ""):
        if re.search(QUANTIFIED, sentence, re.IGNORECASE):
            return sentence.strip()
    return None


# 7. Scoring helpers, 0–5. None means unknown, which is NOT the same as zero.
def frequency_score(text: str | None) -> int | None:
    for pattern, value, _ in FREQUENCY:
        if text and re.search(pattern, text, re.IGNORECASE):
            return value
    return None


def reach_score(text: str | None) -> int | None:
    if not text:
        return None
    if re.search(EVERYONE + r"|\ball (sites|halls|teams)\b", text, re.IGNORECASE):
        return 5
    places = re.search(r"\b(several|multiple|many|[2-9]|\d{2,}) (sites|halls|locations|teams)\b", text, re.IGNORECASE)
    if places:
        return 4
    numbers = [int(n) for n in re.findall(r"\d+", text)]
    if numbers:
        count = max(numbers)
        return 5 if count >= 50 else 4 if count >= 20 else 3 if count >= 5 else 2
    return None


NUMBER = r"\d+(?:[.,]\d+)*"


def grounded(value: str, source: str) -> bool:
    """Every number in an extracted value must appear, as a whole number, in what the source
    actually says ("1" does not count as present just because "2026" contains a 1).
    A cheap, deterministic check that stops invented figures."""
    # Numbers inside web addresses and IDs (v1, SUB-0001, supplier-1) aren't stated facts.
    plain = re.sub(r"https?://\S+|\b[A-Za-z]+-?\d+\b", " ", source or "")
    in_source = {canonical(n) for n in re.findall(NUMBER, plain)}
    return all(canonical(number) in in_source for number in re.findall(NUMBER, value or ""))


def canonical(number: str) -> str:
    """Compare numbers by value: "6.0" == "6", "50,000" == "50000"."""
    number = number.replace(",", "")
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    return number


def is_quantified(text: str | None) -> bool:
    return bool(text and re.search(QUANTIFIED, text, re.IGNORECASE))
