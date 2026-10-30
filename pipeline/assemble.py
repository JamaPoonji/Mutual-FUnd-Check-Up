"""Build Fund objects from stored scheme metrics and run them through the engine.

The five funds at the bottom are a demonstration portfolio with round rupee
amounts, so the report can be read. They are not a client's holdings. An
uploaded file is never read or saved here.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

# duckdb is imported inside the build helpers below, so serving reports does
# not require it in the runtime image.
from mf_plain.benchmarks import benchmark_tests_apply
from mf_plain.engine import analyze
from mf_plain.models import Fund, Portfolio, Thresholds
from mf_plain.render import render_markdown
from pipeline.benchmark_metrics import measures, point_return, store_fields
from pipeline.benchmark_metrics import Series
from pipeline.match import match_holding
from pipeline.store import update_benchmark_metrics

ROOT = Path(__file__).resolve().parents[1]
DATA_SOURCE = "Tig Zig MFPRO (AMFI data)"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_SINCE = re.compile(r"^(?P<name>.*?)\s*\(since\s+(?P<since>\d{4}-\d{2}-\d{2})\)\s*$", re.IGNORECASE)

# Demonstration holdings. Values are round amounts chosen so the report can be read.
HAND_PICKED = (
    (118955, 400_000),  # HDFC Flexi Cap, Direct, Nifty 500 TRI
    (118632, 300_000),  # Nippon India Large Cap, Direct, Nifty 100 TRI
    (127042, 200_000),  # Motilal Oswal Midcap, Direct, Nifty Midcap 150 TRI
    (145678, 150_000),  # Bank of India Small Cap, Direct, Nifty Smallcap 250 TRI
    (120716, 250_000),  # UTI Nifty 50 Index, Direct, Nifty 50 TRI
)


def parse_managers(text: Optional[str]) -> tuple[list[str], Optional[str]]:
    """Names in filing order, and the lead manager's start date.

    The lead is the first name. That person's since-date is the latest time the
    filing says the lead took the fund. A co-manager who joined later does not
    move it. A name with no date leaves the start empty rather than inventing one.
    """
    if not text or not str(text).strip():
        return [], None
    names: list[str] = []
    lead_since: Optional[str] = None
    seen_lead = False
    for part in str(text).split(";"):
        part = part.strip()
        if not part:
            continue
        matched = _SINCE.match(part)
        if matched:
            name, since = matched.group("name").strip(), matched.group("since")
        else:
            name, since = part, None
        if not name:
            continue
        if not seen_lead:
            lead_since = since
            seen_lead = True
        names.append(name)
    return names, lead_since


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text[:10] if text else None


def _num(value) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


def _years(text: Optional[str]) -> dict[int, float]:
    if not text:
        return {}
    return {int(year): float(level) for year, level in json.loads(text).items()}


def _is_index(category: Optional[str], name: Optional[str]) -> bool:
    category_text = (category or "").strip().lower()
    name_text = (name or "").lower()
    return category_text in {"index funds", "equity etf"} or "index" in name_text or "etf" in name_text


def _exit_load(text: Optional[str]) -> str:
    if not text:
        return ""
    flat = " ".join(str(text).split())
    return flat[:300]


def display_as_of(as_of) -> str:
    day = as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of)[:10])
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def _median(values: list) -> Optional[float]:
    """Middle value. Omitted unless at least median_min_funds numbers exist."""
    xs = sorted(v for v in values if v is not None)
    if len(xs) < Thresholds().median_min_funds:
        return None
    mid = len(xs) // 2
    if len(xs) % 2:
        return round(xs[mid], 2)
    return round((xs[mid - 1] + xs[mid]) / 2, 2)


def _plan_key(plan: Optional[str]) -> str:
    return "regular" if "regular" in (plan or "").strip().lower() else "direct"


def _index_category(category: Optional[str]) -> bool:
    text = (category or "").strip().lower()
    return "index" in text or "etf" in text


def display_medians(metrics: dict[int, dict]) -> dict[tuple[str, str], dict]:
    """Category medians for display only: CAGR, each calendar year, worst fall, recovery.

    Same category and plan type. A figure is included only when at least five funds
    have it. Index and ETF categories are left out. Nothing here is scored.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in metrics.values():
        category = (row.get("category_sub") or "").strip()
        if not category or _index_category(category):
            continue
        groups.setdefault((category, _plan_key(row.get("scheme_plan"))), []).append(row)
    out: dict[tuple[str, str], dict] = {}
    for key, rows in groups.items():
        cagr = {}
        for years in (1, 3, 5):
            value = _median([_num(row.get(f"cagr_{years}y")) for row in rows])
            if value is not None:
                cagr[years] = value
        by_year: dict[int, list[float]] = {}
        for row in rows:
            for year, level in _years(row.get("calendar_returns_json")).items():
                by_year.setdefault(year, []).append(level)
        calendar = {}
        for year, levels in by_year.items():
            value = _median(levels)
            if value is not None:
                calendar[year] = value
        draw = _median([_num(row.get("max_drawdown")) for row in rows])
        recovery = _median([
            float(row["recovery_months"]) for row in rows if row.get("recovery_months") is not None
        ])
        if not cagr and not calendar and draw is None and recovery is None:
            continue
        item: dict = {"cagr": cagr, "calendar": calendar}
        if draw is not None:
            item["max_drawdown"] = draw
        if recovery is not None:
            item["recovery_months"] = int(round(recovery))
        out[key] = item
    return out


def fund_from_rows(value: float, details: dict, metrics: Optional[dict], median: Optional[tuple],
                   quality_note: str, used_names: set[str], value_is_weight: bool = False,
                   typical: Optional[dict] = None) -> Fund:
    """One Fund. Missing analytics stay missing. benchmark_applies stays None."""
    scheme_name = (details.get("scheme_name") or "").strip()
    base = (details.get("fund_name_latest") or scheme_name or "Unknown fund").strip()
    plan_raw = details.get("scheme_plan") or (metrics or {}).get("scheme_plan") or ""
    plan = str(plan_raw).strip().lower()
    name = base
    if name in used_names:
        name = f"{base} ({plan})" if plan else f"{base} ({details.get('scheme_code')})"
    used_names.add(name)
    direct = plan != "regular"
    ter = _num(details.get("ter_direct") if direct else details.get("ter_regular"))
    category = (details.get("category_sub") or (metrics or {}).get("category_sub") or "").strip()
    group = (details.get("category_group") or (metrics or {}).get("category_group") or "").strip()
    managers, manager_since = parse_managers(details.get("ssd_fund_managers"))
    row = metrics or {}
    returns, bench_returns, quartiles = {}, {}, {}
    for years in (1, 3, 5):
        cagr = _num(row.get(f"cagr_{years}y"))
        bench = _num(row.get(f"bench_cagr_{years}y"))
        quartile = row.get(f"quartile_{years}y")
        if cagr is not None:
            returns[years] = cagr
        if bench is not None:
            bench_returns[years] = bench
        if quartile is not None:
            quartiles[years] = int(quartile)
    median_ter, median_n = (None, None) if median is None else median
    benchmark = row.get("benchmark_name") or "its benchmark"
    index = _is_index(category, scheme_name)
    shown = {} if index or not typical else typical
    return Fund(
        name=name,
        category=category,
        value=float(value),
        plan=plan or "direct",
        ter=ter,
        category_median_ter=_num(median_ter),
        category_median_n=None if median_n is None else int(median_n),
        benchmark_name=benchmark,
        returns=returns,
        bench_returns=bench_returns,
        typical_returns=dict(shown.get("cagr") or {}),
        calendar_returns=_years(row.get("calendar_returns_json")),
        bench_calendar_returns=_years(row.get("bench_calendar_returns_json")),
        typical_calendar={int(k): float(v) for k, v in (shown.get("calendar") or {}).items()},
        rolling_beat_pct=_num(row.get("rolling_beat_pct")),
        rolling_window_years=int(row["rolling_window_years"]) if row.get("rolling_window_years") else 3,
        upside_capture=_num(row.get("upside_capture")),
        downside_capture=_num(row.get("downside_capture")),
        capture_years=int(row["capture_years"]) if row.get("capture_years") else 3,
        capture_obs=None if row.get("capture_obs") is None else int(row["capture_obs"]),
        max_drawdown=_num(row.get("max_drawdown")),
        bench_max_drawdown=_num(row.get("bench_max_drawdown")),
        drawdown_event=row.get("drawdown_event") or "the worst fall",
        recovery_months=None if row.get("recovery_months") is None else int(row["recovery_months"]),
        bench_recovery_months=None if row.get("bench_recovery_months") is None else int(row["bench_recovery_months"]),
        typical_max_drawdown=shown.get("max_drawdown"),
        typical_recovery_months=shown.get("recovery_months"),
        still_underwater=bool(row.get("still_underwater")),
        quartiles=quartiles,
        peer_count=None if row.get("peer_count") is None else int(row["peer_count"]),
        is_index=index,
        isin=(details.get("isin") or row.get("isin") or None),
        category_group=group,
        benchmark_applies=None,
        history_years=_num(row.get("history_years")),
        aum_cr=_num(details.get("aum_cr")),
        riskometer=(details.get("amfi_daily_riskometer") or "") or "",
        benchmark_riskometer=(details.get("amfi_daily_riskometer_benchmark") or "") or "",
        manager_names=managers,
        manager_since=manager_since,
        allotment_date=_iso(details.get("ssd_allotment_date")),
        exit_load=_exit_load(details.get("ssd_exit_load")),
        ter_date=_iso(details.get("ter_date")),
        data_quality_note=quality_note or "",
        value_is_weight=value_is_weight,
    )


def _label(holding: dict) -> str:
    return (holding.get("name") or "").strip() or (holding.get("isin") or "").strip() or "One holding"


def portfolio_from_holdings(holdings: list[dict], catalog: list[dict], details: dict[int, dict],
                            metrics: dict[int, dict], medians: dict[tuple, tuple], quality: dict[int, str],
                            as_of: str, preferred: Optional[set] = None) -> tuple[Portfolio, list[str]]:
    """Matched holdings become funds. The rest become gap lines and are not given a value of 0."""
    gaps: list[str] = []
    funds: list[Fund] = []
    used: set[str] = set()
    preferred = preferred if preferred is not None else set(metrics)
    comparison = bool(holdings) and all(holding.get("value_is_weight") for holding in holdings)
    typical_lookup = display_medians(metrics)
    for holding in holdings:
        code = match_holding(holding, catalog, preferred)
        if code is None:
            gaps.append(f"{_label(holding)} could not be matched to a scheme.")
            continue
        weight_only = bool(holding.get("value_is_weight"))
        raw_value = 1.0 if weight_only else holding.get("value")
        if raw_value is None or float(raw_value) <= 0:
            gaps.append(f"{_label(holding)}: no holding value was given, so it is left out of the report.")
            continue
        detail = details.get(code) or {"scheme_code": code, "scheme_name": holding.get("name") or str(code)}
        metric = metrics.get(code)
        category = (detail.get("category_sub") or (metric or {}).get("category_sub") or "")
        plan = (detail.get("scheme_plan") or (metric or {}).get("scheme_plan") or "")
        funds.append(fund_from_rows(
            float(raw_value), detail, metric, medians.get((category, plan)), quality.get(code, ""), used,
            value_is_weight=weight_only,
            typical=typical_lookup.get((category.strip(), _plan_key(plan))),
        ))
    day = date.fromisoformat(str(as_of)[:10])
    return Portfolio(
        funds, as_of=display_as_of(day), as_of_date=day.isoformat(), data_source=DATA_SOURCE,
        values_are_weights=comparison and bool(funds),
    ), gaps


def report_for(holdings, catalog, details, metrics, medians, quality, as_of, preferred=None):
    """Engine report. Unmatched holdings are listed and do not drop the rest."""
    portfolio, gaps = portfolio_from_holdings(
        holdings, catalog, details, metrics, medians, quality, as_of, preferred,
    )
    report = analyze(portfolio)
    report.data_gaps.extend(gaps)
    return report


def load_catalog(details_path: Path) -> list[dict]:
    import duckdb

    con = duckdb.connect()
    try:
        cursor = con.execute(
            """
            SELECT scheme_code, scheme_name, fund_name_latest, isin, isin2, is_active
            FROM read_parquet($details)
            """,
            {"details": str(details_path)},
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    finally:
        con.close()


def load_details(details_path: Path, codes: list[int]) -> dict[int, dict]:
    if not codes:
        return {}
    import duckdb

    con = duckdb.connect()
    try:
        cursor = con.execute(
            """
            SELECT scheme_code, scheme_name, fund_name_latest, isin, isin2, scheme_plan,
                   category_sub, category_group_clean AS category_group,
                   ter_direct, ter_regular, ter_date,
                   amfi_daily_fund_aum_cr_all_plans AS aum_cr,
                   amfi_daily_riskometer, amfi_daily_riskometer_benchmark,
                   ssd_fund_managers, ssd_allotment_date, ssd_exit_load
            FROM read_parquet($details)
            WHERE scheme_code IN (SELECT UNNEST($codes))
            """,
            {"details": str(details_path), "codes": codes},
        )
        cols = [d[0] for d in cursor.description]
        return {int(row[0]): dict(zip(cols, row)) for row in cursor.fetchall()}
    finally:
        con.close()


def load_details_all(details_path: Path) -> list[dict]:
    """Every scheme's detail row, in the shape the runtime store stores them."""
    import duckdb

    con = duckdb.connect()
    try:
        cursor = con.execute(
            """
            SELECT scheme_code, scheme_name, fund_name_latest, isin, isin2, scheme_plan,
                   category_sub, category_group_clean AS category_group,
                   ter_direct, ter_regular, ter_date,
                   amfi_daily_fund_aum_cr_all_plans AS aum_cr,
                   amfi_daily_riskometer AS riskometer,
                   amfi_daily_riskometer_benchmark AS riskometer_benchmark,
                   ssd_fund_managers AS fund_managers,
                   ssd_allotment_date AS allotment_date,
                   ssd_exit_load AS exit_load
            FROM read_parquet($details)
            """,
            {"details": str(details_path)},
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    finally:
        con.close()


def load_nav(nav_path: Path, codes: list[int], as_of: str) -> dict[int, list[tuple]]:
    if not codes:
        return {}
    import duckdb

    con = duckdb.connect()
    try:
        rows = con.execute(
            """
            SELECT scheme_code, CAST(date AS DATE) AS date, CAST(nav AS DOUBLE) AS nav
            FROM read_parquet($nav)
            WHERE scheme_code IN (SELECT UNNEST($codes))
              AND CAST(date AS DATE) <= $asof::DATE
              AND CAST(nav AS DOUBLE) > 0
            ORDER BY 1, 2
            """,
            {"nav": str(nav_path), "codes": codes, "asof": as_of},
        ).fetchall()
    finally:
        con.close()
    grouped: dict[int, list[tuple]] = {}
    for code, day, nav in rows:
        grouped.setdefault(int(code), []).append((day, float(nav)))
    return grouped


def load_quality(path: Path) -> dict[int, str]:
    notes: dict[int, list[str]] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            raw = (row.get("scheme_code") or "").strip()
            issue = (row.get("issue") or "").strip()
            if not raw or not issue:
                continue
            try:
                code = int(float(raw))
            except ValueError:
                continue
            bucket = notes.setdefault(code, [])
            if issue not in bucket:
                bucket.append(issue)
    return {code: "; ".join(items) for code, items in notes.items()}


def _read_db(db_path: Path):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def load_metrics(db_path: Path, codes: list[int]) -> dict[int, dict]:
    if not codes:
        return {}
    con = _read_db(db_path)
    try:
        marks = ",".join("?" for _ in codes)
        rows = con.execute(f"SELECT * FROM scheme_metrics WHERE scheme_code IN ({marks})", codes).fetchall()
        return {int(row["scheme_code"]): dict(row) for row in rows}
    finally:
        con.close()


def load_medians(db_path: Path) -> dict[tuple, tuple]:
    con = _read_db(db_path)
    try:
        rows = con.execute(
            "SELECT category, plan, median_ter_pct, fund_count FROM category_median_ter"
        ).fetchall()
        return {(row["category"], row["plan"]): (row["median_ter_pct"], row["fund_count"]) for row in rows}
    finally:
        con.close()


def load_index(db_path: Path, name: str, as_of: str) -> list[tuple]:
    con = _read_db(db_path)
    try:
        return [
            (date.fromisoformat(row["date"]), row["level"])
            for row in con.execute(
                """SELECT date, level FROM index_series
                   WHERE benchmark_name = ? AND date <= ? ORDER BY date""",
                (name, as_of),
            )
        ]
    finally:
        con.close()


def all_scheme_codes(db_path: Path) -> list[int]:
    con = _read_db(db_path)
    try:
        return [int(row[0]) for row in con.execute(
            "SELECT scheme_code FROM scheme_metrics ORDER BY scheme_code"
        )]
    finally:
        con.close()


def fill_all_benchmark_metrics(db_path: Path, nav_path: Path, as_of: str, batch_size: int = 200) -> dict:
    """Write benchmark columns for every scheme. Debt and other non-compared categories stay without an index.

    Each batch is committed on its own, so a stopped run keeps the schemes already measured.
    """
    codes = all_scheme_codes(db_path)
    with_cagr = 0
    for start in range(0, len(codes), batch_size):
        batch = codes[start:start + batch_size]
        measured = fill_benchmark_metrics(db_path, nav_path, batch, as_of)
        with_cagr += sum(
            1 for item in measured.values()
            if item.get("bench_cagr_1y") is not None
            or item.get("bench_cagr_3y") is not None
            or item.get("bench_cagr_5y") is not None
        )
        print(f"benchmark measures {start + len(batch)}/{len(codes)}", flush=True)
    return {"schemes": len(codes), "with_benchmark_cagr": with_cagr}


def fill_benchmark_metrics(db_path: Path, nav_path: Path, codes: list[int], as_of: str) -> dict[int, dict]:
    """Measure the given schemes and write the benchmark columns. Returns the measures."""
    metrics = load_metrics(db_path, codes)
    nav = load_nav(nav_path, codes, as_of)
    indexes: dict[str, list] = {}
    pending = []
    out: dict[int, dict] = {}
    for code in codes:
        row = metrics.get(code)
        if row is None:
            raise ValueError(f"scheme {code} is not in scheme_metrics")
        name = row.get("benchmark_name")
        points = nav.get(code) or []
        bench: list = []
        category = row.get("category_sub") or ""
        group = row.get("category_group") or ""
        if name and benchmark_tests_apply(category, group):
            if name not in indexes:
                indexes[name] = load_index(db_path, name, as_of)
            bench = indexes[name]
            if not bench:
                raise ValueError(f"no stored total-return series for {name}")
        measured = measures(points, bench, as_of)
        series = Series(points).through(date.fromisoformat(as_of))
        nav_as_of = series.dates[-1] if series.dates else date.fromisoformat(as_of)
        measured["nav_as_of"] = nav_as_of.isoformat()
        measured["recomputed_cagr"] = {
            years: point_return(series, nav_as_of, years) for years in (1, 3, 5)
        }
        fields = store_fields(measured)
        fields["scheme_code"] = code
        pending.append(fields)
        out[code] = measured
    update_benchmark_metrics(db_path, pending)
    return out


def _holdings_for(codes_and_values, metrics: dict[int, dict]) -> list[dict]:
    holdings = []
    for code, value in codes_and_values:
        row = metrics[code]
        holdings.append({
            "isin": row.get("isin"),
            "name": row.get("scheme_name"),
            "value": value,
            "scheme_code": code,
        })
    return holdings


def run_demonstration(db_path: Path, details_path: Path, nav_path: Path, quality_path: Path,
                      as_of: str) -> str:
    codes = [code for code, _value in HAND_PICKED]
    print(f"measuring {len(codes)} schemes against their category total-return index")
    measured = fill_benchmark_metrics(db_path, nav_path, codes, as_of)
    metrics = load_metrics(db_path, codes)
    catalog = load_catalog(details_path)
    details = load_details(details_path, codes)
    medians = load_medians(db_path)
    quality = load_quality(quality_path) if quality_path.exists() else {}
    # One holding that is not a real ISIN, so the gap line is visible in this run.
    holdings = _holdings_for(HAND_PICKED, metrics)
    holdings.append({"isin": "INF000000000", "name": "Unknown scheme", "value": 10000})
    nav_dates = {measured[code]["nav_as_of"] for code in codes}
    shown = next(iter(nav_dates)) if len(nav_dates) == 1 else as_of
    report = report_for(holdings, catalog, details, metrics, medians, quality, shown, set(metrics))
    lines = ["Demonstration portfolio (round amounts, not a client's holdings).", ""]
    for code, _value in HAND_PICKED:
        row = metrics[code]
        got = measured[code]
        recomputed = got["recomputed_cagr"]
        lines.append(
            f"{row['scheme_name']}: stored CAGR {row['cagr_1y']}/{row['cagr_3y']}/{row['cagr_5y']}"
            f"  recomputed {recomputed[1]}/{recomputed[3]}/{recomputed[5]}"
            f"  benchmark {row['bench_cagr_1y']}/{row['bench_cagr_3y']}/{row['bench_cagr_5y']}"
            f"  rolling {row['rolling_beat_pct']}  capture {row['upside_capture']}/{row['downside_capture']}"
            f"  fall {row['max_drawdown']} vs {row['bench_max_drawdown']}"
        )
    lines.append("")
    lines.append(render_markdown(report))
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Assemble five demonstration funds and print the engine report.")
    parser.add_argument("--as-of", default=None, help="ISO date. Defaults to the date stored by the nightly job.")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "store" / "mf.sqlite")
    parser.add_argument("--details", type=Path, default=None)
    parser.add_argument("--nav", type=Path, default=None)
    parser.add_argument("--quality", type=Path, default=None)
    parser.add_argument("--all", action="store_true", help="Fill benchmark columns for every scheme, then stop.")
    args = parser.parse_args(argv)
    as_of = args.as_of or _store_as_of(args.db)
    raw = ROOT / "data" / "raw" / as_of
    nav = args.nav or raw / "amfi_nav_master.parquet"
    if args.all:
        print(f"measuring every scheme as of {as_of}", flush=True)
        summary = fill_all_benchmark_metrics(args.db, nav, as_of)
        print(
            f"done: {summary['with_benchmark_cagr']} of {summary['schemes']} schemes have an index CAGR",
            flush=True,
        )
        return 0
    details = args.details or raw / "scheme_details_latest.parquet"
    quality = args.quality or raw / "data_quality.csv"
    print(run_demonstration(args.db, details, nav, quality, as_of))
    return 0


def _store_as_of(db_path: Path) -> str:
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT as_of FROM job_run ORDER BY built_at DESC LIMIT 1").fetchone()
    finally:
        con.close()
    if row is None or not row[0]:
        raise SystemExit("the fund store has no as-of date; pass --as-of")
    return str(row[0])[:10]


if __name__ == "__main__":
    raise SystemExit(main())
