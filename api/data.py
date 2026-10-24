"""Fund figures the report is built from. This is Tig Zig data, not a user's file."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from pipeline.assemble import load_quality

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FundData:
    catalog: list[dict]
    details: dict[int, dict]
    metrics: dict[int, dict]
    medians: dict[tuple, tuple]
    quality: dict[int, str]
    as_of: str
    preferred: set[int] = field(default_factory=set)


def _db_as_of(db_path: Path) -> str:
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT as_of FROM job_run ORDER BY built_at DESC LIMIT 1").fetchone()
        if row and row[0]:
            return str(row[0])[:10]
        row = con.execute("SELECT max(as_of) FROM scheme_metrics").fetchone()
        if row and row[0]:
            return str(row[0])[:10]
    finally:
        con.close()
    raise FileNotFoundError("no as-of date in the fund store")


def _metrics(db_path: Path) -> dict[int, dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT * FROM scheme_metrics").fetchall()
        return {int(row["scheme_code"]): dict(row) for row in rows}
    finally:
        con.close()


def _medians(db_path: Path) -> dict[tuple, tuple]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT category, plan, median_ter_pct, fund_count FROM category_median_ter"
        ).fetchall()
        return {(row[0], row[1]): (row[2], row[3]) for row in rows}
    finally:
        con.close()


def _schemes(details_path: Path) -> tuple[list[dict], dict[int, dict]]:
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
            """,
            {"details": str(details_path)},
        )
        cols = [d[0] for d in cursor.description]
        details = {}
        catalog = []
        for row in cursor.fetchall():
            item = dict(zip(cols, row))
            code = int(item["scheme_code"])
            item["scheme_code"] = code
            details[code] = item
            catalog.append({
                "scheme_code": code,
                "scheme_name": item.get("scheme_name"),
                "fund_name_latest": item.get("fund_name_latest"),
                "isin": item.get("isin"),
                "isin2": item.get("isin2"),
            })
        return catalog, details
    finally:
        con.close()


def load_fund_data(db_path: Path | None = None, details_path: Path | None = None,
                   quality_path: Path | None = None) -> FundData:
    db_path = db_path or ROOT / "data" / "store" / "mf.sqlite"
    as_of = _db_as_of(db_path)
    raw = ROOT / "data" / "raw" / as_of
    details_path = details_path or raw / "scheme_details_latest.parquet"
    quality_path = quality_path or raw / "data_quality.csv"
    catalog, details = _schemes(details_path)
    metrics = _metrics(db_path)
    return FundData(
        catalog=catalog,
        details=details,
        metrics=metrics,
        medians=_medians(db_path),
        quality=load_quality(quality_path) if quality_path.exists() else {},
        as_of=as_of,
        preferred=set(metrics),
    )
