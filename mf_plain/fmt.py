"""Small formatting helpers: Indian rupee grouping and number words."""
from __future__ import annotations


def inr(x: float) -> str:
    """Full Indian grouping: 1234567 -> ₹12,34,567."""
    n = int(round(x))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + "₹" + s


def inr_short(x: float) -> str:
    """Compact form for big sums: ₹4.20 lakh, ₹1.35 crore."""
    n = abs(x)
    sign = "-" if x < 0 else ""
    if n >= 1e7:
        return f"{sign}₹{n / 1e7:.2f} crore"
    if n >= 1e5:
        return f"{sign}₹{n / 1e5:.2f} lakh"
    return inr(x)


NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
                7: "seven", 10: "ten"}


def years(n: int) -> str:
    w = NUMBER_WORDS.get(n, str(n))
    return f"{w}-year"


def pct(x: float) -> str:
    return f"{x:.1f}%"


def signed_pct(x: float) -> str:
    """+38.5% / -4.2% (real minus sign)."""
    return ("+" if x >= 0 else "−") + f"{abs(x):.1f}%"


def pct2(x: float) -> str:
    """Two decimals, for expense ratios where 0.74 vs 0.75 matters."""
    return f"{x:.2f}%"
