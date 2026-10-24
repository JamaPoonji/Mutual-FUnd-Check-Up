"""One-line, jargon-free explanations the UI can show behind a 'what does this mean?' link."""

GLOSSARY = {
    "cagr": (
        "Returns, a year at a time (CAGR)",
        "CAGR is the steady yearly growth rate that would turn your starting amount into "
        "the final amount. It smooths out the ups and downs so you can compare funds fairly. "
        "The benchmark is the market index the fund is measured against.",
    ),
    "calendar": (
        "Calendar-year returns and margin (alpha)",
        "How the fund did from 1 January to 31 December of each year. It shows whether the "
        "results came every year or from one or two big years. The margin (often called alpha) is "
        "simply the fund's return minus the benchmark's for that year: +3 means 3 percentage points "
        "ahead, -2 means 2 behind. It is not the regression-based alpha some websites show.",
    ),
    "capture": (
        "Upside and downside capture",
        "Take all the months the market (the benchmark) went up. Upside capture is how much "
        "of that rise the fund delivered. Do the same for the falling months and you get "
        "downside capture. Above 100 means more than the market, below 100 means less. "
        "You want upside high and downside low.",
    ),
    "quartile": (
        "Quartile ranking",
        "Line up every fund in the same category from best to worst, then cut the line into "
        "four equal groups. Q1 is the best quarter and Q4 is the worst.",
    ),
    "rolling_returns": (
        "Rolling returns",
        "Instead of checking one start date, we check every possible start date and look at "
        "the returns over each 3-year (or 5-year) stretch. It shows how consistent a fund is, "
        "not whether it got lucky with one date.",
    ),
    "drawdown": (
        "Worst fall (drawdown)",
        "How far the value dropped from its highest point to its lowest before recovering. "
        "It answers: how bad did it get, and could I have lived with that?",
    ),
    "ter": (
        "Fund charges (TER)",
        "The yearly fee the fund house takes out of your money, shown as a percentage. "
        "It is already deducted from the returns you see. We compare it with the median (middle) "
        "fee of funds in the same category and the same type of plan, direct with direct and "
        "regular with regular, so the comparison is like for like.",
    ),
    "riskometer": (
        "Riskometer",
        "A label every fund must show, from Low to Very High, set by the fund house under SEBI rules. "
        "It describes how risky the fund's investments are, not how it will perform.",
    ),
    "aum": (
        "Fund size (AUM)",
        "AUM is the total money all investors have put into the fund. Very small funds can be costlier to "
        "run and are sometimes merged or closed; very large ones can find it harder to trade freely.",
    ),
    "manager": (
        "Fund manager",
        "The person or team that picks the fund's investments. A track record belongs to whoever managed "
        "the fund at the time, so a recent change means the past may say less about the future.",
    ),
    "tracking": (
        "Tracking an index",
        "An index fund simply copies an index. A small gap against the index is normal "
        "(mostly the fund's charges); a big gap deserves a look.",
    ),
    "concentration": (
        "Concentration",
        "How much of your money sits in one fund or one type of fund. "
        "The more concentrated, the more one bad patch affects the whole portfolio.",
    ),
}
