-- Reference SQL (DuckDB): point-to-point CAGR and quartile within category + plan.
-- Rules: TigZig CAGR convention (365-day year; start = nearest earlier trading day to as_of - N*365 days;
-- a fund younger than the horizon gets NO value). Growth option only (IDCW NAVs drop on payouts).
-- Parameters: $nav = NAV parquet, $details = scheme_details parquet, $asof = date, $category, $plan
WITH peers AS (
  SELECT scheme_code FROM read_parquet($details)
  WHERE is_active AND category_sub = $category AND scheme_plan = $plan
    AND scheme_name ILIKE '%growth%' AND scheme_name NOT ILIKE '%idcw%' AND scheme_name NOT ILIKE '%dividend%'
), nav AS (
  SELECT n.scheme_code, CAST(n.date AS DATE) AS date, CAST(n.nav AS DOUBLE) AS nav   -- date is VARCHAR in the file
  FROM read_parquet($nav) n JOIN peers USING (scheme_code)
  WHERE CAST(n.date AS DATE) <= $asof::DATE
), endp AS (
  SELECT scheme_code, max(date) AS end_date FROM nav GROUP BY 1
), h AS (SELECT unnest([1, 3, 5]) AS yrs),
pts AS (
  SELECT e.scheme_code, h.yrs, e.end_date, (e.end_date - to_days(CAST(h.yrs * 365 AS INTEGER))) AS target
  FROM endp e CROSS JOIN h
), cagr AS (
  SELECT p.scheme_code, p.yrs,
         e.nav AS end_nav, s.nav AS start_nav, (p.end_date - s.date) AS days
  FROM pts p
  JOIN nav e ON e.scheme_code = p.scheme_code AND e.date = p.end_date
  ASOF JOIN nav s ON s.scheme_code = p.scheme_code AND s.date <= p.target
  WHERE (SELECT min(date) FROM nav m WHERE m.scheme_code = p.scheme_code) <= p.target   -- old enough
)
SELECT scheme_code, yrs,
       round((power(end_nav / start_nav, 365.0 / days) - 1) * 100, 2) AS cagr_pct,
       rank() OVER (PARTITION BY yrs ORDER BY end_nav / start_nav DESC) AS rnk,
       count(*) OVER (PARTITION BY yrs) AS n,
       -- quartile_from_rank: ceil(rank / n * 4); needs n >= 4
       CASE WHEN count(*) OVER (PARTITION BY yrs) >= 4
            THEN ceil(rank() OVER (PARTITION BY yrs ORDER BY end_nav / start_nav DESC)::DOUBLE
                      / count(*) OVER (PARTITION BY yrs) * 4)::INT END AS quartile
FROM cagr
ORDER BY yrs, rnk;
