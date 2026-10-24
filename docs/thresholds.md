# Every threshold the engine uses

Generated from `mf_plain/models.py` by `tools/gen_docs.py`. Do not edit by hand.

| Group | Name | Default | Note |
|---|---|---|---|
| CAGR gap vs benchmark, percentage points per year | `returns_good` | 1.0 |  |
| CAGR gap vs benchmark, percentage points per year | `returns_ok` | -1.0 |  |
| CAGR gap vs benchmark, percentage points per year | `returns_watch` | -3.0 |  |
| CAGR gap vs benchmark, percentage points per year | `index_tracking_ok` | 0.5 | index funds: acceptable gap either way |
| calendar years: share of years the fund beat its benchmark (0-1) | `cal_good` | 0.7 |  |
| calendar years: share of years the fund beat its benchmark (0-1) | `cal_ok` | 0.5 |  |
| calendar years: share of years the fund beat its benchmark (0-1) | `cal_watch` | 0.3 |  |
| calendar years: share of years the fund beat its benchmark (0-1) | `cal_min_years` | 3 |  |
| calendar years: share of years the fund beat its benchmark (0-1) | `cal_max_years` | 6 |  |
| calendar-year alpha (fund minus benchmark, percentage points), averaged over the years shown | `cal_alpha_good` | 1.0 |  |
| calendar-year alpha (fund minus benchmark, percentage points), averaged over the years shown | `cal_alpha_ok` | -1.0 |  |
| calendar-year alpha (fund minus benchmark, percentage points), averaged over the years shown | `cal_alpha_watch` | -3.0 |  |
| rolling windows: % of windows beating benchmark | `rolling_good` | 70.0 |  |
| rolling windows: % of windows beating benchmark | `rolling_ok` | 50.0 |  |
| rolling windows: % of windows beating benchmark | `rolling_watch` | 30.0 |  |
| capture: ratio = upside / downside | `capture_good_ratio` | 1.10 |  |
| capture: ratio = upside / downside | `capture_ok_ratio` | 0.95 |  |
| capture: ratio = upside / downside | `capture_watch_ratio` | 0.85 |  |
| capture: ratio = upside / downside | `index_capture_band` | 3.0 | index funds: within +/-3 of 100 is "moves with the index" |
| fund drawdown minus benchmark drawdown, percentage points (positive = fell less) | `dd_good` | 3.0 |  |
| fund drawdown minus benchmark drawdown, percentage points (positive = fell less) | `dd_ok` | -3.0 |  |
| fund drawdown minus benchmark drawdown, percentage points (positive = fell less) | `dd_watch` | -7.0 |  |
| quartile: average quartile across horizons | `quartile_good` | 1.5 |  |
| quartile: average quartile across horizons | `quartile_ok` | 2.5 |  |
| quartile: average quartile across horizons | `quartile_watch` | 3.5 |  |
| TER minus the category median (same plan), percentage points; negative = cheaper than median | `cost_good_gap` | -0.15 |  |
| TER minus the category median (same plan), percentage points; negative = cheaper than median | `cost_ok_gap` | 0.15 |  |
| TER minus the category median (same plan), percentage points; negative = cheaper than median | `cost_watch_gap` | 0.40 |  |
| data sufficiency | `rolling_min_history_years` | 4.0 | 3-year rolling needs about 4 years of NAV history (5-year: 7) |
| data sufficiency | `capture_min_obs` | 60 | paired daily observations |
| data sufficiency | `median_min_funds` | 5 | fewer funds than this and a category median is not trusted |
| fund facts | `aum_small_cr` | 100.0 | below this, flag as a small fund |
| fund facts | `young_fund_years` | 3.0 | below this, flag a short track record |
| fund facts | `manager_recent_months` | 12 | manager changed within this many months |
| fund facts | `riskometer_gap_levels` | 1 | fund rated this many levels above its benchmark or more |
| portfolio mix | `category_max_share` | 50.0 |  |
| portfolio mix | `fund_max_share` | 35.0 |  |

## Weights (defaults; Vedant supplies the real ones)

| Level | Key | Default |
|---|---|---|
| inside an area | `returns` | 40.0 |
| inside an area | `calendar` | 30.0 |
| inside an area | `consistency` | 30.0 |
| inside an area | `capture` | 50.0 |
| inside an area | `risk` | 50.0 |
| inside an area | `peers` | 1.0 |
| inside an area | `costs` | 1.0 |
| in the fund verdict | `returns` | 35.0 |
| in the fund verdict | `risk` | 25.0 |
| in the fund verdict | `peers` | 25.0 |
| in the fund verdict | `costs` | 15.0 |
| quartile period (years) | `1` | 20.0 |
| quartile period (years) | `3` | 40.0 |
| quartile period (years) | `5` | 40.0 |

## Fund verdict

The label is the weighted mean of the area scores. Needs attention at -1.0 or below. Doing well at 0.5 or above. On track in between.

Worth a closer look when that mean is below 0, or any finding is attention, or two or more findings are watch. One watch stays on the fund and does not change the label by itself.

Index funds are not given a quartile rank. The note is: "Not ranked against other index funds, because that group mixes different indices." Tracking, capture and costs stay.
