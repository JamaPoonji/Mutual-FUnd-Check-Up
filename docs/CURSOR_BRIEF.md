# Brief for Cursor: build the MFRoboAdvisor website

Read this first. Then `METRICS_SPEC.md` (what to compute), `DATA_PIPELINE.md` (where data comes from and how),
`API_CONTRACT.md` (JSON in and out). `thresholds.md` is generated from code.

## What exists already (do not rewrite)
- `mf_plain/`: a pure-Python 3.9+ engine, no dependencies, 88 tests. It takes a `Portfolio` of `Fund` objects
  that already hold the numbers (CAGR, calendar returns, capture, quartiles, TER, ...) and returns a `Report`:
  plain-language sentences, statuses, fund verdicts, flags. It never fetches data and never invents a number.
- `ui/template.html`: the whole front end as ONE self-contained page (no framework, no build step). It renders a
  Report JSON, has a start screen with an upload hook, loading and error states. Dark mode, mobile, accessible.
- `data/tigzig_benchmark_map.csv`: category -> benchmark (73 categories, 7 indices).
- `pipeline/`: two tested reference scripts (category medians, CAGR + quartile SQL).

## What you build
1. **Data layer (nightly job)** -> a `scheme_metrics` store. See `DATA_PIPELINE.md`.
2. **Index series** for the 5 TRI benchmarks (see below). Nobody has supplied these yet.
3. **Holdings ingestion**: broker holdings file or CAMS/KFintech statement -> list of (ISIN or name, value).
4. **Matching**: holding -> scheme_code (ISIN against `isin` / `isin2`; fall back to name search).
5. **Assembler**: for each holding build a `Fund` from `scheme_metrics` + scheme details. Mapping table in `DATA_PIPELINE.md`.
6. **API**: `POST /api/analyze` -> `Report` JSON. Recommended: FastAPI wrapping `mf_plain.analyze`.
7. **Website**: host `ui/template.html`, call the API, call `MFAdvisor.show(report)`. See "Front end" below.

Recommended shape: keep the engine in Python behind a small FastAPI service, precompute metrics nightly, so a user
request is a lookup plus the engine (milliseconds). Do not port the engine to TypeScript: the 88 tests are the spec.

## Index series needed (the open data problem)
Debt, gold, overseas, arbitrage and equity-savings funds are NOT compared with an index (see `benchmarks.py`), so no
G-Sec series is needed. The benchmark tests apply to equity and the equity-heavy hybrids. Total-return (TRI) daily
series are needed for:

| Benchmark | Used by |
|---|---|
| Nifty 50 TRI | Index Funds, Equity ETF, fallback for unmapped categories |
| Nifty 100 TRI | Large Cap |
| Nifty 500 TRI | Flexi, Multi, Focused, ELSS, Value, Contra, Dividend Yield, Large & Mid, Sectoral/Thematic, Aggressive Hybrid, BAF, Multi Asset, Retirement, Children's |
| Nifty Midcap 150 TRI | Mid Cap |
| Nifty Smallcap 250 TRI | Small Cap (Vedant's decision; TigZig uses Smallcap 50, we deliberately differ) |

TigZig's own downloads carry only price indices for Nifty 50 / 500 / Midcap 100 (Yahoo), not TRI. Using price
indices would understate the benchmark by about the dividend yield and flatter every fund. Sources to evaluate: NSE
index site (niftyindices.com) TRI history, or an index fund's NAV as a stand-in (net of fees; short history for new
indices). Whichever source: store one daily series per benchmark, with `source` and `kind` (TRI / proxy) columns, and
show the source on the page when a proxy is used.

## Front end
- Mount contract: `window.MFAdvisor = { onUpload(file), accept, show(report), loading(msg), error(msg), start() }`.
  Set `MFAdvisor.onUpload = async file => { MFAdvisor.loading(); try { MFAdvisor.show(await analyze(file)) } catch (e) { MFAdvisor.error(e.message) } }`
  and `MFAdvisor.accept = ".csv,.xlsx,.pdf"` before the page script runs, or after: both work.
- `__REPORT_JSON__` / `__SAMPLE_JSON__` in the template are build-time slots. In production put `null` in the first (shows the
  start screen) and keep the sample or `null` in the second. `python -m mf_plain --start ui/start.html` shows the result.
- If you move to React/Next later, port the render functions in `ui/template.html` one-for-one; they take only the Report JSON.
- Keep: shape-coded icons (colour is never the only signal), visible focus, `prefers-reduced-motion`, light/dark,
  the "(Strong/Fine/Look closer/Needs attention)" screen-reader text, 16 px side gutters on mobile.
- Do not add new numbers in the front end. Everything the user reads comes from the Report.

## Rules you must not break
1. Numbers come from code, never from an LLM. An LLM may only re-word `Insight.sentence`, and every figure must still be in `Insight.numbers`.
2. Observations and questions only, never trade instructions. A test (`test_no_trade_instructions_in_any_output`) enforces it. Keep it green.
3. Missing data is skipped and listed under `data_gaps`. Never fill a gap with a default.
4. Judge on what the user is told (rolling % is rounded to "k of 10" before scoring).
5. Use the Growth option's NAV only. IDCW NAVs drop on payouts and would understate returns.
6. Count fund AUM once per fund (`fund_dedup_flag`).

## Acceptance checks
- Reproduce, for 5 funds of your choice, the CAGR / rolling beat rate / capture shown in the MFPRO app (https://mfpro.tigzig.com)
  within rounding (CAGR within 0.1 pt). Differences must be explained by the benchmark (we use the TRI category benchmark).
- `python -m pytest` stays green; add a test for each new mapper function.
- Golden file: `docs/sample_report.json` must still validate against `docs/report.schema.json`.
- A portfolio with an unmatched ISIN must still produce a report, with the holding listed as "could not be matched".
- A fund with no TER, no median, or a short history must degrade to a `data_gaps` line, never an error.

## Decisions that are Vedant's, not yours
(Decided: Small Cap uses Smallcap 250 TRI. Index series sourcing is Cursor's job; weights are set.)
- The weights (`Weights` in `models.py`; list in `thresholds.md`).
- Whether the report is positioned as general information (current copy) or as advice. Vedant is an AMFI-registered MFD;
  advice-like output may need a registered investment adviser. Compliance review before launch.
- Privacy: DECIDED, option A. The start screen says "Your file is not saved. We use it only to build this report, then discard it. Close the page and the report is gone." The backend must make that true (see Privacy requirements below).

## Build order
M1 nightly data job + `scheme_metrics` + medians/quartiles  ->  M2 index series  ->  M3 matcher + assembler on 5 hand-picked funds,
engine output eyeballed  ->  M4 FastAPI + front-end wiring  ->  M5 holdings parsers (CSV first, then CAS PDF)  ->  M6 acceptance checks, error states, compliance copy.


## Privacy requirements (the start-screen promise must be true)
The uploaded holdings file and the report are never saved. Build to this:
- Process the upload in memory or a temp file that is deleted in a `finally` block, whether the run succeeds or fails.
- No database rows, object storage, cache or queue entries holding the file, holdings, folio numbers, PAN or report.
- Logs and error trackers (e.g. Sentry) must not contain file contents, holdings, PAN, folio numbers or names. Log only status, timing and error type.
- Do not send the file or holdings to any third-party service. Fund data from TigZig is fetched by ISIN only, never with user identity.
- The report lives only in the browser page; no shareable report URLs, no server-side session copy.
- Analytics, if any, must not capture file or report content.
- Add a test that proves the temp file is gone after both a successful and a failing upload.
- If this ever changes (accounts, saved reports), the start-screen wording and a proper privacy policy must change first. India's DPDP Act applies once personal data is kept.
