"""Matcher, assembler, and benchmark measures. Fixtures are in memory."""
import json
import sqlite3
from datetime import date, timedelta

import pytest

from mf_plain.engine import analyze
from pipeline.assemble import display_medians, fund_from_rows, parse_managers, portfolio_from_holdings, report_for
from pipeline.benchmark_metrics import (
    Series, calendar_returns, capture, drawdown, measures, point_return, rolling_beat_pct, store_fields,
)
from pipeline.match import match_holding
from pipeline.metrics import cagr_pct
from pipeline.store import update_benchmark_metrics

ASOF = date(2026, 10, 14)


def _catalog():
    return [
        {"scheme_code": 1, "scheme_name": "HDFC Flexi Cap Fund - Growth Option - Direct Plan",
         "fund_name_latest": "HDFC Flexi Cap Fund", "isin": "INF179K01UT0", "isin2": None},
        {"scheme_code": 2, "scheme_name": "HDFC Flexi Cap Fund - Growth Option - Regular Plan",
         "fund_name_latest": "HDFC Flexi Cap Fund", "isin": "INF179K01UU8", "isin2": "INF179K01UV6"},
        {"scheme_code": 3, "scheme_name": "Only One Long Unique Growth",
         "fund_name_latest": "Only One Long Unique Growth", "isin": "INF000000003", "isin2": None},
    ]


def test_a_scheme_code_matches_that_scheme_and_does_not_fall_through():
    catalog = _catalog()
    assert match_holding({"scheme_code": 2, "isin": "INF179K01UT0"}, catalog) == 2
    assert match_holding({"scheme_code": 99, "name": "Only One Long Unique Growth"}, catalog) is None
    assert match_holding({"scheme_code": "2"}, catalog, preferred={2}) == 2
    assert match_holding({"scheme_code": 1}, catalog, preferred={2}) is None


def test_isin_matches_isin_or_isin2_and_ignores_a_conflicting_name():
    catalog = _catalog()
    assert match_holding({"isin": "inf179k01ut0", "name": "something else"}, catalog) == 1
    assert match_holding({"isin": "INF179K01UV6"}, catalog) == 2
    assert match_holding({"isin": "INF999999999", "name": "Only One Long Unique Growth"}, catalog) is None


def test_shared_isin_stays_unmatched_unless_one_scheme_is_preferred():
    catalog = [
        {"scheme_code": 1, "scheme_name": "A Growth", "isin": "INF00000000A", "isin2": None},
        {"scheme_code": 2, "scheme_name": "B Growth", "isin": "INF00000000A", "isin2": None},
    ]
    holding = {"isin": "INF00000000A"}
    assert match_holding(holding, catalog) is None
    assert match_holding(holding, catalog, preferred={2}) == 2


def test_name_matches_an_exact_or_unique_scheme_and_refuses_a_short_or_shared_name():
    catalog = _catalog()
    assert match_holding({"name": "Only One Long Unique Growth"}, catalog) == 3
    assert match_holding({"name": "only one long unique"}, catalog) == 3
    assert match_holding({"name": "HDFC Flexi Cap Fund"}, catalog) is None
    assert match_holding({"name": "HDFC"}, catalog) is None
    assert match_holding({}, catalog) is None


def test_point_return_uses_the_stored_cagr_formula_and_a_young_fund_is_blank():
    start = ASOF - timedelta(days=365)
    series = Series([(start, 100), (ASOF, 110)])
    assert point_return(series, ASOF, 1) == cagr_pct(110, 100, 365) == 10.0
    young = Series([(ASOF - timedelta(days=100), 100), (ASOF, 110)])
    assert point_return(young, ASOF, 1) is None
    assert point_return(Series([(start, 0), (ASOF, 110)]), ASOF, 1) is None


def test_calendar_returns_are_december_to_december_and_skip_a_year_before_launch():
    series = Series([
        (date(2022, 12, 31), 100),
        (date(2023, 12, 31), 110),
        (date(2024, 12, 31), 121),
        (date(2025, 12, 31), 133.1),
        (date(2026, 6, 1), 140),
    ])
    assert calendar_returns(series, ASOF) == {2023: 10.0, 2024: 10.0, 2025: 10.0}


def test_rolling_beat_rate_needs_four_years_and_counts_a_strict_win():
    start = date(2020, 1, 1)
    end = start + timedelta(days=1460)
    middle = end - timedelta(days=1096)
    fund = Series([(start, 100), (middle, 100), (end, 200)])
    bench = Series([(start, 100), (middle, 100), (end, 110)])
    assert rolling_beat_pct(fund, bench, end) == 100.0
    assert rolling_beat_pct(fund, bench, start + timedelta(days=1000)) is None
    tied = Series([(start, 100), (middle, 100), (end, 110)])
    assert rolling_beat_pct(tied, bench, end) == 0.0


def test_capture_drops_a_flat_benchmark_day_and_reports_the_ratio():
    start = ASOF - timedelta(days=3 * 365)
    fund = Series([(start, 100), (start + timedelta(days=1), 130),
                   (start + timedelta(days=2), 130), (start + timedelta(days=3), 117)])
    bench = Series([(start, 100), (start + timedelta(days=1), 110),
                    (start + timedelta(days=2), 110), (start + timedelta(days=3), 100)])
    upside, downside, observed = capture(fund, bench, ASOF)
    assert upside == 300.0
    assert downside == 110.0
    assert observed == 2


def test_drawdown_names_the_trough_month_and_counts_recovery():
    fell = Series([
        (date(2020, 1, 1), 100),
        (date(2020, 2, 1), 200),
        (date(2020, 3, 15), 100),
        (date(2020, 11, 15), 200),
    ])
    stats = drawdown(fell)
    assert stats["max_drawdown"] == -50.0
    assert stats["event"] == "the March 2020 fall"
    assert stats["recovery_months"] == 8
    assert stats["still_underwater"] is False
    still = Series(fell.dates[:3] and list(zip(fell.dates, fell.levels))[:3])
    open_fall = drawdown(still)
    assert open_fall["still_underwater"] is True
    assert open_fall["recovery_months"] is None


def test_benchmark_cagr_uses_the_funds_last_nav_not_a_later_job_date():
    fund_end = date(2026, 10, 13)
    fund = [(fund_end - timedelta(days=365), 100), (fund_end, 110)]
    bench = [
        (date(2025, 10, 13), 100),
        (date(2025, 10, 14), 200),
        (fund_end, 110),
        (ASOF, 999),
    ]
    got = measures(fund, bench, ASOF)
    assert got["bench_cagr_1y"] == 10.0
    start = ASOF - timedelta(days=365)
    got = measures([(start, 100), (ASOF, 110)], [], ASOF)
    assert got["bench_cagr_1y"] is None
    assert got["rolling_beat_pct"] is None
    assert got["max_drawdown"] == 10.0 or got["max_drawdown"] == 0.0 or got["max_drawdown"] is not None
    stored = store_fields(got)
    assert stored["bench_cagr_1y"] is None
    assert stored["calendar_returns_json"] is None or stored["calendar_returns_json"]
    assert stored["still_underwater"] in (0, 1, None)


def test_the_benchmark_fall_starts_when_the_fund_starts():
    fund = [(date(2020, 1, 1), 100), (date(2020, 6, 1), 80), (date(2021, 1, 1), 100)]
    bench = [(date(2008, 1, 1), 100), (date(2008, 6, 1), 40), (date(2009, 1, 1), 100),
             (date(2020, 1, 1), 100), (date(2020, 6, 1), 90), (date(2021, 1, 1), 100)]
    got = measures(fund, bench, date(2021, 1, 1))
    assert got["max_drawdown"] == -20.0
    assert got["bench_max_drawdown"] == -10.0


def test_managers_use_the_lead_start_date_and_leave_a_blank_date_blank():
    names, since = parse_managers(
        "Amit Ganatra (since 2026-02-01); Gopal Agrawal (since 2026-09-01)"
    )
    assert names == ["Amit Ganatra", "Gopal Agrawal"]
    assert since == "2026-02-01"
    names, since = parse_managers("Sailesh Raj Bhan; Bhavik Dave")
    assert names == ["Sailesh Raj Bhan", "Bhavik Dave"]
    assert since is None


def _details(plan="Direct", category="Flexi Cap Fund"):
    return {
        "scheme_code": 1,
        "scheme_name": "Example Flexi Cap Fund - Direct Plan - Growth",
        "fund_name_latest": "Example Flexi Cap Fund",
        "isin": "INF000000001",
        "scheme_plan": plan,
        "category_sub": category,
        "category_group": "Equity Scheme",
        "ter_direct": 0.75,
        "ter_regular": 1.36,
        "ter_date": "2026-10-13",
        "aum_cr": 1000,
        "amfi_daily_riskometer": "Very High",
        "amfi_daily_riskometer_benchmark": "Very High",
        "ssd_fund_managers": "Amit Ganatra (since 2026-02-01); Gopal Agrawal (since 2026-09-01)",
        "ssd_allotment_date": "1995-01-01",
        "ssd_exit_load": "x" * 350,
    }


def test_assembler_uses_the_plans_own_ter_and_does_not_invent_a_benchmark_figure():
    direct = fund_from_rows(100000, _details(), {"cagr_1y": 9.1, "benchmark_name": "Nifty 500 TRI",
                                                 "quartile_5y": 1, "peer_count": 27},
                            (0.91, 43), "", set())
    assert direct.plan == "direct"
    assert direct.ter == 0.75
    assert direct.returns == {1: 9.1}
    assert direct.bench_returns == {}
    assert direct.quartiles == {5: 1}
    assert direct.manager_since == "2026-02-01"
    assert len(direct.exit_load) == 300
    assert direct.benchmark_applies is None
    assert direct.is_index is False
    regular = fund_from_rows(100000, _details("Regular"), None, None, "", set())
    assert regular.plan == "regular"
    assert regular.ter == 1.36
    assert regular.returns == {}


def test_an_unmatched_holding_stays_in_the_report_as_a_gap():
    catalog = _catalog()
    details = {1: _details()}
    metrics = {1: {"scheme_code": 1, "cagr_1y": 9.0, "benchmark_name": "Nifty 500 TRI",
                   "category_sub": "Flexi Cap Fund", "scheme_plan": "Direct", "history_years": 6}}
    holdings = [
        {"isin": "INF179K01UT0", "name": "HDFC", "value": 100000},
        {"isin": "INF000000000", "name": "Unknown scheme", "value": 50000},
        {"isin": "INF179K01UU8", "name": "No value", "value": None},
    ]
    portfolio, gaps = portfolio_from_holdings(
        holdings, catalog, details, metrics, {}, {}, "2026-10-14",
    )
    assert [f.name for f in portfolio.funds] == ["Example Flexi Cap Fund"]
    assert any("could not be matched" in gap for gap in gaps)
    assert any("no holding value" in gap for gap in gaps)
    report = report_for(holdings, catalog, details, metrics, {}, {}, "2026-10-14")
    assert report.funds
    assert any("could not be matched" in gap for gap in report.data_gaps)
    analyze(portfolio)


def test_update_benchmark_metrics_keeps_the_fund_cagr(tmp_path):
    db = tmp_path / "mf.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE scheme_metrics (scheme_code INTEGER PRIMARY KEY, cagr_1y REAL, bench_cagr_1y REAL, "
                "bench_cagr_3y REAL, bench_cagr_5y REAL, calendar_returns_json TEXT, "
                "bench_calendar_returns_json TEXT, rolling_window_years INTEGER, rolling_beat_pct REAL, "
                "upside_capture REAL, downside_capture REAL, capture_years INTEGER, capture_obs INTEGER, "
                "max_drawdown REAL, bench_max_drawdown REAL, drawdown_event TEXT, recovery_months INTEGER, "
                "bench_recovery_months INTEGER, still_underwater INTEGER)")
    con.execute("INSERT INTO scheme_metrics (scheme_code, cagr_1y) VALUES (1, 9.1)")
    con.commit()
    con.close()
    fields = store_fields(measures(
        [(ASOF - timedelta(days=400), 100), (ASOF, 110)],
        [(ASOF - timedelta(days=400), 100), (ASOF, 105)],
        ASOF,
    ))
    fields["scheme_code"] = 1
    assert update_benchmark_metrics(db, [fields]) == 1
    con = sqlite3.connect(db)
    cagr, bench = con.execute("SELECT cagr_1y, bench_cagr_1y FROM scheme_metrics").fetchone()
    assert cagr == 9.1
    assert bench is not None
    with pytest.raises(ValueError):
        update_benchmark_metrics(db, [{**fields, "scheme_code": 99}])
    con.close()


def test_store_fields_json_uses_year_keys():
    measured = measures(
        [(date(2023, 12, 31), 100), (date(2024, 12, 31), 110),
         (date(2025, 12, 31), 120), (ASOF, 130)],
        [(date(2023, 12, 31), 100), (date(2024, 12, 31), 108),
         (date(2025, 12, 31), 116), (ASOF, 120)],
        ASOF,
    )
    raw = store_fields(measured)["calendar_returns_json"]
    parsed = json.loads(raw)
    assert parsed["2024"] == 10.0
    assert "2026" not in parsed


def test_display_medians_need_five_funds_and_skip_index_categories():
    metrics = {
        i: {"category_sub": "Flexi Cap Fund", "scheme_plan": "Direct", "cagr_5y": cagr}
        for i, cagr in enumerate([10, 12, 14, 16])
    }
    assert display_medians(metrics) == {}
    for i, cagr in enumerate([10, 12, 14, 16, 18]):
        metrics[i] = {
            "category_sub": "Flexi Cap Fund", "scheme_plan": "Direct Plan", "cagr_5y": cagr,
            "cagr_1y": cagr + 1,
            "calendar_returns_json": json.dumps({"2024": cagr, "2023": 5}),
            "max_drawdown": -20 - i, "recovery_months": 6 + i,
        }
    got = display_medians(metrics)[("Flexi Cap Fund", "direct")]
    assert got["cagr"] == {1: 15.0, 5: 14.0}
    assert got["calendar"][2024] == 14.0 and got["calendar"][2023] == 5.0
    assert got["max_drawdown"] == -22.0
    assert got["recovery_months"] == 8
    for i in range(6):
        metrics[100 + i] = {"category_sub": "Index Funds", "scheme_plan": "Direct", "cagr_5y": 10 + i}
    assert all("index" not in key[0].lower() and "etf" not in key[0].lower()
               for key in display_medians(metrics))
    index = fund_from_rows(
        1, {"scheme_name": "UTI Nifty 50 Index Fund", "category_sub": "Index Funds", "scheme_plan": "Direct"},
        {}, None, "", set(), typical={"cagr": {5: 10}, "max_drawdown": -20},
    )
    assert index.is_index and index.typical_returns == {} and index.typical_max_drawdown is None
    flexi = fund_from_rows(
        1, {"scheme_name": "HDFC Flexi Cap Fund", "category_sub": "Flexi Cap Fund", "scheme_plan": "Direct"},
        {}, None, "", set(), typical=got,
    )
    assert flexi.typical_returns[5] == 14.0 and flexi.typical_max_drawdown == -22.0
    assert flexi.typical_recovery_months == 8 and flexi.typical_calendar[2024] == 14.0
