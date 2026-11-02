# MahadSpace

A rebuild of the MahadSpace dashboard (originally at http://13.207.171.122). The page looks and works the same. The
server behind it is new: it was rewritten from what the page sends and expects, because the original server code
wasn't available.

It does the following:

- **Telegram:** connect a Telegram account, read the Discussion and VIP group members, link each member to their
  Vantage and PU Prime UIDs, send reviewed messages, and read UID replies.
- **Reports:** import IB account and rebate reports (Excel, CSV or JSON).
- **Pages:** Trading Records, Telegram Members and Rebate Insights.

## Run it

```bash
cd mahadspace
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000. The first account you create is the owner and can sign in straight away. Later accounts
need verifying:

```bash
python -m app.admin users
python -m app.admin verify someone@example.com
```

Data is kept in `data/mahadspace.db` (set `MAHADSPACE_DB` to put it elsewhere). Back that file up.

### Try it without a real Telegram account

```bash
MAHADSPACE_TELEGRAM=fake MAHADSPACE_DISCUSSION_GROUP=demo-discussion MAHADSPACE_VIP_GROUP=demo-vip \
  uvicorn app.main:app --port 8000
```

Connect with any phone number (for example +971500000001) and the code **12345**.

### Connect real Telegram

1. Go to https://my.telegram.org, sign in, open **API development tools** and create an app. You get an
   *api_id* and an *api_hash*.
2. Start the server with:

   ```bash
   TELEGRAM_API_ID=123456 TELEGRAM_API_HASH=abcdef... \
   MAHADSPACE_DISCUSSION_GROUP=@your_discussion_group \
   MAHADSPACE_VIP_GROUP=-1001234567890 \
     uvicorn app.main:app --port 8000
   ```

   Each group can be an @username, a t.me link, or a numeric ID. The connected account must be a member of both groups
   (and an admin, to remove people).
3. On the Telegram page, click **Connect** and enter the phone number, the code, and the two-step password if the
   account has one.

On a server, put the site behind HTTPS (for example nginx) and set `MAHADSPACE_SECURE_COOKIE=on`.

## Tests

```bash
cd mahadspace && python -m pytest
```

There are 30 tests. They use a fake Telegram and example Vantage/PU Prime files built inside the tests, so they never
contact Telegram.

## The rules

| What | Rule |
|---|---|
| Active account | At least **$50 equity**, or a **trade in the last 30 days** (counted from today). Exactly $50 counts. |
| Active member | Any linked account is active. *Inactive*: has current account data, none active. *Unknown*: no current account data. |
| Match status | *Matched*: a linked UID is in the latest reports. *Historical only*: only in older reports. *Not in reports*: never seen. *No UID*. |
| A new report | Replaces that broker's dataset. The old one is kept in recoverable trash, and its UIDs are remembered as report history. |
| Sending | Only to recipients you selected, who are eligible for that group and audience *right now*, after ticking the review box and typing **SEND**. At most 100 per send, 1.5 s apart. |
| New members | Joined after you pressed *Start tracking*, and not yet sent a new-member message. |
| Reply UIDs | 5 to 10 digits. International (+…) and local (0…) phone numbers are ignored. An *exact match* needs exactly one UID that is in the reports and not linked to someone else. |
| Removing from groups | Needs **REMOVE** typed. A member who has left both groups leaves the directory, but only after a scan that read **both** groups. |

## Rules I had to guess

The original server code wasn't available, so these choices are mine. Check them against how the old site behaved:

1. **The 30-day trade window counts from today,** not from the date the report was exported. If reports are old,
   members will look inactive. The alternative is to count from each report's import date.
2. **An account sheet with no equity column** uses the balance in place of equity for the $50 rule.
3. **Day-first dates** (03/04/2026 = 3 April) when a date could be read either way.
4. **Which sheet is which** is decided from the column names (see `ALIASES` in `app/reports.py`). If a real export
   isn't recognised, add its column names there.
5. **Name suggestions** after a group scan:
   - an exact full-name match suggests the link (96%)
   - all words of the Telegram name appearing in the report name means "needs review"
   - a one-word name suggests nothing.

   Nothing is linked until you approve it.
6. **The message templates' wording** (`TEMPLATES` in `app/telegram_routes.py`).

## Logic errors fixed compared with the original page

- **Confirmation pop-ups showed `\n\n` as literal text,** for example on report removal, member CSV removal, sending
  and erasing replies.
- **The broker wasn't passed when assigning a report UID to a member** (Trading Records → Assign member). A UID that
  exists at both brokers could be linked to the wrong one. The page now sends the broker, and the server refuses an
  ambiguous UID instead of guessing.
- **Restarting reply monitoring left an extra automatic check queued.** It's now cancelled with the rest.
- **The server (rewritten) guards things the page alone can't:**
  - a UID can belong to only one member
  - a failed read of one group never empties the directory
  - nobody is sent the new-member message twice
  - editing an approved reply undoes the link it created
  - a typed account number is turned into its UID
  - dates are normalised to YYYY-MM-DD, so date sorting and the "last trade" filters work on day-first exports
