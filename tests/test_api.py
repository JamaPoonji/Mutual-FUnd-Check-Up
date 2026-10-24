"""The analyze API. Fixtures are in memory. Uploads must not leave a file behind."""
import logging

from fastapi.testclient import TestClient

from api.app import app, report_payload
from api.data import FundData
from api.parse import UNREADABLE_FILE

FUNDS = FundData(
    catalog=[{
        "scheme_code": 1,
        "scheme_name": "Example Flexi Cap Fund - Direct Plan - Growth",
        "fund_name_latest": "Example Flexi Cap Fund",
        "isin": "INF179K01UT0",
        "isin2": None,
    }],
    details={1: {
        "scheme_code": 1,
        "scheme_name": "Example Flexi Cap Fund - Direct Plan - Growth",
        "fund_name_latest": "Example Flexi Cap Fund",
        "isin": "INF179K01UT0",
        "scheme_plan": "Direct",
        "category_sub": "Flexi Cap Fund",
        "category_group": "Equity Scheme",
        "ter_direct": 0.75,
        "ter_regular": 1.36,
    }},
    metrics={1: {
        "scheme_code": 1,
        "scheme_name": "Example Flexi Cap Fund - Direct Plan - Growth",
        "isin": "INF179K01UT0",
        "category_sub": "Flexi Cap Fund",
        "category_group": "Equity Scheme",
        "scheme_plan": "Direct",
        "cagr_5y": 14.5,
        "bench_cagr_5y": 8.0,
        "benchmark_name": "Nifty 500 TRI",
        "history_years": 10,
        "quartile_5y": 1,
        "peer_count": 27,
    }},
    medians={("Flexi Cap Fund", "Direct"): (0.91, 43)},
    quality={},
    as_of="2026-10-14",
    preferred={1},
)

CSV = b"isin,name,value\nINF179K01UT0,Example Flexi Cap Fund,400000\n"
SECRET = "INFSECRET999999"


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr("api.app.TEMP_DIR", tmp_path)
    monkeypatch.setattr("api.app.get_fund_data", lambda: FUNDS)
    return TestClient(app)


def test_json_holdings_return_a_report_and_an_unknown_isin_is_still_a_report(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    ok = client.post("/api/analyze", json={"holdings": [
        {"isin": "INF179K01UT0", "name": "Example", "value": 400000},
        {"isin": SECRET, "name": "Mystery fund", "value": 10000},
    ]})
    assert ok.status_code == 200
    body = ok.json()
    assert body["schema_version"] == 1
    assert body["funds"][0]["name"] == "Example Flexi Cap Fund"
    assert any("could not be matched" in gap for gap in body["data_gaps"])
    assert SECRET not in " ".join(body["data_gaps"])
    empty = client.post("/api/analyze", json={"holdings": []})
    assert empty.status_code == 422
    assert empty.json()["error"] and empty.json()["unmatched"] == []


def test_upload_temp_file_is_gone_after_success_and_failure(monkeypatch, tmp_path, caplog):
    client = _client(monkeypatch, tmp_path)
    caplog.set_level(logging.INFO, logger="mfadvisor.api")
    good = client.post("/api/analyze", files={"file": ("holdings.csv", CSV, "text/csv")})
    assert good.status_code == 200
    assert good.json()["funds"][0]["verdict"]
    assert list(tmp_path.iterdir()) == []
    bad = client.post("/api/analyze", files={"file": ("statement.pdf", b"%PDF-1.4 secret folio", "application/pdf")})
    assert bad.status_code == 422
    assert bad.json()["error"] == UNREADABLE_FILE
    assert list(tmp_path.iterdir()) == []
    logged = caplog.text
    assert "INF179K01UT0" not in logged
    assert "secret folio" not in logged
    assert "status=200" in logged and "status=422" in logged


def test_excel_upload_returns_a_report_and_a_password_is_not_logged(monkeypatch, tmp_path, caplog):
    from openpyxl import Workbook
    client = _client(monkeypatch, tmp_path)
    caplog.set_level(logging.INFO, logger="mfadvisor.api")
    book = Workbook()
    sheet = book.active
    sheet.append(["ISIN", "Scheme Name", "Current Value"])
    sheet.append(["INF179K01UT0", "Example Flexi Cap Fund", 250000])
    path = tmp_path / "holdings.xlsx"
    book.save(path)
    secret = "ABCDE1234F"
    good = client.post(
        "/api/analyze",
        files={"file": ("holdings.xlsx", path.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"password": secret},
    )
    assert good.status_code == 200
    assert good.json()["funds"][0]["value"] == 250000
    assert secret not in good.text
    assert secret not in caplog.text
    assert list(tmp_path.glob("mfhold-*")) == []


def test_start_page_calls_the_api_and_keeps_the_privacy_promise(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    page = client.get("/")
    assert page.status_code == 200
    html = page.text
    assert "Your file is not saved." in html
    assert "/api/analyze" in html
    assert "MFAdvisor.onUpload" in html
    assert 'body.append("password", pass.value)' in html
    assert "Statement password" in html
    assert "Or pick funds by name" in html
    assert "/api/schemes" in html
    assert "__REPORT_JSON__" not in html
    assert ">null<" in html


def test_report_payload_does_not_invent_a_value():
    payload = report_payload([{"isin": "INF179K01UT0", "name": "Example", "value": None}], FUNDS)
    assert payload["funds"] == []
    assert any("no holding value" in gap for gap in payload["data_gaps"])


def test_picked_funds_are_an_equal_weight_report_and_search_does_not_log_the_query(monkeypatch, tmp_path, caplog):
    from api.parse import EMPTY_FUNDS, TOO_MANY_FUNDS
    client = _client(monkeypatch, tmp_path)
    caplog.set_level(logging.INFO, logger="mfadvisor.api")
    secret = "ZZHIDDEN Flexi"
    found = client.post("/api/schemes", json={"q": "flexi"})
    assert found.status_code == 200
    row = found.json()["schemes"][0]
    assert row["scheme_code"] == 1
    assert "Direct" in row["name"]
    assert row["isin"] == "INF179K01UT0"
    missed = client.post("/api/schemes", json={"q": secret})
    assert missed.json()["schemes"] == []
    short = client.post("/api/schemes", json={"q": "e"})
    assert short.json()["schemes"] == []
    picked = client.post("/api/analyze", json={"schemes": [1, 1]})
    assert picked.status_code == 200
    body = picked.json()
    assert body["equal_weight"] is True
    assert "no amounts were given" in body["equal_weight_note"]
    assert body["funds"][0]["share_pct"] == 100
    assert all(card["topic"] != "mix" for card in body["cards"])
    charges = [
        insight for card in body["cards"] for section in card["sections"]
        for insight in section["insights"] if insight["topic"] == "costs"
    ]
    assert charges and "₹" not in charges[0]["sentence"]
    assert "annual_cost" not in charges[0]["numbers"]
    assert client.post("/api/analyze", json={"schemes": []}).json()["error"] == EMPTY_FUNDS
    assert client.post("/api/analyze", json={"schemes": list(range(26))}).json()["error"] == TOO_MANY_FUNDS
    assert secret not in caplog.text
    assert "INF179K01UT0" not in caplog.text
