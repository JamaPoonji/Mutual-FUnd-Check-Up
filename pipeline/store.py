"""SQLite publication of the nightly tables.

The uploaded holdings file never lands here. These tables are TigZig fund data only.
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Iterable, Mapping

from pipeline.metrics import BENCHMARK_METRIC_COLUMNS

SCHEME_COLUMNS = (
    "scheme_code", "scheme_name", "isin", "category_sub", "category_group", "scheme_plan",
    "as_of", "history_years", "benchmark_name",
    "cagr_1y", "cagr_3y", "cagr_5y",
    "bench_cagr_1y", "bench_cagr_3y", "bench_cagr_5y",
    "calendar_returns_json", "bench_calendar_returns_json",
    "rolling_window_years", "rolling_beat_pct",
    "upside_capture", "downside_capture", "capture_years", "capture_obs",
    "max_drawdown", "bench_max_drawdown", "drawdown_event",
    "recovery_months", "bench_recovery_months", "still_underwater",
    "quartile_1y", "quartile_3y", "quartile_5y", "peer_count",
)

_SCHEMA = """
CREATE TABLE category_median_ter (
  category_group TEXT,
  category TEXT NOT NULL,
  plan TEXT NOT NULL,
  median_ter_pct REAL,
  fund_count INTEGER,
  p25_ter_pct REAL,
  p75_ter_pct REAL,
  latest_ter_date TEXT,
  PRIMARY KEY (category_group, category, plan)
);
CREATE TABLE category_quartiles (
  scheme_code INTEGER NOT NULL,
  category TEXT,
  plan TEXT,
  yrs INTEGER NOT NULL,
  cagr_pct REAL,
  rnk INTEGER,
  n INTEGER,
  quartile INTEGER,
  as_of TEXT NOT NULL,
  PRIMARY KEY (scheme_code, yrs)
);
CREATE TABLE scheme_metrics (
  scheme_code INTEGER PRIMARY KEY,
  scheme_name TEXT,
  isin TEXT,
  category_sub TEXT,
  category_group TEXT,
  scheme_plan TEXT,
  as_of TEXT,
  history_years REAL,
  benchmark_name TEXT,
  cagr_1y REAL, cagr_3y REAL, cagr_5y REAL,
  bench_cagr_1y REAL, bench_cagr_3y REAL, bench_cagr_5y REAL,
  calendar_returns_json TEXT, bench_calendar_returns_json TEXT,
  rolling_window_years INTEGER, rolling_beat_pct REAL,
  upside_capture REAL, downside_capture REAL, capture_years INTEGER, capture_obs INTEGER,
  max_drawdown REAL, bench_max_drawdown REAL, drawdown_event TEXT,
  recovery_months INTEGER, bench_recovery_months INTEGER, still_underwater INTEGER,
  quartile_1y INTEGER, quartile_3y INTEGER, quartile_5y INTEGER,
  peer_count INTEGER
);
CREATE INDEX idx_scheme_metrics_isin ON scheme_metrics(isin);
CREATE TABLE index_series (
  benchmark_name TEXT NOT NULL,
  date TEXT NOT NULL,
  level REAL NOT NULL,
  source TEXT NOT NULL,
  kind TEXT NOT NULL,
  PRIMARY KEY (benchmark_name, date)
);
CREATE TABLE job_run (
  built_at TEXT NOT NULL,
  as_of TEXT NOT NULL,
  median_rows INTEGER,
  quartile_rows INTEGER,
  scheme_rows INTEGER,
  nonpositive_nav_rows INTEGER
);
CREATE TABLE scheme_details (
  scheme_code INTEGER PRIMARY KEY,
  scheme_name TEXT,
  fund_name_latest TEXT,
  isin TEXT,
  isin2 TEXT,
  scheme_plan TEXT,
  category_sub TEXT,
  category_group TEXT,
  ter_direct REAL,
  ter_regular REAL,
  ter_date TEXT,
  aum_cr REAL,
  riskometer TEXT,
  riskometer_benchmark TEXT,
  fund_managers TEXT,
  allotment_date TEXT,
  exit_load TEXT
);
CREATE TABLE scheme_quality (
  scheme_code INTEGER PRIMARY KEY,
  note TEXT NOT NULL
);
"""



DETAIL_COLUMNS = (
    "scheme_code", "scheme_name", "fund_name_latest", "isin", "isin2", "scheme_plan",
    "category_sub", "category_group", "ter_direct", "ter_regular", "ter_date", "aum_cr",
    "riskometer", "riskometer_benchmark", "fund_managers", "allotment_date", "exit_load",
)
def _num(value):
    if value is None or value == "":
        return None
    return float(value)


def _int(value):
    if value is None or value == "":
        return None
    return int(value)


def load_median_rows(csv_path: Path) -> list[dict]:
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            rows.append({
                "category_group": raw.get("category_group") or "",
                "category": raw["category"],
                "plan": raw["plan"],
                "median_ter_pct": _num(raw.get("median_ter_pct")),
                "fund_count": _int(raw.get("fund_count")),
                "p25_ter_pct": _num(raw.get("p25_ter_pct")),
                "p75_ter_pct": _num(raw.get("p75_ter_pct")),
                "latest_ter_date": raw.get("latest_ter_date") or None,
            })
    return rows


def _existing_index_rows(old_path: Path) -> list[tuple]:
    """Rows already published. A nightly rebuild must not drop the index series."""
    if not old_path.exists() or old_path.stat().st_size == 0:
        return []
    try:
        old = sqlite3.connect(f"file:{old_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        found = old.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'index_series'"
        ).fetchone()
        if not found:
            return []
        return old.execute(
            "SELECT benchmark_name, date, level, source, kind FROM index_series"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        old.close()


def write_index_series(db_path: Path, rows: Iterable[Mapping]) -> int:
    """Replace the stored days for the benchmarks in rows. Other tables stay."""
    pending = list(rows)
    if not pending:
        raise ValueError("no index rows to store")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS index_series (
              benchmark_name TEXT NOT NULL,
              date TEXT NOT NULL,
              level REAL NOT NULL,
              source TEXT NOT NULL,
              kind TEXT NOT NULL,
              PRIMARY KEY (benchmark_name, date)
            );
            """
        )
        con.execute("BEGIN")
        names = sorted({row["benchmark_name"] for row in pending})
        con.executemany("DELETE FROM index_series WHERE benchmark_name = ?", [(name,) for name in names])
        con.executemany(
            """INSERT INTO index_series (benchmark_name, date, level, source, kind)
               VALUES (:benchmark_name, :date, :level, :source, :kind)""",
            pending,
        )
        con.commit()
        return len(pending)
    except Exception:
        if con.in_transaction:
            con.rollback()
        raise
    finally:
        con.close()


def update_benchmark_metrics(db_path: Path, rows: Iterable[Mapping]) -> int:
    """Write benchmark-relative columns for schemes already in scheme_metrics.

    Other columns, including the fund's own CAGR, are left as they are.
    A scheme code that is not already stored rolls the whole update back.
    """
    pending = list(rows)
    if not pending:
        return 0
    assign = ", ".join(f"{column} = :{column}" for column in BENCHMARK_METRIC_COLUMNS)
    con = sqlite3.connect(db_path)
    try:
        con.execute("BEGIN")
        for row in pending:
            payload = {column: row.get(column) for column in BENCHMARK_METRIC_COLUMNS}
            payload["scheme_code"] = int(row["scheme_code"])
            found = con.execute(
                "SELECT 1 FROM scheme_metrics WHERE scheme_code = ?",
                (payload["scheme_code"],),
            ).fetchone()
            if found is None:
                raise ValueError(f"scheme {payload['scheme_code']} is not in scheme_metrics")
            con.execute(
                f"UPDATE scheme_metrics SET {assign} WHERE scheme_code = :scheme_code",
                payload,
            )
        con.commit()
        return len(pending)
    except Exception:
        if con.in_transaction:
            con.rollback()
        raise
    finally:
        con.close()


def write_store(db_path: Path, medians: Iterable[Mapping], quartiles: Iterable[Mapping],
                schemes: Iterable[Mapping], job: Mapping) -> None:
    """Replace db_path with a new store. A failed build leaves the previous file in place."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    kept_indices = _existing_index_rows(db_path)
    tmp = db_path.with_name(db_path.name + ".building")
    if tmp.exists():
        tmp.unlink()
    try:
        con = sqlite3.connect(tmp)
        try:
            con.executescript(_SCHEMA)
            if kept_indices:
                con.executemany(
                    """INSERT INTO index_series (benchmark_name, date, level, source, kind)
                       VALUES (?, ?, ?, ?, ?)""",
                    kept_indices,
                )
            con.executemany(
                """INSERT INTO category_median_ter
                   (category_group, category, plan, median_ter_pct, fund_count,
                    p25_ter_pct, p75_ter_pct, latest_ter_date)
                   VALUES (:category_group, :category, :plan, :median_ter_pct, :fund_count,
                           :p25_ter_pct, :p75_ter_pct, :latest_ter_date)""",
                list(medians),
            )
            con.executemany(
                """INSERT INTO category_quartiles
                   (scheme_code, category, plan, yrs, cagr_pct, rnk, n, quartile, as_of)
                   VALUES (:scheme_code, :category, :plan, :yrs, :cagr_pct, :rnk, :n, :quartile, :as_of)""",
                list(quartiles),
            )
            placeholders = ", ".join(":" + c for c in SCHEME_COLUMNS)
            con.executemany(
                f"INSERT INTO scheme_metrics ({', '.join(SCHEME_COLUMNS)}) VALUES ({placeholders})",
                [{c: row.get(c) for c in SCHEME_COLUMNS} for row in schemes],
            )
            con.execute(
                """INSERT INTO job_run
                   (built_at, as_of, median_rows, quartile_rows, scheme_rows, nonpositive_nav_rows)
                   VALUES (:built_at, :as_of, :median_rows, :quartile_rows, :scheme_rows, :nonpositive_nav_rows)""",
                dict(job),
            )
            con.commit()
        finally:
            con.close()
        tmp.replace(db_path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def quartile_insert_row(raw: Mapping, as_of: str) -> dict:
    def num(key):
        v = raw.get(key)
        return None if v is None else float(v)

    def whole(key):
        v = raw.get(key)
        return None if v is None else int(v)

    return {
        "scheme_code": int(raw["scheme_code"]),
        "category": raw.get("category"),
        "plan": raw.get("plan"),
        "yrs": int(raw["yrs"]),
        "cagr_pct": num("cagr_pct"),
        "rnk": whole("rnk"),
        "n": whole("n"),
        "quartile": whole("quartile"),
        "as_of": as_of,
    }


def has_index_rows(db_path: Path) -> bool:
    """True when the store already carries benchmark index levels.

    `pipeline.nightly` needs them before it can fill benchmark-relative columns,
    and downloading the 178 MB NAV master first only to fail is wasteful, so the
    job checks this up front.
    """
    if not db_path.exists():
        return False
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT count(*) FROM index_series").fetchone()
        return bool(row and row[0])
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


def write_details(db_path: Path, details: Iterable[Mapping], quality: Mapping[int, str] | None = None) -> int:
    """Store per-scheme detail rows and data-quality notes in the runtime store.

    Keeping them here is what lets the runtime image carry one file instead of a
    parquet plus the `data/raw/<as-of>/` directory.
    """
    detail_rows = list(details)
    con = sqlite3.connect(db_path)
    try:
        con.execute("DELETE FROM scheme_details")
        con.executemany(
            f"INSERT INTO scheme_details ({', '.join(DETAIL_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in DETAIL_COLUMNS)})",
            [
                tuple(row.get(column) for column in DETAIL_COLUMNS)
                for row in detail_rows
            ],
        )
        if quality is not None:
            con.execute("DELETE FROM scheme_quality")
            con.executemany(
                "INSERT INTO scheme_quality (scheme_code, note) VALUES (?, ?)",
                sorted((int(code), str(note)) for code, note in quality.items()),
            )
        con.commit()
        return len(detail_rows)
    finally:
        con.close()
