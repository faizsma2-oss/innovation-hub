# XAUUSD council

A council of bots that propose, debate and vote on **one trading rule for gold (XAUUSD) in the London and New York sessions**. You choose how many bots sit on it. Every number a bot quotes comes from the same backtester, never from the bot itself. The winning rule is then tested on recent data that no bot saw. If it doesn't hold up there, the council says so instead of handing you a rule.

It's a research tool, not a trading system. Read [Caveats](#caveats) before trading anything it finds.

## Run it

From the repository root, with the project's virtual environment active (`pip install -r requirements.txt` adds `numpy` and `pandas`):

```bash
# 1. Try it on synthetic gold-like data (about 10 seconds; the result means nothing for real trading)
python -m xauusd_council demo --bots 6

# 2. Get real data: free one-minute XAUUSD candles from Dukascopy (UTC), saved to data/xauusd_m1.csv
python -m xauusd_council fetch --start 2020-01-01

# 3. Convene the council on it
python -m xauusd_council run --data data/xauusd_m1.csv --bots 8 --rounds 3
```

You can also use your own export: MetaTrader (`<DATE> <TIME> <OPEN>…`), Dukascopy, HistData or any CSV with a time column and open/high/low/close. **Say which clock the file uses** with `--tz`. MetaTrader exports use the broker's server time, which is often UTC+2/+3 (`--tz Europe/Athens` is a common match). Sessions are cut by London and New York local time, so the wrong clock means the wrong sessions.

The conversation prints as it happens. A full record is written to `data/council/<time>/`:
- `transcript.md`: the agreed rule (or why there isn't one), a training vs holdout table, the votes and the whole debate
- `result.json`: everything, including the rule as data, ready for `Rule.from_dict()`

| Option | Default | |
|---|---|---|
| `--bots N` | 5 | 2 to 20 bots. The first 8 are all different (see below). After that, more proposers join, each with its own idea. |
| `--rounds N` | 2 | Debate rounds before the vote |
| `--holdout F` | 0.3 | Share of the latest days kept hidden from the bots |
| `--timeframe M` | 5 | Bar size in minutes (1, 5, 10, 15, 30, 60). Finer data is combined. |
| `--spread`, `--slippage` | 0.30, 0.10 | USD per ounce. Use your broker's real costs. |
| `--brain` | auto | `scripted`, `claude`, or `auto` (Claude when `ANTHROPIC_API_KEY` is set) |
| `--quick` | off | Smaller search grids, for a fast try |

Timing: 5 years of 5-minute data, 8 bots and 3 rounds take about 15 seconds with the scripted brain.

## How the council works

1. **Opening.** The referee (plain code, not a bot) sets out the brief, the data, the costs, and the split: bots may only test on the older training period. Each bot says what it cares about.
2. **Proposals.** Each proposer searches its own setups on the training data (hundreds of versions) and puts forward the one that scores best by its own measure.
3. **Debate rounds.** The referee posts every rule's results. Each bot reviews the three strongest rules by its own measure, names what fails its checks, and may suggest one change, with the before/after numbers. Each author accepts the change that helps most by *its own* measure, or says why not. Any proposer whose rule is clearly beaten withdraws it and backs the better one.
4. **Vote.** Every bot ranks the remaining rules, and the ranks are added up (a Borda count).
5. **Verdict.** The referee tests the top rules, in vote order (at most three), on the hidden holdout period. To hold up, a rule needs at least 30 trades, a profit factor of 1.1 or more, a **t-stat of 2 or more**, and money made in **both** London and New York. The first rule that holds up is adopted. If none does, the council recommends nothing.

### The bots

| Bot | Proposes | Values most | Won't back a rule that… | Suggests to others |
|---|---|---|---|---|
| Breakout Bot | Opening-range and pre-session breakouts | t-stat, return/drawdown, PF | has < 80 trades or PF < 1.05 | other targets |
| Sweep Bot | Fades of false breaks of the pre-session range | PF, win rate | has < 60 trades or PF < 1.1 | a different entry window |
| Skeptic Bot | — | t-stat, consistency | has < 100 trades, t < 2, < 3 of 4 quarters profitable, settings that are a lucky spike, or barely beats buying every open | the most robust neighbouring settings |
| Trend Bot | EMA trend pullbacks | t-stat, consistency | has < 80 trades, PF < 1.05, or < 2 of 4 quarters profitable | a trend filter |
| Risk Bot | — | return/drawdown | returns < 2× its max drawdown, or has a losing streak > 12 | other stops and targets |
| Momentum Bot | Following big pre-session moves | t-stat, PF | has < 60 trades or PF < 1.05 | a volatility filter |
| Session Bot | — | the weaker session's PF | has PF < 1.05 or < 30 trades in either London or New York | any one-step change |
| Reversion Bot | Bollinger-band and RSI fades | PF, win rate | has < 60 trades or PF < 1.1 | other targets |

Bots 9 to 20 are more proposers ("Breakout Bot 2", …). Each skips entries another bot already proposed, so it brings its own idea.

### Claude bots

With `ANTHROPIC_API_KEY` in `.env` (as for the Hub), each bot is driven by Claude (`claude-opus-5-5`, low effort). Claude gets exactly the evidence the scripted bot would use: its options, its checks, the change it could suggest, every rule's results and what the other bots just said. It then decides which rule to propose, what to say, which suggestion to put forward or accept, and how to vote. Plain code still runs every test, counts every vote and runs the holdout. Withdrawing stays a scripted decision.

Every answer is checked before it's used, as in the Hub's Claude brain:
- it must match a fixed JSON schema
- picks and ids must be ones that were offered, a reply accepts at most one change, and a vote ranks every rule once
- **every number in a message must appear in the evidence Claude was given**, so a bot can't invent a statistic

If a check fails, or Claude can't be reached, the scripted bot answers that turn. The transcript marks it, and `result.json` records the reason. A council of 5 bots over 2 rounds makes roughly 20 to 30 calls. The run's calls and cost are recorded in `result.json` under `claude`.

## The rule language

A rule is one entry setup, applied to both sessions with the same settings. Stops and targets are measured in **daily ATR**: the average range of the previous 14 trading days, so the day being traded is never used. Every rule is intraday: at most one trade per session per day, closed at the session close at the latest.

| Setup | Entry |
|---|---|
| `opening_range_breakout` | Break of the high/low of the session's first N minutes |
| `pre_session_breakout` | Break of the range built before the session (Asia before London; the London morning before New York) |
| `pre_session_sweep` | Price runs past the pre-session high/low, then a bar closes back inside: trade the reversal |
| `trend_pullback` | Fast EMA above slow: buy a green bar that dipped to the fast EMA and closed above it (and the mirror image) |
| `session_momentum` | N minutes after the open, follow a move of at least X ATR since the pre-session began |
| `band_reversion` | Fade a close outside a Bollinger band when RSI is stretched |

Every rule also has `stop_atr`, `target_r` (as a multiple of the stop), an optional trend filter (`trend_ema`, in bars) and an optional volatility filter (`vol_filter`: skip days whose ATR is below that share of its 50-day median).

**Sessions** follow local clock time, so daylight saving is handled by the time zones themselves. London is 08:00–17:00 `Europe/London`; New York is 08:00–17:00 `America/New_York`. For about three weeks each spring and autumn, the two cities change clocks on different dates and the overlap shifts by an hour. The sessions follow that.

## Why its numbers can be trusted (and how far)

- **Conservative fills.** Breakouts fill at the trigger level plus slippage, or at the open if price gapped past it. If a bar touches both the stop and the target, it counts as a stop. A stop that price gaps through fills at that bar's open. On a breakout's entry bar, only the stop can be hit. Every trade pays the spread.
- **No look-ahead.** Indicators only use closed bars, filters on stop orders use the previous close, and the daily ATR is yesterday's. A test checks that a spike on one day changes the next day's ATR but not its own.
- **Checked against noise.** On random-walk data with no costs, pooled over 60 seeds (8,000 to 41,000 trades per setup), every setup's average trade is between +0.002R and +0.025R. None is significantly different from zero (pooled t below 2), and all are smaller than the cost of one trade (about 0.05R). An early version of the synthetic data let stop orders fill too well and showed a fake breakout edge on pure noise (+0.09R a trade after costs). That's why this check is a test.
- **The holdout gate.** On pure noise, no council passed: 0 of 24 quick councils (4 bots, 1.4 and 3 years of data) and 0 of 3 full councils (8 bots, 3 years). Before the t-stat requirement was added, 1 of the same 24 passed, with a holdout t-stat of 0.71. On data with a planted breakout pattern, the council chose an opening-range breakout and passed the holdout in 6 of 6 runs (holdout t-stats 3.4 to 6.1).
- **It counts its own searching.** The transcript says how many rule variants were tried on the training data. A council that tried 1,500 variants will always find something that looks good there. That is why only the holdout counts.

## Caveats

- **Not yet run on real gold prices.** It was built in an environment that couldn't reach any price feed. The Dukascopy downloader's file parsing is tested on a constructed file, not a live download. If a download fails or the prices look wrong, the downloader stops with an error instead of guessing.
- A backtest is not a forecast. A rule that held up on one holdout period can still stop working.
- Costs are assumptions. Gold spreads widen around news (US data at 08:30 New York time) and the daily rollover.
- Results are in R (multiples of the amount risked), not money. Position sizing is up to you.
- Forward-test on a demo account before risking real money. This is not financial advice.

## Files

| File | |
|---|---|
| `market.py` | Sessions, daylight saving, daily ATR, the session-by-bar grids |
| `rules.py` | The rule language: setups, settings, checks, plain-English descriptions |
| `backtest.py` | Entries, fills, exits, metrics; `Lab` (one period, cached tests) |
| `bots.py` | The personas, how each scores and checks a rule, their messages (the scripted brain) |
| `claude_bots.py` | The same bots driven by Claude, with the guardrails above |
| `council.py` | The meeting: proposals, debate, vote, holdout verdict |
| `board.py`, `report.py` | Messages and candidates; the Markdown transcript and JSON record |
| `data.py`, `dukascopy.py` | CSV loading and resampling, synthetic data; the Dukascopy downloader |

Tests: `python -m pytest tests/test_xauusd_council.py` (about 10 seconds). They never call Claude or the network.
