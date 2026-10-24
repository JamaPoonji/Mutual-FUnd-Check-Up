# TigZig MFPRO conventions we can align with (read 2026-10-12)

Source pages: https://www.tigzig.com/ai/llms/methodology.md (index of 19 metric pages under https://www.tigzig.com/mfpro/<metric>),
https://api.tigzig.com/mf/v1/, https://www.tigzig.com/mfpro/benchmark-map. Credit: Amar Harolikar, TigZig (cite source; free use under tigzig.com/terms).

| Metric | TigZig method | Our rule (proposed) |
|---|---|---|
| CAGR | (End/Start)^(365/days)-1; start = nearest prior trading day to as-of minus 365 days; <1y shown as absolute %; fund younger than horizon shows "-" | Same. Younger fund: no value, never 0. |
| Rolling | every trading day is an end date; windows 3M(91d) 6M(183d) 1Y(365d) 3Y(1096d) 5Y(1826d); CAGR for >=1Y with 365.25/actual days; valid only if actual gap > min gap (3Y 986d, 5Y 1643d); needs ~4-5y history for 3Y, 7-8y for 5Y | Same windows. Show 3Y rolling only with >=4y history, 5Y with >=7y. |
| Beat rate | share of paired days where fund rolling return > benchmark rolling return (strict); bands >70 / 50-70 / <50 | Same definition; our 70/50 cut-offs already match. |
| Win rate / % negative | share of rolling windows with positive / negative return | Candidate extra: "chance of losing money over N years". |
| Capture | daily returns; up day = benchmark >0, down day = benchmark <0, zero days dropped; ratio of average fund return to average benchmark return x100; min 60 daily observations; no risk-free | Same. Judge with our ratio bands (no numeric bands published). |
| Alpha / beta | OLS on daily returns, no risk-free; annual alpha = ((1+a_daily/100)^252-1)x100; |t|>=2 = significant | Our calendar "alpha" is simple excess return (fund - benchmark), not regression alpha. Label it "margin over benchmark". |
| Max drawdown | (NAV / running max - 1); bands: about -15 mild, -30 to -40 significant, -50 or worse extreme | Use these bands in wording. |
| Recovery | first date NAV >= peak NAV, counted from the TROUGH in calendar days; "Still underwater" if none; only the single max drawdown | Same, and say "from the bottom". |
| Sharpe | rf fixed 6%, daily excess x252 / (sample sd x sqrt252); bands 1 / 0.5 / 0 | Optional extra measure. |
| Percentile rank | rank/(n-1) x100 within the SELECTED set; bands 75/50/25 | We rank within the whole category and plan (quartile), not a hand-picked set. |
| Dynamic score | weights normalised to sum 100; per-metric 0-1 scaling (min-max, z-score clipped +-3, or percentile); direction-aware; missing metrics dropped and weights renormalised | Our Weights already renormalise over available findings. |

Known inconsistencies on their pages: CAGR exponent 365 vs rolling 365.25; the 3Y CAGR worked example prints 14.56% where the stated formula gives about 14.49%.
Capture and beat-rate pages name Nifty 50 as the benchmark; the benchmark-map page says category benchmarks drive all benchmark metrics. We use the category map.
