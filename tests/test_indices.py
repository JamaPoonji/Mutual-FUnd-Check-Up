"""NSE total-return parsing and storage. No network."""
import json
import sqlite3
from datetime import date

import pytest

from pipeline.indices import (EmptyIndexSeries, fetch_all, nse_date, parse_nse_date,
                              parse_tri_payload, render_summary, series_stats)
from pipeline.store import write_index_series, write_store

ASOF = date(2026, 10, 14)


def _body(rows):
    return {"d": json.dumps(rows)}


def test_nse_dates_are_english_and_not_locale_dependent():
    assert nse_date(date(2026, 10, 14)) == "14-Oct-2026"
    assert parse_nse_date("22 May 2026") == date(2026, 5, 22)


def test_parser_keeps_total_return_levels_and_drops_the_net_series():
    rows = parse_tri_payload(_body([
        {"Date": "13 Oct 2026", "TotalReturnsIndex": "36000.50", "NTR_Value": "31000"},
        {"Date": "12 Oct 2026", "TotalReturnsIndex": "35900", "NTR_Value": "30900"},
        {"Date": "13 Oct 2026", "TotalReturnsIndex": "1", "NTR_Value": "1"},
        {"Date": "11 Oct 2026", "TotalReturnsIndex": "0", "NTR_Value": "0"},
    ]), "NIFTY 50")
    assert [row["date"] for row in rows] == ["2026-10-12", "2026-10-13"]
    assert rows[-1]["level"] == 36000.50
    assert "ntr" not in rows[-1]


def test_a_bare_json_list_is_the_current_response_shape():
    rows = parse_tri_payload([
        {"Date": "14 Oct 2026", "TotalReturnsIndex": "34379.06", "NTR_Value": "29852.04"},
    ], "NIFTY 50")
    assert rows == [{"date": "2026-10-14", "level": 34379.06}]


def test_an_empty_payload_fails_instead_of_storing_a_gap():
    with pytest.raises(EmptyIndexSeries):
        parse_tri_payload({"d": "[]"}, "NIFTY 100")
    with pytest.raises(EmptyIndexSeries):
        parse_tri_payload({}, "NIFTY 100")


def test_fetch_all_stops_on_the_first_empty_name_and_does_not_invent_one():
    calls = []

    def fetch(name, start, end):
        calls.append(name)
        if name == "NIFTY 100":
            raise EmptyIndexSeries(f"{name} returned no total-return rows")
        return [{"date": "2026-10-13", "level": 100.0}]

    with pytest.raises(EmptyIndexSeries, match="NIFTY 100"):
        fetch_all(ASOF, fetch=fetch, pause=0)
    assert calls == ["NIFTY 50", "NIFTY 100"]


def test_index_rows_land_beside_scheme_metrics_and_survive_a_rebuild(tmp_path):
    db = tmp_path / "mf.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE IF NOT EXISTS scheme_metrics (scheme_code INTEGER PRIMARY KEY)")
    con.execute("INSERT INTO scheme_metrics (scheme_code) VALUES (1)")
    con.commit()
    con.close()

    rows = [{
        "benchmark_name": "Nifty 50 TRI", "date": "2026-10-13", "level": 36000.5,
        "source": "NSE Indices (niftyindices.com)", "kind": "TRI",
    }]
    assert write_index_series(db, rows) == 1
    con = sqlite3.connect(db)
    assert con.execute("SELECT scheme_code FROM scheme_metrics").fetchone()[0] == 1
    stored = con.execute("SELECT benchmark_name, kind, source, level FROM index_series").fetchone()
    con.close()
    assert stored == ("Nifty 50 TRI", "TRI", "NSE Indices (niftyindices.com)", 36000.5)

    write_store(
        db,
        [{"category_group": "Equity Scheme", "category": "Flexi Cap Fund", "plan": "Direct",
          "median_ter_pct": 0.91, "fund_count": 43, "p25_ter_pct": 0.8, "p75_ter_pct": 1.2,
          "latest_ter_date": "2026-10-11"}],
        [],
        [],
        {"built_at": "2026-10-14T00:00:00Z", "as_of": "2026-10-14", "median_rows": 1,
         "quartile_rows": 0, "scheme_rows": 0, "nonpositive_nav_rows": 0},
    )
    con = sqlite3.connect(db)
    kept = con.execute("SELECT level, kind FROM index_series").fetchone()
    medians = con.execute("SELECT count(*) FROM category_median_ter").fetchone()[0]
    con.close()
    assert kept == (36000.5, "TRI") and medians == 1


def test_summary_shows_the_price_gap_and_does_not_call_yahoo_a_stored_source():
    rows = []
    for name, level in (
        ("Nifty 50 TRI", 36000.5),
        ("Nifty 100 TRI", 30000.0),
        ("Nifty 500 TRI", 28000.0),
        ("Nifty Midcap 150 TRI", 22000.0),
        ("Nifty Smallcap 250 TRI", 18000.0),
    ):
        rows.append({
            "benchmark_name": name, "date": "2026-10-13", "level": level,
            "source": "NSE Indices (niftyindices.com)", "kind": "TRI",
        })
    text = render_summary(rows, ("2026-10-13", 22721.95))
    assert "Nifty 50 TRI: 2026-10-13 .. 2026-10-13  n=1  latest 36000.50" in text
    assert "Nifty Smallcap 250 TRI" in text
    assert "TRI 36000.50 vs Yahoo ^NSEI close 22721.95" in text
    assert "not stored" in text
    assert series_stats(rows)[0]["kind"] == "TRI"
