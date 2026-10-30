# mf_plain: the plain-language layer

Takes the numbers your analytics already produce and turns them into short sentences,
colour-coded statuses, small pictures and fund verdicts an ordinary investor can read.
Pure Python 3.9+, no dependencies. It needs **no stock-level holdings**, so there is
no overlap analysis.

```bash
python -m mf_plain                        # demo report (markdown) on made-up sample data
python -m mf_plain --json                 # the same report as JSON, for a front end
python -m mf_plain --html ui/index.html   # the report-card page; open it in a browser
python -m mf_plain --start ui/start.html  # the start screen (upload + sample button)
python tools/gen_docs.py                  # regenerate docs/thresholds.md and the JSON schemas
python -m pytest                          # 88 tests
```

## What it measures (four areas per fund, plus portfolio mix)

| Area | Section | Input on `Fund` | What the investor reads |
|---|---|---|---|
| Returns | Growth over 1, 3 and 5 years (CAGR) | `returns`, `bench_returns` | "Grew 17.1% a year; the index grew 14.6%." plus a ₹1,00,000 picture |
| Returns | Year by year (calendar years) | `calendar_returns`, `bench_calendar_returns` | "In every one of the last 5 calendar years this fund beat the index. On average 3.0 points ahead (its alpha)." plus a bar chart with the alpha under each year |
| Returns | Across every start date (rolling) | `rolling_beat_pct`, `rolling_window_years` | "In 8 out of every 10 three-year periods, it did better." |
| Risk | In rising and falling markets (capture) | `upside_capture`, `downside_capture`, `capture_years` | "For every ₹100 the index gained, this fund gained ₹108. For every ₹100 it lost, it lost ₹88." |
| Risk | The worst fall (drawdown) | `max_drawdown`, `bench_max_drawdown`, `recovery_months` | "₹1,00,000 fell to ₹67,000 and took 7 months to come back." |
| Ranking | Quartile in category | `quartiles` ({horizon: 1-4}), `peer_count` | "Top quarter (Q1) of 34 Flexi Cap funds", with Q1-Q4 boxes per period |
| Costs | What you pay | `ter`, `plan`, `category_median_ter` | "Charges 2.15%; the middle Large & Mid Cap regular plan charges 1.80%." (same plan vs same plan) |
| Mix | How your money is spread | `value`, `category` | "40% of your money is in one fund." |

Every field is optional. A missing measure is skipped and listed under "What we could not check".
Nothing is guessed.

## Feeding it data (e.g. from TigZig MFPRO)

```python
from mf_plain import Fund, Portfolio, analyze, quartile_from_rank
fund = Fund(
    name="...", category="Flexi Cap", value=420000, plan="direct", ter=0.75,
    benchmark_name="Nifty 500",
    returns={1: 21.0, 3: 18.4, 5: 17.1}, bench_returns={1: 17.5, 3: 15.2, 5: 14.6},
    calendar_returns={2023: 29.8, 2024: 21.2, 2025: 12.4},       # complete years only
    bench_calendar_returns={2023: 26.9, 2024: 16.2, 2025: 9.9},
    upside_capture=108, downside_capture=88, capture_years=5,
    quartiles={5: quartile_from_rank(rank=8, count=34)}, peer_count=34,
)
report = analyze(Portfolio(funds=[fund], as_of="30 Sep 2026", data_source="TigZig MFPRO"))
```

- **Calendar years:** pass only complete years. Leave out the current year-to-date, because a part-year
  against a full year is not a fair comparison.
- **Capture ratios:** compute them against the same benchmark used for the other comparisons.
- **Quartiles:** rank the fund by its return over each horizon among funds in the same category,
  then `quartile_from_rank(rank, count)`. Q1 = rank in the top quarter. Categories of fewer than 4
  funds raise an error, because a quartile means nothing there.

## How the verdicts work

- **Status per finding:** good / ok / watch / attention, from the cut-offs in `Thresholds` (`models.py`).
- **Status per area:** the weighted average of that area's findings, so one outlier doesn't decide it alone.
- **Calendar years:** status is the worse of the hit rate (years beaten) and the average alpha.
- **Fund verdict:** Doing well, On track, Worth a closer look, Needs attention, or Limited data (fewer
  than two performance findings). Costs can raise a flag but never push a fund to "Needs attention".
- **Capture:** judged on upside divided by downside (1.10 or more is strong). Within 3 points of 100
  both ways reads "moves much like its benchmark".

## Design rules (keep these when you extend it)

1. **Numbers come from code, never from an LLM.** If you add an LLM later, let it re-word
   `Insight.sentence` only. Every figure also sits in `Insight.numbers` so you can check a rewrite.
2. **Observations and questions, not instructions.** Suggestions read "worth asking whether...".
   A test fails if output contains "you should sell/buy", "switch to" or "redeem". Have your
   compliance reviewer confirm the wording before launch (SEBI investment-adviser rules).
3. **Judge on what the user is told.** Rolling win rate is rounded to "5 of 10" first, then scored.
4. **One year is noise.** A 1-year result can never turn a fund green or red on its own.
5. **Index funds are judged on tracking,** not on beating the index. Calendar and rolling
   beat-the-index tests are skipped for them (not reported as missing data).
6. **Costs compare like with like.** A fund's TER is set against the category median for the same plan
   (Direct vs Direct, Regular vs Regular). There is no regular-vs-direct comparison.
7. **Short sentences, pictures for the detail.** Rupee illustrations and per-period figures live in
   `numbers` and are drawn by the UI.

## The UI (`ui/`)

`ui/template.html` is one self-contained page (no build step, no framework). The report JSON is
embedded in it. From top to bottom:

- one sentence on how much of your money is in funds that look healthy, and a **money ribbon**
  (one slice per fund, sized by value, coloured by verdict; tap a slice to jump to the fund)
- **the check-up at a glance:** one line per area with what it is about
- **fund by fund:** a four-icon scorecard (Returns, Risk, Ranking, Costs), "Going well" and
  "Worth a look" lists, then collapsible areas with a one-line explainer under each section
- questions to take to your adviser, what could not be checked, and the disclaimer

Accessibility: every status has its own icon shape and a text label (colour is never the only
signal), keyboard focus is visible, reduced motion is respected, and it follows the system
light/dark setting. Fonts load from Google Fonts and fall back to system fonts offline.

```python
from mf_plain.htmlview import render_html
open("report.html", "w").write(render_html(analyze(portfolio)))
```

## Known limits / next steps

- Weights: pass `analyze(portfolio, weights=Weights(...))`. Defaults are Vedant's choice (not a SEBI/NISM rule): areas Returns 35 / Risk 25 / Ranking 25 / Costs 15; inside Returns CAGR 40 / calendar 30 / rolling 30; inside Risk capture 50 / drawdown 50; quartile periods 1y 20 / 3y 40 / 5y 40. The verdict is the weighted mean of area scores.
- "Alpha" is simple excess return (fund minus benchmark, percentage points), not Jensen's alpha.
- Reference data (benchmarks, category medians) lives in `data/`.
- Needs: the loader (broker file or CAS parser, scheme matching to MFPRO, computing capture
  ratios and quartiles from NAV history).
- A broker holdings export has no transaction history, so it cannot give the investor's own XIRR.
  A CAMS/KFintech CAS can.
- Sample fund names, benchmark names and figures in `sample.py` are invented. Never show them as real data.

## Where things are
- `mf_plain/`: the engine (`engine.py`, `translators.py`, `facts.py`, `benchmarks.py`, `models.py`, `glossary.py`).
- `ui/template.html`: the front end. `ui/index.html` (sample report) and `ui/start.html` (start screen) are generated.
- `data/`: benchmark map (TigZig), a real category-median TER snapshot, reference lists.
- `pipeline/`: tested reference scripts for category medians and CAGR + quartiles (DuckDB).
- `docs/`: **start with `docs/CURSOR_BRIEF.md`**. Also `METRICS_SPEC.md`, `DATA_PIPELINE.md`, `API_CONTRACT.md`,
  `thresholds.md`, `tigzig_conventions.md`, JSON schemas and a sample report.

## Good to know (per fund, never changes the verdict)
Risk label vs benchmark, fund size (small fund flag), track record (young fund flag), manager tenure (recent change flag),
exit load as filed. Inputs: `riskometer`, `benchmark_riskometer`, `aum_cr`, `allotment_date`, `manager_since`, `exit_load`, `Portfolio.as_of_date`.

## Funds that are not compared with an index
Debt, gold, overseas, arbitrage, equity savings and conservative hybrid funds (`mf_plain/benchmarks.py`) are judged on ranking
and costs only, with a note. Rolling needs about 4 years of history, capture needs 60 daily observations, a category median
needs 5 funds. Anything less becomes a line under "What we could not check".

## Building the fund store

The server reads one SQLite file. It is built from TigZig MFPRO, free and
unkeyed, and it is a **two-step job — the order matters**:

```bash
pip install -r requirements-build.txt

python -m pipeline.indices    # NSE total-return series -> index_series
python -m pipeline.nightly    # scheme_metrics, medians, quartiles, details, quality
```

`nightly` fills benchmark-relative columns from the stored TRI series, so it
checks for that series first and stops with a message if `pipeline.indices` has
not run. It downloads the 178 MB NAV master once per day and keeps a dated copy
in `data/raw/<as-of>/`.

`data/store/mf.sqlite` ends up around 5 MB and holds everything the runtime
needs: `scheme_metrics`, `category_median_ter`, `scheme_details`,
`scheme_quality`, `job_run`, and `index_series` (which only the build reads).

## Running it

```bash
pip install -r requirements.txt          # runtime only: no duckdb
uvicorn api.app:app --port 8080
```

`GET /healthz` returns `200 {"status":"ok","as_of":…,"schemes":…}` once the store
loads, and `503` when it cannot. The image's HEALTHCHECK uses it.

## Deploying

The image carries the built store, not the raw data:

- `requirements.txt` (runtime) has no duckdb; `requirements-build.txt` adds it
  for the pipeline.
- The Dockerfile copies `data/store/mf.sqlite`, the benchmark map and the app
  code. `data/raw/` never enters the image.
- `.github/workflows/refresh-data.yml` rebuilds the store nightly and uploads it
  as an artifact; copy that file into `data/store/mf.sqlite` and rebuild to ship
  new numbers.

Scaling to zero is safe: a cold start loads the store in well under a second.
