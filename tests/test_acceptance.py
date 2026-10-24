"""Milestone 6 checks.

The golden report must match the schema. A missing charge, a missing category
median, or a short track record becomes a data-gap line. The page stays general
information, and a failure message is the sentence we wrote, not the exception.
"""
import json
from datetime import date
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from fastapi.testclient import TestClient

from api.app import FAILED, NOT_READY, app
from api.parse import EMPTY_HOLDINGS, LOCKED_STATEMENT, NO_MUTUAL_FUNDS, UNREADABLE_FILE
from mf_plain import Fund, Portfolio, analyze
from mf_plain.engine import DISCLAIMER
from pipeline.assemble import HAND_PICKED, load_index, load_metrics, load_nav
from pipeline.benchmark_metrics import Series, measures, point_return

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-10-14"
STORE = ROOT / "data" / "store" / "mf.sqlite"
NAV = ROOT / "data" / "raw" / AS_OF / "amfi_nav_master.parquet"


def fund(**kw):
    base = dict(name="F", category="Flexi Cap", value=100000, benchmark_name="Nifty 500")
    base.update(kw)
    return Fund(**base)


def test_golden_report_matches_the_schema():
    schema = json.loads((ROOT / "docs" / "report.schema.json").read_text())
    report = json.loads((ROOT / "docs" / "sample_report.json").read_text())
    Draft202012Validator(schema).validate(report)


def test_missing_charge_median_and_short_history_are_gaps():
    no_charge = fund(name="No charge", ter=None, returns={5: 12}, bench_returns={5: 10}, history_years=10)
    young = fund(
        name="Young fund", ter=0.8, history_years=1.5,
        rolling_beat_pct=40, rolling_window_years=3,
        returns={1: 8}, bench_returns={1: 6},
    )
    report = analyze(Portfolio(funds=[no_charge, young]))
    assert len(report.data_gaps) == 2
    young_line = next(gap for gap in report.data_gaps if gap.startswith("Young fund"))
    charge_line = next(gap for gap in report.data_gaps if gap.startswith("No charge"))
    assert young_line.startswith("Young fund is under 2 years old")
    assert "only returns and cost are checked" in young_line
    assert "category median charge is not available" in young_line
    assert "charges (TER)" in charge_line
    assert charge_line.count("No charge") == 1
    assert report.headline


def _store_unavailable():
    raise RuntimeError("folio 999 PAN ABCDE1234F")


def test_copy_stays_general_information_and_errors_hide_the_exception(monkeypatch):
    monkeypatch.setattr("api.app._funds", None)
    monkeypatch.setattr("api.app.load_fund_data", _store_unavailable)
    client = TestClient(app)
    page = client.get("/").text
    assert "This is general information to discuss with an adviser. It is not investment advice" in page
    assert "Your file is not saved." in page
    assert "MFAdvisor.error((e&&e.message)" in page
    assert DISCLAIMER in page

    missing = client.post("/api/analyze", json={"holdings": [{"isin": "INF179K01UT0", "value": 1}]})
    assert missing.status_code == 422
    assert missing.json()["error"] == NOT_READY
    assert "ABCDE1234F" not in missing.text
    assert "folio" not in missing.text.lower()

    from tests.test_api import FUNDS

    monkeypatch.setattr("api.app.get_fund_data", lambda: FUNDS)

    def explode(*_args, **_kwargs):
        raise RuntimeError("password secret-pan holdings dump")

    monkeypatch.setattr("api.app.report_for", explode)
    failed = client.post("/api/analyze", json={"holdings": [{"isin": "INF179K01UT0", "name": "Example", "value": 1}]})
    assert failed.status_code == 500
    assert failed.json()["error"] == FAILED
    assert "secret-pan" not in failed.text
    for sentence in (UNREADABLE_FILE, LOCKED_STATEMENT, EMPTY_HOLDINGS, NO_MUTUAL_FUNDS, NOT_READY, FAILED):
        assert "you should sell" not in sentence.lower()
        assert "you should buy" not in sentence.lower()


@pytest.mark.skipif(not STORE.exists() or not NAV.exists(), reason="local NAV store is not in this checkout")
def test_five_demonstration_funds_match_a_fresh_calculation():
    """Stored CAGR, rolling beat rate and capture are the fresh calculation.

    Compared with MFPRO on 14 Oct 2026, the same end date matches CAGR within
    0.02 points (their exponent is 365.25; ours is 365). Beat rate matches
    within 0.1 for the large-cap, flexi-cap and index fund. The mid-cap gap is
    twenty NSE sessions in October 2023 where MFPRO's Midcap 150 series does
    not match niftyindices.com. The small-cap gap is the benchmark: we use
    Nifty Smallcap 250 TRI, and MFPRO uses Nifty Smallcap 50 TRI.
    """
    codes = [code for code, _value in HAND_PICKED]
    metrics = load_metrics(STORE, codes)
    nav = load_nav(NAV, codes, AS_OF)
    indexes: dict[str, list] = {}
    for code, _value in HAND_PICKED:
        row = metrics[code]
        name = row["benchmark_name"]
        if name not in indexes:
            indexes[name] = load_index(STORE, name, AS_OF)
        points = nav[code]
        measured = measures(points, indexes[name], AS_OF)
        series = Series(points).through(date.fromisoformat(AS_OF))
        anchor = series.dates[-1]
        for years in (1, 3, 5):
            fresh = point_return(series, anchor, years)
            stored = row[f"cagr_{years}y"]
            assert fresh is not None and stored is not None
            assert abs(fresh - stored) <= 0.01, (code, years, fresh, stored)
        for key in ("rolling_beat_pct", "upside_capture", "downside_capture"):
            fresh = measured[key]
            stored = row[key]
            assert fresh is not None and stored is not None
            assert abs(fresh - stored) <= 0.01, (code, key, fresh, stored)
    assert metrics[145678]["benchmark_name"] == "Nifty Smallcap 250 TRI"
