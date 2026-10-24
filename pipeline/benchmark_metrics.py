"""Benchmark-relative measures from a fund NAV series and a total-return index.

Definitions are in docs/METRICS_SPEC.md. A missing input stays None. Nothing
here is stored as zero to mean "we could not measure it".

Point-to-point horizons use the same power formula as the stored fund CAGR.
The benchmark's worst fall is measured only on the dates the fund itself existed,
so a fund launched in 2018 is not compared with a 2008 index crash.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional, Sequence

from pipeline.metrics import cagr_pct

HORIZONS = (1, 3, 5)
ROLLING_WINDOW_DAYS = 1096
ROLLING_MIN_GAP_DAYS = 986
ROLLING_MIN_HISTORY_YEARS = 4.0
CAPTURE_YEARS = 3
CAL_MAX_YEARS = 6

_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


class Series:
    """Positive levels, one per date, oldest first. Later duplicates win."""

    def __init__(self, points: Sequence[tuple]):
        by_date: dict[date, float] = {}
        for raw_day, raw_level in points:
            day = _as_date(raw_day)
            if day is None or raw_level is None:
                continue
            level = float(raw_level)
            if level <= 0:
                continue
            by_date[day] = level
        self.dates = tuple(sorted(by_date))
        self.levels = tuple(by_date[day] for day in self.dates)

    def __len__(self) -> int:
        return len(self.dates)

    def through(self, as_of: date) -> "Series":
        return Series([
            (day, level) for day, level in zip(self.dates, self.levels) if day <= as_of
        ])

    def on_or_from(self, first: date) -> "Series":
        return Series([
            (day, level) for day, level in zip(self.dates, self.levels) if day >= first
        ])

    def on_or_before(self, day: date) -> Optional[tuple[date, float]]:
        # Binary search. Dates are sorted.
        lo, hi = 0, len(self.dates)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.dates[mid] <= day:
                lo = mid + 1
            else:
                hi = mid
        if lo == 0:
            return None
        idx = lo - 1
        return self.dates[idx], self.levels[idx]


def _as_date(value) -> Optional[date]:
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    return date.fromisoformat(text[:10])


def _months(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + (end.month - start.month) - (1 if end.day < start.day else 0))


def point_return(series: Series, as_of: date, years: int) -> Optional[float]:
    """CAGR in percent for a 1, 3 or 5 year horizon. Younger than the horizon: None."""
    as_of = _as_date(as_of)
    if len(series) == 0 or as_of is None:
        return None
    target = as_of - timedelta(days=years * 365)
    end = series.on_or_before(as_of)
    start = series.on_or_before(target)
    if end is None or start is None or start[0] > target or start[0] >= end[0]:
        return None
    return cagr_pct(end[1], start[1], (end[0] - start[0]).days)


def calendar_returns(series: Series, as_of: date, max_years: int = CAL_MAX_YEARS) -> dict[int, float]:
    """Dec-to-Dec simple returns for complete years, latest first, capped at max_years.

    A year counts only when the series already existed on the prior 31 Dec.
    """
    found: dict[int, float] = {}
    for year in range(as_of.year, 1900, -1):
        if len(found) >= max_years:
            break
        year_end = date(year, 12, 31)
        if as_of < year_end:
            continue
        prior = date(year - 1, 12, 31)
        if not series.dates or series.dates[0] > prior:
            continue
        start = series.on_or_before(prior)
        end = series.on_or_before(year_end)
        if start is None or end is None or start[0] >= end[0] or start[1] <= 0:
            continue
        found[year] = round((end[1] / start[1] - 1) * 100, 2)
    return found


def rolling_beat_pct(fund: Series, bench: Series, as_of: date) -> Optional[float]:
    """Share of 3-year windows, in percent, where the fund's CAGR beat the benchmark.

    Needs about four years of fund history. A window counts only when both series
    have a start more than 986 days before the end. Strictly greater wins.
    """
    if len(fund) == 0:
        return None
    if (as_of - fund.dates[0]).days / 365 < ROLLING_MIN_HISTORY_YEARS:
        return None
    beats = 0
    observed = 0
    for end_day, end_level in zip(fund.dates, fund.levels):
        target = end_day - timedelta(days=ROLLING_WINDOW_DAYS)
        start = fund.on_or_before(target)
        if start is None or (end_day - start[0]).days <= ROLLING_MIN_GAP_DAYS:
            continue
        bench_end = bench.on_or_before(end_day)
        bench_start = bench.on_or_before(target)
        if bench_end is None or bench_start is None:
            continue
        if (bench_end[0] - bench_start[0]).days <= ROLLING_MIN_GAP_DAYS:
            continue
        fund_cagr = cagr_pct(end_level, start[1], (end_day - start[0]).days)
        bench_cagr = cagr_pct(bench_end[1], bench_start[1], (bench_end[0] - bench_start[0]).days)
        if fund_cagr is None or bench_cagr is None:
            continue
        observed += 1
        if fund_cagr > bench_cagr:
            beats += 1
    if observed == 0:
        return None
    return round(beats / observed * 100, 2)


def capture(fund: Series, bench: Series, as_of: date, years: int = CAPTURE_YEARS):
    """Upside capture, downside capture, and the number of non-zero benchmark days.

    The window is the last `years` * 365 days. Up means the benchmark rose, down
    means it fell, and a flat benchmark day is left out of both averages.
    """
    window_start = as_of - timedelta(days=years * 365)
    fund_at = dict(zip(fund.dates, fund.levels))
    bench_at = dict(zip(bench.dates, bench.levels))
    common = sorted(set(fund_at) & set(bench_at))
    anchor = [day for day in common if day <= window_start]
    inside = [day for day in common if window_start < day <= as_of]
    if not anchor or not inside:
        return None, None, None
    previous = anchor[-1]
    up_fund, up_bench, down_fund, down_bench = [], [], [], []
    for day in inside:
        bench_return = bench_at[day] / bench_at[previous] - 1
        fund_return = fund_at[day] / fund_at[previous] - 1
        previous = day
        if bench_return > 0:
            up_fund.append(fund_return)
            up_bench.append(bench_return)
        elif bench_return < 0:
            down_fund.append(fund_return)
            down_bench.append(bench_return)
    observed = len(up_fund) + len(down_fund)
    if observed == 0:
        return None, None, None
    return _capture_ratio(up_fund, up_bench), _capture_ratio(down_fund, down_bench), observed


def _capture_ratio(fund_returns: list[float], bench_returns: list[float]) -> Optional[float]:
    if not bench_returns:
        return None
    bench_mean = sum(bench_returns) / len(bench_returns)
    if bench_mean == 0:
        return None
    fund_mean = sum(fund_returns) / len(fund_returns)
    return round(fund_mean / bench_mean * 100, 2)


def drawdown(series: Series) -> Optional[dict]:
    """Worst peak-to-trough fall. None when there are fewer than two points.

    A series that never fell is a real measurement of 0, not a missing one.
    Recovery is counted in calendar months from the trough back to that peak.
    """
    if len(series) < 2:
        return None
    peak_level = series.levels[0]
    worst = 0.0
    trough: Optional[date] = None
    peak_at_worst = peak_level
    for day, level in zip(series.dates, series.levels):
        if level >= peak_level:
            peak_level = level
        fall = level / peak_level - 1
        if fall < worst:
            worst = fall
            trough = day
            peak_at_worst = peak_level
    if trough is None:
        return {
            "max_drawdown": 0.0,
            "event": None,
            "recovery_months": None,
            "still_underwater": False,
        }
    recovery: Optional[date] = None
    for day, level in zip(series.dates, series.levels):
        if day > trough and level >= peak_at_worst:
            recovery = day
            break
    return {
        "max_drawdown": round(worst * 100, 2),
        "event": f"the {_MONTHS[trough.month - 1]} {trough.year} fall",
        "recovery_months": None if recovery is None else _months(trough, recovery),
        "still_underwater": recovery is None,
    }


def measures(fund_points, bench_points, as_of) -> dict:
    """Every benchmark-relative measure for one fund. Values are Python objects."""
    as_of = _as_date(as_of)
    fund = Series(fund_points).through(as_of)
    bench = Series(bench_points).through(as_of)
    # The stored fund CAGR is measured to the fund's own last NAV, which can be
    # the session before the job date. The benchmark uses that same day.
    anchor = fund.dates[-1] if fund.dates else as_of
    overlap = bench.on_or_from(fund.dates[0]) if fund.dates else Series([])
    fund_dd = drawdown(fund)
    bench_dd = drawdown(overlap)
    upside, downside, observed = capture(fund, bench, as_of)
    beat = rolling_beat_pct(fund, bench, as_of)
    return {
        "bench_cagr_1y": point_return(bench, anchor, 1),
        "bench_cagr_3y": point_return(bench, anchor, 3),
        "bench_cagr_5y": point_return(bench, anchor, 5),
        "calendar_returns": calendar_returns(fund, as_of),
        "bench_calendar_returns": calendar_returns(bench, as_of),
        "rolling_window_years": 3 if beat is not None else None,
        "rolling_beat_pct": beat,
        "upside_capture": upside,
        "downside_capture": downside,
        "capture_years": CAPTURE_YEARS if observed is not None else None,
        "capture_obs": observed,
        "max_drawdown": None if fund_dd is None else fund_dd["max_drawdown"],
        "bench_max_drawdown": None if bench_dd is None else bench_dd["max_drawdown"],
        "drawdown_event": None if fund_dd is None else fund_dd["event"],
        "recovery_months": None if fund_dd is None else fund_dd["recovery_months"],
        "bench_recovery_months": None if bench_dd is None else bench_dd["recovery_months"],
        "still_underwater": None if fund_dd is None else fund_dd["still_underwater"],
    }


def _dump_years(years: dict) -> Optional[str]:
    if not years:
        return None
    return json.dumps({str(year): years[year] for year in sorted(years)})


def store_fields(measured: dict) -> dict:
    """Column values for scheme_metrics. Empty calendars stay NULL, not '{}'."""
    underwater = measured["still_underwater"]
    return {
        "bench_cagr_1y": measured["bench_cagr_1y"],
        "bench_cagr_3y": measured["bench_cagr_3y"],
        "bench_cagr_5y": measured["bench_cagr_5y"],
        "calendar_returns_json": _dump_years(measured["calendar_returns"]),
        "bench_calendar_returns_json": _dump_years(measured["bench_calendar_returns"]),
        "rolling_window_years": measured["rolling_window_years"],
        "rolling_beat_pct": measured["rolling_beat_pct"],
        "upside_capture": measured["upside_capture"],
        "downside_capture": measured["downside_capture"],
        "capture_years": measured["capture_years"],
        "capture_obs": measured["capture_obs"],
        "max_drawdown": measured["max_drawdown"],
        "bench_max_drawdown": measured["bench_max_drawdown"],
        "drawdown_event": measured["drawdown_event"],
        "recovery_months": measured["recovery_months"],
        "bench_recovery_months": measured["bench_recovery_months"],
        "still_underwater": None if underwater is None else int(underwater),
    }
