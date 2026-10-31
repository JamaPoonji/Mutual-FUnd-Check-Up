"""Nightly job: TigZig scheme details + NAV history -> local SQLite.

Writes data/store/mf.sqlite with category_median_ter, category_quartiles and
scheme_metrics, then fills benchmark-relative columns from the stored
total-return series. Debt and the other non-compared categories stay without an index.
Dated copies of the downloads sit in data/raw/<as-of>/.

    python -m pipeline.nightly
    python -m pipeline.nightly --as-of 2026-10-14

Run `python -m pipeline.indices` first. This job fills benchmark-relative
columns from the stored TRI series, so it checks for that series before
downloading and stops with a clear message when it is missing.

Fund data only. This job never sees a holdings file.
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from pipeline.assemble import fill_all_benchmark_metrics, load_details_all, load_quality
from pipeline.metrics import index_by_horizon, scheme_metrics_row
from pipeline.quartiles import (connect, load_first_dates, load_schemes, nonpositive_nav_count,
                                run_all_quartiles, run_reference)
from pipeline.store import (has_index_rows, load_median_rows, quartile_insert_row,
                            write_details, write_store)

ROOT = Path(__file__).resolve().parent.parent
DETAILS_URL = "https://api.tigzig.com/mf/v1/download/scheme_details_latest.parquet"
NAV_URL = "https://api.tigzig.com/mf/v1/download/amfi_nav_master.parquet"
QUALITY_URL = "https://api.tigzig.com/mf/v1/download/data_quality.csv"
QUALITY_URL_FALLBACK = "https://api.tigzig.com/mf/v1/download/data_quality?format=csv"
USER_AGENT = "MFRoboAdvisor/0.1 (nightly scheme-metrics job; fund data only)"


def _download_once(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    if tmp.exists():
        tmp.unlink()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as resp, open(tmp, "wb") as fh:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)
        expected = resp.headers.get("Content-Length")
    size = tmp.stat().st_size
    if expected and size != int(expected):
        tmp.unlink()
        raise RuntimeError(f"download size {size} != Content-Length {expected} for {url}")
    if size == 0:
        tmp.unlink()
        raise RuntimeError(f"empty download: {url}")
    if dest.suffix == ".parquet":
        with open(tmp, "rb") as fh:
            if fh.read(4) != b"PAR1":
                tmp.unlink()
                raise RuntimeError(f"not a parquet file: {url}")
    tmp.replace(dest)


def download(url: str, dest: Path, fallback: str = "") -> None:
    try:
        _download_once(url, dest)
    except Exception:
        if not fallback:
            raise
        _download_once(fallback, dest)


def fetch_inputs(as_of: str, raw_root: Path) -> dict[str, Path]:
    """Dated copies. An existing valid file for this as-of is kept."""
    folder = raw_root / as_of
    folder.mkdir(parents=True, exist_ok=True)
    details = folder / "scheme_details_latest.parquet"
    nav = folder / "amfi_nav_master.parquet"
    quality = folder / "data_quality.csv"
    if not details.exists():
        print(f"downloading scheme details -> {details}", flush=True)
        download(DETAILS_URL, details)
    if not nav.exists():
        print(f"downloading NAV history -> {nav}", flush=True)
        download(NAV_URL, nav)
    if not quality.exists():
        print(f"downloading data quality -> {quality}", flush=True)
        download(QUALITY_URL, quality, QUALITY_URL_FALLBACK)
    return {"details": details, "nav": nav, "quality": quality}


def _run_medians(details: Path, out: Path) -> None:
    script = Path(__file__).with_name("build_category_medians.py")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(script), str(details), str(out)], check=True)


def _group(rows: list[dict]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        grouped.setdefault(int(row["scheme_code"]), []).append(row)
    return grouped


def build_store(details: Path, nav: Path, db_path: Path, as_of: str, medians_csv: Path) -> dict:
    """Build the three published tables. Does not download."""
    as_of = date.fromisoformat(as_of).isoformat()
    _run_medians(details, medians_csv)
    medians = load_median_rows(medians_csv)
    con = connect()
    try:
        schemes = load_schemes(con, details)
        first_dates = load_first_dates(con, nav, details, as_of)
        quartiles = run_all_quartiles(con, nav, details, as_of)
        dropped = nonpositive_nav_count(con, nav, details, as_of)
    finally:
        con.close()

    by_scheme = _group(quartiles)
    metric_rows = [
        scheme_metrics_row(s, index_by_horizon(by_scheme.get(int(s["scheme_code"]), [])),
                           as_of, first_dates.get(int(s["scheme_code"])))
        for s in schemes
    ]
    q_rows = []
    for raw in quartiles:
        row = quartile_insert_row(raw, as_of)
        # category and plan come back on the batch query; the reference SQL omits them.
        row["category"] = raw.get("category")
        row["plan"] = raw.get("plan")
        q_rows.append(row)
    job = {
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": as_of,
        "median_rows": len(medians),
        "quartile_rows": len(q_rows),
        "scheme_rows": len(metric_rows),
        "nonpositive_nav_rows": dropped,
    }
    write_store(db_path, medians, q_rows, metric_rows, job)
    return job


def spot_check(db_path: Path, details: Path, nav: Path, as_of: str,
               category: str = "Flexi Cap Fund", plan: str = "Direct") -> tuple[int, int]:
    """Compare stored quartiles with quartiles_and_cagr.sql for one category.

    Returns (reference rows, mismatches).
    """
    con = connect()
    try:
        ref = run_reference(con, nav, details, as_of, category, plan)
    finally:
        con.close()
    db = sqlite3.connect(db_path)
    try:
        batch = [
            dict(zip(("scheme_code", "yrs", "cagr_pct", "rnk", "n", "quartile"), row))
            for row in db.execute(
                """SELECT scheme_code, yrs, cagr_pct, rnk, n, quartile
                   FROM category_quartiles WHERE category = ? AND plan = ?""",
                (category, plan),
            )
        ]
    finally:
        db.close()
    ref_key = {(int(r["scheme_code"]), int(r["yrs"])): r for r in ref}
    bat_key = {(int(r["scheme_code"]), int(r["yrs"])): r for r in batch}
    mismatches = 0
    if set(ref_key) != set(bat_key):
        mismatches += abs(len(ref_key) - len(bat_key)) + len(set(ref_key) ^ set(bat_key))
    for key, got in bat_key.items():
        src = ref_key.get(key)
        if src is None:
            continue
        for col in ("cagr_pct", "rnk", "n", "quartile"):
            if _same(src.get(col), got.get(col)):
                continue
            mismatches += 1
            break
    return len(ref), mismatches


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) or isinstance(b, float):
        return abs(float(a) - float(b)) < 0.001
    return int(a) == int(b)


def render_summary(db_path: Path) -> str:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        job = con.execute("SELECT * FROM job_run").fetchone()
        filled = con.execute(
            """SELECT count(*) AS n FROM scheme_metrics
               WHERE bench_cagr_1y IS NOT NULL OR bench_cagr_3y IS NOT NULL OR bench_cagr_5y IS NOT NULL
                  OR calendar_returns_json IS NOT NULL OR rolling_beat_pct IS NOT NULL
                  OR upside_capture IS NOT NULL OR downside_capture IS NOT NULL
                  OR max_drawdown IS NOT NULL"""
        ).fetchone()["n"]
        cagr = con.execute(
            """SELECT
                 sum(cagr_1y IS NOT NULL) AS y1,
                 sum(cagr_3y IS NOT NULL) AS y3,
                 sum(cagr_5y IS NOT NULL) AS y5,
                 sum(quartile_5y IS NOT NULL) AS q5
               FROM scheme_metrics"""
        ).fetchone()
        samples = con.execute(
            """SELECT scheme_code, scheme_name, category_sub, scheme_plan,
                      cagr_1y, cagr_3y, cagr_5y, quartile_1y, quartile_3y, quartile_5y,
                      peer_count, history_years, benchmark_name
               FROM scheme_metrics
               WHERE cagr_5y IS NOT NULL
                 AND category_sub IN ('Flexi Cap Fund', 'Large Cap Fund', 'Mid Cap Fund', 'Small Cap Fund')
                 AND scheme_plan = 'Direct'
               ORDER BY category_sub, cagr_5y DESC"""
        ).fetchall()
        med = con.execute(
            """SELECT category, plan, median_ter_pct, fund_count
               FROM category_median_ter
               WHERE category IN ('Flexi Cap Fund', 'Large Cap Fund', 'Small Cap Fund')
               ORDER BY category, plan"""
        ).fetchall()
    finally:
        con.close()

    lines = [
        f"as_of {job['as_of']}  built {job['built_at']}",
        f"category_median_ter {job['median_rows']}  category_quartiles {job['quartile_rows']}  "
        f"scheme_metrics {job['scheme_rows']}",
        f"schemes with CAGR 1y/3y/5y: {cagr['y1']} / {cagr['y3']} / {cagr['y5']}; with a 5y quartile: {cagr['q5']}",
        f"benchmark-relative cells filled: {filled} (these wait for the index series)",
        f"non-positive NAV rows dropped: {job['nonpositive_nav_rows']}",
        "",
        "category median TER (same plan):",
    ]
    for row in med:
        lines.append(f"  {row['category']} {row['plan']}: {row['median_ter_pct']}%  n={row['fund_count']}")
    lines.append("")
    lines.append("sample direct growth schemes (5y CAGR, quartiles Q1 best):")
    shown = {}
    for row in samples:
        shown.setdefault(row["category_sub"], 0)
        if shown[row["category_sub"]] >= 2:
            continue
        shown[row["category_sub"]] += 1
        lines.append(
            f"  {row['scheme_code']} {row['scheme_name']} [{row['category_sub']}] "
            f"CAGR {row['cagr_1y']}/{row['cagr_3y']}/{row['cagr_5y']}  "
            f"Q {row['quartile_1y']}/{row['quartile_3y']}/{row['quartile_5y']}  "
            f"peers {row['peer_count']}  history {row['history_years']}y  "
            f"benchmark {row['benchmark_name']}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build scheme_metrics from TigZig MFPRO.")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="ISO date, default today")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "store" / "mf.sqlite")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--details", type=Path, help="local scheme_details parquet; skips that download")
    parser.add_argument("--nav", type=Path, help="local NAV parquet; skips that download")
    parser.add_argument("--no-spot-check", action="store_true")
    args = parser.parse_args(argv)
    as_of = date.fromisoformat(args.as_of).isoformat()

    if not has_index_rows(args.db):
        print(
            "no benchmark index series in the store; run `python -m pipeline.indices` first. "
            "Without the TRI levels this job would download the NAV master and then fail.",
            file=sys.stderr,
        )
        return 2

    if args.details and args.nav:
        paths = {
            "details": args.details,
            "nav": args.nav,
            "quality": args.details.with_name("data_quality.csv"),
        }
    else:
        paths = fetch_inputs(as_of, args.raw_dir)
        if args.details:
            paths["details"] = args.details
        if args.nav:
            paths["nav"] = args.nav

    medians_csv = paths["details"].with_name("category_median_ter.csv")
    print(f"building store as of {as_of}", flush=True)
    job = build_store(paths["details"], paths["nav"], args.db, as_of, medians_csv)
    print(f"wrote {args.db} ({job['scheme_rows']} schemes)", flush=True)
    quality_path = paths.get("quality")
    quality = load_quality(quality_path) if quality_path and quality_path.exists() else {}
    stored = write_details(args.db, load_details_all(paths["details"]), quality)
    print(f"stored {stored} scheme detail rows in the store", flush=True)
    if not args.no_spot_check:
        print("checking Flexi Cap Direct against quartiles_and_cagr.sql", flush=True)
        ref_n, mismatches = spot_check(args.db, paths["details"], paths["nav"], as_of)
        print(f"spot check: {ref_n} reference rows, {mismatches} mismatches", flush=True)
        if mismatches:
            return 1
    print(f"measuring every scheme against its category total-return index as of {as_of}", flush=True)
    summary = fill_all_benchmark_metrics(args.db, paths["nav"], as_of)
    print(
        f"benchmark measures: {summary['with_benchmark_cagr']} of {summary['schemes']} have an index CAGR",
        flush=True,
    )
    print(render_summary(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
