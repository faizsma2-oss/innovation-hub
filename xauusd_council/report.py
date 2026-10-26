"""Writing a council meeting down: a Markdown transcript to read, and a JSON record to keep."""
import json
from pathlib import Path

from .bots import FIGURES

ROWS = ("trades", "win_rate", "avg_r", "total_r", "profit_factor", "max_drawdown_r", "t_stat", "worst_streak",
        "london_pf", "new_york_pf")
CAVEATS = """- This is a backtest. A rule that worked on past data can stop working, and often does.
- The bots tried {tested} rule variants on the training data. The more variants are tried, the likelier it \
is that the best one was luck. The holdout test reduces that risk; it doesn't remove it.
- Costs are assumed: ${spread:.2f} spread per trade and ${slippage:.2f} slippage on breakouts and stops, per \
ounce. Gold spreads widen around news and the daily rollover; use your broker's real costs (`--spread`, `--slippage`).
- Results are in R (multiples of the amount risked per trade), not money. Position size is up to you.
- The data's clock matters: sessions are cut by London and New York local time, so a CSV in broker server \
time needs the right `--tz`.
- Forward-test on a demo account before risking real money. This is not financial advice."""


def section(message: dict, rounds: int) -> str:
    phase, round_ = message["phase"], message["round"]
    if phase == "opening":
        return "Opening"
    if phase == "proposal":
        return "Proposals"
    if phase == "verdict":
        return "Holdout verdict"
    if phase == "vote" or round_ > rounds:
        return "Vote"
    return f"Debate round {round_}"


def comparison(train: dict, holdout: dict) -> list[str]:
    lines = ["| | Training (bots saw this) | Holdout (hidden until the vote) |", "|---|---:|---:|"]
    for key in ROWS:
        label, value, fmt = FIGURES[key]
        lines.append(f"| {label[0].upper() + label[1:]} | {fmt.format(value(train))} | {fmt.format(value(holdout))} |")
    return lines


def markdown(result: dict) -> str:
    data = result["data"]
    lines = [f"# XAUUSD council: {len(result['bots'])} bots, {result['rounds']} debate rounds", ""]
    if result["passed"]:
        lines += [f"**Agreed rule: {result['candidate']}, {result['short']}**", "", result["description"], ""]
        lines += comparison(result["train"], result["holdout"]) + [""]
        lines += ["The rule as data (for `Rule.from_dict`):", "", "```json", json.dumps(result["rule"], indent=2),
                  "```", ""]
    else:
        lines += ["**No rule held up on the holdout.** The council does not recommend trading any of its "
                  "candidates. The holdout results are in the verdict below.", ""]
    claude = result["claude"]
    lines += [f"- Source: {result.get('source', 'your data')}.",
              f"- Data: {data['from']} to {data['to']}, {data['timeframe_minutes']}-minute bars "
              f"({data['bars']:,} bars). Training {data['train'][0]} to {data['train'][1]}; holdout "
              f"{data['holdout'][0]} to {data['holdout'][1]}.",
              f"- Sessions: London {data['sessions']['london']}; New York {data['sessions']['new_york']}.",
              f"- Rule variants tested on the training data: {result['rules_tested']:,}."]
    if claude["calls"]:
        lines.append(f"- Claude: {claude['calls']} calls, ${claude['cost_usd']:.4f}, {claude['fallbacks']} "
                     f"turns answered by the scripted bot instead.")
    lines += ["", "## The bots", "", "| Bot | Role | Brain |", "|---|---|---|"]
    lines += [f"| {bot['name']} | {bot['role']} | {bot['brain']} |" for bot in result["bots"]]
    lines += ["", "## Votes", "", "| Rule | Proposed by | Points |", "|---|---|---:|"]
    lines += [f"| {row['candidate']}: {row['rule']} | {row['author']} | {row['points']} |" for row in result["ranking"]]

    current = None
    for message in result["messages"]:
        heading = section(message, result["rounds"])
        if heading != current:
            lines += ["", f"## {heading}", ""]
            current = heading
        who = f"**{message['author']}**"
        if message.get("to"):
            who += f" → {message['to']}"
        if message.get("candidate"):
            who += f" · {message['candidate']}"
        brain = message.get("brain", "")
        tag = f" _({brain})_" if brain not in ("scripted", "code", "") else ""
        lines.append(f"- {who}{tag}: {message['text']}")

    lines += ["", "## Caveats", "", CAVEATS.format(tested=f"{result['rules_tested']:,}", **result["costs"]), ""]
    return "\n".join(lines)


def write(result: dict, folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    transcript, record = folder / "transcript.md", folder / "result.json"
    transcript.write_text(markdown(result))
    record.write_text(json.dumps(result, indent=2, default=str))
    return transcript, record
