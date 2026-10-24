"""Input and output data shapes for the plain-language engine.

Every analytic field on Fund is OPTIONAL. The engine skips an insight when its
inputs are missing and lists the omission under `data_gaps`, so a partially
covered scheme never crashes the report or gets a made-up number.

All percentages are plain numbers: 12.5 means 12.5%, not 0.125.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

STATUSES = ("good", "ok", "watch", "attention")


def quartile_from_rank(rank: int, count: int) -> int:
    """Rank 1 = best. Returns 1 (top quarter) to 4 (bottom quarter).

    Quartiles are meaningless in a category of fewer than 4 funds, so that raises.
    """
    if count < 4 or not 1 <= rank <= count:
        raise ValueError("need a category of at least 4 funds and 1 <= rank <= count")
    return min(4, max(1, math.ceil(rank / count * 4)))


@dataclass
class Fund:
    name: str
    category: str                      # e.g. "Flexi Cap", "Mid Cap", "Large Cap Index"
    value: float                       # current value in rupees
    plan: str = "direct"               # "direct" | "regular"
    ter: Optional[float] = None        # this plan's expense ratio, %
    # Median TER, %, of this fund's category FOR THE SAME PLAN (Direct median for a direct holder,
    # Regular median for a regular holder). Supplied by the data layer.
    category_median_ter: Optional[float] = None
    benchmark_name: str = "its benchmark"

    # 1) Point-to-point CAGR by horizon in years: {1: 18.2, 3: 15.1, 5: 14.0}
    returns: dict[int, float] = field(default_factory=dict)
    bench_returns: dict[int, float] = field(default_factory=dict)
    # Category median CAGR for display only. Never used in a score or a verdict.
    typical_returns: dict[int, float] = field(default_factory=dict)

    # 2) Calendar-year returns, Jan-Dec: {2023: 29.8, 2024: 21.2}. Pass COMPLETE years only.
    calendar_returns: dict[int, float] = field(default_factory=dict)
    bench_calendar_returns: dict[int, float] = field(default_factory=dict)
    typical_calendar: dict[int, float] = field(default_factory=dict)  # display only

    # 3) Rolling returns: share (0-100) of rolling windows in which the fund beat its benchmark
    rolling_beat_pct: Optional[float] = None
    rolling_window_years: int = 3

    # Upside / downside capture versus the benchmark, in % (100 = same as the benchmark)
    upside_capture: Optional[float] = None
    downside_capture: Optional[float] = None
    capture_years: int = 3

    # Worst peak-to-trough fall, negative %, e.g. -38.0
    max_drawdown: Optional[float] = None
    bench_max_drawdown: Optional[float] = None
    drawdown_event: str = "the worst fall"      # e.g. "the March 2020 crash"
    recovery_months: Optional[int] = None
    bench_recovery_months: Optional[int] = None
    typical_max_drawdown: Optional[float] = None       # display only
    typical_recovery_months: Optional[int] = None      # display only

    # Quartile within category by horizon: {1: 2, 3: 1, 5: 1}; 1 = top quarter, 4 = bottom
    # (use quartile_from_rank to derive it from the fund's rank among its category)
    quartiles: dict[int, int] = field(default_factory=dict)
    peer_count: Optional[int] = None   # funds in the category

    is_index: Optional[bool] = None    # auto-detected from category when None

    # ---- identity / classification (from the scheme master)
    isin: Optional[str] = None
    category_group: str = ""           # Equity | Debt | Hybrid | Other Scheme
    benchmark_applies: Optional[bool] = None  # None = decide from the category (see benchmarks.py)

    # ---- data-sufficiency inputs (so the engine can refuse tests the data cannot support)
    history_years: Optional[float] = None     # years of NAV history of this plan
    capture_obs: Optional[int] = None         # paired daily observations behind the capture ratios
    category_median_n: Optional[int] = None   # funds behind category_median_ter
    still_underwater: bool = False            # worst fall has not yet been recovered
    data_quality_note: str = ""               # reason from the TigZig data_quality list, if any

    # ---- facts shown under "Good to know" (all optional)
    aum_cr: Optional[float] = None            # whole-fund AUM, Rs crore, all plans (count once per fund)
    riskometer: str = ""                      # e.g. "Very High"
    benchmark_riskometer: str = ""
    manager_names: list[str] = field(default_factory=list)
    manager_since: Optional[str] = None       # ISO date the current lead manager took over
    allotment_date: Optional[str] = None      # ISO launch date of the fund
    exit_load: str = ""                       # text as filed
    ter_date: Optional[str] = None
    value_is_weight: bool = False             # value is an equal share, not a rupee holding

    @property
    def index_like(self) -> bool:
        if self.is_index is not None:
            return self.is_index
        c = self.category.lower()
        return "index" in c or "etf" in c


@dataclass
class Portfolio:
    funds: list[Fund]
    as_of: str = ""                                 # data date shown to the user
    as_of_date: Optional[str] = None                # ISO date, used for tenure and age arithmetic
    data_source: str = ""
    values_are_weights: bool = False                # a comparison set, not a rupee portfolio


@dataclass
class Thresholds:
    """Every cut-off the engine uses. Tune here, not in the logic."""
    # CAGR gap vs benchmark, percentage points per year
    returns_good: float = 1.0
    returns_ok: float = -1.0
    returns_watch: float = -3.0
    index_tracking_ok: float = 0.5     # index funds: acceptable gap either way
    # calendar years: share of years the fund beat its benchmark (0-1)
    cal_good: float = 0.7
    cal_ok: float = 0.5
    cal_watch: float = 0.3
    cal_min_years: int = 3
    cal_max_years: int = 6
    # calendar-year alpha (fund minus benchmark, percentage points), averaged over the years shown
    cal_alpha_good: float = 1.0
    cal_alpha_ok: float = -1.0
    cal_alpha_watch: float = -3.0
    # rolling windows: % of windows beating benchmark
    rolling_good: float = 70.0
    rolling_ok: float = 50.0
    rolling_watch: float = 30.0
    # capture: ratio = upside / downside
    capture_good_ratio: float = 1.10
    capture_ok_ratio: float = 0.95
    capture_watch_ratio: float = 0.85
    index_capture_band: float = 3.0    # index funds: within +/-3 of 100 is "moves with the index"
    # fund drawdown minus benchmark drawdown, percentage points (positive = fell less)
    dd_good: float = 3.0
    dd_ok: float = -3.0
    dd_watch: float = -7.0
    # quartile: average quartile across horizons
    quartile_good: float = 1.5
    quartile_ok: float = 2.5
    quartile_watch: float = 3.5
    # TER minus the category median (same plan), percentage points; negative = cheaper than median
    cost_good_gap: float = -0.15
    cost_ok_gap: float = 0.15
    cost_watch_gap: float = 0.40
    # data sufficiency
    rolling_min_history_years: float = 4.0   # 3-year rolling needs about 4 years of NAV history (5-year: 7)
    capture_min_obs: int = 60                # paired daily observations
    median_min_funds: int = 5                # fewer funds than this and a category median is not trusted
    # fund facts
    aum_small_cr: float = 100.0              # below this, flag as a small fund
    young_fund_years: float = 3.0            # below this, flag a short track record
    manager_recent_months: int = 12          # manager changed within this many months
    riskometer_gap_levels: int = 1           # fund rated this many levels above its benchmark or more
    # portfolio mix
    category_max_share: float = 50.0
    fund_max_share: float = 35.0


@dataclass
class Weights:
    """How much each factor counts. Defaults are the product owner's choice (an editorial judgement,
    NOT a SEBI/NISM rule; neither prescribes fund-rating weights). Weights are relative, not percentages.

    findings: weight of each finding INSIDE its area's status (e.g. calendar vs rolling inside Returns)
    areas:    weight of each area in the fund's overall verdict (0 = shown but not counted)
    quartile_horizons: weight of each period when the quartile result is averaged
    """
    findings: dict = field(default_factory=lambda: {
        "returns": 40.0, "calendar": 30.0, "consistency": 30.0,   # Returns area
        "capture": 50.0, "risk": 50.0,                            # Risk area (capture, drawdown)
        "peers": 1.0, "costs": 1.0})                              # single-finding areas
    areas: dict = field(default_factory=lambda: {
        "returns": 35.0, "risk": 25.0, "peers": 25.0, "costs": 15.0})
    quartile_horizons: dict = field(default_factory=lambda: {1: 20.0, 3: 40.0, 5: 40.0})


@dataclass
class Insight:
    id: str
    topic: str            # returns|calendar|consistency|capture|risk|peers|costs|mix
    status: str           # good|ok|watch|attention
    headline: str         # a few words, for a card
    sentence: str         # the plain-language explanation
    fund: Optional[str] = None
    suggestion: Optional[str] = None   # only for watch/attention; a question, never a trade
    jargon_term: Optional[str] = None  # key into GLOSSARY, for "what does this mean?"
    numbers: dict = field(default_factory=dict)  # raw figures behind the sentence


@dataclass
class Section:
    topic: str
    title: str
    what: str             # one plain sentence on what this measures
    insights: list[Insight]


@dataclass
class Card:
    topic: str            # returns|risk|peers|costs|mix
    title: str
    status: str
    one_liner: str
    sections: list[Section]
    insights: list[Insight]            # flat list of all insights in the sections


@dataclass
class ScoreItem:
    topic: str            # returns|risk|peers|costs
    title: str
    status: str           # good|ok|watch|attention|na
    label: str            # Strong|Fine|Look closer|Needs attention|No data
    note: str             # the worst finding's headline, or "" when no data


@dataclass
class FundSummary:
    name: str
    category: str
    value: float
    share_pct: float
    verdict: str          # Doing well|On track|Worth a closer look|Needs attention|Limited data
    status: str
    going_well: list[str]
    look_at: list[str]
    scorecard: list[ScoreItem]
    sections: list[Section]            # this fund's findings, grouped for display
    facts: dict = field(default_factory=dict)   # header-strip values for the UI
    notes: list[str] = field(default_factory=list)  # plain-language caveats about how this fund was judged
    questions: list[str] = field(default_factory=list)  # at most two, most severe first, not repeated


@dataclass
class Report:
    as_of: str
    data_source: str
    headline: str
    counts: dict
    cards: list[Card]
    funds: list[FundSummary]
    flags: list[Insight]               # watch/attention items, most serious first
    data_gaps: list[str]
    glossary: dict
    disclaimer: str
    credits: str = ""
    schema_version: int = 1
