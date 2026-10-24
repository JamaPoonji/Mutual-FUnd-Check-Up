"""Reference job: median TER per category x plan from TigZig scheme_details_latest.

Run:  python pipeline/build_category_medians.py [details.parquet] [out.csv]
Needs: pip install duckdb.   Source: https://api.tigzig.com/mf/v1/download/scheme_details_latest.parquet

Rules (same as the engine):
- one TER per FUND, not per plan row: ter_* columns repeat on every plan of a fund, so we dedupe on
  amfi_ssd_fund_id (rows with no fund id fall back to scheme_code)
- Direct median uses ter_direct, Regular median uses ter_regular (never mix them)
- only active schemes, and only funds with a TER on file
- category = category_sub (TigZig's SEBI sub-category)
- the engine distrusts any median built on fewer than Thresholds.median_min_funds (5) funds
"""
import sys

import duckdb

SRC = sys.argv[1] if len(sys.argv) > 1 else "https://api.tigzig.com/mf/v1/download/scheme_details_latest.parquet"
OUT = sys.argv[2] if len(sys.argv) > 2 else "data/category_median_ter_snapshot.csv"

SQL = f"""
WITH funds AS (
  SELECT coalesce(amfi_ssd_fund_id, 'code:' || scheme_code) AS fund_id,
         any_value(category_group_clean) AS grp,
         any_value(category_sub)         AS category,
         any_value(ter_direct)           AS ter_direct,
         any_value(ter_regular)          AS ter_regular,
         max(ter_date)                   AS ter_date
  FROM read_parquet('{SRC}')
  WHERE is_active AND category_sub IS NOT NULL
  GROUP BY 1
), long AS (
  SELECT grp, category, 'Direct'  AS plan, ter_direct  AS ter, ter_date FROM funds WHERE ter_direct  IS NOT NULL
  UNION ALL
  SELECT grp, category, 'Regular' AS plan, ter_regular AS ter, ter_date FROM funds WHERE ter_regular IS NOT NULL
)
SELECT grp AS category_group, category, plan,
       round(median(ter), 2)                  AS median_ter_pct,
       count(*)                               AS fund_count,
       round(quantile_cont(ter, 0.25), 2)     AS p25_ter_pct,
       round(quantile_cont(ter, 0.75), 2)     AS p75_ter_pct,
       max(ter_date)                          AS latest_ter_date
FROM long
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
"""

if __name__ == "__main__":
    duckdb.sql(SQL).write_csv(OUT)
    n = duckdb.sql(f"select count(*) from read_csv_auto('{OUT}')").fetchone()[0]
    print(f"wrote {n} rows to {OUT}")
