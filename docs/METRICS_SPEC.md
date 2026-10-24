# Metrics spec: what to compute, exactly

Conventions follow TigZig MFPRO (see `tigzig_conventions.md`) so numbers reconcile with https://mfpro.tigzig.com.
Cut-offs live in `thresholds.md` (generated). This file is the definitions.

| Measure | Definition |
|---|---|
| CAGR (1/3/5y) | `(End/Start)^(365/days) - 1`; Start = NAV on the nearest trading day on or before as_of - N x 365 days; `days` = actual days between matched dates. Fund younger than N years: no value. Under 1 year: simple return. Same formula for fund and benchmark. |
| Calendar-year return | Dec-to-Dec: last NAV on or before 31 Dec of the prior year to last NAV on or before 31 Dec. Only complete years; fund must exist at the prior year-end. Latest 6 years, minimum 3 common with the benchmark. |
| Margin ("alpha" on screen) | Fund calendar return minus benchmark calendar return, percentage points. Simple excess return, NOT regression alpha. |
| Rolling beat rate | Every trading day is an end date; 3-year window = 1096 days back (nearest earlier NAV; keep only if actual gap > 986 days); CAGR for fund and benchmark; beat = strictly greater; rate = beats / paired observations. Needs >= 4 years history (5-year window: 7). |
| Upside / downside capture | Daily returns. Up day = benchmark return > 0; down day = < 0; zero days dropped. Upside = mean fund return on up days / mean benchmark return on up days x 100; downside likewise on down days. >= 60 paired observations. No risk-free rate. Window: last 3 years (`capture_years`). |
| Max drawdown | `min over days of (NAV / running max NAV - 1) x 100`. Wording bands: about -15 mild, -30 to -40 significant, -50 or worse extreme. |
| Recovery | From the TROUGH to the first date NAV >= the prior peak, in months. If never: `still_underwater = true`. Only the single worst fall is tracked. Same for the benchmark. |
| Quartile | Rank fund by CAGR over 1/3/5y among funds of the same category_sub and plan (Growth option, active, enough history); `quartile = ceil(rank / n x 4)`; n must be >= 4. |
| Category median TER | Median over distinct funds of the same plan's TER in the same category_sub. Direct vs Direct, Regular vs Regular. n >= 5 else not trusted. |

## Verdict logic (in code, `engine.py`)
- Status per finding: good / ok / watch / attention. Score: +1 / 0 / -1 / -2.
- Area status: weighted mean of its findings' scores (>= 0.5 good, > -0.5 ok, > -1.5 watch, else attention).
- Fund verdict: weighted mean of AREA scores (default area weights: Returns 35, Risk 25, Ranking 25, Costs 15): <= -1.0 Needs attention; below 0, or any attention finding, or two or more watch findings: Worth a closer look; >= 0.5 Doing well; else On track. One watch finding stays visible and does not change the label by itself. Fewer than 2 scored non-cost findings: Limited data
  (1 for funds not compared with an index).
- "Good to know" facts (risk label, size, track record, manager, exit load) never change the verdict. They can add questions.
- Card (all funds) turns red only when the problem is widespread.

## Judgement calls baked in (all deliberate, all changeable in `Thresholds`)
1. A 1-year return can never turn a fund green or red alone (good -> ok, attention -> watch), and says so.
2. Index funds are judged on tracking gap (<= 0.5 pt) and capture within +-3 of 100; calendar and rolling beat-the-index tests are skipped, not reported as missing. They are not given a quartile rank against other index funds, because that group mixes different indices. Tracking, capture and costs stay. The fund carries the note "Not ranked against other index funds, because that group mixes different indices."
3. Funds not compared with an index (debt, gold, overseas, arbitrage, equity savings, conservative hybrid): judged on ranking and costs only, with a note.
4. Calendar-year status = the worse of hit rate (years beaten) and average margin.
5. Capture is judged on upside / downside; downside <= 0 counts as good.
6. Mix: category > 50% or single fund > 35% of the portfolio is flagged; a one-fund portfolio is flagged.
7. Wording: observations and questions only; no buy/sell/switch language.

## Factors that take weights (set by Vedant; an editorial judgement, not a SEBI/NISM rule)
Inside Returns: CAGR, calendar, rolling. Inside Risk: capture, drawdown. Quartile periods 1/3/5y. Areas in the verdict: Returns, Risk, Ranking, Costs.
Not built yet, would need weights: blending of 1/3/5y CAGR, recency weighting of calendar years, upside vs downside capture, weights by fund type, fund-size weighting in the portfolio.
