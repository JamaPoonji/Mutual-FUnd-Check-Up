"""Build standalone pages from ui/template.html.

render_html(report)                 -> the report page (report JSON embedded)
render_html(None, sample=report)    -> the start screen, with a "See a sample report" button
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .engine import to_dict
from .models import Report

TEMPLATE = Path(__file__).resolve().parent.parent / "ui" / "template.html"


def _js(report: Optional[Report]) -> str:
    return "null" if report is None else json.dumps(to_dict(report), ensure_ascii=False).replace("</", "<\\/")


def render_html(report: Optional[Report], template: Path = TEMPLATE, sample: Optional[Report] = None) -> str:
    html = template.read_text(encoding="utf-8")
    return html.replace("__REPORT_JSON__", _js(report)).replace("__SAMPLE_JSON__", _js(sample))
