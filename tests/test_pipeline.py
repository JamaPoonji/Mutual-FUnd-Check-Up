"""Mappers and the nightly store. Fixtures are tiny parquet files; nothing hits the network."""
from datetime import date, timedelta

import duckdb
import pytest

from mf_plain import quartile_from_rank
from pipeline.metrics import (BENCHMARK_METRIC_COLUMNS, benchmark_name_for, cagr_pct,
                              history_years, index_by_horizon, peer_count_for, scheme_metrics_row)
from pipeline.nightly import build_store
from pipeline.quartiles import run_all_quartiles, run_reference
from pipeline.store import write_store

ASOF = date(2026, 10, 14)
END = ASOF.isoformat()
D1 = (ASOF - timedelta(days=365)).isoformat()
D3 = (ASOF - timedelta(days=365 * 3)).isoformat()
D5 = (ASOF - timedelta(days=365 * 5)).isoformat()
D_YOUNG = (ASOF - timedelta(days=100)).isoformat()


def _copy(con, table: str, path) -> None:
    con.execute(f"COPY {table} TO '{path}' (FORMAT PARQUET)")


def _details(path) -> None:
    con = duckdb.connect()
    con.execute("""
      CREATE TABLE d (
        scheme_code INTEGER, scheme_name VARCHAR, isin VARCHAR,
        category_sub VARCHAR, category_group_clean VARCHAR, scheme_plan VARCHAR,
        is_active BOOLEAN, amfi_ssd_fund_id VARCHAR,
        ter_direct DOUBLE, ter_regular DOUBLE, ter_date VARCHAR
      )
    """)
    rows = []
    directs = [(1, 0.50, 1.50), (2, 0.70, 1.70), (3, 0.90, 1.90), (4, 1.10, 2.10)]
    for code, ter_d, ter_r in directs:
        rows.append((code, f"Flexi {code} Direct Growth", f"INF00000000{code}",
                     "Flexi Cap Fund", "Equity Scheme", "Direct", True, f"F{code}",
                     ter_d, ter_r, "2026-10-11"))
        rows.append((code + 10, f"Flexi {code} Regular Growth", f"INF00000001{code}",
                     "Flexi Cap Fund", "Equity Scheme", "Regular", True, f"F{code}",
                     ter_d, ter_r, "2026-10-11"))
    rows.append((5, "Young Direct Growth", "INF000000005",
                 "Test Young Fund", "Equity Scheme", "Direct", True, "FY",
                 0.40, None, "2026-10-11"))
    rows.append((6, "Some Dividend Yield Fund Direct Growth", "INF000000006",
                 "Dividend Yield Fund", "Equity Scheme", "Direct", True, "FD",
                 0.60, None, "2026-10-11"))
    rows.append((7, "Skipped Direct IDCW", "INF000000007",
                 "Flexi Cap Fund", "Equity Scheme", "Direct", True, "FI",
                 None, None, None))
    rows.append((8, "Closed Direct Growth", "INF000000008",
                 "Flexi Cap Fund", "Equity Scheme", "Direct", False, "FC",
                 0.10, 0.10, "2026-10-11"))
    for code, ter in ((21, 0.20), (22, 0.30), (23, 0.40)):
        rows.append((code, f"Thin {code} Direct Growth", f"INF0000000{code}",
                     "Thin Fund", "Equity Scheme", "Direct", True, f"T{code}",
                     ter, None, "2026-10-11"))
    con.executemany("INSERT INTO d VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    _copy(con, "d", path)
    con.close()


def _nav(path) -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE n (scheme_code INTEGER, date VARCHAR, nav DOUBLE)")
    points = []
    ends = {1: 200.0, 2: 150.0, 3: 120.0, 4: 80.0, 11: 190.0, 12: 140.0, 13: 110.0, 14: 70.0,
            21: 130.0, 22: 110.0, 23: 90.0}
    for code, end_nav in ends.items():
        for day in (D5, D3, D1, END):
            points.append((code, day, 100.0 if day != END else end_nav))
    points.append((5, D_YOUNG, 10.0))
    points.append((5, END, 11.0))
    con.executemany("INSERT INTO n VALUES (?,?,?)", points)
    _copy(con, "n", path)
    con.close()


def test_history_years_uses_actual_days_and_skips_missing():
    assert history_years("2021-10-15", "2026-10-14") == 5.0   # 1825 days, five 365-day years
    assert history_years(None, "2026-10-14") is None
    assert history_years("", "2026-10-14") is None
    assert history_years("2026-10-15", "2026-10-14") is None   # inverted, not clamped to 0


def test_cagr_formula_and_missing_inputs():
    assert cagr_pct(200, 100, 1825) == round((2 ** (365 / 1825) - 1) * 100, 2)
    assert cagr_pct(200, 100, 365) == 100.0
    assert cagr_pct(0, 100, 365) is None
    assert cagr_pct(100, 100, 0) is None
    assert cagr_pct(None, 100, 365) is None


def test_peer_count_follows_the_longest_horizon_with_a_quartile():
    by_year = {
        1: {"n": 10, "quartile": 1, "cagr_pct": 5.0},
        5: {"n": 4, "quartile": 2, "cagr_pct": 12.0},
    }
    assert peer_count_for(by_year) == 4
    assert peer_count_for({1: {"n": 3, "quartile": None, "cagr_pct": 5.0}}) == 3
    assert peer_count_for({}) is None


def test_index_by_horizon_keeps_one_row_per_year():
    got = index_by_horizon([
        {"yrs": 1, "cagr_pct": 10, "rnk": 1, "n": 4, "quartile": 1},
        {"yrs": None, "cagr_pct": 1, "rnk": 1, "n": 4, "quartile": 1},
    ])
    assert set(got) == {1}
    assert got[1]["cagr_pct"] == 10.0 and got[1]["quartile"] == 1


def test_benchmark_name_uses_the_engine_map_and_skips_a_blank_category():
    assert benchmark_name_for("Small Cap Fund") == "Nifty Smallcap 250 TRI"
    assert benchmark_name_for("Flexi Cap Fund") == "Nifty 500 TRI"
    assert benchmark_name_for("") is None
    assert benchmark_name_for(None) is None


def test_scheme_row_does_not_invent_benchmark_metrics():
    row = scheme_metrics_row(
        {"scheme_code": 1, "scheme_name": "A", "isin": "  ", "category_sub": "Flexi Cap Fund",
         "category_group": "Equity Scheme", "scheme_plan": "Direct"},
        {5: {"cagr_pct": 14.87, "quartile": 1, "n": 4, "rnk": 1}},
        "2026-10-14", "2021-10-15",
    )
    assert row["isin"] is None
    assert row["cagr_5y"] == 14.87 and row["cagr_1y"] is None and row["quartile_1y"] is None
    assert row["peer_count"] == 4 and row["history_years"] == 5.0
    assert row["benchmark_name"] == "Nifty 500 TRI"
    for column in BENCHMARK_METRIC_COLUMNS:
        assert row[column] is None


def test_reference_sql_matches_the_cagr_formula_and_quartile_from_rank(tmp_path):
    details, nav = tmp_path / "d.parquet", tmp_path / "n.parquet"
    _details(details)
    _nav(nav)
    con = duckdb.connect()
    rows = run_reference(con, nav, details, END, "Flexi Cap Fund", "Direct")
    con.close()
    by_code = {}
    for row in rows:
        by_code.setdefault(int(row["scheme_code"]), {})[int(row["yrs"])] = row
    assert set(by_code) == {1, 2, 3, 4}
    fund = by_code[1]
    assert float(fund[1]["cagr_pct"]) == cagr_pct(200, 100, 365)
    assert float(fund[3]["cagr_pct"]) == cagr_pct(200, 100, 365 * 3)
    assert float(fund[5]["cagr_pct"]) == cagr_pct(200, 100, 365 * 5)
    for yrs in (1, 3, 5):
        assert int(fund[yrs]["rnk"]) == 1 and int(fund[yrs]["n"]) == 4
        assert int(fund[yrs]["quartile"]) == quartile_from_rank(1, 4)
        assert int(by_code[4][yrs]["quartile"]) == quartile_from_rank(4, 4)


def test_batch_quartiles_match_reference_sql(tmp_path):
    details, nav = tmp_path / "d.parquet", tmp_path / "n.parquet"
    _details(details)
    _nav(nav)
    con = duckdb.connect()
    batch = run_all_quartiles(con, nav, details, END)
    ref = []
    for category, plan in (("Flexi Cap Fund", "Direct"), ("Flexi Cap Fund", "Regular"),
                           ("Thin Fund", "Direct"), ("Test Young Fund", "Direct")):
        for row in run_reference(con, nav, details, END, category, plan):
            row = dict(row)
            row["category"] = category
            row["plan"] = plan
            ref.append(row)
    con.close()

    def key(row):
        return (int(row["scheme_code"]), int(row["yrs"]))

    assert {key(r) for r in batch} == {key(r) for r in ref}
    ref_by = {key(r): r for r in ref}
    for got in batch:
        src = ref_by[key(got)]
        assert float(got["cagr_pct"]) == pytest.approx(float(src["cagr_pct"]))
        assert int(got["rnk"]) == int(src["rnk"]) and int(got["n"]) == int(src["n"])
        assert got["quartile"] == src["quartile"]
        assert got["category"] == src["category"] and got["plan"] == src["plan"]
    # Three peers is not a quartile. The young fund is not old enough for any horizon.
    thin = [r for r in batch if r["category"] == "Thin Fund"]
    assert thin and all(r["quartile"] is None and int(r["n"]) == 3 for r in thin)
    assert not any(int(r["scheme_code"]) == 5 for r in batch)


def test_build_store_publishes_medians_quartiles_and_leaves_benchmarks_empty(tmp_path):
    details, nav = tmp_path / "d.parquet", tmp_path / "n.parquet"
    _details(details)
    _nav(nav)
    db = tmp_path / "mf.sqlite"
    job = build_store(details, nav, db, END, tmp_path / "medians.csv")
    assert job["scheme_rows"] == 4 + 4 + 1 + 3   # flexi both plans, young, thin
    assert job["nonpositive_nav_rows"] == 0

    import sqlite3
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    direct = con.execute(
        "SELECT * FROM category_median_ter WHERE category = 'Flexi Cap Fund' AND plan = 'Direct'"
    ).fetchone()
    regular = con.execute(
        "SELECT * FROM category_median_ter WHERE category = 'Flexi Cap Fund' AND plan = 'Regular'"
    ).fetchone()
    # Two plan rows of one fund count once. The IDCW and closed rows are not extra funds.
    assert direct["fund_count"] == 4 and direct["median_ter_pct"] == 0.8
    assert regular["fund_count"] == 4 and regular["median_ter_pct"] == 1.8

    best = con.execute("SELECT * FROM scheme_metrics WHERE scheme_code = 1").fetchone()
    assert best["cagr_1y"] == cagr_pct(200, 100, 365)
    assert best["quartile_5y"] == 1 and best["peer_count"] == 4
    assert best["benchmark_name"] == "Nifty 500 TRI"
    assert best["bench_cagr_5y"] is None and best["rolling_beat_pct"] is None
    assert best["upside_capture"] is None and best["max_drawdown"] is None
    assert best["calendar_returns_json"] is None and best["still_underwater"] is None

    young = con.execute("SELECT * FROM scheme_metrics WHERE scheme_code = 5").fetchone()
    assert young["cagr_1y"] is None and young["quartile_1y"] is None
    assert young["history_years"] == history_years(D_YOUNG, END)
    assert young["benchmark_name"] == "Nifty 50 TRI"

    codes = {r[0] for r in con.execute("SELECT scheme_code FROM scheme_metrics")}
    assert 6 not in codes and 7 not in codes and 8 not in codes
    thin = con.execute("SELECT quartile_5y, peer_count FROM scheme_metrics WHERE scheme_code = 21").fetchone()
    assert thin["quartile_5y"] is None and thin["peer_count"] == 3
    con.close()


def test_a_failed_publish_does_not_replace_the_existing_store(tmp_path):
    db = tmp_path / "mf.sqlite"
    db.write_text("keep")
    with pytest.raises(Exception):
        write_store(db, [{"category_group": "x"}], [], [], {})
    assert db.read_text() == "keep"
    assert not (tmp_path / "mf.sqlite.building").exists()
