"""Metric -> plain-language translators.

Each function takes one fund (or the whole portfolio) and returns an Insight, or
None when the inputs it needs are missing. No function invents a number: every
figure in a sentence comes from the input or from arithmetic on it, and the raw
figures are echoed in `Insight.numbers` so they can be audited.

Sentences stay short on purpose. The rupee illustrations and per-period detail live
in `numbers`, and the UI draws them as small pictures instead of more words.
Suggestions are phrased as questions to discuss, never as buy/sell instructions.
"""
from __future__ import annotations

from typing import Optional

from .fmt import inr, pct, pct2, signed_pct, years
from .models import Fund, Insight, Portfolio, Thresholds, Weights

ILLUSTRATION = 100_000  # the ₹1,00,000 used in "what would have happened" figures


def _slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-")


def _bench(f: Fund) -> str:
    return f.benchmark_name


def _yrs(n: int) -> str:
    return f"{n} year{'s' if n != 1 else ''}"


# ------------------------------------------------------- 1) CAGR (returns)
def returns_insight(f: Fund, th: Thresholds, w: Optional[Weights] = None) -> Optional[Insight]:
    horizons = [y for y in (1, 3, 5) if y in f.returns and y in f.bench_returns]
    if not horizons:
        return None
    horizon = max(horizons)
    fr, br = f.returns[horizon], f.bench_returns[horizon]
    gap = fr - br
    fund_value = ILLUSTRATION * (1 + fr / 100) ** horizon
    bench_value = ILLUSTRATION * (1 + br / 100) ** horizon
    show_typical = not f.index_like
    rows = []
    for y in horizons:
        row = {"years": y, "fund": f.returns[y], "bench": f.bench_returns[y],
               "gap": round(f.returns[y] - f.bench_returns[y], 2)}
        typical = f.typical_returns.get(y) if show_typical else None
        if typical is not None:
            row["typical"] = typical
            row["typical_gap"] = round(f.returns[y] - typical, 2)
            row["typical_value"] = round(ILLUSTRATION * (1 + typical / 100) ** y)
        rows.append(row)
    nums = {"horizon_years": horizon, "fund_cagr": fr, "bench_cagr": br,
            "gap_pts": round(gap, 2), "fund_value": round(fund_value),
            "bench_value": round(bench_value),
            "by_horizon": rows}
    headline_typical = f.typical_returns.get(horizon) if show_typical else None
    if headline_typical is not None:
        nums["typical_cagr"] = headline_typical
        nums["typical_value"] = round(ILLUSTRATION * (1 + headline_typical / 100) ** horizon)
    base = f"returns-{_slug(f.name)}"

    if f.index_like:
        if abs(gap) <= th.index_tracking_ok:
            return Insight(
                id=base, topic="returns", fund=f.name, status="ok",
                headline="Tracking its index closely",
                sentence=(f"This fund copies {_bench(f)}. Over {_yrs(horizon)} it returned {pct(fr)} a year "
                          f"against {pct(br)} for the index, a gap of {abs(gap):.1f}%. That is normal for an index fund."),
                jargon_term="tracking", numbers=nums)
        return Insight(
            id=base, topic="returns", fund=f.name, status="watch",
            headline="Drifting from its index",
            sentence=(f"This fund is meant to copy {_bench(f)}, but over {_yrs(horizon)} it returned {pct(fr)} a year "
                      f"against {pct(br)} for the index. A {abs(gap):.1f}% gap is more than usual for an index fund."),
            suggestion="Worth comparing its charges and tracking gap with other funds on the same index.",
            jargon_term="tracking", numbers=nums)

    if gap >= th.returns_good:
        status, head = "good", "Ahead of its benchmark"
    elif gap > th.returns_ok:
        status, head = "ok", "Roughly in line with its benchmark"
    elif gap > th.returns_watch:
        status, head = "watch", "Behind its benchmark"
    else:
        status, head = "attention", "Well behind its benchmark"

    short_term = horizon == 1
    if short_term:  # one year is mostly noise: never push a fund to the extremes on it
        status = {"good": "ok", "attention": "watch"}.get(status, status)

    if status in ("good", "ok") and abs(gap) < th.returns_good:
        verdict = "about the same"
    else:
        verdict = (f"{abs(gap):.1f}{' percentage points' if short_term else '% a year'} "
                   + ("ahead" if gap > 0 else "behind"))
    if short_term:
        sentence = (f"Over the last year this fund returned {pct(fr)}; {_bench(f)} returned {pct(br)}. "
                    f"That is {verdict}. One year is a short time to judge a fund, so treat this lightly.")
    else:
        sentence = (f"Over {_yrs(horizon)} this fund grew {pct(fr)} a year; {_bench(f)} grew {pct(br)}. "
                    f"That is {verdict}.")
    suggestion = None
    if status in ("watch", "attention"):
        suggestion = ("Worth asking whether this is a rough patch for the fund's style or a lasting gap, "
                      "and how its closest peers did over the same period.")
    return Insight(id=base, topic="returns", fund=f.name, status=status, headline=head,
                   sentence=sentence, suggestion=suggestion, jargon_term="cagr", numbers=nums)


def _points(value: float) -> str:
    return signed_pct(value).replace("%", "")


def _calendar_span(alpha: list[float], years: list[int], hi: int, lo: int) -> str:
    """Name the widest and narrowest margins. A negative margin is a shortfall, so the
    most negative year is the one it fell furthest behind, not the 'narrowest' gap."""
    if alpha[hi] < 0:
        if hi == lo:
            return f"It finished {_points(alpha[lo])} points behind in each of these years."
        return (f"It fell furthest behind in {years[lo]} ({_points(alpha[lo])} points) "
                f"and came closest in {years[hi]} ({_points(alpha[hi])} points).")
    return (f"The widest gap was {_points(alpha[hi])} points in {years[hi]}; "
            f"the narrowest was {_points(alpha[lo])} points in {years[lo]}.")


def history_too_short(f: Fund, th: Thresholds) -> bool:
    """3-year rolling needs ~4 years of NAV history, 5-year ~7 (TigZig rule of thumb)."""
    if f.history_years is None:
        return False
    need = th.rolling_min_history_years + max(0, f.rolling_window_years - 3) * 1.5
    return f.history_years < need


def capture_obs_too_few(f: Fund, th: Thresholds) -> bool:
    return f.capture_obs is not None and f.capture_obs < th.capture_min_obs


# --------------------------------------------------- 2) calendar-year returns
def calendar_insight(f: Fund, th: Thresholds, w: Optional[Weights] = None) -> Optional[Insight]:
    """Hit rate (how many years it beat the benchmark) AND alpha (by how much, each year).

    Alpha here is simple excess return: fund return minus benchmark return, in percentage
    points. It is not Jensen's alpha. Status is the worse of the hit-rate and average-alpha status.
    """
    if f.index_like:
        return None
    common = sorted(set(f.calendar_returns) & set(f.bench_calendar_returns))[-th.cal_max_years:]
    if len(common) < th.cal_min_years:
        return None
    n = len(common)
    fund_r = [f.calendar_returns[y] for y in common]
    bench_r = [f.bench_calendar_returns[y] for y in common]
    alpha = [round(a - b, 2) for a, b in zip(fund_r, bench_r)]
    beats = sum(1 for a in alpha if a > 0)
    share = beats / n
    avg = sum(alpha) / n
    hi = max(range(n), key=lambda k: alpha[k])
    lo = min(range(n), key=lambda k: alpha[k])

    if share >= th.cal_good:
        hit = 0
    elif share >= th.cal_ok:
        hit = 1
    elif share >= th.cal_watch:
        hit = 2
    else:
        hit = 3
    if avg >= th.cal_alpha_good:
        mar = 0
    elif avg > th.cal_alpha_ok:
        mar = 1
    elif avg > th.cal_alpha_watch:
        mar = 2
    else:
        mar = 3
    status = ("good", "ok", "watch", "attention")[max(hit, mar)]
    head = {"good": "Beat its benchmark in most years, by a clear margin",
            "ok": "Roughly level with its benchmark year by year",
            "watch": "Behind its benchmark in most years",
            "attention": "Well behind its benchmark year by year"}[status]

    if beats == 0:
        opener = f"This fund did not beat {_bench(f)} in any of the last {n} calendar years."
    elif beats == n:
        opener = f"In every one of the last {n} calendar years this fund beat {_bench(f)}."
    else:
        opener = f"In {beats} of the last {n} calendar years this fund beat {_bench(f)}."
    sentence = (f"{opener} On average it finished {abs(avg):.1f} percentage points "
                f"{'ahead of' if avg >= 0 else 'behind'} the benchmark each year (its margin over the benchmark, often called alpha). "
                f"{_calendar_span(alpha, common, hi, lo)}")
    suggestion = None
    if status in ("watch", "attention"):
        suggestion = "Worth checking whether the weak years share a cause, such as one theme falling out of favour."
    numbers = {"years": common, "fund": fund_r, "bench": bench_r, "alpha": alpha,
               "avg_alpha": round(avg, 2), "beats": beats, "n": n,
               "best_alpha_year": common[hi], "worst_alpha_year": common[lo]}
    if not f.index_like:
        typical = [f.typical_calendar.get(y) for y in common]
        if any(v is not None for v in typical):
            margins = [None if t is None else round(a - t, 2) for a, t in zip(fund_r, typical)]
            paired = [m for m in margins if m is not None]
            numbers["typical"] = typical
            numbers["typical_margin"] = margins
            numbers["typical_beats"] = sum(1 for m in paired if m > 0)
            numbers["typical_n"] = len(paired)
            numbers["typical_avg"] = round(sum(paired) / len(paired), 2) if paired else None
    return Insight(id=f"calendar-{_slug(f.name)}", topic="calendar", fund=f.name, status=status,
                   headline=head, sentence=sentence, suggestion=suggestion, jargon_term="calendar",
                   numbers=numbers)


# ------------------------------------------------------- 3) rolling returns
def rolling_insight(f: Fund, th: Thresholds, w: Optional[Weights] = None) -> Optional[Insight]:
    if f.index_like or f.rolling_beat_pct is None:
        return None
    if history_too_short(f, th):
        return None
    p = f.rolling_beat_pct
    k = round(p / 10)
    window = years(f.rolling_window_years)
    if k >= 10:
        freq = f"In every {window} period"
    elif k <= 0:
        freq = f"In almost none of the {window} periods"
    else:
        freq = f"In {k} out of every 10 {window} periods"
    sentence = (f"{freq}, counting every possible start date, this fund did better than {_bench(f)}.")
    shown = k * 10  # judge on what the user is told, so "5 of 10" never shows as a warning
    if shown >= th.rolling_good:
        status, head = "good", "Beats its benchmark most of the time"
    elif shown >= th.rolling_ok:
        status, head = "ok", "Beats its benchmark about half the time"
    elif shown >= th.rolling_watch:
        status, head = "watch", "Often behind its benchmark"
    else:
        status, head = "attention", "Rarely beats its benchmark"
    suggestion = None
    if status in ("watch", "attention"):
        suggestion = ("Worth checking whether the fund manager or strategy changed, "
                      "and if the weak stretches are recent or spread across the years.")
    return Insight(id=f"consistency-{_slug(f.name)}", topic="consistency", fund=f.name,
                   status=status, headline=head, sentence=sentence, suggestion=suggestion,
                   jargon_term="rolling_returns",
                   numbers={"beat_pct": p, "window_years": f.rolling_window_years})


# ------------------------------------------------- upside / downside capture
def capture_insight(f: Fund, th: Thresholds, w: Optional[Weights] = None) -> Optional[Insight]:
    u, d = f.upside_capture, f.downside_capture
    if u is None or d is None or capture_obs_too_few(f, th):
        return None
    yrs = _yrs(f.capture_years)
    if d > 0:
        ratio = u / d
        sentence = (f"Over {yrs}, for every ₹100 {_bench(f)} gained in rising months, this fund gained ₹{u:.0f}. "
                    f"For every ₹100 it lost in falling months, this fund lost ₹{d:.0f}.")
    else:
        ratio = float("inf")
        sentence = (f"Over {yrs}, for every ₹100 {_bench(f)} gained in rising months, this fund gained ₹{u:.0f}. "
                    f"In the months it fell, this fund did not lose money.")
    nums = {"upside": u, "downside": d, "ratio": None if ratio == float("inf") else round(ratio, 2),
            "years": f.capture_years}
    base = f"capture-{_slug(f.name)}"

    if f.index_like and abs(u - 100) <= th.index_capture_band and abs(d - 100) <= th.index_capture_band:
        return Insight(id=base, topic="capture", fund=f.name, status="ok",
                       headline="Moves almost exactly with its index",
                       sentence=sentence + " That is what an index fund should do.",
                       jargon_term="capture", numbers=nums)

    if ratio >= th.capture_good_ratio:
        status = "good"
    elif ratio >= th.capture_ok_ratio:
        status = "ok"
    elif ratio >= th.capture_watch_ratio:
        status = "watch"
    else:
        status = "attention"

    gains_more, loses_more = u >= 100, d > 100
    near = abs(u - 100) <= th.index_capture_band and abs(d - 100) <= th.index_capture_band
    if near:
        head = "Moves much like its benchmark"
        extra = "That is close to what the benchmark itself did, so the fund adds little in either direction."
    elif gains_more and not loses_more:
        head, extra = "Gains more, loses less", "That is the helpful mix: more of the gains and less of the losses."
    elif gains_more and loses_more:
        extra = "That makes it bolder than its benchmark: bigger gains, but bigger falls."
        head = {"good": "Bolder, and the extra risk paid off", "ok": "Bolder: bigger gains, bigger falls"}.get(
            status, "Bolder, but the gains don't make up for the falls")
    elif not gains_more and not loses_more:
        extra = "That makes it steadier than its benchmark: smaller gains, but smaller falls."
        head = {"good": "Steadier, and loses much less in falls", "ok": "Steadier: smaller gains, smaller falls"}.get(
            status, "Steadier, but gives up more gains than it saves in falls")
    else:
        head, extra = "Smaller gains and bigger falls", "That is the least helpful mix."
    suggestion = None
    if status in ("watch", "attention"):
        suggestion = "Worth asking whether this mix of gains and falls is what you want from this fund."
    return Insight(id=base, topic="capture", fund=f.name, status=status, headline=head,
                   sentence=sentence + " " + extra, suggestion=suggestion, jargon_term="capture",
                   numbers=nums)


# ------------------------------------------------------------ worst fall
def drawdown_insight(f: Fund, th: Thresholds, w: Optional[Weights] = None) -> Optional[Insight]:
    if f.max_drawdown is None or f.bench_max_drawdown is None:
        return None
    fund_after = ILLUSTRATION * (1 + f.max_drawdown / 100)
    bench_after = ILLUSTRATION * (1 + f.bench_max_drawdown / 100)
    diff = f.max_drawdown - f.bench_max_drawdown  # positive = fund fell less
    sentence = (f"In {f.drawdown_event}, {inr(ILLUSTRATION)} in this fund fell to {inr(fund_after)}. "
                f"In {_bench(f)} it fell to {inr(bench_after)}.")
    if f.still_underwater:
        sentence += " It has not yet got back to its earlier high."
    elif f.recovery_months is not None:
        sentence += f" Counting from the bottom, this fund took {f.recovery_months} months to get back to its earlier high"
        sentence += (f"; the benchmark took {f.bench_recovery_months}." if f.bench_recovery_months is not None else ".")
    size = ("extreme" if f.max_drawdown <= -50 else "significant" if f.max_drawdown <= -30
            else "moderate" if f.max_drawdown <= -15 else "mild")
    if f.max_drawdown <= -40:
        sentence += " Falls this big can happen again, so be sure you could stay invested through one."
    if diff >= th.dd_good:
        status, head = "good", "Fell less than its benchmark"
    elif diff > th.dd_ok:
        status, head = "ok", "Fell about as much as its benchmark"
    elif diff > th.dd_watch:
        status, head = "watch", "Fell more than its benchmark"
    else:
        status, head = "attention", "Fell much more than its benchmark"
    suggestion = None
    if status in ("watch", "attention"):
        suggestion = "Worth asking whether you are comfortable with a fall this deep for the extra return you expect."
    numbers = {"fund_drawdown": f.max_drawdown, "bench_drawdown": f.bench_max_drawdown,
               "fund_after": round(fund_after), "bench_after": round(bench_after),
               "recovery_months": f.recovery_months, "still_underwater": f.still_underwater, "fall_size": size,
               "bench_recovery_months": f.bench_recovery_months}
    if not f.index_like and f.typical_max_drawdown is not None:
        numbers["typical_drawdown"] = f.typical_max_drawdown
        numbers["typical_after"] = round(ILLUSTRATION * (1 + f.typical_max_drawdown / 100))
        if f.typical_recovery_months is not None:
            numbers["typical_recovery_months"] = f.typical_recovery_months
    return Insight(id=f"risk-{_slug(f.name)}", topic="risk", fund=f.name, status=status,
                   headline=head, sentence=sentence, suggestion=suggestion, jargon_term="drawdown",
                   numbers=numbers)


# ----------------------------------------------------- quartile in category
QUARTILE_NAME = {1: "top quarter", 2: "second quarter", 3: "third quarter", 4: "bottom quarter"}
QUARTILE_MEANING = {
    1: "ahead of at least 3 in every 4 similar funds",
    2: "ahead of at least half of similar funds",
    3: "behind more than half of similar funds",
    4: "behind at least 3 in every 4 similar funds",
}


def quartile_insight(f: Fund, th: Thresholds, w: Optional[Weights] = None) -> Optional[Insight]:
    qs = {h: q for h, q in f.quartiles.items() if q in (1, 2, 3, 4)}
    if not qs:
        return None
    horizons = sorted(qs)
    longest = horizons[-1]
    q = qs[longest]
    wh = (w.quartile_horizons if w else {}) or {}
    ws = {h: wh.get(h, 1.0) for h in horizons}
    avg = (sum(qs[h] * ws[h] for h in horizons) / sum(ws.values())) if sum(ws.values()) > 0 \
        else sum(qs.values()) / len(qs)
    if avg <= th.quartile_good:
        status, head = "good", "Top quarter of its category"
    elif avg <= th.quartile_ok:
        status, head = "ok", "Above the middle of its category"
    elif avg <= th.quartile_watch:
        status, head = "watch", "Below the middle of its category"
    else:
        status, head = "attention", "Bottom quarter of its category"
    of_n = f"{f.peer_count} " if f.peer_count else ""
    sentence = (f"Over {_yrs(longest)}, this fund ranked in the {QUARTILE_NAME[q]} (Q{q}) of {of_n}"
                f"{f.category} funds: {QUARTILE_MEANING[q]}.")
    if len(horizons) > 1:
        sentence += " By period: " + ", ".join(f"{_yrs(h)} Q{qs[h]}" for h in horizons) + "."
    suggestion = None
    if status in ("watch", "attention"):
        suggestion = "Worth looking at what the top few funds in this category did differently."
    return Insight(id=f"peers-{_slug(f.name)}", topic="peers", fund=f.name, status=status,
                   headline=head, sentence=sentence, suggestion=suggestion, jargon_term="quartile",
                   numbers={"quartiles": {str(h): qs[h] for h in horizons}, "peer_count": f.peer_count,
                            "category": f.category, "average": round(avg, 2)})


# ----------------------------------------------------------------- costs
def cost_insight(f: Fund, th: Thresholds, w: Optional[Weights] = None) -> Optional[Insight]:
    """Fund's TER against the median TER of its category, same plan (Direct vs Direct, Regular vs Regular)."""
    if f.ter is None:
        return None
    plan = "regular" if f.plan.lower() == "regular" else "direct"
    show_rupees = not f.value_is_weight
    annual = f.value * f.ter / 100 if show_rupees else None
    base = f"costs-{_slug(f.name)}"
    med = f.category_median_ter
    if f.category_median_n is not None and f.category_median_n < th.median_min_funds:
        med = None
    if med is None:
        sentence = f"This fund charges {pct2(f.ter)} a year ({plan} plan)."
        numbers = {"ter": f.ter, "plan": plan, "category_median": None}
        if show_rupees:
            sentence += f" That is about {inr(annual)} on your {inr(f.value)}."
            numbers["annual_cost"] = round(annual)
        sentence += " It is already taken out of the returns you see."
        return Insight(
            id=base, topic="costs", fund=f.name, status="ok", headline="Charges shown",
            sentence=sentence, jargon_term="ter", numbers=numbers)
    gap = f.ter - med
    diff_rs = f.value * abs(gap) / 100 if show_rupees else None
    if gap <= th.cost_good_gap:
        status, head = "good", "Cheaper than the category median"
    elif gap <= th.cost_ok_gap:
        status, head = "ok", "In line with the category median"
    elif gap <= th.cost_watch_gap:
        status, head = "watch", "Above the category median"
    else:
        status, head = "attention", "Well above the category median"
    if status == "ok":
        cmp = "about the same as"
    else:
        cmp = f"{abs(gap):.2f} percentage points {'less' if gap < 0 else 'more'} than"
    sentence = (f"This fund charges {pct2(f.ter)} a year. The middle {f.category} {plan} plan charges "
                f"{pct2(med)}, so this fund is {cmp} the middle.")
    if status != "ok" and show_rupees:
        sentence += f" On your {inr(f.value)} that is about {inr(diff_rs)} a year {'less' if gap < 0 else 'more'}."
    suggestion = None
    if status in ("watch", "attention"):
        suggestion = ("Worth asking what the higher charge pays for, and whether similar funds in the "
                      "category deliver the same for less.")
    return Insight(id=base, topic="costs", fund=f.name, status=status, headline=head,
                   sentence=sentence, suggestion=suggestion, jargon_term="ter",
                   numbers={"ter": f.ter, "plan": plan, "category": f.category, "category_median": med,
                            "gap_pts": round(gap, 3),
                            **({} if not show_rupees else {
                                "annual_cost": round(annual),
                                "annual_vs_median": round(f.value * gap / 100),
                            })})


# ------------------------------------------------------------------- mix
def mix_insights(pf: Portfolio, th: Thresholds) -> list[Insight]:
    total = sum(f.value for f in pf.funds)
    if total <= 0:
        return []
    out: list[Insight] = []
    by_cat: dict[str, float] = {}
    for f in pf.funds:
        by_cat[f.category] = by_cat.get(f.category, 0) + f.value
    top_cat, top_val = max(by_cat.items(), key=lambda kv: kv[1])
    cat_share = top_val / total * 100
    top_fund = max(pf.funds, key=lambda f: f.value)
    fund_share = top_fund.value / total * 100

    if len(pf.funds) == 1:
        return [Insight(
            id="mix-single", topic="mix", status="watch",
            headline="All your money is in one fund",
            sentence=f"All of your money is in {top_fund.name}, so its ups and downs are your whole portfolio's.",
            suggestion="Worth discussing whether one fund should carry the whole portfolio.",
            jargon_term="concentration", numbers={"share_pct": 100.0})]

    if cat_share > th.category_max_share:
        out.append(Insight(
            id="mix-category", topic="mix", status="watch",
            headline=f"Heavy on {top_cat}",
            sentence=f"About {cat_share:.0f}% of your money is in {top_cat} funds, so this one type of fund drives most of your results.",
            suggestion="Worth checking this matches how much risk you want to take.",
            jargon_term="concentration", numbers={"category": top_cat, "share_pct": round(cat_share, 1)}))
    if fund_share > th.fund_max_share:
        out.append(Insight(
            id="mix-fund", topic="mix", status="watch",
            headline="One fund carries a lot of weight",
            sentence=f"{top_fund.name} is {fund_share:.0f}% of your portfolio, so how it does matters more than any other fund.",
            suggestion="Worth confirming you are comfortable with one fund being this large.",
            jargon_term="concentration", numbers={"fund": top_fund.name, "share_pct": round(fund_share, 1)}))
    if not out:
        out.append(Insight(
            id="mix-ok", topic="mix", status="good",
            headline="Reasonably spread out",
            sentence=(f"Your largest category ({top_cat}) is about {cat_share:.0f}% of the portfolio and your "
                      f"largest fund is about {fund_share:.0f}%, so no single choice dominates."),
            jargon_term="concentration",
            numbers={"category": top_cat, "category_share_pct": round(cat_share, 1),
                     "largest_fund_share_pct": round(fund_share, 1)}))
    return out


FUND_TRANSLATORS = [returns_insight, calendar_insight, rolling_insight, capture_insight,
                    drawdown_insight, quartile_insight, cost_insight]
# Tests that only make sense when judging against a benchmark: skipped, not "missing", for index funds
INDEX_SKIPPED = {"calendar_insight", "rolling_insight"}
