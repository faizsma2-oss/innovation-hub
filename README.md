# Innovation Hub — Milestone 9

**Live demo: https://innovation-hub-demo.onrender.com.** Each visitor gets a private copy that resets after 24 hours. If the site has been idle, the first load takes about a minute to wake up.

A learning project by Faaizah Ismail. Independent portfolio demonstration, not an official Khazna application. All data is fictional.

**One employee-facing entry point, two linked processes:** getting help today, and identifying improvements worth exploring. Routine requests reach the department that resolves them. The innovation team receives clear opportunities, with a brief and a transparent priority. The full design is in `docs/intake-agent-workflow.md`.

## Run it on your Mac

First time only (in VS Code: Terminal → New Terminal, inside this folder):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Every time:

```bash
source .venv/bin/activate
fastapi dev backend/main.py
```

Then open **http://127.0.0.1:8000**. The API test page is at **http://127.0.0.1:8000/docs**. Stop the server with Ctrl+C. An older `data/hub.db` is upgraded automatically on start.

### The Claude brain

- **Key:** put your Anthropic API key in `.env` as `ANTHROPIC_API_KEY=...`. The file is in `.gitignore`, so never commit it. Set a monthly spend limit in the Anthropic Console.
- **Which brain is used:** with a key, the assistant uses Claude (`claude-opus-5-5`). Without one, it uses the scripted rules. The page says which. To force the scripted brain, start the server like this:

  ```bash
  HUB_BRAIN=mock fastapi dev backend/main.py
  ```
- **What Claude does:** it understands each message, chooses and words the next question, and writes a short summary for the brief.
- **What stays in plain code:** routing, incidents, policy, statuses, the priority rubric, and every safety check.
- **Checks on every answer:**
  - the reply must match a fixed JSON schema
  - extracted facts may only fill empty fields
  - every number must appear in the employee's own words
  - a question must be one the rules allow
- **Fallback:** if Claude fails, refuses or answers in the wrong shape, the scripted brain answers that turn instead.
- **Cost:** measured live on 16 October 2026 across five cases, using `scripts/live_check.py`. Every turn's tokens, cost and any fallback are logged in the `agent_runs` table.

  | Case | Claude calls | Cost |
  |---|---:|---:|
  | Routine support (routed to IT) | 0 | $0.000 |
  | Recurring reporting problem | 4 | $0.013 |
  | Linked to an existing opportunity | 5 | $0.020 |
  | Incident | 0 | $0.000 |
  | Injection attempt | 5 | $0.015 |

  Each turn takes about 3–6 seconds. There were no fallbacks.
- **Live check:** `python scripts/live_check.py` runs all five cases against Claude on a throwaway database (about $0.05). Run it after changing a prompt.
- **Tests never call Claude.** They use the scripted brain, and a fake Claude for the guardrail tests, so they're free.

## Design

Minimal and futuristic:
- the system font, large headlines and lots of white space
- a frosted-glass top bar and soft depth
- a blue-to-violet accent, and subtle motion

The page follows the computer's light or dark setting automatically. Every color, font and corner radius is in `styles/theme.css`, so change one value there to restyle the whole app. `styles/layout.css` is organized into numbered sections (base, controls, top bar, cards, chat, brief, and so on).

Browsers always check for newer scripts and styles (the server sends `Cache-Control: no-cache`), so a refresh is enough after editing.

## The demo journey (about 3 minutes)

1. **Employee view → "What is making your work difficult?"** Click the three labelled example cases one after another:
   - **Routine support request** → offered to IT support today → *Send* → saved as *Routed*.
   - **Recurring reporting problem** → 3 short questions (frequency was already understood) → *Submit now* → goes to process owner + innovation screening, with a brief.
   - **Linked to an existing opportunity** → linked to SUB-0001, with the employee's own record kept.
2. Rate the chat 1–5 at the end of each one.
3. **Innovation reviewer** → the **Innovation queue** is sorted by priority. Open the reporting request and walk through the brief:
   - facts, estimates and missing evidence, kept separate
   - the rubric, with weights and reasons
   - confidence, feasibility, next step and owner
4. **Correct the screening** (for example, change the alignment score), then confirm a decision. The measures at the top update.
5. Back in the **Employee view**, open the IT request and click **Request innovation review**. It now appears in **Employee-requested reviews**.

## How it fits together

```
Browser
  js/intake.js ── chat ──────▶ POST /api/intake/sessions/{id}/messages
  js/app.js    ── queues ────▶ GET  /api/submissions, /api/metrics
  js/review.js ── decisions ─▶ POST /api/submissions/{id}/review | reroute | scores | feasibility
                               POST /api/submissions/{id}/request-review | resolve | reply | appeal
   ▼
FastAPI server
  backend/intake/workflow.py   the conversation: 2–4 questions, checks, routing, Submit now / Request review
  backend/intake/brain.py      judgement: extract facts, next question, write the brief (MockBrain → Claude later)
  backend/intake/rules.py      plain-code rules: incidents, routes, innovation signals, policy
  backend/intake/search.py     existing tools, guidance, projects, pilots and similar requests
  backend/review/screening.py  priority rubric, confidence, feasibility, owner, next step, recommendation
  backend/review/routes.py     the only place statuses change; corrections; measures
   ▼
SQLite database (data/hub.db): submissions · submission_events · intake_sessions · intake_messages
                               · agent_runs · solutions
```

## What works now

- **Easy submission.** One question at a time, at most 4, and "I don't know" is always fine. The summary is editable throughout. **Submit now** and **Request innovation review** are available at every step.
- **Routing before ranking.** Incidents, IT, HR, facilities and procurement, process owner + innovation, innovation, or human triage. Urgency and innovation potential are separate fields.
- **Checks before anything new:**
  - existing tools and guidance (an employee can say "Helps today, but still worth improving")
  - active projects and previous pilots
  - similar requests, which are **linked with each employee's record kept**
- **Transparent priority:**
  - weighted rubric (35 / 25 / 20 / 20), each score with a reason, and **unknown is not zero**
  - a separate confidence level
  - a separate feasibility label
- **Briefs** with every section reviewers need, and vendor research only after screening.
- **Reviewer controls:**
  - accept, ask, decline or link
  - re-route, correct a score, or set feasibility, with every correction logged
- **Employee controls:** request an innovation review (guarantees a human decision, not funding), mark a routed request resolved, reply, or appeal.
- **Policy declines** happen only for non-requests and for requests that would weaken a safety or security control, never for employee-requested reviews, and can be appealed once.
- **Measures:**
  - median submission time
  - routing accuracy
  - median reviewer time
  - missed opportunities caught
  - ease rating
  - confirmed resolutions
- **Claude as the brain** (`backend/intake/claude_brain.py`), with checked answers, automatic fallback to the scripted brain, and cost logging per turn.
- **Research AI after acceptance** (`backend/research/`). When the team accepts a request:
  - The Research AI proposes 3–5 different solution **approaches**, not vendors, always including a simple baseline.
  - Each option is scored 1–5 on six criteria, with a reason: effectiveness 30%, time to value 15%, cost 15%, risk 15%, fit 15%, evidence 10%.
  - Each option lists pros, cons, assumptions and open questions.
  - The app calculates each option's **usefulness score and ranking** from those scores. The AI never sets the order.
  - Figures the employee didn't give are flagged.
  - The team compares the cards and the side-by-side table, can ask again with feedback, and **selects one option with a reason**. Only then does the status become **Research**, with a drafted research plan: questions, evidence needed, pilot success criteria, risks and next steps.
  - The measures track how often the team picks the top-ranked option.
- **Supplier research after an option is chosen** (`backend/research/suppliers.py`).
  - **"Find suppliers" asks the setup questions every time**, pre-filled with the last answers:
    - which factors to compare: 9 suggested ones (cost, UAE presence, data residency, certifications, integration, data-center references, time to deploy, contract terms, supplier stability), extra factors the AI suggests for this option, and **your own categories**
    - how much each factor matters: must-have (pass/fail), high, medium or low
    - where to look: UAE first, UAE and GCC only, or global
    - how to show prices: published only, published plus labelled estimates, or relative cost
    - how many suppliers, and any notes
  - The Research AI then searches the web (and fetches pages), and a second call turns its notes into a fixed structure.
  - **The app checks everything:**
    - a source counts only if it was actually retrieved, otherwise the finding becomes unknown
    - prices without a source become "price on request"
    - a failed must-have ranks a supplier last
    - unknown is left out of the fit score and lowers confidence instead
  - The team compares the supplier cards and the factor table, then saves a shortlist.
  - Contacting suppliers is left to a person.
- **Supplier evaluation, from shortlist to pilot partner** (`backend/research/evaluation.py`; full detail in `docs/innovation-lifecycle.md`). For each shortlisted supplier:
  - **Prepare:** the AI drafts a meeting brief, prioritised questions and an outreach **draft** email. The app never sends anything.
  - **Contact:** a person records the outreach status.
  - **Meeting notes:** the AI extracts answers, updated findings (labelled as verbal claims), risks and actions. Owners and dates are never invented.
  - **Due diligence:** a checklist where each item has a status, an owner and evidence.
  - **Pilot partner:** can be chosen **only when every required check has passed**. The request then moves to **Pilot planning**, with a drafted plan: baseline, success criteria (targets not in the facts stay "to be agreed"), exit criteria and roles.
- The number check is now stricter: figures count only as whole numbers, and numbers inside links and IDs are ignored.
- **Pilot run and evaluation** (`backend/research/pilot.py`):
  - **Agree** numeric targets, units, whether lower or higher is better, the minimum number of measurements, and a **named owner** (UNASSIGNED isn't accepted).
  - **Measure the baseline first.** "Start pilot" stays locked until every metric has baseline data.
  - **Log** pilot measurements and observations.
  - **Evaluate:** the verdict is calculated in code.
    - Too few measurements on any metric makes the pilot **inconclusive**, with a recommendation to extend.
    - A change within the baseline's normal variation counts as **no clear change**.
    - All targets met recommends scale; some met or improving recommends revise; none improving recommends stop.
    - The AI writes the narrative but can't change the verdict, and figures it didn't get from the data are dropped.
  - **Decide**, with a reason:
    - **scale** moves the request to Scaling
    - **extend** sets a new end date
    - **revise** starts a new round in Pilot planning, keeping the history
    - **stop** moves it to Stopped
  - Every decision is logged as agreeing with or overriding the recommendation.
- 127 automated tests: `python -m pytest` (free: they never call Claude or the web)

## What does NOT exist yet

Screening and routing are still rules: Claude only shapes the conversation and the summary. There's no login and no file uploads. Anyone can act as reviewer in this demo. Every submission belongs to one demo user (`demo-employee`), and view switching is not authorization. The routes, rubric weights and business priorities are **proposals to validate with the team**. The database is on this computer only. Do not use confidential workplace information.

## Learn the files in this order

1. `docs/intake-agent-workflow.md`: the design, in plain words.
2. `backend/intake/workflow.py`: read the stage diagram at the top, then follow one conversation through `first_message` → `ask_next` → `run_checks` → `submit`.
3. `backend/intake/rules.py`: `classify_route` and `SIGNALS` decide where a request goes.
3b. `backend/intake/brain.py` then `claude_brain.py`: the same interface done two ways, and the checks on Claude's answers. Then `tests/test_claude_brain.py`, which uses a fake Claude.
4. `backend/review/screening.py`: `score_criteria` → `compute_priority` → `recommend`.
5. `backend/review/routes.py`: decisions, corrections and the `/api/metrics` measures.
6. `tests/test_intake.py` and `tests/test_review.py`: each test is one scenario. They're the clearest description of what the system must do.
7. `js/intake.js`, `js/app.js`, `js/review.js`: the chat, the queues and the request details.

## Exercises

1. Change the rubric weights in `WEIGHTS` (for example, impact 50%). Which requests move in the queue? Which test fails?
2. Add a business priority such as "Customer onboarding" to `BUSINESS_PRIORITIES`, and see which alignment scores change.
3. Add "generator" to the facilities routing patterns and write a test for "The backup generator needs a repair".
4. Re-route a request as the reviewer and watch **Routing accuracy** drop. Why is that a better measure than "fewer escalations"?
5. Submit the IT example, request an innovation review as the employee, then accept it as the reviewer. Watch **Missed opportunities caught**.
6. Open `data/hub.db` in a SQLite viewer and follow one request through `submission_events`.

## Verification checklist

- The chat opens with "What is making your work difficult?" and shows three labelled examples.
- Routine support → offered to IT support → *Routed*.
- Recurring reporting → at most 4 questions → process owner + innovation screening → brief with facts, estimates and missing evidence kept separate.
- Inspection paperwork → linked to SUB-0001. Its own record is kept, and the supporter count goes up.
- *Submit now* and *Request innovation review* work mid-conversation.
- Reviewer: queues show counts, and the innovation queue is sorted by priority.
- Correcting a score changes the priority, and the "corrected" marker survives a re-route.
- Measures update after ratings, decisions, corrections and resolutions.
- The chat works at phone width.
- `python -m pytest` shows all tests passing.

Verified 16 October 2026: 63 tests pass. The three example cases, reviewer correction and decision were checked in the browser, on desktop and phone width.

## How this connects to the AI agent

The Hub is the app people use. The **Innovation Coordinator** in `coordinator/` is the agent behind it: its instructions, output templates, memory schema and test cases. The agent only creates **PROPOSED** records, and a reviewer approves them in the Hub. Read `docs/agent-integration.md` for the full plan.

## Milestone roadmap

Every milestone leaves a working demo. The AI arrives only after the app can store, review and approve records without it.

| # | Milestone | You learn | Done when |
|---|---|---|---|
| 1 | **Interface** ✅ | HTML structure, CSS variables, rendering data, dialogs | Checklist passes |
| 2 | **API + saved submissions** ✅ | FastAPI, routes, fetch(), SQLite, SQL parameters, validation | New submission survives a restart. Invalid input is rejected by the server |
| 3 | **Intake conversation (mock brain)** ✅ | Chat UI, conversation state, tools, routing, guardrails in code | Chat fills the draft live. Self-service, duplicate, redirect, safety and handover routes all work with a scripted brain. No API key |
| 4 | **Reviewer side + smart screening** ✅ | Status transitions, change history, the PROPOSED → APPROVED pattern | Every request gets accept / ask / decline recommendation; clear policy cases auto-declined with appeal; verdicts logged as `review_outcome` |
| 5 | **One entry point, routing before ranking** ✅ | Routing vs. prioritisation, weighted rubrics with confidence, correction loops, success measures | Three example cases work end to end; reviewer corrections and measures are logged |
| 6 | **Real brain: Claude** ✅ | Model API calls, structured outputs, guardrails on model output, fallbacks, cost tracking | Guardrail tests pass with a fake Claude; the live run of five cases had no invented facts, no fallbacks, and resisted the injection attempt |
| 6b | **Research AI: solution options** ✅ | Generating comparable options, ranking in code from AI scores, human selection gates | Accept → ranked options with pros and cons → team selects with a reason → research plan; tested with scripted and fake Claude |
| 6c | **Supplier research** ✅ (live web check pending) | Configurable comparison factors, web search with source checking, pass/fail plus weighted ranking | Setup questions are remembered; custom and suggested factors; checked and ranked suppliers; shortlist. Tested with scripted and fake Claude |
| 6d | **Supplier evaluation → pilot planning** ✅ | Human-in-the-loop gates, extracting actions from meeting notes, due diligence | Prepare, contact, meeting, checklist, gated pilot partner, pilot plan; tested with scripted and fake Claude |
| 6e | **Pilot run and evaluation** ✅ | Measuring against a baseline, noise versus real change, inconclusive results, human scale/stop decisions | Setup gate, baseline before start, calculated verdict, four decisions with history; tested |
| 7 | **Public demo** | Git, hosting, per-visitor sandboxes (see `docs/hosting-plan.md`) | Interviewers can open a link and try the intake chat |
| 8 | **Projects + meeting notes → actions** | Turning accepted submissions into projects; workflow 1 of the agent | `meeting-01` eval passes, and actions appear in the project for approval |
| 9 | **Vendor documents → evidence comparison** | File uploads, evidence labels, prompt-injection defence | Comparison cites a source for every claim and ignores instructions inside documents |
| 10 | **Weekly report + earned autonomy** | Reporting only from APPROVED records; measuring agent–reviewer agreement | Every report row links to its source. An agreement dashboard decides whether auto-accept can be switched on |

Later: scheduled briefings, pilot analytics, real sign-in and permissions, and hosting that meets data-residency requirements.

**Framework note:** start with direct model API calls from FastAPI. The human-review pause is just a record with status PROPOSED, so no orchestration framework is needed. Add LangGraph later only if a workflow becomes truly branching.
