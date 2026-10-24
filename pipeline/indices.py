"""Daily total-return index levels from NSE Indices.

Yahoo's Nifty symbols are price indices. These five series are the TRI levels
published on niftyindices.com. A name that returns no rows fails the run.

    python -m pipeline.indices
    python -m pipeline.indices --as-of 2026-10-14

Does not read a holdings file and does not fill scheme_metrics.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from pipeline.store import write_index_series

ROOT = Path(__file__).resolve().parent.parent

# The historical-data page posts here. The older Backpage.aspx path now returns HTML.
TRI_URL = "https://www.niftyindices.com/BackPage/getTotalReturnIndexString"
YAHOO_PRICES = "https://yfin-h.tigzig.com/v1/get-all-prices/"
SOURCE = "NSE Indices (niftyindices.com)"
KIND = "TRI"
# A non-browser user agent makes this endpoint accept the POST and then never reply.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 MFRoboAdvisor/0.1"
)
# NSE request name, engine benchmark name. NIFTY 100 is checked live: an empty
# body stops the run instead of a guessed spelling.
SERIES = (
    ("NIFTY 50", "Nifty 50 TRI"),
    ("NIFTY 100", "Nifty 100 TRI"),
    ("NIFTY 500", "Nifty 500 TRI"),
    ("NIFTY MIDCAP 150", "Nifty Midcap 150 TRI"),
    ("NIFTY SMALLCAP 250", "Nifty Smallcap 250 TRI"),
)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONTH_NUMBER = {name: number for number, name in enumerate(_MONTHS, start=1)}


class EmptyIndexSeries(RuntimeError):
    """NSE returned HTTP 200 and no rows. The index name is wrong, or the range is empty."""


def nse_date(day: date) -> str:
    """DD-MMM-YYYY in English, independent of the machine locale."""
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


def parse_nse_date(text: str) -> date:
    """Response dates look like '22 May 2026'."""
    day, month, year = str(text).split()
    return date(int(year), _MONTH_NUMBER[month], int(day))


def parse_tri_payload(body, nse_name: str) -> list[dict]:
    """Turn an NSE TRI payload into dated levels. NTR is ignored.

    The current endpoint returns a JSON list. The older shape was {"d": "<json list>"}.
    """
    if isinstance(body, str):
        body = json.loads(body)
    if isinstance(body, list):
        rows = body
    elif isinstance(body, dict):
        raw = body.get("d")
        if raw is None:
            raise EmptyIndexSeries(f"{nse_name} returned no total-return series")
        rows = json.loads(raw) if isinstance(raw, str) else raw
    else:
        raise EmptyIndexSeries(f"{nse_name} returned no total-return series")
    if not rows:
        raise EmptyIndexSeries(f"{nse_name} returned no total-return rows")
    by_date: dict[str, float] = {}
    for row in rows:
        level = row.get("TotalReturnsIndex")
        when = row.get("Date")
        if level is None or when is None:
            continue
        value = float(level)
        if value <= 0:
            continue
        iso = parse_nse_date(when).isoformat()
        if iso not in by_date:
            by_date[iso] = value
    if not by_date:
        raise EmptyIndexSeries(f"{nse_name} returned no usable total-return levels")
    return [{"date": day, "level": by_date[day]} for day in sorted(by_date)]


def _post_tri(nse_name: str, start: date, end: date):
    payload = {
        "cinfo": (
            "{'name':'%s','startDate':'%s','endDate':'%s','indexName':'%s'}"
            % (nse_name, nse_date(start), nse_date(end), nse_name)
        )
    }
    req = urllib.request.Request(
        TRI_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.niftyindices.com/reports/historical-data",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def fetch_tri(nse_name: str, start: date, end: date) -> list[dict]:
    return parse_tri_payload(_post_tri(nse_name, start, end), nse_name)


def fetch_all(as_of: date, fetch=fetch_tri, pause: float = 1.0) -> list[dict]:
    """All five series. The first empty name raises and nothing is returned."""
    start = date(1999, 1, 1)
    out: list[dict] = []
    for index, (nse_name, benchmark_name) in enumerate(SERIES):
        if index and pause:
            time.sleep(pause)
        points = fetch(nse_name, start, as_of)
        if not points:
            raise EmptyIndexSeries(f"{nse_name} returned no total-return rows")
        for point in points:
            out.append({
                "benchmark_name": benchmark_name,
                "date": point["date"],
                "level": point["level"],
                "source": SOURCE,
                "kind": KIND,
            })
    return out


def yahoo_nifty50_close(on: date) -> tuple[str, float] | None:
    """Close of the Yahoo price index ^NSEI on `on`, or the nearest earlier day in a short window.

    This value is printed for comparison only. It is not stored.
    """
    start = on - timedelta(days=10)
    query = urllib.parse.urlencode({
        "tickers": "^NSEI",
        "start_date": start.isoformat(),
        "end_date": on.isoformat(),
    })
    req = urllib.request.Request(
        YAHOO_PRICES + "?" + query,
        headers={"User-Agent": "MFRoboAdvisor/0.1 (price comparison only; not stored)"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode())
    if not isinstance(body, dict):
        return None
    chosen = None
    for day in sorted(key for key in body if isinstance(body.get(key), dict)):
        bar = body[day].get("^NSEI") if isinstance(body[day], dict) else None
        if not isinstance(bar, dict) or bar.get("Close") is None:
            continue
        chosen = (day, float(bar["Close"]))
        if day == on.isoformat():
            return chosen
    return chosen


def series_stats(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["benchmark_name"], []).append(row)
    order = [name for _, name in SERIES]
    stats = []
    for name in order:
        points = sorted(grouped.get(name, []), key=lambda row: row["date"])
        if not points:
            continue
        latest = points[-1]
        stats.append({
            "benchmark_name": name,
            "rows": len(points),
            "first": points[0]["date"],
            "last": latest["date"],
            "level": latest["level"],
            "source": latest["source"],
            "kind": latest["kind"],
        })
    return stats


def render_summary(rows: list[dict], yahoo: tuple[str, float] | None) -> str:
    lines = ["NSE total-return series (stored):"]
    nifty = None
    for stat in series_stats(rows):
        lines.append(
            f"  {stat['benchmark_name']}: {stat['first']} .. {stat['last']}  "
            f"n={stat['rows']}  latest {stat['level']:.2f}  "
            f"source {stat['source']}  kind {stat['kind']}"
        )
        if stat["benchmark_name"] == "Nifty 50 TRI":
            nifty = stat
    if nifty and yahoo and yahoo[0] == nifty["last"]:
        lines.append(
            f"Nifty 50 on {nifty['last']}: TRI {nifty['level']:.2f} vs Yahoo ^NSEI close "
            f"{yahoo[1]:.2f} (price index, not stored)"
        )
    elif nifty and yahoo:
        lines.append(
            f"Nifty 50 TRI on {nifty['last']}: {nifty['level']:.2f}. "
            f"Yahoo ^NSEI close on {yahoo[0]}: {yahoo[1]:.2f} (price index, not stored; "
            f"no Yahoo bar on the TRI date)"
        )
    elif nifty:
        lines.append(f"Nifty 50 TRI on {nifty['last']}: {nifty['level']:.2f}. Yahoo price comparison unavailable.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Store NSE total-return index series.")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "store" / "mf.sqlite")
    args = parser.parse_args(argv)
    as_of = date.fromisoformat(args.as_of)
    print(f"fetching five NSE total-return series through {as_of.isoformat()}", flush=True)
    rows = fetch_all(as_of)
    written = write_index_series(args.db, rows)
    print(f"wrote {written} index rows to {args.db}", flush=True)
    yahoo = None
    last = next(stat["last"] for stat in series_stats(rows) if stat["benchmark_name"] == "Nifty 50 TRI")
    try:
        yahoo = yahoo_nifty50_close(date.fromisoformat(last))
    except Exception as exc:
        print(f"Yahoo price comparison failed: {type(exc).__name__}", flush=True)
    print(render_summary(rows, yahoo))
    return 0 if yahoo else 1


if __name__ == "__main__":
    raise SystemExit(main())
