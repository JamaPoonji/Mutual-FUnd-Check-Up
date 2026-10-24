"""Pure mappers from TigZig rows onto scheme_metrics.

Nothing here fetches data. A missing input stays None. This nightly row leaves
benchmark-relative measures empty. pipeline.benchmark_metrics fills them from
the stored total-return series, and never with zero.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Mapping, Optional

from mf_plain.benchmarks import benchmark_for

HORIZONS = (1, 3, 5)

# Filled by pipeline.benchmark_metrics once a total-return series is stored.
BENCHMARK_METRIC_COLUMNS = (
    "bench_cagr_1y", "bench_cagr_3y", "bench_cagr_5y",
    "calendar_returns_json", "bench_calendar_returns_json",
    "rolling_window_years", "rolling_beat_pct",
    "upside_capture", "downside_capture", "capture_years", "capture_obs",
    "max_drawdown", "bench_max_drawdown", "drawdown_event",
    "recovery_months", "bench_recovery_months", "still_underwater",
)


def _as_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    return date.fromisoformat(text[:10])


def history_years(first_date, as_of) -> Optional[float]:
    """Years from the plan's first NAV date to as_of, using a 365-day year.

    Missing or inverted dates return None. Never 0, which would look like a measurement.
    """
    start, end = _as_date(first_date), _as_date(as_of)
    if start is None or end is None or start > end:
        return None
    return round((end - start).days / 365, 4)


def cagr_pct(end_nav: float, start_nav: float, days: int) -> Optional[float]:
    """TigZig point-to-point CAGR, in percent, rounded to 0.01.

    (end/start)^(365/days) - 1. A non-positive NAV or a non-positive gap returns None.
    """
    if end_nav is None or start_nav is None or days is None:
        return None
    if start_nav <= 0 or end_nav <= 0 or days <= 0:
        return None
    return round((pow(end_nav / start_nav, 365.0 / days) - 1) * 100, 2)


def _num(value) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _int(value) -> Optional[int]:
    if value is None:
        return None
    return int(value)


def index_by_horizon(rows: Iterable[Mapping]) -> dict[int, dict]:
    """One quartile-SQL row per horizon. Later duplicates keep the last row."""
    out: dict[int, dict] = {}
    for row in rows:
        yrs = _int(row.get("yrs"))
        if yrs is None:
            continue
        out[yrs] = {
            "cagr_pct": _num(row.get("cagr_pct")),
            "rnk": _int(row.get("rnk")),
            "n": _int(row.get("n")),
            "quartile": _int(row.get("quartile")),
        }
    return out


def peer_count_for(by_year: Mapping[int, Mapping]) -> Optional[int]:
    """Peer count shown with the longest horizon that has a quartile.

    The engine's sentence is about that horizon ("Over 5 years ... of N funds").
    If no horizon qualified (n < 4), use the longest horizon that still has a CAGR
    so the category size is not thrown away. No horizons: None.
    """
    for yrs in (5, 3, 1):
        row = by_year.get(yrs)
        if row and row.get("quartile") is not None and row.get("n") is not None:
            return int(row["n"])
    for yrs in (5, 3, 1):
        row = by_year.get(yrs)
        if row and row.get("n") is not None:
            return int(row["n"])
    return None


def benchmark_name_for(category: Optional[str]) -> Optional[str]:
    """Category benchmark from the engine map. Blank category stays blank."""
    if category is None or not str(category).strip():
        return None
    return benchmark_for(str(category))


def _text(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def scheme_metrics_row(scheme: Mapping, by_year: Mapping[int, Mapping], as_of, first_date) -> dict:
    """One scheme_metrics row. Benchmark-relative columns are always None in this job."""
    row = {column: None for column in BENCHMARK_METRIC_COLUMNS}
    row.update({
        "scheme_code": _int(scheme.get("scheme_code")),
        "scheme_name": _text(scheme.get("scheme_name")),
        "isin": _text(scheme.get("isin")),
        "category_sub": _text(scheme.get("category_sub")),
        "category_group": _text(scheme.get("category_group")),
        "scheme_plan": _text(scheme.get("scheme_plan")),
        "as_of": _as_date(as_of).isoformat() if _as_date(as_of) else None,
        "history_years": history_years(first_date, as_of),
        "benchmark_name": benchmark_name_for(scheme.get("category_sub")),
        "peer_count": peer_count_for(by_year),
    })
    for yrs in HORIZONS:
        point = by_year.get(yrs) or {}
        row[f"cagr_{yrs}y"] = point.get("cagr_pct")
        row[f"quartile_{yrs}y"] = point.get("quartile")
    return row
