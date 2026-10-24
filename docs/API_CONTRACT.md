# API contract

## POST /api/analyze
Request: `multipart/form-data` with the holdings file, or JSON `{ "holdings": [{ "isin": "INF...", "name": "...", "value": 420000 }] }`.
Response 200: a `Report` (schema: `docs/report.schema.json`, example: `docs/sample_report.json`).
Response 422: `{ "error": "plain-language message", "unmatched": [ { "name": "...", "isin": "..." } ] }`. The front end shows `error` verbatim,
so write it for a user ("We could not read that file. Please upload the holdings file from your broker as CSV or Excel.").

A report is still returned when some holdings are unmatched or lack data. Unmatched holdings go in a `data_gaps` line; funds with
too little data get verdict "Limited data".

## Engine input
`Fund` / `Portfolio`: `docs/fund_input.schema.json`. All analytic fields optional. Percentages are plain numbers (12.5 = 12.5%).
Mapping from TigZig columns: `DATA_PIPELINE.md`.

## Front-end hooks (browser)
`window.MFAdvisor.onUpload(file)`, `.accept`, `.show(report)`, `.loading(msg)`, `.error(msg)`, `.start()`.

## Versioning
Add `"schema_version": 1` to the Report at the API layer. The front end ignores unknown fields.
