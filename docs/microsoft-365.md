# Microsoft 365 and Copilot in the Innovation Hub

The Hub works with the Microsoft 365 tools the team already uses: Outlook for email and calendar, and Teams for
meetings and transcripts. Copilot can then answer questions from the Hub's records. Nothing is sent without a
person approving it.

## What the team does in the Hub

| Step | In the Hub | In Microsoft 365 |
|---|---|---|
| Write to a supplier | Draft on the company page (only to an official contact on that page) | — |
| Approve & send | A person ticks "I've read this" and clicks **Approve & send** | Sent from **their own Outlook mailbox** |
| Replies | **Check for replies** pulls answers in the same email thread onto the company page | Read from their mailbox |
| Book a meeting | **Book in Outlook with Teams** on the meeting | Outlook event in UAE time, Teams link, supplier invited |
| After the meeting | **Fetch the Teams transcript**, check it, then summarise | Teams transcript (transcription must be on) |
| Ask Copilot | — | "Where are we with Zoho?" in Copilot, answered from the Hub |

Today the public demo uses a **demo mailbox** (`HUB_M365=demo`): fictional replies, Teams links and transcripts,
clearly labelled. The real connector (`backend/m365/client.py`, `GraphM365`) is tested against a fake Microsoft Graph,
**not yet against a real tenant**.

## Switching on Outlook and Teams (Khazna IT, about an hour)

1. **Register the app** in Microsoft Entra ID → App registrations → New registration. Name: *Innovation Hub*.
   Redirect URI (Web): `https://<hub-address>/auth/callback`.
2. **Delegated permissions** (the Hub acts as the signed-in employee, never as a robot account):
   `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`, `OnlineMeetings.Read`, `OnlineMeetingTranscript.Read.All`,
   `offline_access`. An admin grants consent once for the organisation.
3. **Teams meeting policy:** allow transcription for the innovation team, so transcripts exist to fetch.
4. Set `HUB_M365=graph` and the app's client ID, tenant ID and secret as secret environment variables on the server.
5. Still to build at that point: the employee sign-in page (`/auth/login` → Microsoft → `/auth/callback`, using MSAL).
   Until then `HUB_GRAPH_TOKEN` can hold a short-lived token for testing.

Data stays in Khazna's tenant: emails and meetings live in the employee's own mailbox and calendar. The Hub keeps
a copy of the email text and the meeting summary on the company page, so the history is in one place.

## The Copilot agent (needs Microsoft 365 Copilot licences)

The package is in `copilot/appPackage/`:

| File | What it is |
|---|---|
| `manifest.json` | The app package manifest (v1.19) that contains the agent |
| `declarativeAgent.json` | The agent: instructions (answer only from the Hub, never guess, can't send), conversation starters (schema v1.6) |
| `hub-plugin.json` | The API plugin: two read-only functions, `listCompanies` and `getCompanyStatus` (schema v2.4) |
| `openapi.json` | The two Hub endpoints, generated from the Hub's own code by `scripts/build_copilot_package.py` |

Steps:

1. Set a long random `HUB_COPILOT_KEY` on the Hub server. The Copilot endpoints then require it.
2. Register that key in the **Teams Developer Portal → API key registration** (target: the Hub's address).
   It returns a registration ID: put it in place of `${{HUB_COPILOT_KEY_REGISTRATION_ID}}` in `hub-plugin.json`,
   and give the app an ID in `manifest.json` (`${{TEAMS_APP_ID}}`). The Microsoft 365 Agents Toolkit fills these for you.
3. Run `python scripts/build_copilot_package.py https://<hub-address>` to build `copilot/innovation-hub-copilot.zip`.
4. Upload it in the Microsoft 365 admin centre (Integrated apps) for the innovation team, or sideload it to test.

Copilot only **reads**: it can't send emails or book meetings, and it's told to say "not recorded" rather than guess.
On the public demo, Copilot calls get a fresh fictional sandbox, because Copilot has no browser cookie.

Sources: Microsoft Learn, *Declarative agent schema 1.6* and *Plugin manifest schema 2.4* for Microsoft 365 Copilot.
