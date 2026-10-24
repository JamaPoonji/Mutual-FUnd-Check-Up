"""'Good to know' facts: risk label, fund size, track record, manager, exit load.

These come from the scheme master / scheme summary document. They are shown with plain wording and can
raise a question for the adviser, but they never change a fund's verdict score.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from .fmt import inr
from .models import Fund, Insight, Thresholds

FACT_TOPICS = ["riskometer", "size", "age", "manager", "exit"]
RISK_LEVELS = {"low": 1, "low to moderate": 2, "moderate": 3, "moderately high": 4, "high": 5, "very high": 6}


def _slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-")


def _d(s: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def _months(a: date, b: date) -> int:
    return max(0, (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0))


def _span(months: int) -> str:
    if months < 24:
        return f"{months} month{'s' if months != 1 else ''}"
    y, m = divmod(months, 12)
    return f"about {y} years" if m < 6 else f"about {y}.5 years"


def _mon(d: date) -> str:
    return d.strftime("%b %Y")


def _level(text: str) -> Optional[int]:
    return RISK_LEVELS.get(text.strip().lower())


def risk_label(f: Fund, th: Thresholds, today: Optional[date]) -> Optional[Insight]:
    lv = _level(f.riskometer)
    if lv is None:
        return None
    blv = _level(f.benchmark_riskometer)
    sentence = f"The fund house rates this fund '{f.riskometer}' on the official six-step risk scale."
    nums = {"level": lv, "label": f.riskometer, "bench_level": blv, "bench_label": f.benchmark_riskometer}
    if blv is not None:
        sentence += f" Its benchmark is rated '{f.benchmark_riskometer}'."
    if blv is not None and lv - blv >= th.riskometer_gap_levels:
        return Insight(id=f"facts-risk-{_slug(f.name)}", topic="riskometer", fund=f.name, status="watch",
                       headline="Rated riskier than its benchmark", sentence=sentence,
                       suggestion="Worth checking that this level of risk suits you.",
                       jargon_term="riskometer", numbers=nums)
    return Insight(id=f"facts-risk-{_slug(f.name)}", topic="riskometer", fund=f.name, status="ok",
                   headline=f"Official risk level: {f.riskometer}", sentence=sentence,
                   jargon_term="riskometer", numbers=nums)


def fund_size(f: Fund, th: Thresholds, today: Optional[date]) -> Optional[Insight]:
    if f.aum_cr is None:
        return None
    text = f"{inr(f.aum_cr)} crore"
    sentence = f"The fund manages about {text} in total, across all its plans."
    nums = {"aum_cr": f.aum_cr}
    if f.aum_cr < th.aum_small_cr:
        return Insight(id=f"facts-size-{_slug(f.name)}", topic="size", fund=f.name, status="watch",
                       headline="A small fund", sentence=sentence + " That is small for a mutual fund.",
                       suggestion="Worth asking whether a fund this small is likely to stay open and keep its costs low.",
                       jargon_term="aum", numbers=nums)
    return Insight(id=f"facts-size-{_slug(f.name)}", topic="size", fund=f.name, status="ok",
                   headline=f"Fund size: {text}", sentence=sentence, jargon_term="aum", numbers=nums)


def track_record(f: Fund, th: Thresholds, today: Optional[date]) -> Optional[Insight]:
    launch = _d(f.allotment_date)
    yrs = None
    if launch and today:
        yrs = round((today - launch).days / 365.25, 1)
    elif f.history_years is not None:
        yrs = round(f.history_years, 1)
    if yrs is None:
        return None
    when = f" Launched in {_mon(launch)}." if launch else ""
    nums = {"years": yrs, "allotment_date": f.allotment_date}
    if yrs < th.young_fund_years:
        return Insight(id=f"facts-age-{_slug(f.name)}", topic="age", fund=f.name, status="watch",
                       headline="A short track record",
                       sentence=f"This fund is about {yrs:g} years old.{when} That is too short to have been through a long market fall.",
                       suggestion="Worth remembering that a short record says little about how it behaves in a long market fall.",
                       numbers=nums)
    return Insight(id=f"facts-age-{_slug(f.name)}", topic="age", fund=f.name, status="ok",
                   headline=f"About {yrs:g} years of history",
                   sentence=f"This fund is about {yrs:g} years old.{when}", numbers=nums)


def manager(f: Fund, th: Thresholds, today: Optional[date]) -> Optional[Insight]:
    since = _d(f.manager_since)
    if not since or not today:
        return None
    months = _months(since, today)
    who = ", ".join(f.manager_names[:2]) if f.manager_names else "The current fund manager"
    verb = "has" if not f.manager_names or len(f.manager_names) == 1 else "have"
    sentence = f"{who} {verb} run this fund since {_mon(since)}, which is {_span(months)}."
    nums = {"months": months, "since": f.manager_since, "names": f.manager_names}
    if months < th.manager_recent_months:
        return Insight(id=f"facts-manager-{_slug(f.name)}", topic="manager", fund=f.name, status="watch",
                       headline="The fund manager changed recently",
                       sentence=sentence + " Part of the track record above may belong to a previous manager.",
                       suggestion="Worth asking what changed with the new manager and whether the approach is the same.",
                       jargon_term="manager", numbers=nums)
    return Insight(id=f"facts-manager-{_slug(f.name)}", topic="manager", fund=f.name, status="ok",
                   headline=f"Same manager for {_span(months)}", sentence=sentence,
                   jargon_term="manager", numbers=nums)


def exit_load(f: Fund, th: Thresholds, today: Optional[date]) -> Optional[Insight]:
    text = (f.exit_load or "").strip()
    if not text:
        return None
    return Insight(id=f"facts-exit-{_slug(f.name)}", topic="exit", fund=f.name, status="ok",
                   headline="Exit load", sentence=f"As filed by the fund house: {text[:300]}",
                   numbers={"text": text[:300]})


FACT_FUNCS = [risk_label, fund_size, track_record, manager, exit_load]


def fund_facts(f: Fund, th: Thresholds, as_of_date: Optional[str]) -> list[Insight]:
    today = _d(as_of_date)
    return [i for fn in FACT_FUNCS if (i := fn(f, th, today)) is not None]
