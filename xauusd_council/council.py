"""The council: N bots propose, argue about and vote on one XAUUSD rule for London and New York.

1. Opening: the referee sets out the brief and the data; each bot says what it cares about.
2. Proposals: each proposer searches its own setups on the training data and puts its best rule forward.
3. Debate rounds: the referee posts every rule's results. Each bot reviews the strongest rules and may
   suggest a change. Each author accepts the change that helps most by its own measure, or says why
   not. Then any bot whose rule is clearly beaten withdraws it and backs another.
4. Vote: every bot ranks the remaining rules, and the ranks are added up (a Borda count).
5. Verdict: the referee tests the top rules, in vote order, on the holdout period the bots never saw.
   The first that holds up is the council's rule. If none does, the council says so. Holding up means
   at least 30 trades, a profit factor of 1.1 or more, a t-stat of 2 or more (so the profit is unlikely
   to be luck) and money made in both London and New York.

The referee is plain code, not a bot: it runs every test, keeps the holdout, and counts the votes.
"""
from .backtest import Costs, Lab
from .board import Board, Candidate, Message
from .bots import figure, make_bots
from .market import Market, SESSIONS, day_label

HOLDOUT_GATE = {"min_trades": 30, "min_pf": 1.1, "min_t": 2.0}  # and each session must make money on average
HOLDOUT_TRIES = 3   # the vote's top three get a holdout test, in order; trying more would be fishing
REFEREE = "Referee"


class Council:
    def __init__(self, market: Market, n_bots: int = 5, rounds: int = 2, holdout: float = 0.3,
                 costs: Costs = Costs(), factory=None, quick: bool = False, listener=None):
        if rounds < 1:
            raise ValueError("the council needs at least one debate round")
        self.market = market
        train, test = market.split(holdout)
        self.train = Lab(market, train, costs)
        self.holdout = Lab(market, test, costs)  # only the referee reads this, and only in _verdict
        self.costs = costs
        self.rounds = rounds
        self.board = Board()
        if listener:
            self.board.listeners.append(listener)
        self.bots = make_bots(n_bots, self.train, quick, factory)
        for bot in self.bots:
            bot.board = self.board  # Claude bots read what was just said
        self.candidates: list[Candidate] = []

    def bot(self, name: str):
        return next(bot for bot in self.bots if bot.name == name)

    def active(self) -> list[Candidate]:
        return [c for c in self.candidates if c.status == "active"]

    def say(self, phase: str, round_: int, author: str, text: str, bot=None, brain: str = "", **extra) -> Message:
        brain = brain or (getattr(bot, "last_brain", bot.brain) if bot else "code")
        return self.board.post(Message(phase, round_, author, text, brain=brain, **extra))

    # ── The meeting ──────────────────────────────────────────────────────────

    def run(self) -> dict:
        self._opening()
        self._proposals()
        if not self.candidates:
            raise RuntimeError("no bot could propose a rule (are there any proposers among the bots?)")
        for round_ in range(1, self.rounds + 1):
            self._debate(round_)
        ballots, tally = self._vote()
        chosen, tried = self._verdict(tally)
        return self._result(ballots, tally, chosen, tried)

    def _opening(self):
        (start, end), (h_start, h_end) = self.train.period, self.holdout.period
        self.say("opening", 0, REFEREE,
                 f"The brief: agree one rule for trading XAUUSD in the London and New York sessions. "
                 f"Data: {day_label(self.market.days[0])} to {day_label(self.market.days[-1])}, "
                 f"{self.market.bar_minutes}-minute bars. You may test rules on {day_label(start)} to {day_label(end)} "
                 f"({self.train.trading_days} trading days). I keep {day_label(h_start)} to {day_label(h_end)} "
                 f"({self.holdout.trading_days} days) hidden until the vote is over. Every trade pays "
                 f"${self.costs.spread:.2f} spread, and breakouts and stops pay ${self.costs.slippage:.2f} slippage, per ounce.")
        for bot in self.bots:
            self.say("opening", 0, bot.name, bot.persona.opener, bot, brain="scripted")

    def _proposals(self):
        taken = set()
        for bot in self.bots:
            if not bot.proposes:
                continue
            proposal = bot.propose(taken)
            if not proposal:
                continue
            rule, text = proposal
            candidate = Candidate(f"C{len(self.candidates) + 1}", bot.name, rule)
            candidate.history.append({"version": 1, "rule": rule.to_dict(), "change": "proposed"})
            self.candidates.append(candidate)
            taken.add((rule.setup, rule.params))
            self.say("proposal", 0, bot.name, text, bot, candidate=candidate.id)

    def _results(self, round_: int):
        for c in self.active():
            m = self.train.test(c.rule)
            base = self.train.baseline(c.rule)
            figures = ", ".join(figure(key, m) for key in ("trades", "win_rate", "avg_r", "profit_factor",
                                                             "max_drawdown_r", "t_stat", "london_pf", "new_york_pf",
                                                             "folds_positive"))
            self.say("results", round_, REFEREE,
                     f"{c.id} v{c.version} ({c.author}) {c.rule.short()}: {figures}. Buying every open with the same "
                     f"stop and target: avg {base['avg_r']:+.2f}R.", candidate=c.id)

    def _debate(self, round_: int):
        self._results(round_)
        suggestions: dict[str, list] = {}
        count = 0
        for bot in self.bots:
            for review in bot.review(self.active()):
                candidate = next(c for c in self.candidates if c.id == review.candidate)
                if review.amendment is not None:
                    count += 1
                    review.id = f"A{round_}.{count}"
                    suggestions.setdefault(candidate.id, []).append(review)
                self.say("review", round_, bot.name, review.text, bot, to=candidate.author, candidate=candidate.id)

        for candidate in self.active():
            reviews = suggestions.get(candidate.id)
            if not reviews:
                continue
            author = self.bot(candidate.author)
            by_id = {review.id: review for review in reviews}
            for reply in author.reply(candidate, reviews):
                review = by_id[reply.amendment]
                self.say("reply", round_, author.name, reply.text, author, to=review.critic, candidate=candidate.id)
                if reply.accept:
                    candidate.amend(review.amendment, f"{review.change} (suggested by {review.critic})")

        for bot in self.bots:
            own = next((c for c in self.active() if c.author == bot.name), None)
            if own is None:
                continue
            decision = bot.reconsider(own, self.active())
            if decision:
                backed, text = decision
                own.status = "withdrawn"
                self.say("withdrawal", round_, bot.name, text, bot, candidate=own.id, to=self._author(backed))

    def _author(self, candidate_id: str) -> str:
        return next(c.author for c in self.candidates if c.id == candidate_id)

    def _vote(self) -> tuple[dict, list]:
        self._results(self.rounds + 1)
        active = self.active()
        points = {c.id: 0 for c in active}
        ballots = {}
        for bot in self.bots:
            ranking, text = bot.vote(active)
            ballots[bot.name] = ranking
            for place, cid in enumerate(ranking):
                points[cid] += len(ranking) - place
            self.say("vote", self.rounds + 1, bot.name, text, bot)
        tally = sorted(active, key=lambda c: (points[c.id], self.train.test(c.rule)["t_stat"]), reverse=True)
        self.say("vote", self.rounds + 1, REFEREE,
                 "The count (points from every ballot): " + ", ".join(f"{c.id} {points[c.id]}" for c in tally) + ".")
        return ballots, [(c, points[c.id]) for c in tally]

    def _verdict(self, tally: list) -> tuple[Candidate | None, list]:
        tried = []
        for candidate, _ in tally[:HOLDOUT_TRIES]:
            m = self.holdout.test(candidate.rule)
            problems = holdout_problems(m)
            tried.append({"candidate": candidate.id, "metrics": m, "problems": problems})
            figures = ", ".join(figure(key, m) for key in ("trades", "win_rate", "avg_r", "profit_factor",
                                                             "max_drawdown_r", "t_stat", "london_pf", "new_york_pf"))
            outcome = "It holds up." if not problems else "It fails: " + "; ".join(problems) + "."
            self.say("verdict", self.rounds + 2, REFEREE,
                     f"Holdout test of {candidate.id} ({day_label(self.holdout.period[0])} to "
                     f"{day_label(self.holdout.period[1])}, never seen by the bots): {figures}. {outcome}",
                     candidate=candidate.id)
            if not problems:
                self.say("verdict", self.rounds + 2, REFEREE,
                         f"The council's rule is {candidate.id}, proposed by {candidate.author}: "
                         f"{candidate.rule.describe()}", candidate=candidate.id)
                return candidate, tried
        self.say("verdict", self.rounds + 2, REFEREE,
                 f"None of the top {len(tried)} rules held up on data the bots hadn't seen. The council does not "
                 f"recommend trading any of them. Try more data, different costs or more bots, and treat any "
                 f"rule that only works on the training years as luck.")
        return None, tried

    # ── The record ───────────────────────────────────────────────────────────

    def _result(self, ballots: dict, tally: list, chosen: Candidate | None, tried: list) -> dict:
        meter = [entry for bot in self.bots for entry in bot.meter]
        fallbacks = [entry for bot in self.bots for entry in bot.fallbacks]
        return {
            "passed": chosen is not None,
            "rounds": self.rounds,
            "candidate": chosen.id if chosen else None,
            "rule": chosen.rule.to_dict() if chosen else None,
            "short": chosen.rule.short() if chosen else None,
            "description": chosen.rule.describe() if chosen else None,
            "train": self.train.test(chosen.rule) if chosen else None,
            "holdout": next(t["metrics"] for t in tried if t["candidate"] == chosen.id) if chosen else None,
            "holdout_tested": tried,
            "ranking": [{"candidate": c.id, "author": c.author, "points": points, "rule": c.rule.short()} for c, points in tally],
            "ballots": ballots,
            "candidates": [{"id": c.id, "author": c.author, "status": c.status, "version": c.version,
                            "rule": c.rule.to_dict(), "short": c.rule.short(), "train": self.train.test(c.rule),
                            "history": c.history} for c in self.candidates],
            "bots": [{"name": bot.name, "persona": bot.persona.key, "role": bot.persona.role, "brain": bot.brain}
                     for bot in self.bots],
            "data": {"from": day_label(self.market.days[0]), "to": day_label(self.market.days[-1]),
                     "timeframe_minutes": self.market.bar_minutes, "bars": len(self.market.bars),
                     "train": [day_label(d) for d in self.train.period],
                     "holdout": [day_label(d) for d in self.holdout.period],
                     "sessions": {name: f"{s.open_minute // 60:02d}:00-{s.close_minute // 60:02d}:00 {s.tz}"
                                  for name, s in SESSIONS.items()}},
            "costs": {"spread": self.costs.spread, "slippage": self.costs.slippage},
            "rules_tested": self.train.tested,
            "claude": {"calls": len(meter), "cost_usd": round(sum(e.get("cost_usd", 0) for e in meter), 4),
                       "fallbacks": len(fallbacks), "fallback_reasons": [f.get("error", "") for f in fallbacks]},
            "messages": [message.to_dict() for message in self.board.messages],
        }


def holdout_problems(m: dict) -> list[str]:
    problems = []
    if m["trades"] < HOLDOUT_GATE["min_trades"]:
        problems.append(f"only {m['trades']} trades")
    if m["profit_factor"] < HOLDOUT_GATE["min_pf"]:
        problems.append(f"PF {m['profit_factor']:.2f} is below {HOLDOUT_GATE['min_pf']:.2f}")
    if m["t_stat"] < HOLDOUT_GATE["min_t"]:
        problems.append(f"a t-stat of {m['t_stat']:.2f} is below {HOLDOUT_GATE['min_t']:.1f}, so the result could be luck")
    for name, session in SESSIONS.items():
        s = m["sessions"].get(name)
        if not s:
            problems.append(f"no {session.label} trades")
        elif s["avg_r"] <= 0:
            problems.append(f"{session.label} lost money (avg {s['avg_r']:+.2f}R over {s['trades']} trades)")
    return problems

