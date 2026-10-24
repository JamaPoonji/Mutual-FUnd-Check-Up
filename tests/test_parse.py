"""Broker tables and statement readings. Fixtures are made up. No file is kept."""
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from api.parse import (
    LOCKED_STATEMENT, NO_MUTUAL_FUNDS, UNREADABLE_FILE, Unreadable,
    holdings_from_csv, holdings_from_excel, holdings_from_pdf, holdings_from_statement,
)


BROKER = """Client,ABCDE1234F
Symbol,ISIN,Quantity Available,Previous Closing Price
HDFC Flexi Cap,INF179K01UT0,"1,000",40.5
HDFC Flexi Cap,INF179K01UT0,10,20
Total,,,
"""


def test_broker_csv_uses_units_times_price_and_adds_the_same_scheme():
    rows = holdings_from_csv(BROKER)
    assert rows == [{"isin": "INF179K01UT0", "name": "HDFC Flexi Cap", "value": 1000 * 40.5 + 200}]
    assert "ABCDE1234F" not in str(rows)


def test_a_market_value_column_is_used_as_given():
    text = "Scheme Name,ISIN,Current Value\nExample Fund,INF179K01UT0,\"₹4,00,000\"\n"
    rows = holdings_from_csv(text)
    assert rows[0]["value"] == 400000


def test_a_file_without_a_holdings_header_is_refused():
    with pytest.raises(Unreadable, match=UNREADABLE_FILE):
        holdings_from_csv("hello,world\n1,2\n")


def test_excel_uses_the_same_columns(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.append(["Notes"])
    sheet.append(["Fund Name", "ISIN Code", "Units", "NAV"])
    sheet.append(["Example Flexi Cap Fund", "INF179K01UT0", 100, 40])
    path = tmp_path / "holdings.xlsx"
    book.save(path)
    rows = holdings_from_excel(path)
    assert rows == [{"isin": "INF179K01UT0", "name": "Example Flexi Cap Fund", "value": 4000}]


def test_statement_keeps_mutual_funds_and_drops_folio_pan_and_sold_lines():
    parsed = SimpleNamespace(
        folios=[SimpleNamespace(
            folio="FOLIO999",
            PAN="ABCDE1234F",
            schemes=[
                SimpleNamespace(scheme="HDFC Flexi Cap Fund", isin="INF179K01UT0", close=10,
                                valuation=SimpleNamespace(value=405)),
                SimpleNamespace(scheme="Sold fund", isin="INF000000001", close=0,
                                valuation=SimpleNamespace(value=0)),
            ],
        )],
        accounts=[SimpleNamespace(
            mutual_funds=[SimpleNamespace(name="HDFC Flexi Cap Fund", isin="INF179K01UT0",
                                           balance=5, value=100)],
            equities=[
                SimpleNamespace(name="A share", isin="INE000000001", num_shares=1, value=50),
                SimpleNamespace(name="An ETF", isin="INF789F01XA0", num_shares=2, value=200),
            ],
        )],
    )
    rows = holdings_from_statement(parsed)
    by_isin = {row["isin"]: row["value"] for row in rows}
    assert by_isin == {"INF179K01UT0": 505, "INF789F01XA0": 200}
    blob = str(rows)
    assert "FOLIO999" not in blob and "ABCDE1234F" not in blob


def test_a_statement_with_no_mutual_funds_says_so():
    parsed = SimpleNamespace(folios=[], accounts=[SimpleNamespace(
        mutual_funds=[], equities=[SimpleNamespace(name="A share", isin="INE000000001",
                                                    num_shares=1, value=50)],
    )])
    with pytest.raises(Unreadable, match=NO_MUTUAL_FUNDS):
        holdings_from_statement(parsed)


def test_a_locked_statement_asks_for_the_password_without_repeating_it(monkeypatch, tmp_path):
    from casparser.exceptions import IncorrectPasswordError

    def _locked(*_args, **_kwargs):
        raise IncorrectPasswordError("Incorrect PDF password!")

    monkeypatch.setattr("casparser.read_cas_pdf", _locked)
    path = tmp_path / "statement.pdf"
    path.write_bytes(b"%PDF-1.4")
    with pytest.raises(Unreadable, match=LOCKED_STATEMENT) as caught:
        holdings_from_pdf(path, "ABCDE1234F")
    assert "ABCDE1234F" not in str(caught.value)
