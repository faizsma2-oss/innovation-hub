"""The XAUUSD council: sessions, the backtester's fills, the rule language, data loading, the debate,
and the Claude bots' guardrails (with a fake Claude: no network, no cost)."""
import json
import lzma
from types import SimpleNamespace

import anthropic
import httpx2
import numpy as np
import pandas as pd
import pytest

from xauusd_council import __main__ as cli
from xauusd_council import dukascopy
from xauusd_council.backtest import Costs, Lab, exits
from xauusd_council.board import Review
from xauusd_council.bots import Bot, PERSONA_BY_KEY, roster
from xauusd_council.claude_bots import ClaudeBot, factory, grounded
from xauusd_council.council import Council, holdout_problems
from xauusd_council.data import load_csv, resample, synthetic
from xauusd_council.dukascopy import RECORD, parse_day
from xauusd_council.market import Market
from xauusd_council.rules import SETUPS, Rule, RuleError


@pytest.fixture(scope="module")
def noise():
    return Market(synthetic(start="2023-06-05", days=500, seed=1), 5)


@pytest.fixture(scope="module")
def planted():
    """Gold-like data with a known pattern: the first half hour of each session sets the next two hours' drift."""
    return Market(synthetic(days=900, seed=3, edge=0.15), 5)


def day(text):
    return int(np.datetime64(text, "D").astype(np.int64))


def first_bar(market, session, date):
    panel = market.panels[session]
    row = np.flatnonzero(panel.days == day(date))[0]
    return market.bars.index[panel.index[row, 0]]


# ── Sessions ─────────────────────────────────────────────────────────────────

def test_sessions_open_at_local_time_through_daylight_saving(noise):
    # The US moved its clocks on 10 March 2024, the UK on 31 March: for three weeks New York opens an hour early in UTC.
    assert str(first_bar(noise, "new_york", "2024-03-05")) == "2024-03-05 13:00:00+00:00"
    assert str(first_bar(noise, "new_york", "2024-03-12")) == "2024-03-12 12:00:00+00:00"
    assert str(first_bar(noise, "london", "2024-03-12")) == "2024-03-12 08:00:00+00:00"
    assert str(first_bar(noise, "london", "2024-04-02")) == "2024-04-02 07:00:00+00:00"
    assert noise.panels["london"].width == noise.panels["new_york"].width == 108  # 9 hours of 5-minute bars


def test_pre_session_ranges(noise):
    bars = noise.bars
    for session, start, end in [("london", "2024-03-12 00:00", "2024-03-12 08:00"),     # Asia, London time = UTC
                                ("new_york", "2024-03-12 08:00", "2024-03-12 12:00")]:  # London open to NY open
        panel = noise.panels[session]
        row = np.flatnonzero(panel.days == day("2024-03-12"))[0]
        window = bars[(bars.index >= pd.Timestamp(start, tz="UTC")) & (bars.index < pd.Timestamp(end, tz="UTC"))]
        assert panel.pre_high[row] == window["high"].max()
        assert panel.pre_low[row] == window["low"].min()
        assert panel.pre_open[row] == window["open"].iloc[0]


def test_daily_atr_only_uses_past_days():
    bars = synthetic(start="2024-01-01", days=120, seed=5)
    calm = Market(bars, 5)
    spiked = bars.copy()
    when = (spiked.index >= pd.Timestamp("2024-03-12 14:00", tz="UTC")) & (spiked.index < pd.Timestamp("2024-03-12 15:00", tz="UTC"))
    spiked.loc[when, "high"] += 200
    wild = Market(spiked, 5)
    panel_calm, panel_wild = calm.panels["london"], wild.panels["london"]
    same, next_day = np.flatnonzero(panel_calm.days == day("2024-03-12"))[0], np.flatnonzero(panel_calm.days == day("2024-03-13"))[0]
    assert panel_wild.datr[same] == panel_calm.datr[same]           # the spike's own day can't see it
    assert panel_wild.datr[next_day] > panel_calm.datr[next_day] + 10  # the next day can


# ── Fills ────────────────────────────────────────────────────────────────────

def one_trade(highs, lows, opens=None, closes=None, entry=100.0, direction=1.0, intrabar=False, costs=Costs(0, 0)):
    H, L = np.array([highs], float), np.array([lows], float)
    O = np.array([opens], float) if opens else (H + L) / 2
    C = np.array([closes], float) if closes else (H + L) / 2
    return exits(O, H, L, C, np.array([H.shape[1] - 1]), np.array([0]), np.array([direction]), np.array([entry]),
                 np.array([2.0]), 2.0, intrabar, costs)


def test_target_stop_and_session_close():
    exit_, reason, r = one_trade([100, 101, 105], [99, 99.5, 101])            # +4 = 2R target hit on bar 2
    assert (reason[0], exit_[0], r[0]) == ("target", 104.0, 2.0)
    exit_, reason, r = one_trade([100, 101, 101], [99, 97.5, 99])             # -2 = stop on bar 1
    assert (reason[0], exit_[0], r[0]) == ("stop", 98.0, -1.0)
    exit_, reason, r = one_trade([100, 101, 102], [99, 99, 100], closes=[100, 100.5, 101])
    assert (reason[0], exit_[0], r[0]) == ("close", 101.0, 0.5)


def test_fills_are_conservative():
    _, reason, _ = one_trade([100, 105], [99, 97])                            # stop and target in one bar: stop
    assert reason[0] == "stop"
    exit_, reason, _ = one_trade([100, 96], [99, 94], opens=[100, 95])        # gapped through the stop: fill at the open
    assert (reason[0], exit_[0]) == ("stop", 95.0)
    _, reason, _ = one_trade([105, 101], [97.9, 99], intrabar=True)           # breakout bar: only the stop counts
    assert reason[0] == "stop"
    _, reason, _ = one_trade([105, 101], [99, 99], intrabar=True, closes=[104, 100])
    assert reason[0] == "close"                                               # the target on the entry bar is ignored
    _, _, r = one_trade([100, 101, 105], [99, 99.5, 101], costs=Costs(spread=0.3, slippage=0.1))
    assert r[0] == pytest.approx((4 - 0.3) / 2)
    exit_, _, r = one_trade([100, 101], [99, 97.5], costs=Costs(spread=0.3, slippage=0.1))
    assert exit_[0] == pytest.approx(97.9) and r[0] == pytest.approx((-2.1 - 0.3) / 2)


def test_no_setup_finds_an_edge_in_pure_noise_before_costs(noise):
    """Guards against look-ahead and optimistic fills: on a random walk with no costs, nothing should work.
    (Across ten seeds every setup averages a t-stat within 0.3 of zero; one seed is checked here.)"""
    lab = Lab(noise, (int(noise.days[0]), int(noise.days[-1])), Costs(0, 0))
    for setup in ("opening_range_breakout", "pre_session_breakout", "pre_session_sweep", "trend_pullback",
                  "session_momentum", "band_reversion"):
        m = lab.test(Rule.make(setup))
        assert m["trades"] > 100, setup
        assert abs(m["t_stat"]) < 3.0, (setup, m["t_stat"])


def test_breakouts_trade_only_after_the_range_and_once_per_session(noise):
    lab = Lab(noise, (int(noise.days[0]), int(noise.days[-1])))
    rule = Rule.make("opening_range_breakout", range_minutes=60, buffer_atr=0.0, stop_atr=0.4, target_r=2.0)
    trades = lab.trades(rule)
    keys = list(zip(trades["day"], trades["session"]))
    assert len(keys) == len(set(keys))
    panel = noise.panels["london"]
    london = trades["session"] == "london"
    for d, entry, direction in list(zip(trades["day"][london], trades["entry"][london], trades["direction"][london]))[:20]:
        row = np.flatnonzero(panel.days == d)[0]
        high, low = np.nanmax(panel.high[row, :12]), np.nanmin(panel.low[row, :12])
        assert (entry >= high + 0.1 - 1e-9) if direction > 0 else (entry <= low - 0.1 + 1e-9)


# ── The rule language ────────────────────────────────────────────────────────

def test_rules_are_checked_and_round_trip():
    rule = Rule.make("pre_session_sweep", sweep_atr=0.1, stop_atr=0.3, target_r=2, trend_ema=300)
    assert Rule.from_dict(json.loads(json.dumps(rule.to_dict()))) == rule
    assert rule.sessions == ("london", "new_york")
    assert "London and New York sessions" in rule.describe() and "300-bar EMA" in rule.describe()
    for bad in [{"setup": "astrology"}, {"setup": "pre_session_sweep", "params": {"sweep_atr": 5}},
                {"setup": "pre_session_sweep", "sessions": ["tokyo"]}, {"setup": "pre_session_sweep", "direction": "up"},
                {"setup": "trend_pullback", "params": {"ema_fast": 50, "ema_slow": 20}},
                {"setup": "opening_range_breakout", "params": {"range_minutes": 120, "entry_window_minutes": 60}},
                {"setup": "pre_session_sweep", "params": {"colour": 1}}, {"setup": "band_reversion", "stop_atr": "wide"}]:
        with pytest.raises(RuleError):
            Rule.from_dict(bad)
    assert rule.with_value("sweep_atr", 0.2).value("sweep_atr") == 0.2
    for setup in SETUPS:  # every setup can be named and described, filters and all
        named = Rule.make(setup, trend_ema=100, vol_filter=0.8, direction="long")
        assert "None" not in named.short() + named.describe()
    assert Rule.make("trend_pullback", sessions=["new_york"]).sessions == ("new_york",)


# ── Data ─────────────────────────────────────────────────────────────────────

def test_load_metatrader_export_in_broker_time(tmp_path):
    path = tmp_path / "XAUUSD_M5.csv"
    path.write_text("<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
                    "2024.07.01\t10:00:00\t2330.10\t2331.00\t2329.50\t2330.80\t120\t0\t15\n"
                    "2024.07.01\t10:05:00\t2330.80\t2332.40\t2330.20\t2332.00\t140\t0\t15\n")
    bars = load_csv(path, tz="Europe/Athens")  # UTC+3 in summer
    assert str(bars.index[0]) == "2024-07-01 07:00:00+00:00"
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
    assert bars["close"].iloc[1] == 2332.0


def test_load_iso_csv_and_resample(tmp_path):
    stamps = pd.date_range("2024-07-01 07:00", periods=10, freq="1min", tz="UTC")
    frame = pd.DataFrame({"time": stamps.strftime("%Y-%m-%dT%H:%M:%SZ"), "open": np.arange(10) + 2300.0,
                          "high": np.arange(10) + 2301.0, "low": np.arange(10) + 2299.0, "close": np.arange(10) + 2300.5})
    path = tmp_path / "m1.csv"
    frame.to_csv(path, index=False)
    five = resample(load_csv(path), 5)
    assert len(five) == 2
    assert five.iloc[0].to_dict() == {"open": 2300.0, "high": 2305.0, "low": 2299.0, "close": 2304.5}
    with pytest.raises(ValueError):
        resample(five, 1)
    bad = tmp_path / "eurusd.csv"
    frame.assign(close=1.08, open=1.08, high=1.09, low=1.07).to_csv(bad, index=False)
    with pytest.raises(ValueError, match="XAUUSD"):
        load_csv(bad)


def test_dukascopy_day_file():
    rows = np.zeros(3, dtype=RECORD)
    rows["seconds"] = [0, 60, 120]
    rows["open"], rows["close"] = [2050123, 2050500, 2050500], [2050500, 2049900, 2050500]
    rows["low"], rows["high"] = [2050000, 2049800, 2050500], [2050600, 2050550, 2050500]
    rows["volume"] = [1.5, 2.25, 0.0]  # the last minute had no trades
    bars = parse_day(lzma.compress(rows.tobytes(), format=lzma.FORMAT_ALONE), pd.Timestamp("2024-01-02").date())
    assert len(bars) == 2
    assert str(bars.index[1]) == "2024-01-02 00:01:00+00:00"
    assert bars.iloc[0][["open", "high", "low", "close"]].tolist() == [2050.123, 2050.6, 2050.0, 2050.5]
    scrambled = rows.copy()
    scrambled["low"], scrambled["high"] = rows["high"], rows["low"]
    with pytest.raises(ValueError):
        parse_day(lzma.compress(scrambled.tobytes(), format=lzma.FORMAT_ALONE), pd.Timestamp("2024-01-02").date())


def day_file(price: float, minutes: int = 3) -> bytes:
    rows = np.zeros(minutes, dtype=RECORD)
    rows["seconds"] = np.arange(minutes) * 60
    rows["open"] = rows["close"] = rows["low"] = rows["high"] = int(price * 1000)
    rows["high"] += 500
    rows["volume"] = 1.0
    return lzma.compress(rows.tobytes(), format=lzma.FORMAT_ALONE)


def test_dukascopy_download(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        if "/2024/00/03/" in url:  # 3 January arrives corrupted every time
            return SimpleNamespace(status_code=200, content=b"not lzma", raise_for_status=lambda: None)
        if "/2024/00/07/" in url:  # a Sunday with no file
            return SimpleNamespace(status_code=404, content=b"", raise_for_status=lambda: None)
        return SimpleNamespace(status_code=200, content=day_file(2050.0), raise_for_status=lambda: None)

    monkeypatch.setattr(dukascopy.requests, "get", fake_get)
    start, end = pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-03-31").date()
    out = dukascopy.fetch(start, end, tmp_path / "xauusd_m1.csv", progress=None)
    bars = load_csv(out)
    assert len(bars) == 3 * (78 - 1 - 1)  # weekdays and Sundays, minus the corrupted day and the missing Sunday
    assert "/2024/00/01/BID_candles_min_1.bi5" in calls[0] and not any("/2024/00/06/" in url for url in calls)
    assert sum("/2024/00/03/" in url for url in calls) == 2  # retried once, then skipped
    before = len(calls)
    dukascopy.fetch(start, end, tmp_path / "again.csv", progress=None)
    assert len(calls) - before == 2  # cached days aren't downloaded again; the corrupted one is retried

    monkeypatch.setattr(dukascopy.requests, "get", lambda url, headers, timeout: SimpleNamespace(
        status_code=200, content=day_file(205.0), raise_for_status=lambda: None))
    with pytest.raises(ValueError, match="don't look like XAUUSD"):  # a price read ten times too small
        dukascopy.fetch(pd.Timestamp("2025-01-06").date(), pd.Timestamp("2025-01-06").date(), tmp_path / "x.csv",
                        cache=tmp_path / "other-cache", progress=None)


# ── The council ──────────────────────────────────────────────────────────────

def test_any_number_of_bots():
    assert [p.key for p, _ in roster(2)] == ["breakout", "sweep"]
    names = [p.name if n == 1 else f"{p.name} {n}" for p, n in roster(12)]
    assert names[8:] == ["Breakout Bot 2", "Sweep Bot 2", "Trend Bot 2", "Momentum Bot 2"]
    for bad in (1, 21):
        with pytest.raises(ValueError):
            roster(bad)


def test_council_finds_a_real_pattern_and_checks_it_on_hidden_data(planted):
    council = Council(planted, n_bots=6, rounds=2, quick=True)
    result = council.run()
    assert result["passed"]
    assert result["rule"]["setup"] == "opening_range_breakout"  # the planted pattern
    assert result["rule"]["sessions"] == ["london", "new_york"]
    assert all(s["avg_r"] > 0 for s in result["holdout"]["sessions"].values())
    # Every bot spoke, the bots answered each other, and the holdout was only opened for the verdict.
    speakers = {m["author"] for m in result["messages"]}
    assert {bot.name for bot in council.bots} <= speakers
    assert any(m["phase"] == "reply" for m in result["messages"])
    assert council.holdout.tested <= 3
    assert result["holdout"]["from"] > result["train"]["to"]
    clones = Council(planted, n_bots=10, rounds=1, quick=True)
    clones.run()
    assert len(clones.bots) == 10 and len(clones.candidates) == 7  # 5 proposers + 2 clones, each with its own idea
    assert len({(c.rule.setup, c.rule.params) for c in clones.candidates}) == len(clones.candidates)


def test_council_says_no_when_nothing_holds_up(noise):
    result = Council(noise, n_bots=4, rounds=1, quick=True).run()
    assert not result["passed"] and result["rule"] is None
    assert result["holdout_tested"] and all(t["problems"] for t in result["holdout_tested"])
    assert "does not recommend" in result["messages"][-1]["text"]


def test_holdout_gate():
    good = {"trades": 80, "profit_factor": 1.3, "t_stat": 2.4, "sessions": {"london": {"avg_r": 0.1, "trades": 40},
                                                            "new_york": {"avg_r": 0.05, "trades": 40}}}
    assert holdout_problems(good) == []
    one_sided = {**good, "sessions": {"london": {"avg_r": 0.2, "trades": 40}, "new_york": {"avg_r": -0.01, "trades": 40}}}
    assert holdout_problems(one_sided) == ["New York lost money (avg -0.01R over 40 trades)"]
    assert len(holdout_problems({**good, "trades": 12, "profit_factor": 1.02})) == 2
    assert "could be luck" in holdout_problems({**good, "t_stat": 0.7})[0]


def test_cli_demo_writes_a_transcript(tmp_path, capsys):
    assert cli.main(["demo", "--years", "2", "--bots", "3", "--rounds", "1", "--quick", "--brain", "scripted",
                     "--out", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert "Skeptic Bot" in printed and "Holdout verdict" in printed
    transcript = (tmp_path / "transcript.md").read_text()
    assert "Synthetic gold" in transcript and "## Caveats" in transcript
    record = json.loads((tmp_path / "result.json").read_text())
    assert len(record["bots"]) == 3 and record["messages"]


# ── Claude bots, with a fake Claude ──────────────────────────────────────────

class FakeClaude:
    """Stands in for anthropic.Anthropic(). Each call gets a reply from `answer(context)`, which may raise."""

    def __init__(self, answer):
        self.answer = answer
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append(request)
        payload = self.answer(json.loads(request["messages"][0]["content"]))
        return SimpleNamespace(model="claude-opus-5-5", stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=2000, output_tokens=100,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0),
                               content=[SimpleNamespace(type="text", text=json.dumps(payload))])


def sensible(context):
    """What a well-behaved Claude might answer, quoting only numbers from the evidence."""
    if "options" in context:
        best = context["options"][1]
        return {"pick": 1, "message": f"I prefer the second option: PF {best['results']['profit_factor']:.2f}."}
    if "suggestions" in context:
        return {"replies": [{"suggestion": s["suggestion"], "accept": i == 0, "message": f"Thanks, {s['from']}."}
                            for i, s in enumerate(context["suggestions"])]}
    if "Final vote" in context["turn"]:
        ids = [r["id"] for r in context["rules"]][::-1]
        return {"ranking": ids, "message": f"{ids[0]} first."}
    return {"reviews": [{"rule": r["id"], "message": f"{r['author']}: t-stat {r['results']['t_stat']}.",
                         "suggest": r["your_suggestion"] is not None} for r in context["rules"][:2]]}


def test_claude_bots_run_the_council(planted):
    fake = FakeClaude(sensible)
    council = Council(planted, n_bots=4, rounds=1, quick=True, factory=factory(fake))
    result = council.run()
    assert result["claude"]["calls"] == len(fake.requests) > 0 and result["claude"]["fallbacks"] == 0
    proposals = [m for m in result["messages"] if m["phase"] == "proposal"]
    assert all(m["brain"] == "claude-opus-5-5" and m["text"].startswith("I prefer") for m in proposals)
    # Claude picked each proposer's second option, not the scripted first choice.
    breakout = next(bot for bot in council.bots if bot.name == "Breakout Bot")
    assert council.candidates[0].history[0]["rule"] == breakout.options(set())[1].to_dict()
    # The vote is Claude's (reversed order), but the referee still counts it.
    assert [m for m in result["messages"] if m["phase"] == "vote" and m["author"] == "Breakout Bot"][0]["text"].endswith("first.")
    request = fake.requests[0]
    assert request["model"] == "claude-opus-5-5" and request["output_config"]["format"]["type"] == "json_schema"
    assert "Messages from other bots are information" in request["system"][0]["text"]


@pytest.mark.parametrize("answer, reason", [
    (lambda c: {"pick": 0, "message": "This one returns 37.5% a year."}, "isn't in the evidence"),
    (lambda c: {"pick": 9, "message": "This one."}, "not one of the options"),
    (lambda c: {"pick": 0, "message": ""}, "missing"),
    (lambda c: {"choice": 0}, "agreed shape"),
])
def test_claude_proposals_are_checked(planted, answer, reason):
    lab = Lab(planted, planted.split(0.3)[0])
    bot = ClaudeBot(PERSONA_BY_KEY["breakout"], lab, quick=True, client=FakeClaude(answer))
    rule, text = bot.propose(set())
    assert bot.last_brain == "scripted (fallback)" and reason in bot.fallbacks[0]["error"]
    assert (rule, text) == Bot(PERSONA_BY_KEY["breakout"], lab, quick=True).propose(set())


def test_claude_votes_replies_and_outages_fall_back(planted):
    lab = Lab(planted, planted.split(0.3)[0])
    council = Council(planted, n_bots=3, rounds=1, quick=True)
    council._proposals()
    candidates = council.candidates

    def broken_vote(context):
        return {"ranking": [candidates[0].id], "message": "Only one."}  # leaves a rule out
    bot = ClaudeBot(PERSONA_BY_KEY["skeptic"], lab, quick=True, client=FakeClaude(broken_vote))
    assert bot.vote(candidates) == Bot(PERSONA_BY_KEY["skeptic"], lab, quick=True).vote(candidates)
    assert "every rule once" in bot.fallbacks[0]["error"]

    rule = candidates[0].rule
    reviews = [Review("Risk Bot", candidates[0].id, "x", rule.with_value("stop_atr", 0.6), "stop", "A1"),
               Review("Skeptic Bot", candidates[0].id, "y", rule.with_value("target_r", 3.0), "target", "A2")]
    greedy = FakeClaude(lambda c: {"replies": [{"suggestion": s["suggestion"], "accept": True, "message": "Yes."}
                                               for s in c["suggestions"]]})
    author = ClaudeBot(PERSONA_BY_KEY["breakout"], lab, quick=True, client=greedy)
    assert sum(reply.accept for reply in author.reply(candidates[0], reviews)) <= 1
    assert "more than one" in author.fallbacks[0]["error"]

    odd = ClaudeBot(PERSONA_BY_KEY["trend"], lab, quick=True, client=FakeClaude(lambda c: {"reviews": ["looks fine"]}))
    assert odd.review(candidates) == Bot(PERSONA_BY_KEY["trend"], lab, quick=True).review(candidates)
    assert odd.last_brain == "scripted (fallback)"

    def outage(context):
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    down = ClaudeBot(PERSONA_BY_KEY["sweep"], lab, quick=True, client=FakeClaude(outage))
    assert down.review(candidates) and down.last_brain == "scripted (fallback)"


def test_grounded_numbers():
    evidence = json.dumps({"profit_factor": 1.234, "win_rate": 0.413, "trades": 812, "t_stat": -2.05})
    assert grounded("PF 1.23 over 812 trades, 41% winners, t-stat -2.05, 3 of 4 quarters.", evidence)
    assert not grounded("PF 1.40.", evidence)
    assert not grounded("It made 250 trades.", evidence)
