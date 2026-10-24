"""Plain-text/markdown rendering of a Report, for the CLI, emails or quick previews."""
from __future__ import annotations

from .models import Report

ICON = {"good": "✅", "ok": "🟢", "watch": "🟡", "attention": "🔴", "na": "⚪"}


def render_markdown(r: Report) -> str:
    out = ["# Your mutual fund check-up", ""]
    if r.as_of:
        out.append(f"*Data as of {r.as_of}" + (f" from {r.data_source}" if r.data_source else "") + "*")
        out.append("")
    out += [f"**{r.headline}**", ""]
    out.append("## At a glance")
    for c in r.cards:
        out.append(f"- {ICON[c.status]} **{c.title}**: {c.one_liner}")
    out.append("")
    out.append("## Fund by fund")
    for f in r.funds:
        out.append(f"### {ICON[f.status]} {f.name}: {f.verdict}")
        out.append(f"*{f.category}, {f.share_pct:.0f}% of your portfolio*")
        out.append("Scorecard: " + "  ".join(f"{s.title} {ICON[s.status]}" for s in f.scorecard))
        if f.going_well:
            out.append("Going well: " + "; ".join(f.going_well) + ".")
        if f.look_at:
            out.append("Worth a look: " + "; ".join(f.look_at) + ".")
        out.append("")
        for sec in f.sections:
            out.append(f"**{sec.title}**")
            for i in sec.insights:
                out.append(f"- {ICON[i.status]} **{i.headline}.** {i.sentence}")
            out.append("")
    port = [i for c in r.cards if c.topic == "mix" for i in c.insights]
    if port:
        out.append("## Across your whole portfolio")
        for i in port:
            out.append(f"- {ICON[i.status]} **{i.headline}.** {i.sentence}")
        out.append("")
    asked = [(f.name, f.questions) for f in r.funds if f.questions]
    mix = []
    seen = set()
    for i in port:
        if i.suggestion and i.suggestion not in seen:
            seen.add(i.suggestion)
            mix.append(i.suggestion)
    if mix:
        asked.append(("Your portfolio as a whole", mix))
    if asked:
        out.append("## Questions worth discussing")
        for who, items in asked:
            out.append(f"**{who}**")
            for question in items:
                out.append(f"- {question}")
        out.append("")
    if r.data_gaps:
        out.append("## What we could not check")
        out += [f"- {g}" for g in r.data_gaps]
        out.append("")
    out += ["---", f"*{r.disclaimer}*"]
    return "\n".join(out)
