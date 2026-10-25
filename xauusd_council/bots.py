"""The bots: who they are, how each one judges a rule, and what they say to each other.

Every bot works from the same training data and the same backtester, but each has its own idea of a
good rule:
  - weights turn a rule's results into the bot's own score
  - gates are the checks a rule must pass before the bot will rank it highly
  - amendments are the kinds of change it suggests to other bots' rules
Proposers search their own setups for the rule that scores best by their measure. Reviewers
propose nothing: they test the others' rules and push them towards robustness.

This is the scripted brain. claude_bots.ClaudeBot gives Claude the same evidence and lets it make the
calls and write the messages; if Claude can't be used, these scripted answers stand in.
"""
from dataclasses import dataclass
from itertools import product

import numpy as np

from .board import Candidate, Reply, Review
from .rules import Rule, RuleError

MIN_TRADES = 30  # below this a rule scores -10: there's nothing to judge

# The values bots search when proposing, and the ladders they step along when suggesting changes.
GRIDS = {
    "opening_range_breakout": {"range_minutes": [15, 30, 60, 90], "buffer_atr": [0.0, 0.05, 0.1],
                               "entry_window_minutes": [120, 240]},
    "pre_session_breakout": {"buffer_atr": [0.0, 0.05, 0.1, 0.2], "entry_window_minutes": [120, 240, 360]},
    "pre_session_sweep": {"sweep_atr": [0.0, 0.05, 0.1, 0.2], "entry_window_minutes": [120, 240, 360]},
    "trend_pullback": {"ema_fast": [10, 20, 50], "ema_slow": [50, 100, 200], "entry_window_minutes": [240, 480]},
    "session_momentum": {"delay_minutes": [15, 30, 60, 120], "momentum_atr": [0.2, 0.4, 0.6, 0.8]},
    "band_reversion": {"band_period": [20, 40], "band_k": [2.0, 2.5, 3.0], "rsi_level": [20, 30],
                       "entry_window_minutes": [240, 480]},
}
STOPS = [0.15, 0.25, 0.4, 0.6]
TARGETS = [1.0, 1.5, 2.0, 3.0]
QUICK = {"grid": 2, "stops": [0.25, 0.4], "targets": [1.0, 2.0]}  # the first two values of each grid
LADDERS = {
    "range_minutes": [15, 30, 45, 60, 90, 120], "buffer_atr": [0.0, 0.05, 0.1, 0.15, 0.2, 0.3],
    "entry_window_minutes": [60, 120, 180, 240, 360, 480], "sweep_atr": [0.0, 0.05, 0.1, 0.15, 0.2, 0.3],
    "ema_fast": [5, 10, 20, 30, 50], "ema_slow": [30, 50, 100, 200, 300], "delay_minutes": [5, 15, 30, 60, 90, 120],
    "momentum_atr": [0.2, 0.3, 0.4, 0.6, 0.8, 1.0], "band_period": [10, 20, 30, 40, 60],
    "band_k": [1.5, 2.0, 2.5, 3.0, 3.5], "rsi_level": [10, 15, 20, 25, 30, 35],
    "stop_atr": [0.1, 0.15, 0.25, 0.4, 0.6, 0.8], "target_r": [0.5, 1.0, 1.5, 2.0, 3.0, 4.0],
}
TREND_EMAS = [0, 100, 300]
VOL_FILTERS = [0.0, 0.8, 1.0]

# How a setting is named in messages: label and unit.
LABELS = {
    "range_minutes": ("opening range", " min"), "buffer_atr": ("breakout buffer", " ATR"),
    "entry_window_minutes": ("entry window", " min"), "sweep_atr": ("sweep depth", " ATR"),
    "ema_fast": ("fast EMA", " bars"), "ema_slow": ("slow EMA", " bars"), "delay_minutes": ("delay", " min"),
    "momentum_atr": ("momentum threshold", " ATR"), "band_period": ("band length", " bars"),
    "band_k": ("band width", " SD"), "rsi_level": ("RSI level", ""), "stop_atr": ("stop", " ATR"),
    "target_r": ("target", "R"), "trend_ema": ("trend filter", "-bar EMA"), "vol_filter": ("volatility filter", "× median ATR"),
}

# How results are quoted: label, value, format.
FIGURES = {
    "trades": ("trades", lambda m: m["trades"], "{:d}"),
    "win_rate": ("win rate", lambda m: m["win_rate"] * 100, "{:.0f}%"),
    "avg_r": ("avg", lambda m: m["avg_r"], "{:+.2f}R"),
    "total_r": ("total", lambda m: m["total_r"], "{:+.1f}R"),
    "profit_factor": ("PF", lambda m: m["profit_factor"], "{:.2f}"),
    "max_drawdown_r": ("max drawdown", lambda m: m["max_drawdown_r"], "{:.1f}R"),
    "t_stat": ("t-stat", lambda m: m["t_stat"], "{:.2f}"),
    "worst_streak": ("worst losing streak", lambda m: m["worst_streak"], "{:d}"),
    "folds_positive": ("quarters positive", lambda m: round(m["folds_positive"] * 4), "{:d}/4"),
    "london_pf": ("London PF", lambda m: m["sessions"].get("london", {}).get("profit_factor", 0.0), "{:.2f}"),
    "new_york_pf": ("New York PF", lambda m: m["sessions"].get("new_york", {}).get("profit_factor", 0.0), "{:.2f}"),
}


def figure(key: str, m: dict) -> str:
    label, value, fmt = FIGURES[key]
    return f"{label} {fmt.format(value(m))}"


def change_of(key: str, before: dict, after: dict) -> str:
    label, value, fmt = FIGURES[key]
    return f"{label} {fmt.format(value(before))} → {fmt.format(value(after))}"


@dataclass(frozen=True)
class Persona:
    key: str
    name: str
    role: str
    opener: str
    pitch: str              # why its proposal should work, in one line
    setups: tuple           # what it proposes; empty for reviewers
    weights: dict
    gates: dict
    amendments: tuple
    focus: tuple            # the figures it quotes


PERSONAS = [
    Persona("breakout", "Breakout Bot", "Trades the first clean break after each session opens.",
            "Gold moves hardest at the London and New York opens. I want to be on board when it breaks out of its "
            "early range, not guessing before.",
            "When gold breaks its early range, the move tends to carry.",
            ("opening_range_breakout", "pre_session_breakout"), {"t": 1.0, "recovery": 0.5, "pf": 0.5},
            {"min_trades": 80, "min_pf": 1.05}, ("target",), ("avg_r", "profit_factor", "t_stat")),
    Persona("sweep", "Sweep Bot", "Fades false breaks of the pre-session range.",
            "Gold loves to run the stops just past the Asian high or low, then snap back. I trade the snap-back.",
            "Stop runs past the pre-session range often reverse.",
            ("pre_session_sweep",), {"pf": 1.0, "win": 0.5, "t": 0.5},
            {"min_trades": 60, "min_pf": 1.1}, ("window",), ("win_rate", "profit_factor", "avg_r")),
    Persona("skeptic", "Skeptic Bot", "Asks whether an edge is real or luck.",
            "I don't propose rules. I check that a result isn't luck: enough trades, a t-stat above 2, profits in "
            "most quarters, settings that aren't a lucky spike, and a clear win over simply buying every open.",
            "", (), {"t": 1.2, "consistency": 0.8},
            {"min_trades": 100, "min_t": 2.0, "min_folds": 0.75, "beats_baseline": 0.03}, ("plateau",),
            ("t_stat", "folds_positive", "trades")),
    Persona("trend", "Trend Bot", "Joins the intraday trend on pullbacks.",
            "Gold trends for weeks. Inside a session I join the trend on a pullback instead of chasing it.",
            "Pullbacks to the fast EMA in a trend give a good price with the trend behind you.",
            ("trend_pullback",), {"t": 1.0, "recovery": 0.5, "consistency": 0.5},
            {"min_trades": 80, "min_pf": 1.05, "min_folds": 0.5}, ("trend_filter",), ("avg_r", "t_stat", "folds_positive")),
    Persona("risk", "Risk Bot", "Cares about drawdowns and losing streaks.",
            "A rule is only tradable if you can live through its worst stretch. I look at drawdown, losing streaks "
            "and return per unit of pain.",
            "", (), {"recovery": 1.2, "t": 0.4, "pf": 0.4},
            {"min_recovery": 2.0, "max_streak": 12}, ("stop", "target"), ("total_r", "max_drawdown_r", "worst_streak")),
    Persona("momentum", "Momentum Bot", "Follows big pre-session moves into the session.",
            "When gold has already moved a lot before a session opens, the big players are usually still pushing. "
            "I follow.",
            "A big move before the open tends to keep going after it.",
            ("session_momentum",), {"t": 0.8, "pf": 0.6, "recovery": 0.4},
            {"min_trades": 60, "min_pf": 1.05}, ("vol_filter",), ("avg_r", "profit_factor", "trades")),
    Persona("session", "Session Bot", "Makes sure a rule works in both London and New York.",
            "The brief is one rule for London and New York. A rule that only works in one of them isn't the "
            "answer, so I check each session on its own.",
            "", (), {"sessions": 1.2, "t": 0.6, "consistency": 0.4},
            {"session_pf": 1.05, "min_session_trades": 30}, ("neighbours",), ("london_pf", "new_york_pf", "t_stat")),
    Persona("reversion", "Reversion Bot", "Fades stretched moves back towards the mean.",
            "Most intraday spikes in gold get partly retraced. I fade the stretch and take profit quickly.",
            "Closes outside the bands with RSI stretched tend to snap back.",
            ("band_reversion",), {"win": 0.6, "pf": 0.8, "t": 0.4},
            {"min_trades": 60, "min_pf": 1.1}, ("target",), ("win_rate", "profit_factor", "avg_r")),
]
PERSONA_BY_KEY = {persona.key: persona for persona in PERSONAS}
MAX_BOTS = 20


def roster(n: int) -> list[tuple[Persona, int]]:
    """The first n bots: each persona once, then more proposers with their own variants."""
    if not 2 <= n <= MAX_BOTS:
        raise ValueError(f"the council needs 2 to {MAX_BOTS} bots")
    picks = [(persona, 1) for persona in PERSONAS]
    proposers = [persona for persona in PERSONAS if persona.setups]
    number = 2
    while len(picks) < n:
        picks += [(persona, number) for persona in proposers]
        number += 1
    return picks[:n]


# ── Judging a rule ───────────────────────────────────────────────────────────

def clip(value: float, low: float, high: float) -> float:
    return float(min(max(value, low), high))


def score_parts(m: dict) -> dict:
    sessions_pf = [s["profit_factor"] for s in m["sessions"].values()]
    return {
        "t": clip(m["t_stat"], -5, 8),
        "pf": clip((m["profit_factor"] - 1) * 5, -5, 5),
        "recovery": clip(m["total_r"] / max(m["max_drawdown_r"], 1.0) / 2, -5, 5),
        "consistency": m["folds_positive"] * 3,
        "sessions": clip((min(sessions_pf) - 1) * 5, -5, 5) if len(sessions_pf) == 2 else -5.0,
        "win": clip((m["win_rate"] - 0.5) * 10, -5, 5),
    }


def check(gate: str, limit, m: dict, baseline: dict | None) -> str | None:
    """None if the rule passes the gate, else what's wrong, in words."""
    sessions = m["sessions"]
    if gate == "min_trades" and m["trades"] < limit:
        return f"only {m['trades']} trades (I want {limit}+)"
    if gate == "min_pf" and m["profit_factor"] < limit:
        return f"PF {m['profit_factor']:.2f} is below my minimum of {limit:.2f}"
    if gate == "min_t" and m["t_stat"] < limit:
        return f"a t-stat of {m['t_stat']:.2f} could easily be luck (I want {limit:.1f}+)"
    if gate == "min_folds" and m["folds_positive"] < limit:
        return f"only {round(m['folds_positive'] * 4)}/4 quarters of the training period were profitable"
    if gate == "beats_baseline" and baseline is not None and m["avg_r"] - baseline["avg_r"] < limit:
        return (f"avg {m['avg_r']:+.2f}R barely beats simply buying every session open with the same stop and "
                f"target ({baseline['avg_r']:+.2f}R)")
    if gate == "min_recovery":
        recovery = m["total_r"] / max(m["max_drawdown_r"], 1.0)
        if recovery < limit:
            return (f"it made {m['total_r']:+.1f}R but drew down {m['max_drawdown_r']:.1f}R on the way "
                    f"(return/drawdown {recovery:.2f}, I want {limit:.1f}+)")
    if gate == "max_streak" and m["worst_streak"] > limit:
        return f"a losing streak of {m['worst_streak']} trades is hard to sit through (my limit is {limit})"
    if gate == "session_pf":
        weak = [(name, s["profit_factor"]) for name, s in sessions.items() if s["profit_factor"] < limit]
        weak += [(name, 0.0) for name in ("london", "new_york") if name not in sessions]
        if weak:
            names = {"london": "London", "new_york": "New York"}
            return " and ".join(f"{names[name]} PF is {pf:.2f}" for name, pf in weak) + f" (I want {limit:.2f}+ in both)"
    if gate == "min_session_trades":
        thin = [name for name in ("london", "new_york") if sessions.get(name, {}).get("trades", 0) < limit]
        if thin:
            return f"too few trades in {' and '.join({'london': 'London', 'new_york': 'New York'}[n] for n in thin)}"
    return None


def step(value, ladder: list, direction: int):
    lower, higher = [v for v in ladder if v < value], [v for v in ladder if v > value]
    if direction < 0:
        return max(lower) if lower else None
    return min(higher) if higher else None


def neighbours(rule: Rule, names: list | None = None) -> list[Rule]:
    """Rules one step away along each setting's ladder."""
    names = names or [name for name, _ in rule.params] + ["stop_atr", "target_r"]
    found = []
    for name in names:
        for direction in (-1, 1):
            value = step(rule.value(name), LADDERS[name], direction)
            if value is None:
                continue
            try:
                found.append(rule.with_value(name, value))
            except RuleError:
                continue
    return found


def describe_change(before: Rule, after: Rule) -> str:
    old, new = before.to_dict(), after.to_dict()
    parts = []
    for name in list(old["params"]) + ["stop_atr", "target_r", "trend_ema", "vol_filter"]:
        a = old["params"].get(name, old.get(name))
        b = new["params"].get(name, new.get(name))
        if a != b:
            label, unit = LABELS[name]
            show = (lambda v: "off" if not v else f"{v}{unit}") if name in ("trend_ema", "vol_filter") else (lambda v: f"{v}{unit}")
            parts.append(f"{label} {show(a)} → {show(b)}")
    return ", ".join(parts) or "no change"


# ── A bot ────────────────────────────────────────────────────────────────────

class Bot:
    brain = "scripted"

    def __init__(self, persona: Persona, lab, number: int = 1, quick: bool = False):
        self.persona = persona
        self.lab = lab
        self.number = number
        self.quick = quick
        self.name = persona.name if number == 1 else f"{persona.name} {number}"
        self.meter: list = []
        self.fallbacks: list = []

    @property
    def proposes(self) -> bool:
        return bool(self.persona.setups)

    def score(self, rule: Rule) -> float:
        m = self.lab.test(rule)
        if m["trades"] < MIN_TRADES:
            return -10.0
        parts = score_parts(m)
        return round(sum(weight * parts[name] for name, weight in self.persona.weights.items()), 3)

    def failures(self, rule: Rule) -> list[str]:
        m = self.lab.test(rule)
        baseline = self.lab.baseline(rule) if "beats_baseline" in self.persona.gates else None
        found = [check(gate, limit, m, baseline) for gate, limit in self.persona.gates.items()]
        return [text for text in found if text]

    def rank_key(self, rule: Rule) -> tuple:
        return (not self.failures(rule), self.score(rule))

    def quote(self, rule: Rule) -> str:
        m = self.lab.test(rule)
        return ", ".join(figure(key, m) for key in self.persona.focus)

    def compare(self, before: Rule, after: Rule) -> str:
        a, b = self.lab.test(before), self.lab.test(after)
        return ", ".join(change_of(key, a, b) for key in self.persona.focus)

    # ── Proposing ────────────────────────────────────────────────────────────

    def options(self, taken: set) -> list[Rule]:
        """Every version of this bot's setups it would consider, best first by its own measure.
        Entries another bot already put forward are skipped, so a second bot of a kind finds its own idea."""
        rules = []
        stops, targets = (QUICK["stops"], QUICK["targets"]) if self.quick else (STOPS, TARGETS)
        for setup in self.persona.setups:
            grid = GRIDS[setup]
            values = [grid[name][:QUICK["grid"]] if self.quick else grid[name] for name in grid]
            for combo, stop, target in product(product(*values), stops, targets):
                try:
                    rule = Rule.make(setup, **dict(zip(grid, combo)), stop_atr=stop, target_r=target)
                except RuleError:
                    continue
                if (rule.setup, rule.params) not in taken:
                    rules.append(rule)
        return sorted(rules, key=self.rank_key, reverse=True)

    def propose(self, taken: set) -> tuple[Rule, str] | None:
        options = self.options(taken)
        if not options:
            return None
        rule = options[0]
        return rule, self._proposal_text(rule, len(options))

    def _proposal_text(self, rule: Rule, tested: int) -> str:
        text = (f"{self.persona.pitch} My pick from the {tested} versions of my setups I tested is "
                f"{rule.short()}: {self.quote(rule)}.")
        problems = self.failures(rule)
        if problems:
            text += f" To be honest it misses one of my own checks: {problems[0]}."
        return text

    # ── Reviewing the others' rules ──────────────────────────────────────────

    def to_review(self, candidates: list[Candidate], limit: int = 3) -> list[Candidate]:
        """The rules this bot looks at this round: the strongest by its own measure, not its own."""
        others = [c for c in candidates if c.status == "active" and c.author != self.name]
        return sorted(others, key=lambda c: self.rank_key(c.rule), reverse=True)[:limit]

    def suggestion(self, rule: Rule) -> tuple[Rule, float, float] | None:
        """The change this bot would make to a rule, if one helps enough by its own measure.
        Returns (amended rule, score before, score after)."""
        before = self.score(rule)
        options = []
        for kind in self.persona.amendments:
            if kind == "plateau":
                best = self.plateau(rule)
                if best != rule:
                    return best, self.smoothed(rule), self.smoothed(best)
                continue
            options += self.variants(rule, kind)
        if not options:
            return None
        best = max(options, key=self.rank_key)
        after = self.score(best)
        if after >= before + max(0.05 * abs(before), 0.1) and len(self.failures(best)) <= len(self.failures(rule)):
            return best, before, after
        return None

    def variants(self, rule: Rule, kind: str) -> list[Rule]:
        if kind == "stop":
            return neighbours(rule, ["stop_atr"])
        if kind == "target":
            return neighbours(rule, ["target_r"])
        if kind == "window":
            return neighbours(rule, ["entry_window_minutes"]) if "entry_window_minutes" in dict(rule.params) else []
        if kind == "trend_filter":
            return [rule.with_value("trend_ema", v) for v in TREND_EMAS if v != rule.trend_ema]
        if kind == "vol_filter":
            return [rule.with_value("vol_filter", v) for v in VOL_FILTERS if v != rule.vol_filter]
        if kind == "neighbours":
            return neighbours(rule)
        raise ValueError(kind)

    def smoothed(self, rule: Rule) -> float:
        """The average score of a rule and its one-step neighbours. A lucky spike scores well alone,
        but not here."""
        scores = [self.score(rule)] + [self.score(other) for other in neighbours(rule)]
        return round(float(np.mean(scores)), 3)

    def plateau(self, rule: Rule) -> Rule:
        best = max([rule] + neighbours(rule), key=self.smoothed)
        return best if self.smoothed(best) >= self.smoothed(rule) + 0.1 else rule

    def review(self, candidates: list[Candidate]) -> list[Review]:
        """Comments on the strongest rules. A plain "passes my checks" is only said about my favourite."""
        reviews = []
        for place, candidate in enumerate(self.to_review(candidates)):
            review = self.review_one(candidate)
            if review.amendment is not None or not review.text.startswith("Passes") or place == 0:
                reviews.append(review)
        return reviews

    def review_one(self, candidate: Candidate) -> Review:
        rule = candidate.rule
        problems = self.failures(rule)
        if "plateau" in self.persona.amendments:
            spike = self.score(rule) - self.smoothed(rule)
            if spike > max(1.0, 0.5 * abs(self.score(rule))):
                problems.append(f"its settings look like a lucky spike: one step either way averages "
                                f"{self.smoothed(rule):.2f} on my measure against {self.score(rule):.2f}")
        found = self.suggestion(rule)
        parts = []
        if problems:
            parts.append("; ".join(problems) + ".")
        if found:
            amended, before, after = found
            change = describe_change(rule, amended)
            measure = "my smoothed measure" if "plateau" in self.persona.amendments else "my measure"
            parts.append(f"{'Suggestion' if problems else 'It passes my checks. One improvement'}: {change}. "
                         f"On {measure} it goes from {before:.2f} to {after:.2f} ({self.compare(rule, amended)}).")
            return Review(self.name, candidate.id, " ".join(parts), amended, change)
        if problems:
            return Review(self.name, candidate.id, " ".join(parts))
        return Review(self.name, candidate.id, f"Passes all my checks: {self.quote(rule)}.")

    # ── Answering suggestions about my own rule ──────────────────────────────

    def reply(self, candidate: Candidate, reviews: list[Review]) -> list[Reply]:
        """Accept the one suggestion that helps most by my own measure (if any), and say why not to the rest."""
        before = self.score(candidate.rule)
        rated = [(review, self.score(review.amendment), self.failures(review.amendment)) for review in reviews]
        own_failures = len(self.failures(candidate.rule))
        good = [item for item in rated
                if item[1] >= before + max(0.02 * abs(before), 0.05) and len(item[2]) <= own_failures]
        chosen = max(good, key=lambda item: item[1])[0] if good else None
        replies = []
        for review, after, failures in rated:
            if review is chosen:
                text = (f"Accepted {review.critic}'s change ({review.change}): my measure goes from {before:.2f} to "
                        f"{after:.2f} ({self.compare(candidate.rule, review.amendment)}).")
            elif review in [item[0] for item in good]:
                text = (f"{review.critic}'s change ({review.change}) helps too ({before:.2f} → {after:.2f}), but "
                        f"{chosen.critic}'s helps more, and I take one change a round.")
            elif len(failures) > own_failures:
                text = f"Rejected {review.critic}'s change ({review.change}): it would fail my check: {failures[0]}."
            else:
                text = (f"Rejected {review.critic}'s change ({review.change}): my measure would go from {before:.2f} "
                        f"to {after:.2f} ({self.compare(candidate.rule, review.amendment)}).")
            replies.append(Reply(review.id, review is chosen, text))
        return replies

    # ── Changing my mind ─────────────────────────────────────────────────────

    def reconsider(self, own: Candidate, candidates: list[Candidate]) -> tuple[str, str] | None:
        """Withdraw my rule and back another if, by my own measure, another is clearly better."""
        others = [c for c in candidates if c.status == "active" and c.id != own.id]
        if not others:
            return None
        best = max(others, key=lambda c: self.rank_key(c.rule))
        mine, theirs = self.score(own.rule), self.score(best.rule)
        my_problems, their_problems = self.failures(own.rule), self.failures(best.rule)
        if (my_problems and not their_problems) or (theirs > mine + max(0.15 * abs(mine), 0.2) and
                                                     len(their_problems) <= len(my_problems)):
            text = f"I withdraw {own.id}. By my own measure {best.id} is better ({theirs:.2f} against {mine:.2f})"
            if my_problems:
                text += f", and {own.id} fails my check: {my_problems[0]}"
            return best.id, text + f". I back {best.id}."
        return None

    # ── Voting ───────────────────────────────────────────────────────────────

    def vote(self, candidates: list[Candidate]) -> tuple[list[str], str]:
        active = [c for c in candidates if c.status == "active"]
        ranked = sorted(active, key=lambda c: self.rank_key(c.rule), reverse=True)
        top = ranked[0]
        text = f"My ranking: {', '.join(c.id for c in ranked)}. {top.id} scores {self.score(top.rule):.2f} on my measure ({self.quote(top.rule)})."
        failing = [c.id for c in ranked if self.failures(c.rule)]
        if failing and len(failing) == len(ranked):
            text += f" None of them passes all my checks; {top.id}'s problem: {self.failures(top.rule)[0]}."
        elif failing:
            text += f" {', '.join(failing)} {'fails' if len(failing) == 1 else 'fail'} my checks."
        return [c.id for c in ranked], text


def make_bots(n: int, lab, quick: bool = False, factory=None) -> list[Bot]:
    factory = factory or Bot
    return [factory(persona, lab, number, quick) for persona, number in roster(n)]
