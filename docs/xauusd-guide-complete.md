# XAUUSD session-momentum rule: complete guide record

**SIMULATION and BACKTEST only.** Nothing here is a trading signal or financial advice. Steps 1 to 3 are recorded in detail in [`xauusd-guide-steps-1-3.md`](xauusd-guide-steps-1-3.md). This document covers Steps 4 to 6, the Prompt 4 log row, the final checklist and what remains.

---

## Status

| Guide step | Status | What remains, and who does it |
|---|---|---|
| 1. Time windows | Done (backtest) | Nothing |
| 2. Signal score | Done for one setup. The score did not separate trades reliably | Nothing (see steps 1 to 3 record, section 4) |
| 3. Position size | Done. $10,000 balance and 0.5% risk, confirmed by the user on 26 Oct 2026 | Check the broker's minimum size: **you** |
| 4. Risk rules | Confirmed by the user on 26 Oct 2026, with the $100 daily cap kept. Written after testing, which the guide does not intend | A human review of the plan (not yet done). Do not change anything to fit results |
| 5. Trade log | Built and tested (`journal` command). Waiting for sessions after 23 Oct 2026 | Run `fetch` and `journal` after each session, and fill in the hand columns: **you** |
| 6. Review | Scheduled monthly. Needs at least one month of journal rows | Run the monthly review: **you**, with the steps below |
| Final checklist | Partly met (see below) | Forward test on unseen data, which has not started: **time** |

---

## Step 4: strict risk rules

Written after the backtest, not before. The guide intends the rules to come first, so these are frozen for the forward test. Changing them starts a new test.

| Required field | Rule |
|---|---|
| Entry condition | 08:30 local time (30 minutes after the open), using that bar's close. Buy if the close is at least 0.6 × daily ATR above the pre-session start price and above the 300-bar EMA. Sell if it is at least 0.6 × daily ATR below and below the EMA. At most one entry per session. |
| Invalidation or stop condition | 0.6 × daily ATR from entry. |
| Target or exit condition | 2 × the stop distance from entry, or the 17:00 session close, whichever comes first. If the stop and target are both hit in one 5-minute bar, count the stop. |
| Maximum simulated risk per trade | 0.5% of the simulated balance: $50 on $10,000. |
| Maximum simulated daily loss | $100 (1%), kept by the user's decision on 26 Oct 2026. A day where both sessions hit their stops loses about $103 with costs, which the user accepted. The cap cannot stop a second trade. |
| Maximum open positions | 2, one per session. |
| Pause conditions | (a) After 5 losing trades in a row, stop simulating and review before continuing. (b) Skip a session if its required data is missing or out of date. |
| What happens after a rule violation | Log `rule_followed = no` with a note. Take no further trades that session. Include it in the monthly review. |

**Decision recorded:** the $100 daily cap is kept. A full stop costs about $51 with costs, so two full stops in one day lose about $103, which is above the cap. The cap cannot stop a second trade, because one trade cannot lose $100 by itself. The user accepted this on 26 October 2026.

### Pre-trade check (the guide's six questions)

Worked on the 2024-09-30 New York sell as an example. This is a historical example, not a live check.

| Question | Answer |
|---|---|
| Is the setup allowed in this time window? | Yes. 08:30 New York local time, inside the 08:00 to 17:00 session, and the first entry of that session. |
| Does the signal score pass the threshold? | Not required. The score isn't part of this rule, because it didn't separate trades reliably (steps 1 to 3 record, section 4). Adding a score filter now would be a new rule. For this example the score was 60. |
| Are entry, stop and exit rules present? | Yes. Entry 2637.68, stop 2656.89, target 2599.25 (2R), exit at 17:00 at the latest. |
| Is the position within the risk cap? | Yes. 2.60 oz × $19.21 = $49.95, within $50. |
| Is any required data missing? | No. All four inputs are present. |
| Has a human reviewed the plan? | **No.** No person has reviewed this plan yet. Review it before relying on it. |

## Step 5: trade log

### The journal

- **File:** `data/journal.csv` on your Mac, created by the `journal` command.
- **Columns:** the guide's order, plus the rule's own fields. Full list: `date, session, entry_time_local, market, setup, signal_score, direction, entry, stop, target, exit, exit_reason, result_R, costs_usd, simulated_size, rule_followed, actual_entry, actual_exit, notes, source`.
- **Written by the command:** every column except the five you fill in by hand.
- **Filled by you:** `signal_score` (optional), `simulated_size` (= $50 ÷ |entry − stop|), `rule_followed`, `actual_entry`, `actual_exit`, `notes`.
- **Only closed sessions are logged.** A session appears only once its 17:00 close is in the data.

### Routine, after each trading day

```bash
.venv/bin/python -m xauusd_council fetch --start 2020-01-01 --out data/xauusd_m1.csv
.venv/bin/python -m xauusd_council journal --rule data/council/real-20261026-095550/result.json
```

Run it the morning after, not the same evening. Use the same `result.json` every time.

### Limit of the journal

The journal is written after each session closes. It shows what the rule would have done. It is **not** a live forward test, because a real trade at 08:30 would need the signal before the session starts, which this setup does not provide. A real-time forward test needs live prices and a check at 08:30. That is a separate piece of work.

### Prompt 4: log the test (one row)

This row records the holdout test of the rule. Missing fields are marked MISSING, as the guide requires.

| Date and time | Market | Setup name | Signal score | Entry | Stop | Target or exit rule | Simulated position size | Outcome | Fees and slippage | Rule followed | Notes | Source or chart link |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Test window 2024-10-24 to 2026-10-23; run 2026-10-26 | XAUUSD | Session momentum, rule C4 | MISSING for the rule (the score was tested on its 68 trades, see steps 1 to 3 record) | MISSING (per trade, see trade list) | MISSING (per trade) | 2R target, stop, or 17:00 close | $50 risk per trade ($10,000 at 0.5%): 0.31 to 2.94 oz | 68 trades, +19.0R total, +0.28R average, max drawdown 5.2R, worst losing streak 4. BACKTEST | $0.30 spread per trade; $0.10 slippage per oz on stop exits | MISSING (no forward trades yet) | BACKTEST, not live performance. The holdout had already been examined for the verdict, the score, four exit times and three spreads, so this is not a clean out-of-sample result | `docs/xauusd-guide-steps-1-3.md`; council run `real-20261026-095550` |

---

## Step 6: review

### Schedule

- **Monthly**, in the first week of the following month. At this trade frequency (about 34 a year), a weekly review usually has fewer than three trades.
- **Before the review:** confirm the journal is up to date (run `fetch` and `journal`), and fill in every hand column for the month.

### Procedure (the guide's Prompt 5)

1. Copy the month's rows from `data/journal.csv`.
2. Paste them into Prompt 5 in a Claude chat, in place of `[PASTE JOURNAL ROWS]`.
3. Check each number Claude gives against the rows yourself: the count of trades, the total of `result_R`, the wins and losses. Trust the arithmetic from your spreadsheet over Claude's.
4. Note the rule violations (`rule_followed = no`) and any pause condition triggered.
5. Treat Claude's three suggested experiments as ideas for a future simulation period only.

### What the review must not do

- Change any rule, limit or setting during the forward test.
- Rerun the council, which would produce a different rule.
- Call a pattern proven when the sample is small. The guide's own warning applies: a small winning sample does not prove an edge.

---

## Final checklist (the guide's, with honest status)

- [x] The $80 → $4,218 result is labeled self-reported and was not used as a benchmark.
- [x] All results are labeled simulation or backtest.
- [~] Every number can be traced to supplied data. Partly: the analysis scripts for steps 1 and 2 are pasted in the conversation and not yet committed, and the data and council outputs are only on your Mac. Commit the scripts before relying on them.
- [x] Fees, slippage, drawdown and losing streaks are included.
- [x] No live credentials or API keys were shared.
- [x] No automated order execution was enabled.
- [ ] A human reviewed every output. **Pending:** you tick this after your own review.
- [x] Nothing promises guaranteed profit.
- [ ] The framework was tested on unseen data before any real-money decision. **Not met.** The holdout was examined many times, and the forward test has not started. A real-money decision should wait for that.

---

## What remains, in order

1. **You:** review the Step 4 plan. No human has reviewed it yet.
2. **You:** check the broker's minimum position size (Step 3).
3. **You:** after each trading day, run `fetch` and `journal`, and fill in the hand columns (Step 5).
4. **You:** after the first full month of journal rows, run the monthly review (Step 6).
5. **You:** keep the forward test going for at least about two years before any real-money decision, because a sample big enough to judge takes that long at this frequency.
6. **Us:** commit the analysis scripts for steps 1 and 2, and fix the backtester's missing-bar issue (see the steps 1 to 3 record, section 3.4). Fixing it changes the backtest numbers, so the holdout result must be recomputed and reported as a new run.
