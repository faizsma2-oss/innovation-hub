# Hosting plan: a public demo link for interviewers

## Goal
A link, such as `https://innovation-hub-demo.onrender.com`, that an interviewer can open on any device and try in under two minutes. Every visitor should see a clean, working demo, whatever earlier visitors typed.

## What changes when the app is public

On your laptop, only you use the app. On a public link:

| Risk | Example | Fix |
|---|---|---|
| Visitors see each other's entries | Interviewer A sees junk typed by a stranger | **Private sandbox per visitor** (below) |
| Spam or abuse | A bot posts 10,000 submissions | Cap of 20 submissions per visitor, plus the existing length limits |
| Data is wiped on restart | Free hosts often reset files on redeploy | That's acceptable *by design*: the demo resets to the sample records |
| Slow first load | Free hosts sleep when idle (about 30–60 s to wake) | Warm it up before an interview, or use a paid always-on tier for interview weeks |
| Later: AI costs | Someone triggers 1,000 AI runs | Per-visitor quota and a daily spending cap (milestone 5) |
| Confidentiality | Real Khazna data in a public demo | Fictional data only. Banner and README say it's unofficial |

## Key design: a private sandbox per visitor

- On the first visit, the server gives the browser a random ID in a cookie, such as `demo_session=7f3a…`.
- Each new submission is stored with that ID.
- Each visitor sees the **3 shared sample records plus only their own submissions**.
- Submissions older than 24 hours are deleted automatically.

**Result:** every interviewer gets a fresh demo, and nobody sees anyone else's entries. This needs one new database column and about 20 lines of code. You'll also learn about cookies and sessions, which you'll need again for real sign-in later.

The page banner will say: *"Public demo · fictional data · your entries are visible only in your browser and are deleted after 24 hours."*

## Recommended host: Render

| | Render (recommended) | Railway | Fly.io |
|---|---|---|---|
| Setup | Connect GitHub, fill in 3 fields | Similar | Command line and config file |
| Free option | Yes, but sleeps when idle and has no lasting disk | Trial credit, then paid | Needs a card |
| Deploys on every `git push` | Yes | Yes | Manual or CI |
| Fits a beginner | Best | Good | Harder |

**Why Render:** it deploys straight from GitHub with almost no configuration. Its free tier's main drawback (the disk resets) doesn't matter here, because the sandbox design expects the demo to reset. Its other drawback, sleeping when idle, is handled by opening the link a minute before an interview, or by switching to the cheapest paid tier for interview weeks.

*Free tiers and prices change. Confirm the current limits when you sign up.*

## Steps

### Phase A: prepare the code (in this project)
1. **Git and GitHub.** Put the project under version control and push it to a public GitHub repository. It doubles as your portfolio link.
2. **Visitor sandboxes.** Add the `sandbox` column, the cookie, the 24-hour cleanup and the 20-submission cap. Add tests for each.
3. **Public banner** on the page.
4. **Production start command:** `fastapi run backend/main.py --host 0.0.0.0 --port $PORT`. `fastapi run` is production mode: no auto-reload, and it listens on the port the host gives it.
5. **Pin the Python version** so the host uses 3.12, like your laptop.

### Phase B: deploy on Render
1. Sign up at render.com with your GitHub account.
2. **New → Web Service →** choose the repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: the one from A4.
5. Health check path: `/api/health`. Render uses it to tell whether the app started correctly.
6. Deploy, open the link, and run the README checklist on your laptop **and** your phone.

### Phase C: before each interview
- Open the link 1–2 minutes early so it's awake.
- Put the link at the top of the README and in your CV or email.
- Keep a 60-second walkthrough ready: submit a problem → see it in the reviewer inbox → open the details.

## Later milestones on the same host
- **Milestone 5 (real AI):** the model API key goes into Render's *environment variables* (secret settings), never into code or GitHub. Add a per-sandbox AI quota and a daily spending cap first.
- **A real deployment for a company** would be different: hosting inside the country for data residency, company sign-in (SSO), a managed database such as Postgres, and access controls. Keep this demo clearly separate from that.
