"""Category -> benchmark mapping (TigZig MFPRO, as of 2026-10-02) and where benchmark tests make sense.

TigZig measures every benchmark-based metric against ONE index per category so funds in a category
stay comparable. The fund's own filed benchmark is information only. Categories with no entry fall
back to Nifty 50 TRI.
"""
from __future__ import annotations

import csv
import os
from functools import lru_cache

DEFAULT_BENCHMARK = "Nifty 50 TRI"
_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "tigzig_benchmark_map.csv")

# Categories where a benchmark comparison would mislead (the mapped index is not what the fund
# is trying to beat). They are judged on category ranking and costs instead.
NO_BENCHMARK_TESTS = {
    "arbitrage fund", "equity savings", "equity savings fund", "conservative hybrid fund",
    "gold etf", "overseas", "fof overseas", "fund of funds investing overseas",
    "debt etf", "debt funds", "other etf", "other etfs",
}


@lru_cache(maxsize=1)
def benchmark_map() -> dict[str, str]:
    with open(_CSV, newline="") as f:
        return {r["category_sub"].strip().lower(): r["benchmark"].strip() for r in csv.DictReader(f)}


def benchmark_for(category: str) -> str:
    m, c = benchmark_map(), category.strip().lower()
    return m.get(c) or m.get(c + " fund") or DEFAULT_BENCHMARK


def benchmark_tests_apply(category: str, category_group: str = "") -> bool:
    c = category.strip().lower()
    if category_group.strip().lower().startswith("debt") or c in NO_BENCHMARK_TESTS:
        return False
    # debt categories by name, in case the group is missing
    g = benchmark_map().get(c, "")
    return not g.startswith("G-Sec")
