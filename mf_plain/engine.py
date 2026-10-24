"""Turns a Portfolio into a plain-language Report.

Pipeline: per-fund translators -> sections -> per-area scorecard and fund verdict ->
portfolio mix -> area cards -> headline -> flags. Deterministic and auditable: an LLM
(if you add one later) should only re-word `Insight.sentence`, never create or change numbers.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from .benchmarks import benchmark_tests_apply
from .facts import FACT_TOPICS, fund_facts
from .glossary import GLOSSARY
from .models import (Card, FundSummary, Insight, Portfolio, Report, ScoreItem, Section,
                     Thresholds, Weights)
from .translators import (FUND_TRANSLATORS, INDEX_SKIPPED, capture_obs_too_few, history_too_short,
                          mix_insights)

SCORE = {"good": 1, "ok": 0, "watch": -1, "attention": -2}
SEVERITY = {"attention": 3, "watch": 2, "ok": 1, "good": 0}
STATUS_WORD = {"good": "Strong", "ok": "Fine", "watch": "Look closer", "attention": "Needs attention",
               "na": "No data"}

# Display areas: (key, title, [insight topics shown inside it, in order])
AREAS = [
    ("returns", "Returns", ["returns", "calendar", "consistency"]),
    ("risk", "Risk", ["capture", "risk"]),
    ("peers", "Ranking in category", ["peers"]),
    ("costs", "Costs", ["costs"]),
]
PORTFOLIO_AREAS = [("mix", "Portfolio mix", ["mix"])]

SECTIONS = {
    "returns": ("Growth over 1, 3 and 5 years",
                "How fast your money grew each year on average, compared with the market index."),
    "calendar": ("Year by year",
                 "How the fund did in each calendar year, and by how much it finished ahead of or behind the benchmark (its alpha)."),
    "consistency": ("Across every start date",
                    "How often it beat the index if you had started on any day, not just one lucky day."),
    "capture": ("In rising and falling markets",
                "How much of the market's gains and losses this fund took part in."),
    "risk": ("The worst fall",
             "How far the fund dropped in its worst fall, and how long it took to come back."),
    "peers": ("Ranking in its category",
              "How it ranks against funds of the same type. Q1 is the best quarter of the list, Q4 the worst."),
    "costs": ("What you pay", "What the fund charges you every year, compared with the middle fund in its category."),
    "riskometer": ("Official risk level",
                   "The risk label the fund house must publish, on a six-step scale from Low to Very High."),
    "size": ("Fund size", "How much money the fund manages in total."),
    "age": ("Track record", "How long the fund has existed."),
    "manager": ("Fund manager", "Who runs the fund, and since when."),
    "exit": ("Exit load", "A charge some funds take if you sell within a set time."),
    "mix": ("How your money is spread", "Whether too much of your money rides on one fund or one type of fund."),
}

GAP_TEXT = {
    "returns_insight": "growth over 1, 3 and 5 years",
    "calendar_insight": "year-by-year returns",
    "rolling_insight": "rolling-return consistency",
    "capture_insight": "upside and downside capture",
    "drawdown_insight": "worst-fall comparison",
    "quartile_insight": "quartile ranking in its category",
    "cost_insight": "charges (TER)",
}

# Tests that compare a fund with its benchmark: skipped, with a note, where the benchmark would mislead
BENCH_TESTS = {"returns_insight", "calendar_insight", "rolling_insight", "capture_insight", "drawdown_insight"}

CREDITS = ("Fund data: AMFI, compiled by TigZig MFPRO (Amar Harolikar), released under CC0. "
           "This report is not affiliated with or endorsed by AMFI or TigZig.")

DISCLAIMER = (
    "This report describes how your funds have behaved in the past using the data shown. "
    "Past performance does not guarantee future results. It is general information and "
    "observations to discuss, not personal investment advice or a recommendation to buy, "
    "sell or switch any fund. Please speak to a registered adviser before acting on it."
)


def group_score(insights: list[Insight], w: Optional[Weights] = None) -> Optional[float]:
    """Weighted mean score of a group of findings (None when there is nothing to weigh)."""
    fw = (w or Weights()).findings
    pairs = [(SCORE[i.status], fw.get(i.topic, 1.0)) for i in insights]
    tot = sum(x for _, x in pairs)
    if not pairs or tot <= 0:
        return None
    return sum(sc * x for sc, x in pairs) / tot


def status_from_score(m: Optional[float]) -> str:
    if m is None:
        return "na"
    if m >= 0.5:
        return "good"
    if m > -0.5:
        return "ok"
    if m > -1.5:
        return "watch"
    return "attention"


def group_status(insights: list[Insight], w: Optional[Weights] = None) -> str:
    """One status for a group of findings: the weighted average, so one outlier doesn't decide it alone."""
    return status_from_score(group_score(insights, w))


def _worst(insights: list[Insight]) -> Insight:
    return max(insights, key=lambda i: SEVERITY[i.status])


def _fund_verdict(insights: list[Insight], w: Optional[Weights] = None,
                  min_perf: int = 2) -> tuple[str, str]:
    """Verdict = weighted mean of the AREA scores (area weight 0 = shown but not counted).

    Worth a closer look when that mean is below 0, any finding is attention, or two
    or more findings are watch. One watch stays on the fund and does not change the label.
    """
    if not insights:
        return "Not enough data", "ok"
    w = w or Weights()
    worst = _worst(insights)
    counted = {k: w.areas.get(k, 1.0) for k, _, _ in AREAS}
    perf = [i for k, _, ts in AREAS if counted[k] > 0 and k != "costs" for i in insights if i.topic in ts]  # cost alone is not performance evidence
    if len(perf) < min_perf and SEVERITY[worst.status] < SEVERITY["watch"]:
        return "Limited data", "ok"
    num = den = 0.0
    for k, _, ts in AREAS:
        if counted[k] <= 0:
            continue
        sc = group_score([i for i in insights if i.topic in ts], w)
        if sc is not None:
            num += sc * counted[k]
            den += counted[k]
    mean = num / den if den else 0
    watches = sum(1 for i in insights if i.status == "watch")
    any_attention = any(i.status == "attention" for i in insights)
    if mean <= -1.0:
        return "Needs attention", "attention"
    if mean < 0 or any_attention or watches >= 2:
        return "Worth a closer look", "watch"
    if mean >= 0.5:
        return "Doing well", "good"
    return "On track", "ok"


def _sections(insights: list[Insight], topics: list[str]) -> list[Section]:
    out = []
    for t in topics:
        items = [i for i in insights if i.topic == t]
        if items:
            title, what = SECTIONS[t]
            out.append(Section(topic=t, title=title, what=what, insights=items))
    return out


def _fund_card_status(insights: list[Insight]) -> str:
    """Card status over several funds: red only when the problem is widespread."""
    worst = _worst(insights).status
    bad = sum(1 for i in insights if i.status in ("watch", "attention"))
    n_att = sum(1 for i in insights if i.status == "attention")
    if worst == "attention" and not (n_att >= 2 or bad * 2 >= len(insights)):
        return "watch"
    return worst


def _area_card(key: str, title: str, topics: list[str], per_fund: dict[str, list[Insight]],
               n_funds: int, w: Optional[Weights] = None) -> Optional[Card]:
    flat = [i for ins in per_fund.values() for i in ins if i.topic in topics]
    if not flat:
        return None
    fund_status = {name: group_status([i for i in ins if i.topic in topics], w)
                   for name, ins in per_fund.items() if any(i.topic in topics for i in ins)}
    total = len(fund_status)
    fine = sum(1 for s in fund_status.values() if s in ("good", "ok"))
    worst_by_fund = [s for s in fund_status.values()]
    pseudo = [Insight(id="", topic=key, status=s, headline="", sentence="") for s in worst_by_fund]
    status = _fund_card_status(pseudo)
    if fine == total:
        line = f"All {total} funds look fine here." if total > 1 else "Looks fine here."
    else:
        line = f"{fine} of {total} funds look fine here; {total - fine} worth a closer look."
    if total < n_funds:
        line += f" ({n_funds - total} not covered by this check.)"
    return Card(topic=key, title=title, status=status, one_liner=line,
                sections=_sections(flat, topics), insights=flat)


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _gap_line(name: str, history_years: Optional[float], missing: list[str],
              short_record: bool, few_days: bool, no_median: bool, shown: set[str]) -> Optional[str]:
    """One plain line for everything this fund could not be checked on."""
    parts: list[str] = []
    young = history_years is not None and history_years < 2
    if young and (missing or short_record):
        checked = []
        if "returns" in shown:
            checked.append("returns")
        if "costs" in shown:
            checked.append("cost")
        if len(checked) == 1:
            what = f"only {checked[0]} is checked"
        elif checked:
            what = "only " + " and ".join(checked) + " are checked"
        else:
            what = "it could not be checked"
        parts.append(f"{name} is under 2 years old, so {what}.")
        missing = []
        short_record = False
    clauses: list[str] = []
    if missing:
        verb = "is" if len(missing) == 1 else "are"
        clauses.append(f"{_join(missing)} {verb} not shown because the data is not available")
    if short_record:
        clauses.append("rolling-return consistency is not shown because the fund's track record is too short")
    if few_days:
        clauses.append("upside and downside capture is not shown because there are too few days of data")
    if no_median:
        clauses.append("the category median charge is not available, so its charges are shown without a comparison")
    if clauses:
        body = (_join(clauses) if len(clauses) > 1 else clauses[0]) + "."
        if parts:
            parts.append(body[0].upper() + body[1:])
        else:
            parts.append(f"{name}: {body}")
    if not parts:
        return None
    return " ".join(parts)


def _select_questions(items: list[Insight]) -> list[str]:
    """At most two questions, most severe first, each wording once. Cleared off the findings
    so a panel does not repeat them."""
    ranked = sorted(
        (item for item in items if item.suggestion and item.status in ("watch", "attention")),
        key=lambda item: -SEVERITY[item.status],
    )
    chosen: list[str] = []
    seen: set[str] = set()
    for item in ranked:
        if item.suggestion in seen:
            continue
        seen.add(item.suggestion)
        chosen.append(item.suggestion)
        if len(chosen) == 2:
            break
    for item in items:
        item.suggestion = None
    return chosen


def _headline(summaries: list[FundSummary]) -> tuple[str, dict]:
    counts = {"Doing well": 0, "On track": 0, "Worth a closer look": 0, "Needs attention": 0,
              "Limited data": 0, "Not enough data": 0}
    for s in summaries:
        counts[s.verdict] += 1
    n = len(summaries)
    parts = []
    if counts["Doing well"]:
        parts.append(f"{counts['Doing well']} doing well")
    if counts["On track"]:
        parts.append(f"{counts['On track']} on track")
    if counts["Worth a closer look"]:
        parts.append(f"{counts['Worth a closer look']} worth a closer look")
    if counts["Needs attention"]:
        parts.append(f"{counts['Needs attention']} needing attention")
    limited = counts["Limited data"] + counts["Not enough data"]
    if limited:
        parts.append(f"{limited} with limited data")
    return f"Of your {n} fund{'s' if n != 1 else ''}: " + ", ".join(parts) + ".", counts


def analyze(portfolio: Portfolio, thresholds: Optional[Thresholds] = None,
            weights: Optional[Weights] = None) -> Report:
    th = thresholds or Thresholds()
    w = weights or Weights()
    total_value = sum(f.value for f in portfolio.funds) or 1.0
    gaps: list[str] = []
    per_fund: dict[str, list[Insight]] = {}
    summaries: list[FundSummary] = []

    flag_facts: list[Insight] = []
    for f in portfolio.funds:
        insights: list[Insight] = []
        missing: list[str] = []
        short_record = False
        few_days = False
        no_median = False
        bench_ok = f.benchmark_applies if f.benchmark_applies is not None else \
            benchmark_tests_apply(f.category, f.category_group)
        notes: list[str] = []
        if not bench_ok:
            notes.append("This kind of fund is not compared with an index, because the index would not be a fair "
                         "yardstick for it. It is judged on its ranking among similar funds and on its costs.")
        if f.data_quality_note:
            notes.append("The data for this fund has a known quirk: " + f.data_quality_note)
        # Equity index funds copy one index. Ranking them inside "Index Funds" mixes
        # different indices, so the quartile finding is left out. Tracking, capture and costs stay.
        skip_peer_rank = f.index_like and bench_ok
        if skip_peer_rank:
            notes.append("Not ranked against other index funds, because that group mixes different indices.")
        for tr in FUND_TRANSLATORS:
            name = tr.__name__
            if not bench_ok and name in BENCH_TESTS:
                continue
            if skip_peer_rank and name == "quartile_insight":
                continue
            ins = tr(f, th, w)
            if ins is None:
                if name in INDEX_SKIPPED and f.index_like:
                    continue  # not meaningful for an index fund, so not a data gap
                if name == "rolling_insight" and f.rolling_beat_pct is not None and history_too_short(f, th):
                    short_record = True
                elif name == "capture_insight" and f.upside_capture is not None and capture_obs_too_few(f, th):
                    few_days = True
                else:
                    missing.append(GAP_TEXT[name])
                continue
            insights.append(ins)
            if name == "cost_insight" and ins.numbers.get("category_median") is None:
                no_median = True
        per_fund[f.name] = insights
        line = _gap_line(f.name, f.history_years, missing, short_record, few_days, no_median,
                         {i.topic for i in insights})
        if line:
            gaps.append(line)

        facts = fund_facts(f, th, portfolio.as_of_date)
        questions = _select_questions(insights + facts)
        flag_facts += [i for i in facts if i.status in ("watch", "attention")]
        verdict, status = _fund_verdict(insights, w, min_perf=2 if bench_ok else 1)
        score = []
        for key, title, topics in AREAS:
            grp = [i for i in insights if i.topic in topics]
            st = group_status(grp, w)
            label = STATUS_WORD[st]
            if st == "na" and not bench_ok and key in ("returns", "risk"):
                label = "Not compared"
            if st == "na" and skip_peer_rank and key == "peers":
                label = "Not ranked"
            score.append(ScoreItem(topic=key, title=title, status=st, label=label,
                                   note=_worst(grp).headline if grp else ""))
        good = [i.headline for i in insights if i.status == "good"][:3]
        look = [i.headline for i in sorted(insights + facts, key=lambda i: -SEVERITY[i.status])
                if i.status in ("watch", "attention")][:3]
        all_topics = [t for _, _, ts in AREAS for t in ts] + FACT_TOPICS
        facts_hdr = {"plan": f.plan, "benchmark": f.benchmark_name, "ter": f.ter, "aum_cr": f.aum_cr,
                     "riskometer": f.riskometer or None, "benchmark_applies": bench_ok}
        for i in facts:
            if i.topic == "age":
                facts_hdr["age_years"] = i.numbers["years"]
            if i.topic == "manager":
                facts_hdr["manager_months"] = i.numbers["months"]
        summaries.append(FundSummary(
            name=f.name, category=f.category, value=f.value,
            share_pct=round(f.value / total_value * 100, 1), verdict=verdict, status=status,
            going_well=good, look_at=look, scorecard=score, sections=_sections(insights + facts, all_topics),
            facts=facts_hdr, notes=notes, questions=questions))

    cards: list[Card] = []
    for key, title, topics in AREAS:
        c = _area_card(key, title, topics, per_fund, len(portfolio.funds), w)
        if c:
            cards.append(c)
    # Equal shares are a comparison, not a record of how someone's money is split.
    mix = [] if portfolio.values_are_weights else mix_insights(portfolio, th)
    if mix:
        w = _worst(mix)
        cards.append(Card(topic="mix", title="Portfolio mix", status=w.status, one_liner=w.headline + ".",
                          sections=_sections(mix, ["mix"]), insights=mix))

    flat = [i for c in cards for i in c.insights] + flag_facts
    flags = sorted((i for i in flat if i.status in ("watch", "attention")), key=lambda i: -SEVERITY[i.status])

    headline, counts = _headline(summaries)
    used = {i.jargon_term for i in flat if i.jargon_term}
    glossary = {k: {"title": GLOSSARY[k][0], "text": GLOSSARY[k][1]} for k in GLOSSARY if k in used}

    return Report(as_of=portfolio.as_of, data_source=portfolio.data_source, headline=headline,
                  counts=counts, cards=cards, funds=summaries, flags=flags, data_gaps=gaps,
                  glossary=glossary, disclaimer=DISCLAIMER, credits=CREDITS)


def to_dict(report: Report) -> dict:
    """JSON-ready dict for an API or front end."""
    return asdict(report)
