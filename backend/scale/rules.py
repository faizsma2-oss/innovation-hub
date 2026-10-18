"""Business case and benefits tracking, calculated in plain code.

Money is never estimated by the AI:
  - costs come from people (supplier quotes, internal estimates)
  - the benefit per period comes from the PILOT'S MEASURED improvement (baseline average
    minus pilot average), multiplied by inputs people give: periods per year, how many sites
    or teams it will reach, and what one unit (an hour, an error) is worth

Benefits tracking compares measurements after rollout with the baseline and the pilot:
  realised = (baseline − now) / (baseline − pilot)      for "lower is better" metrics
  ≥ 80% held · 30–80% partly held · < 30% eroded
"""

HELD, PARTLY = 0.8, 0.3
CHECKIN_MONTHS = (3, 6, 12)

# Pilots usually do better than the rollout. Each scenario = share of the pilot's saving that holds, and
# how far costs run over. "expected" is the plain calculation. The team can change these per case.
SCENARIOS = {"low": {"benefit": 0.5, "cost": 1.2}, "expected": {"benefit": 1.0, "cost": 1.0},
             "high": {"benefit": 1.2, "cost": 1.0}}


def improvements(evaluation: dict) -> list[dict]:
    """The pilot's measured improvement per period, for metrics that actually improved."""
    lines = []
    for metric in evaluation["metrics"]:
        if metric["status"] not in ("target met", "improved, target not met"):
            continue
        gain = metric["baseline_mean"] - metric["pilot_mean"]
        if metric["direction"] == "higher_better":
            gain = -gain
        lines.append({"metric_key": metric["key"], "metric": metric["metric"], "unit": metric["unit"],
                      "direction": metric["direction"], "baseline": metric["baseline_mean"],
                      "pilot": metric["pilot_mean"], "gain_per_period": round(gain, 2)})
    return lines


def business_case(inputs: dict, evaluation: dict) -> dict:
    measured = {line["metric_key"]: line for line in improvements(evaluation)}
    benefit_lines = []
    for item in inputs["benefits"]:
        line = measured.get(item["metric_key"])
        if line is None:
            continue                       # only metrics the pilot actually improved can carry a benefit
        annual = line["gain_per_period"] * item["periods_per_year"] * item["multiplier"] * item["value_per_unit"]
        benefit_lines.append(line | {k: item[k] for k in ("periods_per_year", "multiplier", "value_per_unit")}
                             | {"annual_value": round(annual, 2)})
    one_off = round(sum(c["amount"] for c in inputs["one_off"]), 2)
    yearly = round(sum(c["amount"] for c in inputs["yearly"]), 2)
    annual_benefit = round(sum(line["annual_value"] for line in benefit_lines), 2)
    net_annual = round(annual_benefit - yearly, 2)
    payback = round(one_off / net_annual * 12, 1) if net_annual > 0 else None
    settings = inputs.get("scenarios") or SCENARIOS
    return {"currency": inputs["currency"], "benefit_lines": benefit_lines, "one_off_total": one_off,
            "scenarios": {name: scenario(annual_benefit, one_off, yearly, settings[name]) for name in SCENARIOS},
            "break_even_share": break_even(annual_benefit, one_off, yearly),
            "yearly_cost_total": yearly, "annual_benefit": annual_benefit, "net_annual": net_annual,
            "payback_months": payback, "three_year_net": round(3 * net_annual - one_off, 2),
            "verdict": (f"Pays back in {payback} months" if payback is not None and payback <= 36 else
                        "Pays back, but only after three years" if payback is not None else
                        "Does not pay back: yearly costs exceed the measured benefit")}


def scenario(annual_benefit: float, one_off: float, yearly: float, factors: dict) -> dict:
    benefit = annual_benefit * factors["benefit"]
    one_off, yearly = one_off * factors["cost"], yearly * factors["cost"]
    net = benefit - yearly
    payback = round(one_off / net * 12, 1) if net > 0 else None
    return {"benefit_factor": factors["benefit"], "cost_factor": factors["cost"], "annual_benefit": round(benefit, 2),
            "one_off_total": round(one_off, 2), "yearly_cost_total": round(yearly, 2), "net_annual": round(net, 2),
            "payback_months": payback, "three_year_net": round(3 * net - one_off, 2),
            "pays_back_in_3_years": payback is not None and payback <= 36}


def break_even(annual_benefit: float, one_off: float, yearly: float) -> float | None:
    """The smallest share of the pilot's saving that still pays everything back within three years
    (costs as quoted): 3 × (share × benefit − yearly) = one-off."""
    if annual_benefit <= 0:
        return None
    return round((yearly + one_off / 3) / annual_benefit, 2)


def realised(values: dict, case: dict) -> dict:
    """How much of the pilot's improvement held after rollout, per metric and overall."""
    rows, fractions, realised_annual = [], [], 0.0
    for line in case["benefit_lines"]:
        if line["metric_key"] not in values:
            continue
        now = values[line["metric_key"]]
        gain_now = (line["baseline"] - now) if line["direction"] == "lower_better" else (now - line["baseline"])
        fraction = round(gain_now / line["gain_per_period"], 2) if line["gain_per_period"] else 0.0
        status = "held" if fraction >= HELD else "partly held" if fraction >= PARTLY else "eroded"
        fractions.append(fraction)
        realised_annual += max(fraction, 0) * line["annual_value"]
        rows.append({"metric": line["metric"], "unit": line["unit"], "baseline": line["baseline"], "pilot": line["pilot"],
                     "now": now, "realised_fraction": fraction, "status": status})
    overall = round(sum(fractions) / len(fractions), 2) if fractions else None
    verdict = (None if overall is None else "held" if overall >= HELD else "partly held" if overall >= PARTLY else "eroded")
    return {"metrics": rows, "overall_fraction": overall, "verdict": verdict,
            "realised_annual_value": round(realised_annual, 2), "currency": case["currency"]}
