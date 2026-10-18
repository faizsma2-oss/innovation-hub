"""The intake workflow: a state machine in plain code that asks the brain for judgement.

One entry point, two linked processes: getting help today, and spotting improvements
worth exploring. Stages a conversation moves through:

  listening ─▶ clarifying (2–4 questions) ─▶ checks ─▶ confirming ─▶ closed
      │                                        │
      │                                        ├─ solution_offer  (existing tool or guidance)
      │                                        └─ link_offer      (similar request or active project)
      ├─▶ route_offer   (routine IT / HR / facilities request: send it today?)
      └─▶ safety_check  (any stage, when incident words appear)

"Submit now" and "Request innovation review" work at every stage after the first message.

Outcomes when closed: routed, handed_over, human_triage, linked, self_service,
safety_escalated, auto_declined.

The brain proposes; this code disposes. It decides which moves are allowed, routes the
request, and is the only place that creates a submission. It can never accept or decline
an innovation request: that stays with the innovation team.
"""
import json
import uuid
from datetime import datetime

from pydantic import ValidationError

from .. import db
from ..models import DEMO_USER, INNOVATION_ROUTES, ROUTES, ROUTINE_ROUTES, SubmissionIn
from ..review import screening
from . import language, learned_routes, rules, search
from ..llm import LLMError
from .brain import MOCK, QUESTIONS, get_brain

MAX_QUESTIONS = 4
DRAFT_FIELDS = list(SubmissionIn.model_fields)
FIELD_LIMITS = {name: field.metadata[-1].max_length if field.metadata else 2000
                for name, field in SubmissionIn.model_fields.items()}
SUBMITTABLE = {"route_offer", "clarifying", "solution_offer", "link_offer", "confirming"}

GREETING = ("What is making your work difficult?\n\nDescribe it in your own words. You don't need to know "
            "the category, the solution or what it costs. \"I don't know\" is a fine answer to any question.")
INCIDENT_QUESTION_AR = ("قبل أي شيء: إذا كان أحد في خطر، أو هناك حادث تبريد أو كهرباء أو أمن يحدث الآن، توقّف عن "
                        "استخدام هذه المحادثة واستخدم قناة الحوادث التشغيلية أو السلامة أو الأمن فورًا.\n\nهل هذا حادث يحدث الآن؟\n\n")
INCIDENT_QUESTION = ("Before anything else: if someone is in danger, or a cooling, power or security incident is "
                     "happening right now, stop using this chat and use the operations, safety or security "
                     "incident channel immediately.\n\nIs this an active incident?")
INCIDENT_CLOSED = ("Please use the incident channel now. I've closed this conversation and flagged it. Once the "
                   "immediate response is over, you're welcome to come back and describe any improvement that "
                   "would stop it happening again.")
REVIEW_ACK = ("Noted: you've asked for an innovation review. The innovation team will look at this and give you "
              "an answer, even if it's also routed elsewhere. That guarantees consideration, not funding.")

# Typed yes/no answers map to the same actions as the buttons.
YES_NO_ACTIONS = {
    "safety_check": ("emergency_yes", "emergency_no"),
    "route_offer": ("route_send", "route_wider"),
    "solution_offer": ("solved", "not_solved"),
    "link_offer": ("link_yes", "link_no"),
    "confirming": ("submit", None),
}


class IntakeError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code, self.detail = status_code, detail


def option(label: str, action: str) -> dict:
    return {"label": label, "action": action}


def new_state() -> dict:
    return {
        "draft": {field: None for field in DRAFT_FIELDS},
        "unknown": [],            # fields the employee said they don't know
        "asked": [],              # fields already asked about (never ask twice)
        "pending_field": None,    # the field the last question was about
        "checks": [],             # lookups already run
        "checked": [],            # what was checked, in words, for the brief
        "related": [],            # similar requests and projects found
        "previous_attempts": [],  # earlier pilots found
        "offer": None,            # the solution or link currently offered
        "notes": [],              # facts for the reviewer
        "flags": [],              # warnings for the reviewer
        "safety_cleared": False,
        "held": None,             # a message paused by the incident question
        "route": None,            # a route agreed with the employee (else decided at submit)
        "route_reason": None,
        "route_candidate": None,
        "innovation_track": "none",
        "technology_first": False,
        "last_message": "",
        "last_options": [],
    }


# ── Public functions used by the API ──────────────────────────────────────────

def start_session() -> dict:
    session_id = uuid.uuid4().hex
    state = new_state()
    with db.connect() as conn:
        conn.execute("INSERT INTO intake_sessions (id, stage, outcome, state_json, created_at, updated_at)"
                     " VALUES (?, 'listening', NULL, ?, ?, ?)",
                     (session_id, json.dumps(state), db.now(), db.now()))
        log_message(conn, session_id, "assistant", GREETING)
    return {"session_id": session_id, "stage": "listening", "message": GREETING, "options": [],
            "draft": state["draft"], "unknown": [], "outcome": None, "submission_id": None,
            "can_submit": False, "review_requested": False}


def handle_message(session_id: str, text: str | None = None, action: str | None = None,
                   edits: dict | None = None) -> dict:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM intake_sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise IntakeError(404, "Intake conversation not found")
        if row["stage"] == "closed":
            raise IntakeError(409, "This conversation is closed. Start a new one.")
        turn = Turn(conn, session_id, row["stage"], json.loads(row["state_json"]), row["created_at"])
        turn.apply_edits(edits or {})
        if text is not None:
            turn.on_text(text)
        else:
            turn.on_action(action or "")
        turn.localise()
        turn.save(input_text=text if text is not None else f"[action] {action}")
        return turn.reply()


def rate(session_id: str, score: int):
    """The employee's 1–5 rating of how easy it was. One of the success measures."""
    with db.connect() as conn:
        updated = conn.execute("UPDATE intake_sessions SET satisfaction = ? WHERE id = ?", (score, session_id))
        if updated.rowcount == 0:
            raise IntakeError(404, "Intake conversation not found")


def stats() -> dict:
    with db.connect() as conn:
        rows = conn.execute("SELECT outcome, COUNT(*) AS n FROM intake_sessions"
                            " WHERE outcome IS NOT NULL GROUP BY outcome").fetchall()
    return {"outcomes": {row["outcome"]: row["n"] for row in rows}}


def log_message(conn, session_id: str, role: str, text: str):
    conn.execute("INSERT INTO intake_messages (session_id, role, text, created_at) VALUES (?, ?, ?, ?)",
                 (session_id, role, text, db.now()))


# ── One turn of the conversation ──────────────────────────────────────────────

class Turn:
    def __init__(self, conn, session_id: str, stage: str, state: dict, started_at: str):
        self.conn, self.session_id, self.stage, self.state = conn, session_id, stage, state
        self.started_at = started_at
        self.message, self.options = "", []
        self.outcome, self.submission_id = None, None
        self.brain = get_brain()  # Claude, or the scripted brain
        self.meter = []           # tokens, cost and fallbacks for this turn

    @property
    def draft(self) -> dict:
        return self.state["draft"]

    def say(self, message: str, options=()):
        self.message, self.options = message, list(options)

    # Edits the employee typed straight into the summary panel. Their words always win.
    def apply_edits(self, edits: dict):
        for field, value in edits.items():
            if field not in DRAFT_FIELDS:
                continue
            value = value.strip()[: FIELD_LIMITS[field]] if isinstance(value, str) else None
            self.draft[field] = value or None
            if value and field in self.state["unknown"]:
                self.state["unknown"].remove(field)

    def on_text(self, text: str):
        text = text.strip()
        if not text:
            raise IntakeError(422, "Message is empty")
        log_message(self.conn, self.session_id, "employee", text)
        original, untranslated = None, False
        if language.is_arabic(text):
            # Translate in: the rules work on English; the original words are kept for the team.
            self.state["language"], original = "ar", text
            self.state["notes"].append(f"Original (Arabic): «{text[:1500]}»")
            try:
                if not language.available():
                    raise LLMError("Claude is off or over budget")
                english = language.to_english(text, self.meter)
                if language.numbers_added(english, text):
                    self.state["flags"].append("translation_numbers")
                    self.state["notes"].append(f"Check the translation: it has a number the Arabic doesn't (“{english[:200]}”)")
                log_message(self.conn, self.session_id, "employee (English translation)", english)
                text = english
            except LLMError:
                untranslated = True
                if "untranslated" not in self.state["flags"]:
                    self.state["flags"].append("untranslated")

        if rules.looks_like_instruction_attempt(text) and "instruction_attempt" not in self.state["flags"]:
            self.state["flags"].append("instruction_attempt")
            self.state["notes"].append(f"Employee message contained an instruction to the assistant: \"{text[:200]}\"")

        # Guardrail: incident words pause everything, whatever stage we're in (Arabic words checked on the original).
        if not self.state["safety_cleared"] and (rules.is_safety_concern(text)
                                                 or (original and language.arabic_safety_concern(original))):
            self.state["held"] = {"stage": self.stage, "text": text}
            self.stage = "safety_check"
            self.say((INCIDENT_QUESTION_AR if original else "") + INCIDENT_QUESTION,
                     [option("Yes, it's happening now / نعم، يحدث الآن", "emergency_yes"),
                      option("No, it's an improvement idea / لا، إنها فكرة للتحسين", "emergency_no")]
                     if original else [option("Yes, it's happening now", "emergency_yes"),
                                       option("No, it's an improvement idea", "emergency_no")])
            self.localised = bool(original)                 # already in both languages
            return
        self.dispatch_text(text)
        if untranslated:
            self.message, self.localised = language.NO_TRANSLATOR + "\n\n" + self.message, True

    def localise(self):
        """Translate out: the reply and its buttons in Arabic, when the employee is writing in Arabic."""
        if self.state.get("language") != "ar" or getattr(self, "localised", False) or not self.message:
            return
        if not language.available():
            return
        try:
            message, labels = language.to_arabic(self.message, [o["label"] for o in self.options], self.meter)
        except LLMError:
            return                                          # English is still correct, just not translated
        self.message = message
        self.options = [o | {"label": label} for o, label in zip(self.options, labels)]

    def dispatch_text(self, text: str):
        if self.stage == "listening":
            return self.first_message(text)
        if self.stage == "clarifying":
            return self.answer(text)
        answer = rules.yes_or_no(text)
        yes_action, no_action = YES_NO_ACTIONS[self.stage]
        if answer == "yes" and yes_action:
            return self.on_action(yes_action)
        if answer == "no" and no_action:
            return self.on_action(no_action)
        hint = ("You can edit any field in the summary directly, then submit."
                if self.stage == "confirming" else "Please choose one of the options below.")
        self.say(hint, self.state["last_options"])

    def on_action(self, action: str):
        stage = self.stage

        # Available at every stage after the first message.
        if action == "submit" and stage in SUBMITTABLE:
            return self.submit()
        if action == "request_review" and stage in SUBMITTABLE:
            self.state["innovation_track"] = "employee_requested"
            self.state["notes"].append("Employee requested an innovation review")
            return self.say(f"{REVIEW_ACK}\n\n{self.state['last_message']}", self.state["last_options"])

        if stage == "clarifying" and action == "dont_know":
            return self.answer("don't know")

        if stage == "safety_check" and action == "emergency_yes":
            self.state["flags"].append("incident_escalated")
            return self.close("safety_escalated", INCIDENT_CLOSED)
        if stage == "safety_check" and action == "emergency_no":
            held = self.state["held"]
            self.state.update(safety_cleared=True, held=None)
            self.stage = held["stage"]
            return self.dispatch_text(held["text"])

        if stage == "route_offer" and action == "route_send":
            self.state["route"] = self.state["route_candidate"]
            self.state["route_reason"] = "Routine request; employee chose to send it today"
            return self.submit()
        if stage == "route_offer" and action == "route_wider":
            if self.state["innovation_track"] == "none":
                self.state["innovation_track"] = "screening"
            self.state["notes"].append(f"Looked like a {ROUTES[self.state['route_candidate']]} request; "
                                       "employee says there's a wider, recurring problem behind it")
            self.think(self.draft["description"])
            return self.ask_next("Understood. Let's capture the wider problem. ")

        if stage == "solution_offer" and action == "solved":
            return self.close("self_service", f"Glad that helps. I've recorded it as resolved with "
                                              f"\"{self.state['offer']['title']}\". Nothing more is needed.")
        if stage == "solution_offer" and action == "solved_but_improve":
            offer = self.state["offer"]
            self.state["notes"].append(f"{offer['id']} \"{offer['title']}\" resolves today's need; the employee "
                                       "says the underlying problem is still worth improving")
            self.state["previous_attempts"].append(f"Workaround in use: {offer['id']} {offer['title']}")
            if self.state["innovation_track"] == "none":
                self.state["innovation_track"] = "screening"
            return self.run_checks("Good, that covers today. I'll keep the improvement opportunity open. ")
        if stage == "solution_offer" and action == "not_solved":
            offer = self.state["offer"]
            self.state["notes"].append(f"Offered {offer['id']} \"{offer['title']}\"; employee says it doesn't solve the problem")
            return self.run_checks("Thanks, that's useful for the team to know. ")

        if stage == "link_offer" and action == "link_yes":
            return self.link()
        if stage == "link_offer" and action == "link_no":
            self.state["notes"].append(f"Similar to {self.state['offer']['id']}; employee says theirs is different")
            return self.run_checks()

        raise IntakeError(422, f"'{action}' is not a valid choice right now")

    # ── Steps ────────────────────────────────────────────────────────────────

    def first_message(self, text: str):
        self.draft["description"] = text[: FIELD_LIMITS["description"]]
        self.draft["title"] = make_title(text)
        # Routing is a rule, decided before asking the brain anything.
        route, _ = learned_routes.classify(self.conn, text, allow_incident=not self.state["safety_cleared"])
        if route in ROUTINE_ROUTES and not rules.innovation_signals(text):
            self.state["route_candidate"] = route
            self.stage = "route_offer"
            return self.say(f"This sounds like something {ROUTES[route]} can help with today. I can send it to them "
                            "now with your description.\n\nOr is there a wider, recurring problem behind it that's "
                            "worth improving?",
                            [option(f"Send to {ROUTES[route]}", "route_send"),
                             option("There's a wider problem", "route_wider")])
        self.state["technology_first"] = route == "innovation_screening"
        self.think(text)
        self.ask_next("Thanks, I've started your summary on the right. ")

    def think(self, text: str | None):
        """Ask the brain what the message tells us and what to ask next. Its suggestions are
        checked here: extracted facts only fill empty fields, and only if every number in them
        appears in what the employee wrote."""
        result = self.brain.step(text, self.draft, self.state["unknown"], self.state["asked"],
                                 self.state["technology_first"], self.meter)
        self.apply(result, text)

    def apply(self, result: dict, text: str | None):
        for field, value in result["extracted"].items():
            if (field in QUESTIONS and value and not self.draft.get(field)
                    and field not in self.state["asked"] and rules.grounded(value, text or "")):
                self.draft[field] = value[: FIELD_LIMITS[field]]
        self.state["plan"] = {"field": result["next_field"], "question": result["question"]}

    def ask_next(self, prefix: str = ""):
        if len(self.state["asked"]) >= MAX_QUESTIONS:
            return self.run_checks(prefix)
        if not self.state.get("plan"):
            self.think(None)
        plan = self.state.pop("plan")
        field, question = plan["field"], plan["question"]
        allowed = field in QUESTIONS and not self.draft.get(field) \
            and field not in self.state["unknown"] and field not in self.state["asked"]
        if field is not None and not allowed:  # the brain suggested something the rules don't allow
            field = MOCK.next_question(self.draft, self.state["unknown"], self.state["asked"])
            question = None
        if field is None:
            return self.run_checks(prefix)
        self.state["asked"].append(field)
        self.state["pending_field"] = field
        self.stage = "clarifying"
        self.say(prefix + (question or MOCK.question(field, self.state["technology_first"])),
                 [option("I don't know", "dont_know")])

    def answer(self, text: str):
        field = self.state["pending_field"]
        # An answer that tries to instruct the assistant is never stored as evidence.
        injected = rules.looks_like_instruction_attempt(text)
        if rules.is_dont_know(text) or injected:
            if field not in self.state["unknown"]:
                self.state["unknown"].append(field)
            if injected:
                self.state["notes"].append(f"The answer about {field.replace('_', ' ')} contained an instruction "
                                           "to the assistant, so it was not used as evidence")
            self.state["pending_field"] = None
            self.think(None)
            return self.ask_next()
        self.state["pending_field"] = None
        # The brain plans the next question as if the answer were filed where asked (as it usually is).
        result = self.brain.step(text, self.draft | {field: text[: FIELD_LIMITS[field]]}, self.state["unknown"],
                                 self.state["asked"], self.state["technology_first"], self.meter)
        elsewhere = refiled_fields(field, result["extracted"], text)
        if elsewhere:
            # The answer is about something else: file it there, keep what was there, leave the question open.
            for other, value in elsewhere.items():
                current = self.draft.get(other)
                if not current:
                    self.draft[other] = value[: FIELD_LIMITS[other]]
                elif value.lower() not in current.lower():
                    self.draft[other] = f"{current}; {value}"[: FIELD_LIMITS[other]]
            self.state["notes"].append(
                f"The answer to the question about {LABEL_TEXT[field]} was about "
                f"{' and '.join(LABEL_TEXT[f] for f in elsewhere)}, so it was filed there: “{text[:200]}”")
        else:
            self.draft[field] = text[: FIELD_LIMITS[field]]  # their own words, kept as written
        self.apply(result, text)
        self.ask_next()

    def run_checks(self, prefix: str = ""):
        """Before proposing anything new: existing tools and guidance, active projects and
        previous pilots, then similar employee requests."""
        text = self.full_text()
        checks = self.state["checks"]

        if "catalog" not in checks:
            checks.append("catalog")
            self.state["checked"].append("Approved guidance and existing tools; active projects and previous pilots")
            match = search.find_solution(self.conn, text)
            if match and match["kind"] in ("tool", "guidance"):
                self.state["offer"] = {"id": match["id"], "title": match["title"]}
                self.stage = "solution_offer"
                return self.say(prefix + "Before this goes further, there's an existing "
                                f"{'tool' if match['kind'] == 'tool' else 'guidance'} that may help today:\n\n"
                                f"{match['title']}: {match['summary']}\nHow to use it: {match['how_to']}\n"
                                f"Source: {match['source']}\n\nDoes it solve your problem?",
                                [option("Yes, solved", "solved"),
                                 option("Helps today, but still worth improving", "solved_but_improve"),
                                 option("No", "not_solved")])
            if match and match["kind"] == "active_project":
                self.state["offer"] = {"id": match["id"], "title": match["title"]}
                self.state["related"].append(f"{match['id']} {match['title']}")
                self.stage = "link_offer"
                return self.say(prefix + f"A similar improvement is already being explored: {match['title']}. "
                                f"{match['summary']}\n\nWould you like to add your experience to it? "
                                "Your own request is kept and linked.",
                                [option("Add my experience", "link_yes"), option("Mine is different", "link_no")])
            if match and match["kind"] == "previous_pilot":
                self.state["previous_attempts"].append(f"{match['id']} {match['title']}: {match['summary']}")
                prefix += (f"Useful context: a previous pilot looked at something similar ({match['title']}). "
                           "I'll include its result in your brief. ")

        if "similar" not in checks:
            checks.append("similar")
            self.state["checked"].append("Similar employee submissions")
            similar = search.find_similar_submission(self.conn, text)
            if similar:
                # Only the ID, title and status are shown: never another employee's description.
                self.state["offer"] = {"id": similar["id"], "title": similar["title"]}
                self.state["related"].append(f"{similar['id']} {similar['title']} ({similar['status']})")
                self.stage = "link_offer"
                return self.say(prefix + f"A similar improvement is already being reviewed: {similar['id']} "
                                f"\"{similar['title']}\" ({similar['status']}).\n\nWould you like to add your "
                                "experience to it? Your own request is kept and linked, so the team sees that "
                                "more people are affected.",
                                [option(f"Add my experience to {similar['id']}", "link_yes"),
                                 option("Mine is different", "link_no")])

        route, _ = self.decide_route()
        track = self.decide_track(route)
        destination = ROUTES[route] + (" and innovation screening"
                                       if track != "none" and route not in INNOVATION_ROUTES else "")
        self.stage = "confirming"
        self.say(prefix + "That's what I need. Please check the summary on the right and edit anything that isn't "
                 f"quite right, then submit.\n\nIt will go to: {destination}.", [option("Submit", "submit")])

    def decide_route(self) -> tuple[str, str]:
        if self.state["route"]:
            return self.state["route"], self.state["route_reason"]
        route, reason = learned_routes.classify(self.conn, self.full_text(), allow_incident=not self.state["safety_cleared"])
        if route == "incident":  # an incident never waits in a queue: hand it to a person
            return "human_triage", "Mentions an incident; a person should check it"
        return route, reason

    def decide_track(self, route: str) -> str:
        """Innovation potential is judged separately from the route."""
        if self.state["innovation_track"] != "none":
            return self.state["innovation_track"]
        if route in INNOVATION_ROUTES:
            return "screening"
        signals = set(rules.innovation_signals(self.full_text()))
        if route in ROUTINE_ROUTES and signals & {"recurring_effort", "persistent_failure", "wider_impact"}:
            return "screening"  # a wider underlying problem has emerged
        if route == "human_triage" and signals and rules.is_meaningful_need(self.draft["description"]):
            return "screening"
        return "none"

    def link(self):
        """Save this employee's own request, linked to the shared opportunity."""
        target = self.state["offer"]
        submission = self.validated()
        if submission is None:
            return
        brief = self.brief(submission.model_dump())
        # An employee-requested review is guaranteed a human decision, so it stays open while linked.
        requested = self.state["innovation_track"] == "employee_requested"
        self.submission_id = db.insert_submission(
            self.conn, submission.model_dump(), DEMO_USER, brief=brief,
            status="Submitted" if requested else "Linked", linked_to=target["id"],
            innovation_track=self.state["innovation_track"], route=None, route_reason=f"Linked to {target['id']}",
            intake_session_id=self.session_id, submission_seconds=self.seconds_so_far())
        if target["id"].startswith("SUB-"):
            parent_pk = db.parse_pk(target["id"])
            self.conn.execute("UPDATE submissions SET supporters = supporters + 1 WHERE pk = ?", (parent_pk,))
            db.add_event(self.conn, parent_pk, DEMO_USER, "linked", None, None,
                         f"{self.submission_id} added their experience")
        self.close("linked", f"Done. Your request is saved as {self.submission_id} and linked to {target['id']}. "
                             "Your own details and updates are kept, and the team sees more people are affected.")

    def submit(self):
        submission = self.validated()
        if submission is None:
            return
        values = submission.model_dump()
        route, route_reason = self.decide_route()
        track = self.decide_track(route)
        status = "Routed" if route in ROUTINE_ROUTES else "Submitted"
        # A request simply routed to a department doesn't need an AI summary, so no Claude call is spent on it.
        brief = MOCK.write_brief(values, self.brief_context()) if route in ROUTINE_ROUTES and track == "none" \
            else self.brief(values)
        self.submission_id = db.insert_submission(
            self.conn, values, DEMO_USER, brief=brief, status=status, route=route,
            route_reason=route_reason, innovation_track=track, intake_session_id=self.session_id,
            submission_seconds=self.seconds_so_far())
        recommendation = screening.screen(self.conn, self.submission_id)

        sid, owner = self.submission_id, ROUTES[route]
        if recommendation.get("auto_applied"):
            return self.close("auto_declined", f"{sid} was closed straight away. {recommendation['suggested_message']} "
                                               "You can do that from Your submissions → View details.")
        if route in ROUTINE_ROUTES:
            extra = (" The wider problem also goes to innovation screening." if track != "none" else
                     " If it turns out to be part of a bigger problem, you can still request an innovation review "
                     "from Your submissions.")
            return self.close("routed", f"Saved as {sid} and sent to {owner}, who handle requests like this today.{extra}")
        if route == "human_triage" and track == "none":
            return self.close("human_triage", f"Saved as {sid}. It isn't clear which team owns this, so a person "
                                              "will triage it rather than me guessing.")
        requested = track == "employee_requested"
        self.close("handed_over", f"Saved as {sid} and sent to {owner} with a brief. "
                   + ("Because you asked for an innovation review, the team will give you an answer. That "
                      "guarantees consideration, not funding." if requested else
                      "Any questions from the team will come back to you."))

    def validated(self) -> SubmissionIn | None:
        try:
            # Leave out empty fields so defaults apply (department: "Not specified").
            return SubmissionIn(**{field: value for field in DRAFT_FIELDS
                                   if (value := self.draft.get(field)) is not None})
        except ValidationError as error:
            problems = "; ".join(f"{problem['loc'][-1]}: {problem['msg']}" for problem in error.errors())
            self.say(f"I can't submit yet ({problems}). Please fix it in the summary and try again.",
                     self.state["last_options"])
            return None

    def brief(self, values: dict) -> dict:
        return self.brain.write_brief(values, self.brief_context(), self.meter)

    def brief_context(self) -> dict:
        return {key: self.state[key] for key in ("unknown", "flags", "notes", "checked", "related", "previous_attempts")}

    def full_text(self) -> str:
        return " ".join(filter(None, [self.draft[field] for field in
                                      ("title", "description", "current_process", "frequency", "people_affected",
                                       "impact", "tried_already", "desired_outcome")]))

    def seconds_so_far(self) -> int:
        return int((datetime.fromisoformat(db.now()) - datetime.fromisoformat(self.started_at)).total_seconds())

    def close(self, outcome: str, message: str):
        self.stage, self.outcome = "closed", outcome
        self.state["pending_field"] = None
        self.say(message, [])

    # ── Saving and replying ──────────────────────────────────────────────────

    def save(self, input_text: str):
        self.state["last_message"], self.state["last_options"] = self.message, self.options
        self.conn.execute("UPDATE intake_sessions SET stage = ?, outcome = COALESCE(?, outcome),"
                          " state_json = ?, updated_at = ? WHERE id = ?",
                          (self.stage, self.outcome, json.dumps(self.state), db.now(), self.session_id))
        log_message(self.conn, self.session_id, "assistant", self.message)
        # Which brain actually answered, what it cost, and whether the scripted brain had to step in.
        last = self.meter[-1] if self.meter else {"brain": self.brain.name, "version": self.brain.version}
        self.conn.execute("INSERT INTO agent_runs (workflow, session_id, prompt_version, model, input_text,"
                          " output_json, created_at, input_tokens, output_tokens, cost_usd, fallback_used)"
                          " VALUES ('intake', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (self.session_id, last["version"], last["brain"], input_text,
                           json.dumps({"stage": self.stage, "message": self.message, "options": self.options,
                                       "outcome": self.outcome, "calls": self.meter}), db.now(),
                           sum(m.get("input_tokens", 0) for m in self.meter),
                           sum(m.get("output_tokens", 0) for m in self.meter),
                           round(sum(m.get("cost_usd", 0) for m in self.meter), 5),
                           int(any(m.get("fallback") for m in self.meter))))

    def reply(self) -> dict:
        return {"session_id": self.session_id, "stage": self.stage, "message": self.message,
                "options": self.options, "draft": self.draft, "unknown": self.state["unknown"],
                "outcome": self.outcome, "submission_id": self.submission_id,
                "can_submit": self.stage in SUBMITTABLE,
                "review_requested": self.state["innovation_track"] == "employee_requested"}


LABEL_TEXT = {"current_process": "what happens today", "frequency": "how often", "people_affected": "who is affected",
              "impact": "the impact", "tried_already": "what was already tried"}
REFILE_COVERAGE = 0.6


def refiled_fields(asked: str, extracted: dict, answer: str) -> dict:
    """When an answer doesn't address the question asked but clearly describes other fields, those fields.
    "Clearly": the extracted words (checked against the answer) cover most of the answer's meaningful words."""
    if not answer or extracted.get(asked):
        return {}
    others = {f: v for f, v in extracted.items() if f != asked and f in QUESTIONS and v and rules.grounded(v, answer)}
    if not others:
        return {}
    words = lambda t: set(search.meaningful(t).split())
    said = words(answer)
    covered = set().union(*(words(v) for v in others.values())) & said
    return others if said and len(covered) / len(said) >= REFILE_COVERAGE else {}


def make_title(text: str) -> str:
    """First sentence, trimmed to a readable length. The employee can edit it."""
    first = text.strip().split("\n")[0]
    for mark in (". ", "? ", "! "):
        first = first.split(mark)[0]
    first = first.rstrip(".!? ")
    return first if len(first) <= 80 else first[:77].rsplit(" ", 1)[0] + "…"
