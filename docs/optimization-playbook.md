# Optimisation playbook

A repeatable way to decide **what to improve next** and **which tool to use** for every step of the Hub,
plus the overview to write before starting any task.

Use it in three moves:

1. **Find the pain** at a step (where time, errors or waiting pile up).
2. **Pick the tool** with the decision ladder below: the simplest one that does the job.
3. **Score the idea** and build the highest score first.

---

## 1. Find the pain

For each step, ask four questions and write the answer as a number where you can:

| Question | Where the answer comes from in the Hub |
|---|---|
| How long does this step take a person? | Median time to submit, reviewer time per request (the measures at the top) |
| How long do requests **wait** here? | Days in stage on the portfolio board |
| How often does it go wrong? | Routing corrections, screening overrides, overdue actions, fallbacks in `agent_runs` |
| What does it cost? | AI cost per run in `agent_runs` (`cost_usd`) |

In the demo these numbers are fictional. With real use they tell you where to look first: **the step where
requests wait longest is usually the best place to start**, not the step that looks most interesting.

## 2. Pick the tool: the decision ladder

Go down the ladder and **stop at the first rung that works**. Lower rungs are cheaper, faster and easier to test.

| Rung | Ask | Use | Why this order |
|---|---|---|---|
| 1 | Can a fixed rule do it reliably? (a calculation, a threshold, a date) | **Plain code** | Free, instant, the same answer every time, easy to test |
| 2 | Does it need judgement over words? (summarise, draft, compare, extract) | **Claude**, with a fixed answer format, a check in code and a scripted fallback | Good at language; the code check catches invented facts |
| 3 | Does it need fresh facts from outside? (suppliers, prices, contacts) | **Claude web search and fetch**, keeping only sources it actually opened | The model's memory is out of date; sources make it checkable |
| 4 | Does it need to act inside Khazna's tools? (email, calendar, files, tasks) | **Microsoft 365 through Microsoft Graph**, acting as the signed-in person | Work stays in the systems people already use |
| 5 | Should people get it where they already work? (Teams, Outlook) | **Copilot agent** (read-only) or a **Teams message** | No new app to open |
| 6 | Does someone have to be accountable? (money, sending, choosing a supplier, stopping) | **A person decides**, with a recorded reason | Some decisions are never automated |

**Rules that always apply**, whatever the rung:

- The AI never decides money, approvals, supplier choice or what gets sent. It prepares; a person decides.
- Owners and dates come only from what people wrote. If they're missing they stay UNASSIGNED / NO DATE AGREED.
- Anything sent outside Khazna needs a person's approval first.
- Every AI step has a fallback that still works when the AI is down or over budget.
- Data stays in the UAE where Khazna requires it. Check this before adding any outside service.

## 3. Score the idea

Give each idea three scores from 1 to 5:

| Score | 1 | 3 | 5 |
|---|---|---|---|
| **Impact**: time saved, errors avoided, decisions made faster | A small convenience | Noticeable for one team | Changes how the whole step works |
| **Confidence**: how sure we are it helps and works | A guess | A similar thing worked before | Already proven, or the data says so |
| **Effort**: how much to build | A few hours | A few days | Weeks, or needs Khazna IT |

**Priority = Impact × Confidence ÷ Effort.** Build from the top.

Two overrides:
- **Needs Khazna IT or licences** (a tenant, admin consent, Copilot licences): goes into the *Later, with IT* list, whatever the score.
- **Needed before real use** (sign-in, permissions, security): goes into the *Before going live* list, whatever the score.

---

## 4. Every step, scored

Ideas for each step of the flow (the numbers match `docs/innovation-lifecycle.md` and the flow walkthrough).
I = impact, C = confidence, E = effort.

| Step | Idea | Ladder rung | I | C | E | Priority |
|---|---|---|---|---|---|---|
| 5 Solution options | ✅ **Done.** Always include an option built on tools Khazna **already licenses** (Power Automate, Power BI, SharePoint lists, Forms) before suggesting new software | 2 Claude + 1 code check | 5 | 4 | 1 | **20** |
| 15 Pilot | ✅ **Done.** **Import measurements from Excel or CSV** instead of typing each value | 1 code | 3 | 5 | 1 | **15** |
| 17 Business case | ✅ **Done.** **Low / expected / high scenarios** (e.g. 50%, 100%, 120% of the pilot saving) so management sees the risk | 1 code | 3 | 5 | 1 | **15** |
| 2 Checks | ✅ **Done** (labelled set: tools 10/16 → 16/16, similar requests 5/6 → 6/6). **Better matching** of duplicates and lessons (SQLite full-text search instead of exact keywords) | 1 code | 3 | 4 | 1 | **12** |
| 23 Copilot | ✅ **Done.** New read-only questions: **"what's overdue?"** and **"what needs my decision?"** | 5 Copilot + 1 code | 3 | 4 | 1 | **12** |
| 22 Reports | ✅ **Done.** **Prepare the weekly report automatically** every Monday morning (UAE week) | 1 code (schedule) | 2 | 5 | 1 | **10** |
| 21 Lessons | ✅ **Done.** A **lessons library** page, searchable, for the team and employees | 1 code | 2 | 5 | 1 | **10** |
| 9–10 Reply → meeting | ✅ **Done.** **Read the supplier's reply** and pre-fill the times they offered into "Book in Outlook" | 2 Claude | 4 | 4 | 2 | **8** |
| 6, 8 Research | ✅ **Done.** **Reuse** supplier research and contacts from earlier requests instead of searching again (saves cost and time) | 1 code | 3 | 5 | 2 | **7.5** |
| 4 Screening | ✅ **Done.** **Earned autonomy dashboard**: how often the team agrees with the recommendation, per route | 1 code | 3 | 4 | 2 | **6** |
| 13 Notes | Turn notes into **structured facts** (price, certificates, hosting) that update the supplier comparison | 2 Claude | 3 | 3 | 2 | 4.5 |
| 3 Routing | Suggest **rule changes** from the team's routing corrections | 1 code + 6 person | 3 | 3 | 2 | 4.5 |
| 1 Intake | **Arabic and voice** input for employees | 2 Claude | 4 | 3 | 3 | 4 |
| 14 Evaluation | **Upload documents** (quotes, security certificates) and extract evidence with sources | 2 Claude | 4 | 3 | 4 | 3 |

**Later, with Khazna IT** (needs the Microsoft 365 tenant, consent or licences):

| Step | Idea | Ladder rung |
|---|---|---|
| 9–11 | Switch the demo mailbox to real Outlook and Teams (`docs/microsoft-365.md`) | 4 Graph |
| 10 | **Find a time** that suits all our attendees (Graph `findMeetingTimes`) | 4 Graph |
| 11 | Fetch the transcript **automatically** when the meeting ends | 4 Graph |
| 12 | A **daily Teams message** to each owner with their due actions | 5 Teams |
| 18 | Management approves the business case in **Teams Approvals** | 4 Graph + 6 person |
| 19 | Turn the handover checklist into **Planner tasks** | 4 Graph |
| 23 | Install the Copilot agent for the innovation team | 5 Copilot |

**Before going live** (not needed for the demo):

- Real sign-in with Microsoft Entra ID, and roles (employee, reviewer, manager) so only the right people can approve.
- Hosting in a UAE region, backups, and an audit log export.

### Top picks right now

1. **Step 5: tools Khazna already licenses** (priority 20). Avoids buying software that duplicates something already paid for, and it's a strong interview point.
2. **Step 15: import pilot measurements from Excel** (15). Removes the most tedious typing in the pilot.
3. **Step 17: business case scenarios** (15). Management decides with a range, not a single number.

---

## 5. Before starting any task: the overview

Before building anything, write this short overview (and read it back with the team). It takes ten minutes
and catches most misunderstandings early.

```
TASK: <name>                                    STEP: <number and name in the flow>

Why            What pain it removes, with a number if possible (e.g. "6 hours a week of retyping").
How it works   3–6 plain steps, from the user's click to the result.
Tools          Each part and its ladder rung, with the reason:
                 - <part>: plain code, because …
                 - <part>: Claude, because … (fallback: …)
Guardrails     What a person must approve; what the AI is never allowed to decide.
Data           What is stored, where, and anything leaving Khazna.
Measure        How we'll know it worked (the number from "Why", before and after).
Cost           AI cost per use, and effort to build.
Done when      The tests and checks that prove it, including one browser check.
Files          Which parts of the code change.
```

### Example: import pilot measurements from Excel

```
TASK: Import pilot measurements                 STEP: 15 Pilot

Why            Technicians type every reading by hand; a 3-metric, 3-week pilot is ~60 values.
How it works   1. On the pilot, click "Import from Excel/CSV" and choose the file.
               2. The Hub shows a preview: which column is which metric, dates, values.
               3. Rows it can't read are listed, not guessed.
               4. A person clicks "Import"; values appear under Baseline or Pilot.
Tools          - Reading the file and matching columns: plain code (fixed format, must be exact).
               - No AI needed: rung 1 is enough.
Guardrails     Nothing is saved until the person confirms the preview; duplicates are skipped.
Data           Only the numbers and dates are stored; the file isn't kept.
Measure        Time to log a pilot's data: before (typing) vs after (import).
Cost           No AI cost. About half a day to build.
Done when      Tests for good file, wrong columns, bad dates, duplicates; browser check of the preview.
Files          backend/research/pilot_routes.py, js/research.js, tests/test_pilot.py
```
