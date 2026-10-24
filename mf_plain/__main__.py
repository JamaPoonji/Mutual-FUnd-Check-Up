"""Demo: python -m mf_plain [--json | --html OUT.html | --start OUT.html]"""
import json
import sys

from . import analyze, render_markdown, to_dict
from .htmlview import render_html
from .sample import sample_portfolio

report = analyze(sample_portfolio())
if "--json" in sys.argv:
    print(json.dumps(to_dict(report), indent=2, ensure_ascii=False))
elif "--html" in sys.argv:
    out = sys.argv[sys.argv.index("--html") + 1]
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render_html(report))
    print(f"Wrote {out}")
elif "--start" in sys.argv:  # the start screen (no report yet), with a sample report behind a button
    out = sys.argv[sys.argv.index("--start") + 1]
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render_html(None, sample=report))
    print(f"Wrote {out}")
else:
    print(render_markdown(report))
