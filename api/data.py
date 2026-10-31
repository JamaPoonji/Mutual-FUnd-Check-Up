"""Fund figures the report is built from. This is Tig Zig data, not a user's file.

Everything here is read from the single SQLite file that `pipeline.nightly`
writes: scheme metrics, category medians, per-scheme details and data-quality
notes. The 178 MB NAV master and the parquet files stay in the build job, so the
runtime image needs one 5 MB file and no duckdb.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "store" / "mf.sqlite"

DETAIL_COLUMNS = (
    "scheme_code", "scheme_name", "fund_name_latest", "isin", "isin2", "scheme_plan",
    "category_sub", "category_group", "ter_direct", "ter_regular", "ter_date",
    "aum_cr", "riskometer", "riskometer_benchmark", "fund_managers",
    "allotment_date", "exit_load",
)
CATALOG_COLUMNS = ("scheme_code", "scheme_name", "fund_name_latest", "isin", "isin2")
STORE_TABLES = ("scheme_metrics", "category_median_ter", "job_run", "scheme_details")


@dataclass
class FundData:
    catalog: list[dict]
    details: dict[int, dict]
    metrics: dict[int, dict]
    medians: dict[tuple, tuple]
    quality: dict[int, str]
    as_of: str
    preferred: set[int] = field(default_factory=set)


class StoreNotReady(Exception):
    """The store is missing, unreadable, or built by an older pipeline."""


def _connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise StoreNotReady(f"fund store not found at {db_path}")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _missing_table(con: sqlite3.Connection) -> str | None:
    present = {
        row["name"]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    for table in STORE_TABLES:
        if table not in present:
            return table
    return None


def _as_of(con: sqlite3.Connection) -> str:
    row = con.execute("SELECT as_of FROM job_run ORDER BY built_at DESC LIMIT 1").fetchone()
    if row and row[0]:
        return str(row[0])[:10]
    row = con.execute("SELECT max(as_of) FROM scheme_metrics").fetchone()
    if row and row[0]:
        return str(row[0])[:10]
    raise StoreNotReady("no as-of date in the fund store")


def _details(con: sqlite3.Connection) -> tuple[list[dict], dict[int, dict]]:
    columns = ", ".join(DETAIL_COLUMNS)
    rows = con.execute(f"SELECT {columns} FROM scheme_details").fetchall()
    details: dict[int, dict] = {}
    catalog: list[dict] = []
    for row in rows:
        item = dict(zip(DETAIL_COLUMNS, tuple(row)))
        code = int(item["scheme_code"])
        item["scheme_code"] = code
        details[code] = item
        catalog.append({column: item.get(column) for column in CATALOG_COLUMNS})
    return catalog, details


def _metrics(con: sqlite3.Connection) -> dict[int, dict]:
    rows = con.execute("SELECT * FROM scheme_metrics").fetchall()
    return {int(row["scheme_code"]): dict(row) for row in rows}


def _medians(con: sqlite3.Connection) -> dict[tuple, tuple]:
    rows = con.execute(
        "SELECT category, plan, median_ter_pct, fund_count FROM category_median_ter"
    ).fetchall()
    return {(row[0], row[1]): (row[2], row[3]) for row in rows}


def _quality(con: sqlite3.Connection) -> dict[int, str]:
    rows = con.execute("SELECT scheme_code, note FROM scheme_quality").fetchall()
    return {int(row[0]): str(row[1]) for row in rows}


def load_fund_data(db_path: Path | None = None) -> FundData:
    """Read the runtime store. Raises StoreNotReady with a usable message."""
    path = Path(db_path) if db_path else DEFAULT_DB
    con = _connect(path)
    try:
        missing = _missing_table(con)
        if missing:
            raise StoreNotReady(
                f"fund store at {path} has no {missing} table; rebuild it with "
                "`python -m pipeline.indices` then `python -m pipeline.nightly`"
            )
        as_of = _as_of(con)
        catalog, details = _details(con)
        metrics = _metrics(con)
        return FundData(
            catalog=catalog,
            details=details,
            metrics=metrics,
            medians=_medians(con),
            quality=_quality(con),
            as_of=as_of,
            preferred=set(metrics),
        )
    finally:
        con.close()
