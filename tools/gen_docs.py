"""Regenerates the parts of docs/ that must never drift from the code:
   docs/thresholds.md, docs/report.schema.json, docs/fund_input.schema.json, docs/sample_report.json
Run from the project root:  python tools/gen_docs.py
"""
import dataclasses
import inspect
import json
import re
import sys
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mf_plain import analyze, to_dict  # noqa: E402
from mf_plain import models  # noqa: E402
from mf_plain.sample import sample_portfolio  # noqa: E402


def thresholds_md() -> str:
    src = inspect.getsource(models.Thresholds).splitlines()
    comments, rows, group = [], [], ""
    for ln in src:
        t = ln.strip()
        if t.startswith("#"):
            group = t.lstrip("# ").strip()
            continue
        m = re.match(r"(\w+): (\w+) = ([^#]+?)\s*(?:#\s*(.*))?$", t)
        if m:
            rows.append((group, m.group(1), m.group(3).strip(), (m.group(4) or "").strip()))
    out = ["# Every threshold the engine uses", "",
           "Generated from `mf_plain/models.py` by `tools/gen_docs.py`. Do not edit by hand.", "",
           "| Group | Name | Default | Note |", "|---|---|---|---|"]
    out += [f"| {g} | `{n}` | {d} | {c} |" for g, n, d, c in rows]
    w = models.Weights()
    out += ["", "## Weights (defaults; Vedant supplies the real ones)", "",
            "| Level | Key | Default |", "|---|---|---|"]
    out += [f"| inside an area | `{k}` | {v} |" for k, v in w.findings.items()]
    out += [f"| in the fund verdict | `{k}` | {v} |" for k, v in w.areas.items()]
    out += [f"| quartile period (years) | `{k}` | {v} |" for k, v in w.quartile_horizons.items()]
    out += ["", "## Fund verdict", "",
            "The label is the weighted mean of the area scores. Needs attention at -1.0 or below. "
            "Doing well at 0.5 or above. On track in between.", "",
            "Worth a closer look when that mean is below 0, or any finding is attention, or two or more "
            "findings are watch. One watch stays on the fund and does not change the label by itself.", "",
            "Index funds are not given a quartile rank. The note is: "
            "\"Not ranked against other index funds, because that group mixes different indices.\" "
            "Tracking, capture and costs stay."]
    return "\n".join(out) + "\n"


def schema_for(cls, defs):
    hints = typing.get_type_hints(cls)
    props, req = {}, []
    for f in dataclasses.fields(cls):
        props[f.name] = js(hints[f.name], defs)
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
            req.append(f.name)
    return {"type": "object", "properties": props, "required": req}


def js(t, defs):
    origin, args = typing.get_origin(t), typing.get_args(t)
    if origin is typing.Union:
        non = [a for a in args if a is not type(None)]
        s = js(non[0], defs)
        return {"anyOf": [s, {"type": "null"}]}
    if origin in (list, typing.List):
        return {"type": "array", "items": js(args[0], defs) if args else {}}
    if origin in (dict, typing.Dict):
        return {"type": "object"}
    if dataclasses.is_dataclass(t):
        if t.__name__ not in defs:
            defs[t.__name__] = None
            defs[t.__name__] = schema_for(t, defs)
        return {"$ref": f"#/$defs/{t.__name__}"}
    return {"type": {str: "string", int: "integer", float: "number", bool: "boolean", dict: "object"}.get(t, "string")}


def main():
    d = ROOT / "docs"
    d.mkdir(exist_ok=True)
    (d / "thresholds.md").write_text(thresholds_md())
    defs = {}
    root = schema_for(models.Report, defs)
    root.update({"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Report", "$defs": defs})
    (d / "report.schema.json").write_text(json.dumps(root, indent=2))
    defs2 = {}
    fs = schema_for(models.Fund, defs2)
    fs.update({"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Fund (engine input)"})
    (d / "fund_input.schema.json").write_text(json.dumps(fs, indent=2))
    (d / "sample_report.json").write_text(json.dumps(to_dict(analyze(sample_portfolio())), indent=2, ensure_ascii=False))
    print("docs regenerated")


if __name__ == "__main__":
    main()
