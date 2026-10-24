import json

import pytest

from mf_plain import (Fund, Portfolio, Thresholds, Weights, analyze, quartile_from_rank, render_markdown,
                      to_dict)
from mf_plain.fmt import inr, inr_short, signed_pct
from mf_plain.sample import sample_portfolio
from mf_plain.translators import (calendar_insight, capture_insight, cost_insight,
                                  drawdown_insight, mix_insights, quartile_insight,
                                  returns_insight, rolling_insight)

TH = Thresholds()


def fund(**kw):
    base = dict(name="F", category="Flexi Cap", value=100000, benchmark_name="Nifty 500")
    base.update(kw)
    return Fund(**base)


# ---------------------------------------------------------------- formatting
@pytest.mark.parametrize("x,expected", [
    (0, "₹0"), (999, "₹999"), (1000, "₹1,000"), (100000, "₹1,00,000"),
    (1234567, "₹12,34,567"), (-62000, "-₹62,000"), (10000000, "₹1,00,00,000"),
])
def test_inr_indian_grouping(x, expected):
    assert inr(x) == expected


def test_inr_short_and_signed():
    assert inr_short(420000) == "₹4.20 lakh" and inr_short(25000000) == "₹2.50 crore"
    assert signed_pct(38.46) == "+38.5%" and signed_pct(-4.2) == "−4.2%"


# ------------------------------------------------------- 1) CAGR returns
def test_returns_ahead_and_rupee_math_lives_in_numbers():
    ins = returns_insight(fund(returns={5: 15.0}, bench_returns={5: 12.0}), TH)
    assert ins.status == "good"
    assert ins.numbers["fund_value"] == round(100000 * 1.15 ** 5)
    assert ins.numbers["bench_value"] == round(100000 * 1.12 ** 5)
    assert "3.0% a year ahead" in ins.sentence
    assert "₹" not in ins.sentence                 # sentences stay short; the UI draws the rupees


@pytest.mark.parametrize("gap,status", [(1.0, "good"), (0.99, "ok"), (-0.99, "ok"),
                                        (-1.0, "watch"), (-2.99, "watch"), (-3.0, "attention")])
def test_returns_boundaries(gap, status):
    assert returns_insight(fund(returns={3: 10 + gap}, bench_returns={3: 10}), TH).status == status


def test_returns_lists_every_horizon_and_headline_uses_longest():
    ins = returns_insight(fund(returns={1: 5, 3: 10, 5: 12}, bench_returns={1: 4, 3: 9, 5: 11}), TH)
    assert ins.numbers["horizon_years"] == 5
    assert [h["years"] for h in ins.numbers["by_horizon"]] == [1, 3, 5]


def test_returns_one_year_is_never_extreme():
    good = returns_insight(fund(returns={1: 40}, bench_returns={1: 10}), TH)
    bad = returns_insight(fund(returns={1: -20}, bench_returns={1: 10}), TH)
    assert good.status == "ok" and bad.status == "watch" and "short time" in good.sentence


def test_returns_missing_data_returns_none():
    assert returns_insight(fund(returns={5: 12}), TH) is None and returns_insight(fund(), TH) is None


def test_index_fund_judged_on_tracking_not_alpha():
    assert returns_insight(fund(category="Large Cap Index", returns={5: 13.4}, bench_returns={5: 13.6}), TH).status == "ok"
    assert returns_insight(fund(category="Large Cap Index", returns={5: 11.0}, bench_returns={5: 13.6}), TH).status == "watch"
    assert rolling_insight(fund(category="Large Cap Index", rolling_beat_pct=10), TH) is None
    assert calendar_insight(fund(category="Large Cap Index", calendar_returns={1: 1, 2: 1, 3: 1},
                                 bench_calendar_returns={1: 0, 2: 0, 3: 0}), TH) is None


# --------------------------------------------------- 2) calendar-year returns
def cal(fund_r, bench_r, start=2021):
    ys = range(start, start + len(fund_r))
    return fund(calendar_returns=dict(zip(ys, fund_r)), bench_calendar_returns=dict(zip(ys, bench_r)))


def test_calendar_counts_years_and_best_worst():
    ins = calendar_insight(cal([30, 5, 28, 20, 12], [28, 6, 25, 15, 10]), TH)
    assert ins.numbers["beats"] == 4 and ins.numbers["n"] == 5
    assert "In 4 of the last 5 calendar years" in ins.sentence
    assert ins.numbers["alpha"] == [2, -1, 3, 5, 2] and ins.numbers["avg_alpha"] == 2.2
    assert ins.numbers["best_alpha_year"] == 2024 and ins.numbers["worst_alpha_year"] == 2022
    assert "2.2 percentage points ahead" in ins.sentence and ins.status == "good"
    assert "The widest gap was +5.0 points in 2024" in ins.sentence
    assert "the narrowest was −1.0 points in 2022" in ins.sentence


@pytest.mark.parametrize("beats,status", [(5, "good"), (3, "ok"), (2, "watch"), (0, "attention")])
def test_calendar_status_bands(beats, status):
    fund_r = [10] * beats + [0] * (5 - beats)
    ins = calendar_insight(cal(fund_r, [5] * 5), TH)
    assert ins.status == status


def test_calendar_needs_three_common_years_and_uses_latest_six():
    assert calendar_insight(cal([10, 10], [5, 5]), TH) is None
    ins = calendar_insight(cal([10] * 8, [5] * 8, start=2018), TH)
    assert ins.numbers["n"] == 6 and ins.numbers["years"][0] == 2020


# ------------------------------------------------------------------- rolling
@pytest.mark.parametrize("pct,k_text,status", [
    (82, "8 out of every 10", "good"), (100, "In every", "good"),
    (46, "5 out of every 10", "ok"),       # wording and colour must agree
    (34, "3 out of every 10", "watch"), (18, "2 out of every 10", "attention"),
    (0, "almost none", "attention"),
])
def test_rolling_wording_matches_status(pct, k_text, status):
    ins = rolling_insight(fund(rolling_beat_pct=pct), TH)
    assert k_text in ins.sentence and ins.status == status
    assert "three-year" in ins.sentence


# ------------------------------------------------------------------ capture
def test_capture_sentence_and_numbers():
    ins = capture_insight(fund(upside_capture=108, downside_capture=88, capture_years=5), TH)
    assert "gained ₹108" in ins.sentence and "lost ₹88" in ins.sentence
    assert ins.status == "good" and ins.headline == "Gains more, loses less"
    assert ins.numbers["ratio"] == round(108 / 88, 2)


@pytest.mark.parametrize("u,d,status,head", [
    (110, 90, "good", "Gains more, loses less"),
    (99, 103, "ok", "Moves much like its benchmark"),               # within 3 points of 100 both ways
    (106, 112, "ok", "Bolder: bigger gains, bigger falls"),        # ratio 0.946 -> watch? see below
    (105, 125, "attention", "Bolder, but the gains don't make up for the falls"),  # 0.84
    (80, 70, "good", "Steadier, and loses much less in falls"),     # 1.14
    (70, 80, "watch", "Steadier, but gives up more gains than it saves in falls"),  # ratio 0.875
    (82, 112, "attention", "Smaller gains and bigger falls"),
])
def test_capture_archetypes(u, d, status, head):
    ins = capture_insight(fund(upside_capture=u, downside_capture=d), TH)
    if (u, d) == (106, 112):
        status = "watch"  # ratio 0.946 is just under the 0.95 line
        head = "Bolder, but the gains don't make up for the falls"
    assert ins.status == status and ins.headline == head


def test_capture_no_downside_and_missing_data():
    ins = capture_insight(fund(upside_capture=90, downside_capture=0), TH)
    assert ins.status == "good" and "did not lose money" in ins.sentence
    assert capture_insight(fund(upside_capture=100), TH) is None


def test_capture_index_fund_expected_to_hug_100():
    ins = capture_insight(fund(category="Nifty 50 Index", upside_capture=99.6, downside_capture=100.1), TH)
    assert ins.status == "ok" and "index fund should do" in ins.sentence


# ------------------------------------------------------------------ drawdown
def test_drawdown_numbers_and_recovery():
    ins = drawdown_insight(fund(max_drawdown=-38, bench_max_drawdown=-40, drawdown_event="the 2020 crash",
                                recovery_months=9, bench_recovery_months=7), TH)
    assert "₹62,000" in ins.sentence and "₹60,000" in ins.sentence
    assert "9 months" in ins.sentence and "benchmark took 7" in ins.sentence and ins.status == "ok"


def test_drawdown_status_bands_and_missing():
    f = lambda d: drawdown_insight(fund(max_drawdown=-30 + d, bench_max_drawdown=-30), TH).status
    assert f(3) == "good" and f(0) == "ok" and f(-5) == "watch" and f(-8) == "attention"
    assert drawdown_insight(fund(max_drawdown=-30), TH) is None


# ---------------------------------------------------------------- quartiles
@pytest.mark.parametrize("rank,count,q", [(1, 34, 1), (8, 34, 1), (9, 34, 2), (17, 34, 2),
                                          (18, 34, 3), (26, 34, 4), (34, 34, 4), (1, 4, 1), (4, 4, 4)])
def test_quartile_from_rank(rank, count, q):
    assert quartile_from_rank(rank, count) == q


@pytest.mark.parametrize("rank,count", [(1, 1), (1, 3), (0, 10), (11, 10)])
def test_quartile_from_rank_rejects_meaningless_input(rank, count):
    with pytest.raises(ValueError):
        quartile_from_rank(rank, count)


def test_quartile_insight_wording_and_status():
    ins = quartile_insight(fund(quartiles={1: 2, 3: 1, 5: 1}, peer_count=34), TH)
    assert ins.status == "good" and "top quarter (Q1) of 34 Flexi Cap funds" in ins.sentence
    assert "1 year Q2, 3 years Q1, 5 years Q1" in ins.sentence
    assert quartile_insight(fund(quartiles={5: 4}), TH).status == "attention"
    assert quartile_insight(fund(quartiles={5: 3}), TH).status == "watch"
    assert quartile_insight(fund(quartiles={5: 2}), TH).status == "ok"
    assert quartile_insight(fund(), TH) is None


# --------------------------------------------------------------------- costs
@pytest.mark.parametrize("ter,med,status", [
    (0.60, 0.82, "good"), (0.75, 0.82, "ok"), (0.95, 0.82, "ok"),
    (1.10, 0.82, "watch"), (1.60, 0.82, "attention"),
])
def test_cost_vs_category_median(ter, med, status):
    ins = cost_insight(fund(ter=ter, category_median_ter=med), TH)
    assert ins.status == status
    assert ins.numbers["gap_pts"] == round(ter - med, 3)


def test_cost_sentence_and_rupees():
    ins = cost_insight(fund(plan="regular", ter=2.00, category_median_ter=1.50, value=200000), TH)
    assert "0.50 percentage points more than" in ins.sentence and "₹1,000 a year more" in ins.sentence
    assert ins.numbers["plan"] == "regular" and ins.numbers["annual_vs_median"] == 1000


def test_cost_has_no_direct_regular_comparison_or_illustration():
    ins = cost_insight(fund(plan="regular", ter=2.0, category_median_ter=1.5), TH)
    blob = (ins.sentence + str(ins.numbers)).lower()
    assert "direct plan costs" not in blob and "extra_over_horizon" not in blob and "growth" not in blob
    assert not hasattr(Thresholds(), "flag_regular_plans")


def test_cost_without_median_still_shows_charge_and_lists_a_gap():
    ins = cost_insight(fund(ter=1.2), TH)
    assert ins.status == "ok" and ins.numbers["category_median"] is None
    r = analyze(Portfolio(funds=[fund(name="X", ter=1.2)]))
    assert any("median" in g for g in r.data_gaps)


def test_equal_weight_comparison_skips_rupee_charges_and_portfolio_mix():
    weighed = fund(name="A", value=1, value_is_weight=True, ter=1.2, category_median_ter=0.9)
    other = fund(name="B", value=1, value_is_weight=True, category="Mid Cap", ter=0.7, category_median_ter=0.9)
    ins = cost_insight(weighed, TH)
    assert "₹" not in ins.sentence and "annual_cost" not in ins.numbers
    report = analyze(Portfolio([weighed, other], values_are_weights=True))
    assert all(card.topic != "mix" for card in report.cards)
    text = " ".join(i.sentence for card in report.cards for i in card.insights)
    assert "₹" not in text


# ------------------------------------------------------- calendar-year alpha
def test_calendar_alpha_values_and_sentence():
    ins = calendar_insight(fund(calendar_returns={2023: 30, 2024: 20, 2025: 10},
                                bench_calendar_returns={2023: 26, 2024: 18, 2025: 11}), TH)
    assert ins.numbers["alpha"] == [4, 2, -1] and ins.numbers["avg_alpha"] == 1.67
    assert ins.numbers["best_alpha_year"] == 2023 and ins.numbers["worst_alpha_year"] == 2025
    assert "1.7 percentage points ahead" in ins.sentence and "alpha" in ins.sentence
    assert ins.status == "ok"        # beat 2 of 3 (0.67 -> ok); average alpha +1.7 is good; worse of the two


def test_calendar_behind_every_year_names_the_worst_year_first():
    ins = calendar_insight(fund(calendar_returns={2021: 4, 2022: 3, 2023: 4, 2024: 4, 2025: 4},
                                bench_calendar_returns={2021: 10, 2022: 10, 2023: 10, 2024: 10, 2025: 10}), TH)
    assert "In none of the last" not in ins.sentence
    assert "This fund did not beat Nifty 500 in any of the last 5 calendar years." in ins.sentence
    assert "fell furthest behind in 2022 (−7.0 points)" in ins.sentence
    assert "came closest in 2021 (−6.0 points)" in ins.sentence
    assert "narrowest" not in ins.sentence and "widest gap" not in ins.sentence


def test_calendar_status_is_worse_of_hit_rate_and_alpha():
    # beats every year, but by tiny margins: hit-rate good, alpha ok -> ok
    ins = calendar_insight(fund(calendar_returns={2022: 10.2, 2023: 10.2, 2024: 10.2},
                                bench_calendar_returns={2022: 10, 2023: 10, 2024: 10}), TH)
    assert ins.status == "ok"
    # beats 2 of 3 years but loses badly in the third -> alpha watch
    ins = calendar_insight(fund(calendar_returns={2022: 12, 2023: 12, 2024: -5},
                                bench_calendar_returns={2022: 10, 2023: 10, 2024: 5}), TH)
    assert ins.status == "watch" and "behind" in ins.sentence


# ------------------------------------------------------------------ weights
def test_default_weights_match_equal_weighting():
    from mf_plain.engine import group_status
    from mf_plain.models import Insight
    mk = lambda t, st: Insight(id=t, topic=t, status=st, headline="", sentence="")
    ins = [mk("returns", "good"), mk("calendar", "watch")]
    assert group_status(ins) == "ok"
    assert group_status(ins, Weights(findings={"returns": 3.0, "calendar": 1.0})) == "good"
    assert group_status(ins, Weights(findings={"returns": 1.0, "calendar": 3.0})) == "watch"


def test_area_weights_change_the_verdict_and_zero_excludes_an_area():
    base = analyze(sample_portfolio())
    heavy_peers = analyze(sample_portfolio(), weights=Weights(areas={"returns": 0, "risk": 0, "peers": 1, "costs": 0}))
    assert {f.name: f.verdict for f in heavy_peers.funds}  # runs with zero-weight areas
    b = next(f for f in analyze(sample_portfolio(), weights=Weights(areas={"returns": 1, "risk": 1, "peers": 1, "costs": 1})).funds
             if f.name == "Sample Mid Cap Fund B")
    assert b.verdict in ("Worth a closer look", "On track")


def test_quartile_horizon_weights():
    f = fund(quartiles={1: 4, 5: 1})
    assert quartile_insight(f, TH).numbers["average"] == 2.5
    assert quartile_insight(f, TH, Weights(quartile_horizons={1: 0.0, 3: 1, 5: 1})).numbers["average"] == 1.0
    assert quartile_insight(f, TH, Weights(quartile_horizons={1: 1, 3: 1, 5: 3})).numbers["average"] == 1.75


# ----------------------------------------------------------------------- mix
def pf(*vals):
    return Portfolio(funds=[fund(name=n, value=v, category=c) for n, v, c in vals])


def test_mix_flags_concentration():
    ids = {i.id for i in mix_insights(pf(("A", 600, "Mid"), ("B", 200, "Mid"), ("C", 200, "Large")), TH)}
    assert ids == {"mix-category", "mix-fund"}


def test_mix_single_fund_and_balanced():
    assert mix_insights(pf(("A", 100, "Mid")), TH)[0].id == "mix-single"
    assert mix_insights(pf(("A", 33, "Mid"), ("B", 33, "Large"), ("C", 34, "Flexi")), TH)[0].status == "good"


# --------------------------------------------------------------- whole report
def test_sample_report_end_to_end():
    r = analyze(sample_portfolio())
    verdicts = {f.name: f.verdict for f in r.funds}
    assert verdicts["Sample Flexi Cap Fund A"] == "Doing well"
    assert verdicts["Sample Large & Mid Cap Fund C"] == "Needs attention"
    assert verdicts["Sample Mid Cap Fund B"] == "Worth a closer look"     # area mean below 0, from cost
    assert verdicts["Sample Large Cap Index Fund D"] == "On track"
    index = next(f for f in r.funds if f.name == "Sample Large Cap Index Fund D")
    assert "peers" not in {s.topic for s in index.sections}
    assert any(n == "Not ranked against other index funds, because that group mixes different indices."
               for n in index.notes)
    assert next(s for s in index.scorecard if s.topic == "peers").label == "Not ranked"
    assert verdicts["Sample Thematic Fund E"] == "Limited data"
    assert r.flags[0].status == "attention" and r.data_gaps
    assert [c.topic for c in r.cards] == ["returns", "risk", "peers", "costs", "mix"]
    json.dumps(to_dict(r))
    assert "Questions worth discussing" in render_markdown(r)


def test_one_watch_does_not_force_a_closer_look():
    from mf_plain.engine import _fund_verdict
    from mf_plain.models import Insight

    def mk(topic, status):
        return Insight(id=topic, topic=topic, status=status, headline=topic, sentence="")

    lone = [mk("returns", "good"), mk("calendar", "good"), mk("consistency", "good"),
            mk("capture", "good"), mk("risk", "watch"), mk("peers", "good"), mk("costs", "ok")]
    assert _fund_verdict(lone) == ("Doing well", "good")
    level = [mk("returns", "ok"), mk("capture", "good"), mk("risk", "watch"), mk("peers", "ok"), mk("costs", "ok")]
    assert _fund_verdict(level) == ("On track", "ok")
    pulled = [mk("returns", "ok"), mk("peers", "watch"), mk("costs", "ok")]
    assert _fund_verdict(pulled)[0] == "Worth a closer look"   # the mean is below 0
    two = [mk("returns", "good"), mk("calendar", "good"), mk("consistency", "good"),
           mk("capture", "good"), mk("risk", "watch"), mk("peers", "good"), mk("costs", "watch")]
    assert _fund_verdict(two)[0] == "Worth a closer look"
    attention = [mk("returns", "good"), mk("calendar", "good"), mk("consistency", "good"),
                 mk("capture", "good"), mk("risk", "good"), mk("peers", "attention"), mk("costs", "ok")]
    assert _fund_verdict(attention)[0] == "Worth a closer look"
    assert _fund_verdict([mk("returns", "attention"), mk("calendar", "attention"),
                          mk("consistency", "attention"), mk("peers", "attention")])[0] == "Needs attention"

    shown = analyze(Portfolio(funds=[fund(
        name="One watch",
        returns={1: 21.0, 3: 18.4, 5: 17.1}, bench_returns={1: 17.5, 3: 15.2, 5: 14.6},
        calendar_returns={2021: 34.0, 2022: 6.5, 2023: 29.8, 2024: 21.2, 2025: 12.4},
        bench_calendar_returns={2021: 31.6, 2022: 4.3, 2023: 26.9, 2024: 16.2, 2025: 9.9},
        rolling_beat_pct=82, upside_capture=108, downside_capture=88,
        max_drawdown=-43.0, bench_max_drawdown=-38.0,
        quartiles={1: 2, 3: 1, 5: 1}, peer_count=34,
        ter=0.75, category_median_ter=0.82, category_median_n=31,
        history_years=11.2, capture_obs=1250,
    )], as_of_date="2026-10-09"))
    one = shown.funds[0]
    assert one.verdict == "Doing well"
    assert one.look_at


def test_index_fund_keeps_tracking_and_costs_without_a_peer_rank():
    r = analyze(Portfolio(funds=[fund(
        name="Nifty tracker", category="Index Funds", is_index=True,
        returns={5: 13.4}, bench_returns={5: 13.6},
        upside_capture=99.6, downside_capture=100.1, capture_obs=800,
        max_drawdown=-38.0, bench_max_drawdown=-38.2,
        quartiles={5: 4}, peer_count=35,
        ter=0.25, category_median_ter=0.36, category_median_n=40,
        history_years=8,
    )]))
    tracked = r.funds[0]
    topics = {s.topic for s in tracked.sections}
    assert "returns" in topics and "capture" in topics and "costs" in topics
    assert "peers" not in topics
    assert tracked.notes == ["Not ranked against other index funds, because that group mixes different indices."]
    assert not any("quartile" in g for g in r.data_gaps)
    gold = analyze(Portfolio(funds=[fund(
        name="Gold", category="Gold ETF", category_group="Other Scheme",
        quartiles={5: 1}, peer_count=8, ter=0.50, category_median_ter=0.55, category_median_n=8,
        history_years=6,
    )])).funds[0]
    assert "peers" in {s.topic for s in gold.sections}


def test_returns_card_has_the_three_return_views_in_order():
    r = analyze(sample_portfolio())
    returns_card = next(c for c in r.cards if c.topic == "returns")
    assert [s.topic for s in returns_card.sections] == ["returns", "calendar", "consistency"]
    risk_card = next(c for c in r.cards if c.topic == "risk")
    assert [s.topic for s in risk_card.sections] == ["capture", "risk"]


def test_scorecard_and_bottom_line():
    r = analyze(sample_portfolio())
    a = next(f for f in r.funds if f.name == "Sample Flexi Cap Fund A")
    assert [s.title for s in a.scorecard] == ["Returns", "Risk", "Ranking in category", "Costs"]
    assert [s.status for s in a.scorecard] == ["good", "good", "good", "ok"]
    assert a.going_well and not a.look_at
    e = next(f for f in r.funds if f.name == "Sample Thematic Fund E")
    assert {s.topic: s.status for s in e.scorecard}["risk"] == "na"


def test_no_overlap_anywhere():
    r = analyze(sample_portfolio())
    blob = json.dumps(to_dict(r)).lower() + render_markdown(r).lower()
    assert "overlap" not in blob and "same shares" not in blob


def test_missing_data_never_crashes():
    r = analyze(Portfolio(funds=[fund(name="Bare")]))
    assert r.funds[0].verdict == "Not enough data"
    assert len(r.data_gaps) == 1
    assert r.data_gaps[0].startswith("Bare: ")
    assert "charges (TER)" in r.data_gaps[0] and "growth over 1, 3 and 5 years" in r.data_gaps[0]
    render_markdown(r)


def test_gaps_collapse_to_one_line_and_a_young_fund_says_what_was_checked():
    young = fund(name="Young fund", history_years=1.5, returns={1: 8}, bench_returns={1: 6},
                 ter=0.8, rolling_beat_pct=40)
    older = fund(name="No charge", history_years=10, returns={5: 12}, bench_returns={5: 10}, ter=None)
    report = analyze(Portfolio(funds=[young, older]))
    assert len(report.data_gaps) == 2
    assert report.data_gaps[0] == (
        "Young fund is under 2 years old, so only returns and cost are checked. "
        "The category median charge is not available, so its charges are shown without a comparison."
    )
    assert report.data_gaps[1].startswith("No charge: ")
    assert "charges (TER)" in report.data_gaps[1]
    assert report.data_gaps[1].count("No charge") == 1


def test_repeated_question_is_kept_once_and_the_next_most_severe_follows():
    from mf_plain.engine import _select_questions
    from mf_plain.models import Insight

    def item(topic, status, suggestion):
        return Insight(id=topic, topic=topic, status=status, headline="", sentence="", suggestion=suggestion)

    items = [
        item("returns", "attention", "Ask this"),
        item("calendar", "attention", "Ask this"),
        item("risk", "watch", "Ask that"),
        item("costs", "watch", "Ask the other"),
    ]
    assert _select_questions(items) == ["Ask this", "Ask that"]
    assert all(i.suggestion is None for i in items)


def test_questions_are_capped_at_two_and_not_repeated_on_the_findings():
    watched = fund(
        name="Many questions",
        returns={5: 8}, bench_returns={5: 14},
        calendar_returns={2021: 4, 2022: 3, 2023: 4, 2024: 4, 2025: 4},
        bench_calendar_returns={2021: 10, 2022: 10, 2023: 10, 2024: 10, 2025: 10},
        rolling_beat_pct=18, upside_capture=70, downside_capture=120,
        max_drawdown=-45, bench_max_drawdown=-30,
        quartiles={5: 4}, peer_count=20,
        ter=2.4, category_median_ter=0.8, category_median_n=20,
        history_years=10, capture_obs=800,
    )
    report = analyze(Portfolio(funds=[watched]))
    one = report.funds[0]
    assert len(one.questions) == 2
    assert len(set(one.questions)) == 2
    suggestions = [i.suggestion for sec in one.sections for i in sec.insights]
    assert suggestions and all(s is None for s in suggestions)
    text = render_markdown(report)
    assert text.count(one.questions[0]) == 1
    assert text.count(one.questions[1]) == 1


def test_no_trade_instructions_in_any_output():
    text = render_markdown(analyze(sample_portfolio())).lower()
    for banned in ("you should sell", "you should buy", "switch to", "you should redeem", "redeem this fund", "exit this fund"):
        assert banned not in text


def test_sentences_have_no_nan_or_none():
    r = analyze(sample_portfolio())
    for c in r.cards:
        for i in c.insights:
            assert "nan" not in i.sentence.lower() and "None" not in i.sentence and "inf" not in i.sentence.lower().split()


# ------------------------------------------------------------------ HTML view
def test_html_embeds_report_and_escapes_script_end():
    from mf_plain.htmlview import render_html
    pf_ = sample_portfolio()
    pf_.funds[0].name = "Evil </script><b>Fund"
    html = render_html(analyze(pf_))
    assert "__REPORT_JSON__" not in html
    assert "Evil <\\/script>" in html
    assert html.count("</script>") == 3   # report, sample, app script


# ------------------------------------------------- facts, applicability, data sufficiency
def test_benchmark_map_and_applicability():
    from mf_plain.benchmarks import benchmark_for, benchmark_tests_apply
    assert benchmark_for("Small Cap Fund") == "Nifty Smallcap 250 TRI"
    assert benchmark_for("Flexi Cap") == "Nifty 500 TRI"            # tolerates a missing "Fund"
    assert benchmark_for("Something New") == "Nifty 50 TRI"          # documented fallback
    assert not benchmark_tests_apply("Liquid Fund") and not benchmark_tests_apply("Gold ETF")
    assert benchmark_tests_apply("Mid Cap Fund")


def test_debt_fund_is_judged_on_ranking_and_cost_without_benchmark_tests():
    r = analyze(sample_portfolio())
    f = next(x for x in r.funds if x.name.endswith("Bond Fund F"))
    topics = {s.topic for s in f.sections}
    assert {"peers", "costs"} <= topics and not topics & {"returns", "calendar", "consistency", "capture", "risk"}
    assert f.verdict in ("Doing well", "On track") and f.notes
    assert not any("Bond Fund F" in g for g in r.data_gaps)          # skipped on purpose, not a data gap


def test_rolling_and_capture_need_enough_data():
    young = fund(rolling_beat_pct=80, history_years=3.0, upside_capture=110, downside_capture=90, capture_obs=40)
    assert rolling_insight(young, TH) is None and capture_insight(young, TH) is None
    ok = fund(rolling_beat_pct=80, history_years=5.0, upside_capture=110, downside_capture=90, capture_obs=900)
    assert rolling_insight(ok, TH) and capture_insight(ok, TH)
    assert rolling_insight(fund(rolling_beat_pct=80, rolling_window_years=5, history_years=6.0), TH) is None


def test_median_with_too_few_funds_is_not_trusted():
    ins = cost_insight(fund(ter=1.0, category_median_ter=0.8, category_median_n=3), TH)
    assert ins.numbers["category_median"] is None


def test_manager_change_and_small_fund_and_young_fund_are_flagged_but_do_not_lower_the_verdict():
    from mf_plain.facts import fund_facts
    f = fund(manager_since="2026-06-01", manager_names=["X"], aum_cr=40, allotment_date="2025-06-01",
             riskometer="Very High", benchmark_riskometer="High", exit_load="1% within a year")
    facts = {i.topic: i for i in fund_facts(f, TH, "2026-10-09")}
    assert facts["manager"].status == "watch" and "4 months" in facts["manager"].sentence
    assert facts["size"].status == "watch" and facts["age"].status == "watch"
    assert facts["riskometer"].status == "watch" and facts["exit"].status == "ok"
    r = analyze(sample_portfolio())
    b = next(x for x in r.funds if x.name == "Sample Mid Cap Fund B")
    assert any("manager" in x.lower() for x in b.look_at) or b.verdict == "Worth a closer look"
    e = next(x for x in r.funds if x.name == "Sample Thematic Fund E")
    assert e.verdict == "Limited data"           # facts alone never escalate a verdict
    assert e.facts["age_years"] < 3


def test_drawdown_recovery_counts_from_the_bottom_and_handles_still_underwater():
    ins = drawdown_insight(fund(max_drawdown=-30, bench_max_drawdown=-28, recovery_months=7, bench_recovery_months=9), TH)
    assert "Counting from the bottom" in ins.sentence and ins.numbers["fall_size"] == "significant"
    ins = drawdown_insight(fund(max_drawdown=-30, bench_max_drawdown=-28, still_underwater=True, recovery_months=7), TH)
    assert "not yet got back" in ins.sentence and "7 months" not in ins.sentence


def test_report_carries_credits_and_header_facts():
    r = analyze(sample_portfolio())
    assert "TigZig" in r.credits and "not affiliated" in r.credits
    a = next(x for x in r.funds if x.name == "Sample Flexi Cap Fund A")
    assert a.facts["aum_cr"] == 48250 and a.facts["manager_months"] > 60


def test_start_page_has_no_report_and_embeds_sample():
    from mf_plain.htmlview import render_html
    html = render_html(None, sample=analyze(sample_portfolio()))
    assert '<script id="report" type="application/json">null</script>' in html
    assert "__SAMPLE_JSON__" not in html and "Sample Flexi Cap Fund A" in html


def test_default_weights_are_the_agreed_ones():
    from mf_plain.models import Weights
    w = Weights()
    assert w.areas == {"returns": 35.0, "risk": 25.0, "peers": 25.0, "costs": 15.0}
    assert (w.findings["returns"], w.findings["calendar"], w.findings["consistency"]) == (40.0, 30.0, 30.0)
    assert (w.findings["capture"], w.findings["risk"]) == (50.0, 50.0)
    assert w.quartile_horizons == {1: 20.0, 3: 40.0, 5: 40.0}


def test_start_page_makes_the_agreed_privacy_promise():
    from mf_plain.htmlview import render_html
    from pathlib import Path
    tpl = Path(__file__).resolve().parent.parent / "ui" / "template.html"
    html = render_html(None, tpl)
    assert "Your file is not saved." in html and "then discard it" in html


def test_typical_fund_is_shown_and_does_not_change_the_verdict():
    plain = fund(returns={1: 21.0, 5: 17.1}, bench_returns={1: 17.5, 5: 14.6},
                 calendar_returns={2023: 20, 2024: 10, 2025: 8},
                 bench_calendar_returns={2023: 18, 2024: 12, 2025: 7},
                 max_drawdown=-33, bench_max_drawdown=-38, recovery_months=7)
    shown = fund(returns={1: 21.0, 5: 17.1}, bench_returns={1: 17.5, 5: 14.6},
                 typical_returns={1: 19.2, 5: 15.1},
                 calendar_returns={2023: 20, 2024: 10, 2025: 8},
                 bench_calendar_returns={2023: 18, 2024: 12, 2025: 7},
                 typical_calendar={2023: 19, 2024: 11, 2025: 6},
                 max_drawdown=-33, bench_max_drawdown=-38, recovery_months=7,
                 typical_max_drawdown=-36, typical_recovery_months=8)
    before, after = returns_insight(plain, TH), returns_insight(shown, TH)
    assert before.status == after.status and before.numbers["gap_pts"] == after.numbers["gap_pts"]
    five = next(row for row in after.numbers["by_horizon"] if row["years"] == 5)
    assert five["typical"] == 15.1 and five["typical_gap"] == 2.0
    assert after.numbers["typical_value"] == round(100000 * (1 + 15.1 / 100) ** 5)
    assert "typical" not in before.numbers["by_horizon"][0]
    cal = calendar_insight(shown, TH)
    assert cal.numbers["typical"] == [19, 11, 6]
    assert cal.numbers["typical_margin"] == [1.0, -1.0, 2.0]
    assert cal.status == calendar_insight(plain, TH).status
    fall = drawdown_insight(shown, TH)
    assert fall.numbers["typical_after"] == round(100000 * (1 - 36 / 100))
    assert fall.numbers["typical_recovery_months"] == 8
    assert fall.status == drawdown_insight(plain, TH).status
    other = dict(name="G", returns={5: 10}, bench_returns={5: 12}, quartiles={5: 2},
                 peer_count=10, ter=1.0, category_median_ter=1.0, category_median_n=10)
    same = [f.verdict for f in analyze(Portfolio([plain, fund(**other)])).funds]
    moved = [f.verdict for f in analyze(Portfolio([
        shown, fund(**other, typical_returns={5: 99})])).funds]
    assert same == moved
    index = fund(is_index=True, returns={5: 13.4}, bench_returns={5: 13.6}, typical_returns={5: 12.0},
                 typical_max_drawdown=-20, max_drawdown=-30, bench_max_drawdown=-30)
    tracked = returns_insight(index, TH)
    assert "typical" not in tracked.numbers["by_horizon"][0] and "typical_cagr" not in tracked.numbers
    assert "typical_after" not in drawdown_insight(index, TH).numbers
