"""Search the stored fund list. This is public scheme data, not a user's file."""
from __future__ import annotations

from pipeline.match import normalize_name
from api.data import FundData


def search_schemes(funds: FundData, query: str, limit: int = 20) -> list[dict]:
    """Schemes whose name, plan, category or ISIN contains the query.

    Fewer than two letters matches nothing. At most `limit` rows come back,
    names that start with the query first.
    """
    needle = normalize_name(query)[:80]
    if len(needle) < 2:
        return []
    hits = []
    for code in funds.preferred or funds.metrics:
        detail = funds.details.get(code) or {}
        metric = funds.metrics.get(code) or {}
        name = (detail.get("fund_name_latest") or detail.get("scheme_name") or metric.get("scheme_name") or "").strip()
        scheme = (detail.get("scheme_name") or metric.get("scheme_name") or "").strip()
        plan = str(detail.get("scheme_plan") or metric.get("scheme_plan") or "").strip()
        category = (detail.get("category_sub") or metric.get("category_sub") or "").strip()
        isin = str(detail.get("isin") or metric.get("isin") or "").strip()
        blob = normalize_name(" ".join(part for part in (name, scheme, plan, category, isin) if part))
        if needle not in blob:
            continue
        label = name or scheme or "Unknown fund"
        if plan:
            label = f"{label} ({plan})"
        starts = normalize_name(name).startswith(needle) or normalize_name(scheme).startswith(needle)
        hits.append((0 if starts else 1, label.lower(), {
            "scheme_code": int(code),
            "name": label,
            "category": category,
            "plan": plan,
            "isin": isin or None,
        }))
    hits.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in hits[:limit]]


def scheme_holdings(codes: list[int], funds: FundData) -> list[dict]:
    """Equal-weight holdings for schemes the user picked. Value 1 is a share, not rupees."""
    rows = []
    for code in codes:
        detail = funds.details.get(code) or {}
        metric = funds.metrics.get(code) or {}
        name = (detail.get("fund_name_latest") or detail.get("scheme_name") or metric.get("scheme_name") or "").strip()
        plan = str(detail.get("scheme_plan") or metric.get("scheme_plan") or "").strip()
        if name and plan:
            name = f"{name} ({plan})"
        isin = detail.get("isin") or metric.get("isin") or None
        rows.append({
            "scheme_code": int(code),
            "name": name or "A selected fund",
            "isin": isin,
            "value": 1,
            "value_is_weight": True,
        })
    return rows
