"""CAGR and category quartiles.

`quartiles_and_cagr.sql` is the reference, run once per category and plan.
`run_all_quartiles` applies those same rules in one pass so the nightly job
does not scan the NAV file once per category. A test checks the two agree.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

SQL_PATH = Path(__file__).with_name("quartiles_and_cagr.sql")

# Same growth-option screen as quartiles_and_cagr.sql. Names containing
# "dividend" are excluded by that file, which also drops Dividend Yield funds.
GROWTH_WHERE = """
is_active
AND category_sub IS NOT NULL
AND scheme_plan IN ('Direct', 'Regular')
AND scheme_name ILIKE '%growth%'
AND scheme_name NOT ILIKE '%idcw%'
AND scheme_name NOT ILIKE '%dividend%'
"""

_BATCH = """
WITH peers AS (
  SELECT scheme_code, category_sub, scheme_plan
  FROM read_parquet($details)
  WHERE """ + GROWTH_WHERE + """
),
nav AS (
  SELECT n.scheme_code, CAST(n.date AS DATE) AS date, CAST(n.nav AS DOUBLE) AS nav
  FROM read_parquet($nav) n
  JOIN peers USING (scheme_code)
  WHERE CAST(n.date AS DATE) <= $asof::DATE
    AND CAST(n.nav AS DOUBLE) > 0
),
firsts AS (
  SELECT scheme_code, min(date) AS first_date FROM nav GROUP BY 1
),
endp AS (
  SELECT scheme_code, max(date) AS end_date FROM nav GROUP BY 1
),
h AS (SELECT unnest([1, 3, 5]) AS yrs),
pts AS (
  SELECT e.scheme_code, h.yrs, e.end_date,
         (e.end_date - to_days(CAST(h.yrs * 365 AS INTEGER))) AS target
  FROM endp e CROSS JOIN h
),
cagr AS (
  SELECT p.scheme_code, p.yrs,
         e.nav AS end_nav, s.nav AS start_nav, (p.end_date - s.date) AS days
  FROM pts p
  JOIN firsts f ON f.scheme_code = p.scheme_code AND f.first_date <= p.target
  JOIN nav e ON e.scheme_code = p.scheme_code AND e.date = p.end_date
  ASOF JOIN nav s ON s.scheme_code = p.scheme_code AND s.date <= p.target
  WHERE (p.end_date - s.date) > 0 AND s.nav > 0 AND e.nav > 0
)
SELECT c.scheme_code,
       peers.category_sub AS category,
       peers.scheme_plan AS plan,
       c.yrs,
       round((power(c.end_nav / c.start_nav, 365.0 / c.days) - 1) * 100, 2) AS cagr_pct,
       rank() OVER (PARTITION BY peers.category_sub, peers.scheme_plan, c.yrs
                    ORDER BY c.end_nav / c.start_nav DESC) AS rnk,
       count(*) OVER (PARTITION BY peers.category_sub, peers.scheme_plan, c.yrs) AS n,
       CASE WHEN count(*) OVER (PARTITION BY peers.category_sub, peers.scheme_plan, c.yrs) >= 4
            THEN ceil(rank() OVER (
                   PARTITION BY peers.category_sub, peers.scheme_plan, c.yrs
                   ORDER BY c.end_nav / c.start_nav DESC)::DOUBLE
                 / count(*) OVER (PARTITION BY peers.category_sub, peers.scheme_plan, c.yrs) * 4)::INT
       END AS quartile
FROM cagr c
JOIN peers ON peers.scheme_code = c.scheme_code
ORDER BY 2, 3, 4, 6
"""

_SCHEMES = """
SELECT scheme_code, scheme_name, isin, category_sub,
       category_group_clean AS category_group, scheme_plan
FROM read_parquet($details)
WHERE """ + GROWTH_WHERE + """
ORDER BY scheme_code
"""

_FIRST_DATES = """
WITH peers AS (
  SELECT scheme_code FROM read_parquet($details) WHERE """ + GROWTH_WHERE + """
)
SELECT n.scheme_code, min(CAST(n.date AS DATE)) AS first_date
FROM read_parquet($nav) n
JOIN peers USING (scheme_code)
WHERE CAST(n.date AS DATE) <= $asof::DATE
  AND CAST(n.nav AS DOUBLE) > 0
GROUP BY 1
"""


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    return con


def _rows(cursor) -> list[dict]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def reference_sql() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def run_reference(con, nav, details, as_of: str, category: str, plan: str) -> list[dict]:
    """Run pipeline/quartiles_and_cagr.sql for one category and plan."""
    cur = con.execute(reference_sql(), {
        "nav": str(nav), "details": str(details), "asof": as_of,
        "category": category, "plan": plan,
    })
    return _rows(cur)


def run_all_quartiles(con, nav, details, as_of: str) -> list[dict]:
    """CAGR, rank, n and quartile for every growth Direct and Regular scheme."""
    cur = con.execute(_BATCH, {"nav": str(nav), "details": str(details), "asof": as_of})
    return _rows(cur)


def load_schemes(con, details) -> list[dict]:
    return _rows(con.execute(_SCHEMES, {"details": str(details)}))


def load_first_dates(con, nav, details, as_of: str) -> dict[int, object]:
    rows = _rows(con.execute(_FIRST_DATES, {
        "nav": str(nav), "details": str(details), "asof": as_of,
    }))
    return {int(r["scheme_code"]): r["first_date"] for r in rows}


def nonpositive_nav_count(con, nav, details, as_of: str) -> int:
    """Peer NAV rows at or below zero. Those days are left out of the CAGR pass."""
    row = con.execute(
        """
        WITH peers AS (
          SELECT scheme_code FROM read_parquet($details) WHERE """ + GROWTH_WHERE + """
        )
        SELECT count(*) FROM read_parquet($nav) n
        JOIN peers USING (scheme_code)
        WHERE CAST(n.date AS DATE) <= $asof::DATE
          AND CAST(n.nav AS DOUBLE) <= 0
        """,
        {"nav": str(nav), "details": str(details), "asof": as_of},
    ).fetchone()
    return int(row[0])
