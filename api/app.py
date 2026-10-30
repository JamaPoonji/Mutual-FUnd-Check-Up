"""POST /api/analyze and the start page.

The uploaded file is written to a temp file and deleted in a finally block,
whether the report is built or the file cannot be read. The report is returned
once and not stored. Logs are status, timing and error type only.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import logging
import os
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from mf_plain.engine import to_dict
from mf_plain.sample import sample_portfolio
from mf_plain import analyze
from mf_plain.htmlview import render_html
from pipeline.assemble import report_for
from api.data import FundData, StoreNotReady, load_fund_data
from api.parse import (
    EMPTY_HOLDINGS, UNREADABLE_FILE, UNREADABLE_REQUEST, Unreadable,
    holdings_from_file, holdings_from_json, scheme_codes_from_json,
)
from api.search import scheme_holdings, search_schemes

log = logging.getLogger("mfadvisor.api")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
TEMP_DIR = Path(tempfile.gettempdir()) / "mf-advisor-uploads"
NOT_READY = "The fund figures are not ready yet. Try again later."
TOO_LARGE = "That file is too large. Upload a statement under 8 MB."
FAILED = "Something went wrong while building the report."
EQUAL_WEIGHT_NOTE = (
    "These funds are weighted equally, because no amounts were given. "
    "Upload a holdings file if you want the report to use what you actually hold."
)

_UPLOAD_HOOK = """<script>
window.MFAdvisor=window.MFAdvisor||{};
window.MFAdvisor.accept=".csv,.xlsx,.pdf";
window.MFAdvisor.onUpload=async function(file){
  MFAdvisor.loading();
  try{
    var body=new FormData();
    body.append("file", file, file.name||"holdings");
    var pass=document.getElementById("caspass");
    if(pass&&pass.value) body.append("password", pass.value);
    var res=await fetch("/api/analyze",{method:"POST",body:body});
    var data={};
    try{data=await res.json()}catch(e){data={}}
    if(!res.ok) throw new Error((data&&data.error)||"We could not build your report.");
    MFAdvisor.show(data);
  }catch(e){
    MFAdvisor.error((e&&e.message)||"We could not build your report.");
  }
};
</script>
"""

MAX_UPLOAD_BYTES = 8_000_000
MAX_REQUEST_BYTES = 10_000_000  # multipart framing sits on top of the file


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Load once at startup so the first visitor does not pay for it, and so a
    # store that cannot be read shows up in /healthz rather than in the first
    # report request.
    try:
        get_fund_data()
        start_page()
    except Exception:
        log.exception("startup preload failed; /healthz will report unavailable")
    yield


app = FastAPI(title="MF check-up", docs_url=None, redoc_url=None, openapi_url=None,
              lifespan=lifespan)
_funds: FundData | None = None
_page: str | None = None


class AnalyzeError(Exception):
    def __init__(self, message: str, status: int = 422):
        self.message = message
        self.status = status


def get_fund_data() -> FundData:
    global _funds
    if _funds is None:
        try:
            _funds = load_fund_data()
        except Exception as exc:
            log.exception("fund data could not be loaded")
            raise AnalyzeError(NOT_READY) from exc
    return _funds


def report_payload(holdings: list[dict], funds: FundData, *, equal_weight: bool = False) -> dict:
    if not holdings:
        raise AnalyzeError(EMPTY_HOLDINGS)
    report = report_for(
        holdings, funds.catalog, funds.details, funds.metrics, funds.medians,
        funds.quality, funds.as_of, funds.preferred,
    )
    payload = to_dict(report)
    payload["schema_version"] = 1
    if equal_weight:
        payload["equal_weight"] = True
        payload["equal_weight_note"] = EQUAL_WEIGHT_NOTE
    return payload


def _reject(message: str, status: int = 422) -> JSONResponse:
    return JSONResponse({"error": message, "unmatched": []}, status_code=status)


async def _read_capped(upload, limit: int) -> bytes:
    """Read an upload in chunks so a huge body is refused, not buffered."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1 << 20)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise AnalyzeError(TOO_LARGE, 413)
        chunks.append(chunk)
    return b"".join(chunks)


def _scratch(data: bytes, suffix: str) -> Path:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="mfhold-", suffix=suffix, dir=TEMP_DIR)
    path = Path(name)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


def _upload_holdings(data: bytes, password: str) -> list[dict]:
    if len(data) > 8_000_000:
        raise AnalyzeError(UNREADABLE_FILE)
    if data.startswith(b"%PDF"):
        suffix = ".pdf"
    elif data.startswith(b"PK"):
        suffix = ".xlsx"
    else:
        suffix = ".csv"
    path = _scratch(data, suffix)
    try:
        try:
            return holdings_from_file(path, password)
        except Unreadable as exc:
            raise AnalyzeError(str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)


def start_page() -> str:
    global _page
    if _page is None:
        html = render_html(None, sample=analyze(sample_portfolio()))
        needle = "<script>\n(function(){"
        if needle not in html:
            raise RuntimeError("start page template has no app script")
        _page = html.replace(needle, _UPLOAD_HOOK + needle, 1)
    return _page


@app.get("/", response_class=HTMLResponse)
def home():
    return start_page()


@app.get("/healthz")
def healthz():
    try:
        funds = get_fund_data()
    except AnalyzeError:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ok", "as_of": funds.as_of, "schemes": len(funds.metrics)}


@app.post("/api/schemes")
async def find_schemes(request: Request):
    started = time.perf_counter()
    status = 200
    error_type = ""
    try:
        try:
            body = await request.json()
        except Exception as exc:
            raise AnalyzeError(UNREADABLE_REQUEST) from exc
        if not isinstance(body, dict) or not isinstance(body.get("q", ""), str):
            raise AnalyzeError(UNREADABLE_REQUEST)
        funds = get_fund_data()
        hits = await run_in_threadpool(search_schemes, funds, body.get("q") or "")
        return {"schemes": hits}
    except AnalyzeError as exc:
        status = exc.status
        error_type = type(exc).__name__
        return _reject(exc.message, exc.status)
    except Exception as exc:
        log.exception("request failed")
        status = 500
        error_type = type(exc).__name__
        return _reject(FAILED, 500)
    finally:
        log.info(
            "status=%s ms=%d error_type=%s",
            status, int((time.perf_counter() - started) * 1000), error_type,
        )


@app.post("/api/analyze")
async def analyze_holdings(request: Request):
    started = time.perf_counter()
    status = 200
    error_type = ""
    try:
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type:
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
                raise AnalyzeError(TOO_LARGE, 413)
            form = await request.form()
            upload = None
            password = ""
            try:
                upload = form.get("file")
                raw_password = form.get("password")
                if isinstance(raw_password, str):
                    password = raw_password
                if upload is None or not hasattr(upload, "read"):
                    upload = next((value for value in form.values() if hasattr(value, "read")), None)
                if upload is None:
                    raise AnalyzeError(UNREADABLE_FILE)
                data = await _read_capped(upload, MAX_UPLOAD_BYTES)
                holdings = await run_in_threadpool(_upload_holdings, data, password)
            finally:
                if upload is not None:
                    await upload.close()
        else:
            try:
                body = await request.json()
            except Exception as exc:
                raise AnalyzeError(UNREADABLE_REQUEST) from exc
            try:
                if isinstance(body, dict) and "schemes" in body:
                    codes = scheme_codes_from_json(body)
                    fund_data = get_fund_data()
                    holdings = scheme_holdings(codes, fund_data)
                    return await run_in_threadpool(
                        report_payload, holdings, fund_data, equal_weight=True
                    )
                holdings = holdings_from_json(body)
            except Unreadable as exc:
                raise AnalyzeError(str(exc)) from exc
        return await run_in_threadpool(report_payload, holdings, get_fund_data())
    except AnalyzeError as exc:
        status = exc.status
        error_type = type(exc).__name__
        return _reject(exc.message, exc.status)
    except Exception as exc:
        log.exception("request failed")
        status = 500
        error_type = type(exc).__name__
        return _reject(FAILED, 500)
    finally:
        log.info(
            "status=%s ms=%d error_type=%s",
            status, int((time.perf_counter() - started) * 1000), error_type,
        )
