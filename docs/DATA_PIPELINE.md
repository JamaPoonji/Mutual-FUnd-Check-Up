# Data pipeline

All fund data comes from TigZig MFPRO (AMFI data, CC0). Free, no key. Courtesy credit is already in `Report.credits`.
Docs: https://api.tigzig.com/mf/v1/ , https://www.tigzig.com/downloads , https://www.tigzig.com/mfpro/<metric>.

## Sources
| File | Size | Refresh | Use |
|---|---|---|---|
| `https://api.tigzig.com/mf/v1/download/amfi_nav_master.parquet` | 178 MB | 3x daily | every scheme's NAV since 2006. Columns: scheme_code INT, **date VARCHAR (cast it)**, nav DECIMAL, scheme_name, isin. Range requests work: DuckDB reads only what it needs. |
| `.../scheme_details_latest.parquet` | 1 MB | 4x daily | one row per scheme, 60 columns (data dictionary: https://www.tigzig.com/md/mfpro/data-dictionary.md) |
| `.../amfi_nav_master_latest.parquet` | 2 MB | 3x daily | scheme universe, first/last NAV date, latest NAV, quarterly AAUM |
| `.../data_quality.csv` | 160 KB | 4x daily | 556 rows where AMFI feed and scheme documents did not match cleanly, with a reason |
| `/mf/v1/nav`, `/details`, `/search` | REST | live | single lookups, 300 req/min, bulk up to 50 schemes |
| MCP `https://api.tigzig.com/mf/mcp` | | | `mf_search`, `mf_nav`, `mf_details` |

Verified on 2026-10-12: details file = 11,209 rows, 8,224 with a regular TER and 8,098 with a direct TER; the category
medians script ran in seconds; the quartile SQL ran in ~30 s over the remote NAV parquet for one category.

## Nightly job
1. Download `scheme_details_latest.parquet`, `data_quality.csv`. Keep a dated copy.
2. `python pipeline/build_category_medians.py` -> `category_median_ter` table (median, count, p25, p75 per category x plan).
3. For each (category_sub, plan): run `pipeline/quartiles_and_cagr.sql` -> CAGR 1/3/5y, rank, n, quartile per scheme.
   Peer set = active, same category_sub, same plan, Growth option, history >= horizon. Quartile needs n >= 4.
4. For every active equity/hybrid scheme compute the rest from NAV and the category benchmark series (see METRICS_SPEC.md):
   calendar returns (last 6 complete years), rolling 3Y beat rate, upside/downside capture (3Y, daily), max drawdown + recovery,
   history_years. Write one row per scheme to `scheme_metrics`.
5. Publish `scheme_metrics`, `category_median_ter`, `category_quartiles` (SQLite or Parquet) to the API service.

### scheme_metrics (one row per scheme_code)
`scheme_code, as_of, history_years, cagr_1y, cagr_3y, cagr_5y, bench_cagr_1y/3y/5y, calendar_returns_json, bench_calendar_returns_json,
rolling_window_years, rolling_beat_pct, upside_capture, downside_capture, capture_years, capture_obs, max_drawdown, bench_max_drawdown,
drawdown_event, recovery_months, bench_recovery_months, still_underwater, quartile_1y/3y/5y, peer_count, benchmark_name`

## TigZig column -> `Fund` field
| Fund field | Source |
|---|---|
| name | `scheme_name` (display `fund_name_latest` if cleaner) |
| isin | `isin` / `isin2` |
| category | `category_sub` ; category_group = `category_group_clean` |
| plan | `scheme_plan` lowercased (direct / regular) |
| ter | `ter_direct` if direct else `ter_regular` (the TER incl. levies); `ter_date` -> ter_date |
| category_median_ter, category_median_n | `category_median_ter` table, same category and same plan |
| benchmark_name | `data/tigzig_benchmark_map.csv` via `mf_plain.benchmarks.benchmark_for(category_sub)`; fund's own filed benchmark is NOT used |
| value | user's holding value (units x latest NAV, or the broker's value) |
| returns / bench_returns | `scheme_metrics.cagr_*` / `bench_cagr_*` |
| calendar_returns / bench_* | `scheme_metrics` (Dec-to-Dec on last NAV on or before 31 Dec; complete years only) |
| rolling_beat_pct, rolling_window_years | `scheme_metrics` |
| upside_capture, downside_capture, capture_years, capture_obs | `scheme_metrics` |
| max_drawdown, bench_max_drawdown, drawdown_event, recovery_months, bench_recovery_months, still_underwater | `scheme_metrics` |
| quartiles {1,3,5}, peer_count | `category_quartiles` |
| history_years | years since the plan's first NAV date |
| aum_cr | `amfi_daily_fund_aum_cr_all_plans` |
| riskometer, benchmark_riskometer | `amfi_daily_riskometer`, `amfi_daily_riskometer_benchmark` |
| manager_names, manager_since | parse `ssd_fund_managers` (names with start dates). Define manager_since = start date of the most recent change of lead manager; inspect real values before fixing the parser |
| allotment_date | `ssd_allotment_date` |
| exit_load | `ssd_exit_load` (text, shown as filed, truncated to 300 chars) |
| is_index | category `Index Funds`, `Equity ETF`, name contains "Index" or "ETF" |
| data_quality_note | `data_quality.csv` reason for this scheme_code, if any |
| benchmark_applies | leave None; the engine decides from the category |

Portfolio: `as_of` (display string), `as_of_date` (ISO, NAV date used), `data_source` = "TigZig MFPRO (AMFI data)".

## Known data traps
- Fund-level columns (AUM, managers, benchmark, riskometer, TER) repeat on every plan row. Count AUM once per fund.
- TER can be blank: matched only on the exact SEBI scheme code. Handle nulls (engine lists a data gap).
- "Index Funds" is one category of ~260 funds across many different indices: its TER median (0.36 direct) is crude. Prefer
  grouping index funds by underlying index when the data allows; until then treat the cost comparison for index funds as soft.
- NAV `date` is a string in the parquet.
- Category names changed in SEBI's Feb 2026 renaming; the benchmark CSV lists both old and new names.
- Matured/merged schemes stay in the NAV file: filter `is_active`.
- Real exit-load text contains "redeemed". That is a filed fact, not an instruction; do not filter it.

## Holdings ingestion (your call)
Broker holdings CSV/Excel (ISIN + units/value) is the simplest path; a CAMS/KFintech CAS PDF gives transaction history
(enables the user's own XIRR, out of scope for v1). Match by ISIN first. A holding that cannot be matched is reported, not dropped silently.
