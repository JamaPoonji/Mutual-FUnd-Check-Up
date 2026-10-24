# Reference data the engine needs

- `tigzig_benchmark_map.csv`: **the benchmark mapping the engine should use.** One benchmark per category (73 categories, 7 indices),
  as of 2026-10-02, from TigZig MFPRO. One index per category keeps funds in a category comparable. The fund's own filed
  benchmark is shown for information only (`ssd_benchmark_tier1_std` in the details data).
- `benchmarks_tier1.csv` (reference only, superseded by the file above): default benchmark per SEBI/AMFI category, taken from AMFI's Tier-1 list
  (the copy circulated with AMFI email 35P/76 of 10 Dec 2021, via CafeMutual). Re-check against the latest
  AMFI list before launch. A scheme's own benchmark in its SID overrides the category default. Use the
  TRI (total return) version so dividends are counted on both sides.
- `category_medians_template.csv`: fill `median_ter_pct` per category and plan. Compute it from the
  scheme master you use (TigZig MFPRO or AMFI TER disclosures) as the median over every scheme in the same
  category and plan, then pass it to each holding as `Fund.category_median_ter`.
- `category_median_ter_snapshot.csv`: a REAL snapshot (built 2026-10-12 by `pipeline/build_category_medians.py` from TigZig
  scheme_details_latest): median, p25, p75 TER and fund count per category x plan (132 rows, 29 with fewer than 5 funds).
  It supersedes `category_medians_template.csv`. Rebuild nightly in production; do not ship the snapshot as live data.
