# Khazna Innovation Coordinator

An AI agent that helps the Khazna innovation team move from an idea to a well-supported decision, with less administrative work.

## Folder map

| Path | What it is |
|---|---|
| `agent/system-prompt.md` | The agent's working instructions: role, decision loop, rules, approval limits |
| `agent/templates/` | The exact shape of each deliverable (action tracker, vendor comparison, weekly report, meeting brief) |
| `memory/schema.md` | What the shared project memory stores and how records are labelled |
| `evals/` | Test cases with expected answers, plus a scoring sheet |

## Learning roadmap

Each phase teaches one idea from agent design and produces something usable.

| Phase | You learn | You build | Done when |
|---|---|---|---|
| **1. Instructions** | How a system prompt shapes behaviour; why rules beat examples for edge cases | System prompt + templates *(drafted)* | Agent produces outputs in the template shape |
| **2. Evaluation** | You can't improve what you don't measure; answer keys; failure categories | 10–15 test cases from realistic meetings and vendor docs | Scores recorded for every case |
| **3. Iteration** | Reading failures, changing one rule at a time, re-testing | Revised prompt; a change log | Zero invented owners/dates; ≥90% of actions found |
| **4. Memory** | Structured state vs. chat history; drafts vs. approved records | Project memory as files or a spreadsheet following `memory/schema.md` | Weekly report built only from memory records, each with a source |
| **5. Tools** | Tool use: search, read files, write records; approval gates | API version (Claude Agent SDK) connected to real document stores | The three workflows run end to end on real data |
| **6. Pilot with the team** | Adoption, trust, measuring time saved | Two-week trial with the innovation team | Team keeps using it; time saved is measured |

Phases 1–4 need **no API key**.

## How to test now (no API key)

1. Create a **Project** in Claude (claude.ai → Projects → New project).
2. Paste `agent/system-prompt.md` into the project's custom instructions.
3. Upload the files in `agent/templates/` and `memory/schema.md` as project knowledge.
4. Start a chat, paste `evals/meeting-01/input-notes.md`, and ask: *"Process these meeting notes."*
5. Compare the result with `evals/meeting-01/expected-output.md` and score it with `evals/scoring.md`.

## Assumptions (to replace with real details)

- Systems of record are unknown. Typical candidates are SharePoint/Teams for documents, Planner or Jira for tasks, and Outlook for meetings. Confirm them with the team.
- Every company, vendor and person in `evals/` is fictional.
