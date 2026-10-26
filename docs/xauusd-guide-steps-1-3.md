# XAUUSD session-momentum rule: guide steps 1 to 3

**SIMULATION and BACKTEST only.** Nothing here is a trading signal or financial advice. Every result comes from historical data, with the caveats in section 7.

This document records what was done for steps 1 to 3 of the Simulation-First Setup Guide: time windows, signal score and position size. It also records every decision that was made, who made it, and which data was looked at, so the work can be checked and reproduced.

---

## 1. The rule being tested

Produced by the council run on 26 October 2026 (`data/council/real-20261026-095550/result.json`, not in the repo, because `data/` is git-ignored). The council's agreed rule is called **C4**.

- **Market and timeframe:** XAUUSD, 5-minute bars, from Dukascopy 1-minute bid candles (UTC).
- **Sessions:** London 08:00 to 17:00 Europe/London, and New York 08:00 to 17:00 America/New_York. Daylight saving is handled by the time-zone database.
- **Entry:** at 08:30 local time, which is 30 minutes after the open, using that bar's close. Buy if the close is at least 0.6 × daily ATR above the pre-session start price **and** above the 300-bar EMA. Sell if it is at least 0.6 × daily ATR below **and** below the EMA. At most one trade per session per day.
- **Pre-session start price:** London uses the first price from 00:00 to 08:00 London time. New York uses the first price from 08:00 London time to 08:00 New York time.
- **Daily ATR:** the average true range over the previous 14 trading days, using yesterday's value only.
- **Stop:** 0.6 × daily ATR from entry.
- **Target:** 2 × the stop distance from entry.
- **Exit:** the first of stop, target, or the 17:00 session close.
- **Costs:** $0.30 spread per trade; $0.10 slippage on stop exits. Results are in R (multiples of the amount risked per trade).

---

## 2. Data

| Item | Value |
|---|---|
| Source | Dukascopy XAUUSD BID one-minute candles, UTC |
| Downloaded | 2020-01-01 to 2026-10-26: 2,135 days read, 42 days could not be read (the first were 8, 9, 12, 13 and 14 January 2020) |
| Trading data used | 2020-01-28 to 2026-10-23 (the first weeks are used to warm up the ATR) |
| Five-minute bars | 474,107 |
| London session-days | 1,714 |
| New York session-days | 1,660 |
| Split | 70% training: 2020-01-28 to 2024-10-23 (1,199 trading days). 30% holdout: 2024-10-24 to 2026-10-23 (515 days) |

The holdout is the last 30% of days. It was set aside before the council ran, so the bots could not see it.

---

## 3. Step 1: find the strongest time windows

### 3.1 How the rule was found

- A council of **8 scripted bots** ran **3 debate rounds** on the training data only. No Claude model was used in this run.
- The bots tested **1,819 rule variants** on the training data.
- The top-voted rule was then tested once on the holdout. It passed the council's gate: at least 30 trades, a profit factor of at least 1.1, a t-stat of at least 2.0, and profit in both London and New York.

### 3.2 Training and holdout results (rule C4, $0.30 spread, $0.10 slippage)

| | Training (110 trades) | Holdout (68 trades) |
|---|---|---|
| Total | +22.8R | +19.0R |
| Average per trade | +0.21R | +0.28R |
| Win rate | 56% | 63% |
| Profit factor | 1.76 | 2.07 |
| t-stat | 2.30 | 2.43 |
| Max drawdown | 3.7R | 5.2R |
| Worst losing streak | 5 | 4 |

**Exit types**

| Exit | Training: trades, total R | Holdout: trades, total R |
|---|---|---|
| 2R target | 12, +23.8R | 9, +17.9R |
| Stop | 21, −21.6R | 12, −12.1R |
| 17:00 session close | 77, +20.6R | 47, +13.2R |

Most trades close at the session end rather than at the target. In the holdout, the session-end exits made +13.2R of the +19.0R total. The win rate is high partly because many session-end exits are small winners.

### 3.3 Time-window tables

Entries always happen at 08:30 local time, so there are no hour-of-day windows to compare. The windows that can be compared are session, direction, weekday and year. Groups under about 20 trades are too small to read.

**Session and direction**

| Group | Training: trades, avg R | Holdout: trades, avg R |
|---|---|---|
| London | 45, +0.19 | 46, +0.32 (win 70%, max drawdown 2.4R) |
| New York | 65, +0.22 | 22, +0.20 (win 50%, max drawdown 3.2R) |
| Buys | 50, +0.06 | 36, +0.15 |
| Sells | 60, +0.33 | 32, +0.43 |

Both sessions are positive in both periods. Sells beat buys in both periods. That's consistent, but it isn't yet a trading rule.

**Weekday**

| Day | Training: trades, avg R | Holdout: trades, avg R |
|---|---|---|
| Monday | 27, +0.07 | 19, +0.29 |
| Tuesday | 20, +0.00 | 12, +0.28 |
| Wednesday | 17, +0.06 | 13, +0.36 |
| Thursday | 26, +0.36 | 12, −0.07 |
| Friday | 20, +0.52 | 12, +0.52 |

The weekday pattern doesn't hold up. Thursday goes from +0.36R in training to −0.07R in the holdout. Friday is positive in both, but across both periods it's only 32 trades. **No weekday filter should be used.**

**Year (holdout):** 2024 (3 trades, +0.88R), 2025 (40 trades, +0.18R, max drawdown 5.2R), 2026 (25 trades, +0.37R). Every year is positive. In training, 2021 and 2023 are close to zero.

### 3.4 Data checks

| Check | Result |
|---|---|
| Timestamps in the right time zone | Every London session-day starts at 08:00 local (0 exceptions in 1,714). Every New York session-day starts at 08:00 local (0 exceptions in 1,660). |
| Each trade counted once | No session-day has more than one trade, in either the training list or the holdout list. |
| Trades on session-days with missing bars | 0 of 68 holdout trades. The training list was not checked this way. |

**Known backtester issue:** if a bar is missing from the data, the backtester cannot see a stop-out inside that bar. A test confirmed this: a stop at −1R was recorded as a close at −0.25R. The holdout is not affected, because none of its trades fell on a session-day with missing bars. The fix has not been made yet. It should be made before any new backtest is run.

### 3.5 Robustness: when the session closes

Each run uses the same trades and the same rule. Only the session close changes.

| Session closes | Training: trades, avg R, PF, t | Holdout: trades, avg R, PF, t |
|---|---|---|
| 17:00 (the design) | 110, +0.21, 1.76, 2.30 | 68, +0.28, 2.07, 2.43 |
| 16:00 | 110, +0.22, 1.82, 2.43 | 68, +0.28, 2.09, 2.45 |
| 15:00 | 110, +0.16, 1.60, 1.89 | 68, +0.22, 1.95, 2.07 |
| 14:00 | 110, +0.14, 1.57, 1.78 | 68, +0.15, 1.64, 1.48 |

The 17:00 row reproduces the transcript exactly. Closing at 16:00 changes almost nothing. At 15:00 the holdout stays positive, but its t-stat is only just above 2.0. At 14:00 it fails the gate. Holdout profit falls from +19.0R to about +9.9R. **The design stays at 17:00.** The other closes are robustness checks, not alternatives to choose between.

### 3.6 Robustness: spread

| Spread | Training: avg R, PF, t | Holdout: avg R, PF, t |
|---|---|---|
| $0.30 (the design) | +0.21, 1.76, 2.30 | +0.28, 2.07, 2.43 |
| $1.00 | +0.16, 1.53, 1.75 | +0.26, 1.98, 2.26 |
| $2.00 | +0.09, 1.26, 0.96 | +0.23, 1.84, 2.02 |

The holdout survives a $2.00 spread, but only just, with a t-stat of 2.02. Training weakens a lot. The likely reason is that early stops were only about $8 to $36 wide, so a fixed extra cost takes a bigger share of each trade's risk. Holdout stops are usually wider. This is an inference from the trade lists. Slippage was held at $0.10. Real slippage around news could be larger.

### 3.7 What Step 1 shows, and what it doesn't

- The rule passed its holdout test, with the design costs.
- It stays positive at a $2.00 spread and at a 15:00 close, but the margin narrows.
- It depends on late-session moves more than on the first 30 minutes.
- No time window can be named as an edge. Sessions and direction are the only groups large enough to read, and even those are small.

---

## 4. Step 2: signal score

### 4.1 Rubric

The guide's example categories and weights were used, with thresholds set in advance. Every input is measured at the 08:30 bar, so nothing depends on later bars.

| Category (max) | Measured as | Points |
|---|---|---|
| Trend (40) | Distance of the 08:30 close from the 300-bar EMA, in daily ATR | ≥1.0 → 40; 0.5 to <1.0 → 25; <0.5 → 10 |
| Momentum (25) | Move from the pre-session start to the 08:30 close, in daily ATR | ≥1.0 → 25; 0.8 to <1.0 → 15; 0.6 to <0.8 → 10 |
| Volume (20) | First-30-minute volume ÷ median of the previous 20 sessions' first-30-minute volume | ≥1.5× → 20; 1.0 to <1.5× → 10; <1.0× → 0 |
| Volatility and risk (15) | Today's ATR ÷ its 50-day median | 0.8 to 1.5 → 15; 0.6 to <0.8, or 1.5 to 2.0 → 8; otherwise 0 |

**Bands:** 85 to 100, normal simulated size; 70 to 84, review or a smaller size; below 70, skip.

**Volume caveat:** Dukascopy's volume is an activity count, not exchange volume for gold. The first-30-minute totals are only about 2 units, so the ratio rests on small numbers.

### 4.2 How it performed

The score was run once on the training trades and once on the holdout trades.

| Band | Training: trades, win, avg R | Holdout: trades, win, avg R |
|---|---|---|
| Normal (85–100) | 13, 62%, +0.44 | 10, 50%, +0.44 |
| Review (70–84) | 23, 39%, −0.01 | 7, 100%, +0.87 |
| Skip (below 70) | 73, 60%, +0.24 | 51, 61%, +0.17 |

- The normal band beats the skip band in both periods, but on only 10 to 13 trades.
- The review band reverses between the two periods. It's the worst band in training and the best in the holdout, on 7 trades. The middle band tells us nothing.
- **Momentum:** a move of at least 1.0 ATR is the strongest input. Training +0.53R (18 trades); holdout +0.66R (14 trades). Lower levels don't rank consistently.
- **Volume:** the top level (≥1.5×) beats the bottom level in both periods. Training +0.27R against −0.06R (35 and 25 trades); holdout +0.57R against +0.09R.
- **Trend:** flat across its levels in both periods.
- **Volatility:** the middle band beats the normal-volatility band in both periods. That doesn't fit any sensible story, so it's probably noise.

**Conclusion:** the score doesn't separate winners reliably enough to be used as a filter. Momentum and volume may be worth testing forward, as hypotheses. There were about twenty comparisons, so some results will look good by chance.

### 4.3 Worked example

Setup: **2024-09-30, New York** (a training-period trade, which the rule took as a sell).

| Input | Value |
|---|---|
| 08:30 close | 2637.68 |
| Pre-session start price | 2657.76 |
| 300-bar EMA | 2654.52 |
| Daily ATR (previous 14 days) | 32.02 |
| Today's ATR ÷ 50-day median | 0.928 |
| First-30-minute volume ÷ previous 20-session median | 2.24 ÷ 2.12 = 1.06 |

| Category | Points | Reason |
|---|---|---|
| Trend | 25 of 40 | 16.84 ÷ 32.02 = 0.53 ATR, in the 0.5–1.0 band |
| Momentum | 10 of 25 | 20.08 ÷ 32.02 = 0.63 ATR, in the 0.6–0.8 band |
| Volume | 10 of 20 | 1.06, in the 1.0–1.5 band |
| Volatility and risk | 15 of 15 | 0.93, in the 0.8–1.5 band |
| **Total** | **60 of 100** | **Skip band** |

The trade closed at +0.165R. One example proves nothing, but it shows that the score would have skipped a winner.

---

## 5. Step 3: simulated position size

### 5.1 Limits chosen

Confirmed by the user on 26 October 2026. Fixed for the whole simulation: the guide says not to change the risk limit during a test. The user accepted that 29 holdout trades fall under 1 oz (section 5.5).

- **Simulated balance:** $10,000
- **Risk per trade:** 0.5%, which is **$50.00**

The balance was chosen so that position sizes stay near the 1-ounce minimum that many brokers use. At $1,000, the risk would be $5 per trade, which is too small for most brokers.

### 5.2 Formula

> **Position size (oz) = risk amount ÷ stop distance**, where stop distance = |entry − stop| in dollars per ounce.

### 5.3 Examples

| Date | Session | Side | Stop distance | Size | Result | Dollars at $50 risk |
|---|---|---|---|---|---|---|
| 2024-09-30 | New York | sell | $19.21 | 2.60 oz | +0.165R | +$8.25 |
| 2024-11-06 | New York | sell | $18.28 | 2.74 oz | +0.931R | +$46.55 |
| 2025-12-15 | London | buy | $34.97 | 1.43 oz | −1.011R | −$50.55 |
| 2026-10-09 | London | buy | $47.38 | 1.06 oz | −0.134R | −$6.70 |

### 5.4 Results at these limits

A backtest with no compounding. Each trade is sized to risk $50.

| | Training (110 trades) | Holdout (68 trades) |
|---|---|---|
| Size range | 1.39 to 6.20 oz (median 3.55) | 0.31 to 2.94 oz (median 1.05) |
| Trades under 1 oz | 0 | 29 |
| Total P&L | +$1,138 (+11.4% of balance) | +$951 (+9.5% of balance) |
| Worst trade | −$52 | −$51 |
| Max drawdown | $185 (1.9%) | $258 (2.6%) |

### 5.5 Problem to check

Holdout stops are much wider than training stops (median $48, against $14). That leaves **29 holdout trades under 1 oz**. Many brokers' smallest XAUUSD size is 1 oz (0.01 lot). **Check your broker's minimum before trading this.** If the minimum is 1 oz, those trades would risk more than $50, up to about $160 (1.6% of the balance). The limit was not changed to hide this, and the user confirmed it with this known. A larger balance would fix it, and that choice belongs to the user.

### 5.6 Step 4 fields (confirmed)

The user confirmed all of these on 26 October 2026. They were proposed by the assistant at the user's request.

- **Max simulated risk per trade:** 0.5% ($50).
- **Max simulated daily loss:** $100 (1%). With at most one trade per session, two full stops is the most a day can lose, so this cap can't bind on its own.
- **Max open positions:** 2, one per session. London and New York overlap for about four hours a day, so two trades can be open together.
- **Pause condition:** after 5 losing trades in a row, stop simulating and review.
- **Rule violation:** log `rule_followed = no` and take no further trades that session.

Step 4 was meant to be written before testing. It was written after, so these rules describe the frozen design and must not be changed to fit the forward results.

---

## 6. Holdout use (an honest log)

The holdout is the only out-of-sample data this work has, and it has been examined several times. Any new conclusion from it is weaker than the numbers suggest.

| Look at the holdout | Purpose |
|---|---|
| 1. Council verdict | Rule C4 passed the gate |
| 2. Signal score | Score bands and categories, run on holdout trades |
| 3. Session close at 17:00, 16:00, 15:00 and 14:00 | Robustness |
| 4. Spread at $0.30, $1.00 and $2.00 | Robustness |
| 5. Position sizes and dollar results | Arithmetic only, no new selection |

The days after 23 October 2026 haven't been looked at for this rule. They are the next clean test (see section 8).

---

## 7. Limits and known issues

- **Backtest only.** Results do not show that the rule will work in the future.
- **Small samples.** 110 training and 68 holdout trades; about 34 trades a year. Confidence intervals are wide. For the holdout average, the approximate 95% range is +0.05R to +0.51R.
- **Optimistic fills.** Entries are assumed at the exact 08:30 close. A real order would fill slightly later and at a worse price.
- **Missing-bar bug.** See section 3.4. Not yet fixed.
- **Volume** is a coarse proxy (section 4.1).
- **Costs and slippage** are assumed. Real spreads widen around news and at the opens, which is when this rule trades.
- **Data source:** Dukascopy bid prices, not a broker's prices.
- **Selection:** 1,819 variants were tested before the rule was chosen. The holdout test removes some of that risk, but not all of it.
- **Scripted bots** ran the council. The Claude-driven bots exist in the code but weren't used for these results.

---

## 8. Guide steps 4 to 6: where things stand

- **Step 4, risk rules:** section 5.6, confirmed by the user on 26 October 2026.
- **Step 5, trade log:** a forward journal is built (`xauusd_council/journal.py`). It logs each new session once its 17:00 close is in the data. No forward sessions are logged yet, because the data ends on 23 October 2026.
- **Step 6, weekly review:** starts after a week of journal entries.

Open decision for the user: check the broker's minimum position size before trading.

---

## 9. How to reproduce

Run from the `innovation-hub` folder on a Mac, after `pip install -r requirements.txt` and with the virtual environment active.

```bash
python -m xauusd_council fetch --start 2020-01-01 --out data/xauusd_m1.csv
bash scripts/run_xauusd_council.sh            # runs the council; writes data/council/real-<time>/
python -m xauusd_council journal --rule data/council/real-20261026-095550/result.json
```

The step 1 robustness runs (session close, spread), the position-size calculation and the step 2 score were run as short Python scripts, pasted into a terminal, and checked in the conversation. They are **not yet in the repo**. They should be committed before anyone relies on them.

---

## 10. Code and commits (branch `claude/multi-bot-xauusd-rules-lxt6k8`)

| Commit | What it added |
|---|---|
| `0225ecb` | The council: market, rules, backtester, bots, referee, tests |
| `6fb6e48` | Demo labelling for synthetic runs |
| `61ba7de` | One-command Mac script; a sturdier Dukascopy downloader |
| `fc8af63` | The forward journal, its `journal` command, and a test |
