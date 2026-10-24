"""Turn a request into a holdings list.

CSV and Excel may use a broker's own column names. A statement PDF is read
locally. The file, its password, folio numbers and PAN are not kept and are
not put in the error text.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Optional

UNREADABLE_FILE = (
    "We could not read that file. Please upload the holdings file from your broker as CSV or Excel."
)
UNREADABLE_REQUEST = "We could not read that request. Send a holdings list, or a CSV with isin and value columns."
EMPTY_HOLDINGS = "Add at least one holding."
EMPTY_FUNDS = "Add at least one fund."
TOO_MANY_FUNDS = "You can select at most 25 funds."
LOCKED_STATEMENT = (
    "This statement is locked. Add the password from the email that sent it, then upload the file again."
)
NO_MUTUAL_FUNDS = "That file has no mutual fund holdings we can check."

_ISIN_HEADERS = ("isin", "isin code", "isin no", "isin number")
_NAME_HEADERS = ("scheme name", "fund name", "mutual fund", "scheme", "fund", "symbol", "name")
_VALUE_HEADERS = (
    "current value", "market value", "present value", "current market value",
    "market val", "mkt value", "valuation", "value",
)
_UNIT_HEADERS = (
    "quantity available", "balance units", "closing unit balance", "unit balance",
    "holdings qty", "quantity", "units", "qty", "balance",
)
_NAV_HEADERS = ("current nav", "previous closing price", "last nav", "closing price", "nav", "ltp")
_ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")
_SKIP_NAMES = {"total", "totals", "grand total"}


class Unreadable(Exception):
    """The file or body is not a holdings list we can use."""


def _header(name: Optional[str]) -> str:
    return " ".join((name or "").strip().lower().replace("_", " ").split())


def _number(value) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _row(isin, name, value) -> dict:
    isin_text = str(isin).strip() if isin else ""
    name_text = str(name).strip() if name else ""
    return {"isin": isin_text or None, "name": name_text or None, "value": _number(value)}


def holdings_from_json(body) -> list[dict]:
    if not isinstance(body, dict) or not isinstance(body.get("holdings"), list):
        raise Unreadable(UNREADABLE_REQUEST)
    rows = []
    for item in body["holdings"]:
        if not isinstance(item, dict):
            raise Unreadable(UNREADABLE_REQUEST)
        rows.append(_row(item.get("isin"), item.get("name"), item.get("value")))
    if not rows:
        raise Unreadable(EMPTY_HOLDINGS)
    return rows


def _column(headers: list[str], names: tuple[str, ...]) -> Optional[int]:
    for name in names:
        if name in headers:
            return headers.index(name)
    return None


def _cell(row: list[str], index: Optional[int]):
    if index is None or index >= len(row):
        return None
    return row[index]


def _isin_cell(value) -> Optional[str]:
    text = "".join(str(value or "").split()).upper()
    return text if _ISIN_RE.fullmatch(text) else None


def _looks_like_header(headers: list[str]) -> bool:
    named = _column(headers, _ISIN_HEADERS) is not None or _column(headers, _NAME_HEADERS) is not None
    valued = _column(headers, _VALUE_HEADERS) is not None or _column(headers, _UNIT_HEADERS) is not None
    return named and valued


def _merge(rows: list[dict]) -> list[dict]:
    """One line per scheme. Values add. A missing value is not treated as zero."""
    merged: list[dict] = []
    index: dict[tuple, int] = {}
    for row in rows:
        isin = _isin_cell(row.get("isin"))
        name = str(row.get("name") or "").strip() or None
        if name and name.lower() in _SKIP_NAMES and not isin:
            continue
        if not isin and not name:
            continue
        key = ("isin", isin) if isin else ("name", " ".join(name.lower().split()))
        value = row.get("value")
        if isinstance(value, bool) or value is None:
            number = None
        else:
            number = float(value) if isinstance(value, (int, float)) else _number(value)
            if number is not None and number <= 0:
                number = None
        if key in index:
            kept = merged[index[key]]
            if number is not None and kept["value"] is not None:
                kept["value"] = kept["value"] + number
            elif number is not None:
                kept["value"] = number
            if not kept["name"] and name:
                kept["name"] = name
        else:
            index[key] = len(merged)
            merged.append({"isin": isin, "name": name, "value": number})
        if len(merged) > 500:
            raise Unreadable(UNREADABLE_FILE)
    if not merged:
        raise Unreadable(EMPTY_HOLDINGS)
    return merged


def _holdings_from_table(table: list[list]) -> list[dict]:
    header_at = None
    headers: list[str] = []
    for i, raw in enumerate(table[:40]):
        cells = [_header(str(cell) if cell is not None else "") for cell in raw]
        if _looks_like_header(cells):
            header_at = i
            headers = cells
            break
    if header_at is None:
        raise Unreadable(UNREADABLE_FILE)
    isin_at = _column(headers, _ISIN_HEADERS)
    name_at = _column(headers, _NAME_HEADERS)
    value_at = _column(headers, _VALUE_HEADERS)
    units_at = _column(headers, _UNIT_HEADERS)
    nav_at = _column(headers, _NAV_HEADERS)
    parsed = []
    for raw in table[header_at + 1:]:
        if not any(str(cell).strip() for cell in raw if cell is not None):
            continue
        value = _number(_cell(raw, value_at))
        if value is None or value <= 0:
            units = _number(_cell(raw, units_at))
            nav = _number(_cell(raw, nav_at))
            value = units * nav if units and nav and units > 0 and nav > 0 else None
        parsed.append({
            "isin": _cell(raw, isin_at),
            "name": _cell(raw, name_at),
            "value": value,
        })
        if len(parsed) > 500:
            raise Unreadable(UNREADABLE_FILE)
    return _merge(parsed)


def _table(text: str, delimiter: str) -> list[list[str]]:
    try:
        return list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error as exc:
        raise Unreadable(UNREADABLE_FILE) from exc


def holdings_from_csv(text: str) -> list[dict]:
    """A holdings table. The header need not be the first line."""
    last = Unreadable(UNREADABLE_FILE)
    for delimiter in (",", ";", "\t"):
        try:
            return _holdings_from_table(_table(text, delimiter))
        except Unreadable as exc:
            last = exc
    raise last


def holdings_from_excel(path: Path) -> list[dict]:
    """The first sheet of an .xlsx file, using the same columns as the CSV reader."""
    try:
        import openpyxl
    except ImportError as exc:
        raise Unreadable(UNREADABLE_FILE) from exc
    try:
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise Unreadable(UNREADABLE_FILE) from exc
    try:
        sheet = book.worksheets[0]
        table = []
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            table.append(["" if cell is None else cell for cell in row])
            if i >= 5000:
                break
    finally:
        book.close()
    return _holdings_from_table(table)


def holdings_from_statement(parsed) -> list[dict]:
    """Current mutual fund lines from a parsed statement. Transactions, folios and PAN are dropped."""
    rows = []
    for folio in getattr(parsed, "folios", None) or []:
        for scheme in getattr(folio, "schemes", None) or []:
            close = getattr(scheme, "close", None)
            if close is not None and float(close) <= 0:
                continue
            valuation = getattr(scheme, "valuation", None)
            value = getattr(valuation, "value", None) if valuation is not None else None
            rows.append({
                "isin": getattr(scheme, "isin", None),
                "name": getattr(scheme, "scheme", None),
                "value": value,
            })
    for account in getattr(parsed, "accounts", None) or []:
        for fund in getattr(account, "mutual_funds", None) or []:
            balance = getattr(fund, "balance", None)
            if balance is not None and float(balance) <= 0:
                continue
            rows.append({
                "isin": getattr(fund, "isin", None),
                "name": getattr(fund, "name", None),
                "value": getattr(fund, "value", None),
            })
        for equity in getattr(account, "equities", None) or []:
            isin = _isin_cell(getattr(equity, "isin", None))
            shares = getattr(equity, "num_shares", None)
            if not isin or not isin.startswith("INF"):
                continue
            if shares is not None and float(shares) <= 0:
                continue
            rows.append({
                "isin": isin,
                "name": getattr(equity, "name", None),
                "value": getattr(equity, "value", None),
            })
    if not rows:
        raise Unreadable(NO_MUTUAL_FUNDS)
    return _merge(rows)


def holdings_from_pdf(path: Path, password: str = "") -> list[dict]:
    """Read a CAMS, KFintech, CDSL or NSDL statement on this machine."""
    from casparser import read_cas_pdf
    from casparser.exceptions import CASParseError, IncorrectPasswordError

    try:
        parsed = read_cas_pdf(str(path), password or "")
    except IncorrectPasswordError as exc:
        raise Unreadable(LOCKED_STATEMENT) from exc
    except CASParseError as exc:
        raise Unreadable(UNREADABLE_FILE) from exc
    except Exception as exc:
        if "PASSWORD" in str(exc).upper():
            raise Unreadable(LOCKED_STATEMENT) from exc
        raise Unreadable(UNREADABLE_FILE) from exc
    return holdings_from_statement(parsed)


def holdings_from_file(path: Path, password: str = "") -> list[dict]:
    """CSV, Excel, or a statement PDF. The caller deletes the file."""
    data = path.read_bytes()
    if data.startswith(b"%PDF"):
        return holdings_from_pdf(path, password)
    if data.startswith(b"PK"):
        return holdings_from_excel(path)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Unreadable(UNREADABLE_FILE) from exc
    return holdings_from_csv(text)


def scheme_codes_from_json(body) -> list[int]:
    """Scheme codes chosen from the fund list. Duplicates are dropped."""
    if not isinstance(body, dict) or not isinstance(body.get("schemes"), list):
        raise Unreadable(UNREADABLE_REQUEST)
    codes = []
    seen = set()
    for item in body["schemes"]:
        if isinstance(item, bool) or not isinstance(item, int):
            raise Unreadable(UNREADABLE_REQUEST)
        if item in seen:
            continue
        seen.add(item)
        codes.append(item)
    if len(codes) > 25:
        raise Unreadable(TOO_MANY_FUNDS)
    if not codes:
        raise Unreadable(EMPTY_FUNDS)
    return codes
