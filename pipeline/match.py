"""Match a holding to a scheme_code.

ISIN is tried first, against isin and isin2. A name is used only when the
holding has no ISIN. An ISIN that matches nothing is not guessed from the name.
Several schemes for one ISIN or one name stay unmatched, unless exactly one of
them is in the preferred set (the schemes we actually score).
"""
from __future__ import annotations

from typing import Optional, Sequence


def normalize_name(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in str(value)).split())


def _isin(value: Optional[str]) -> str:
    if not value:
        return ""
    return "".join(str(value).split()).upper()


def _choose(codes: Sequence[int], preferred: Optional[set]) -> Optional[int]:
    unique = list(dict.fromkeys(codes))
    if len(unique) == 1:
        return unique[0]
    if preferred:
        chosen = [code for code in unique if code in preferred]
        if len(chosen) == 1:
            return chosen[0]
    return None


def match_holding(holding: dict, catalog: Sequence[dict], preferred: Optional[set] = None) -> Optional[int]:
    """scheme_code, or None when the holding cannot be matched to one scheme."""
    raw_code = holding.get("scheme_code")
    if raw_code not in (None, ""):
        try:
            code = int(raw_code)
        except (TypeError, ValueError):
            return None
        known = {int(row["scheme_code"]) for row in catalog}
        if code not in known or (preferred is not None and code not in preferred):
            return None
        return code

    wanted = _isin(holding.get("isin"))
    if wanted:
        hits = [
            int(row["scheme_code"]) for row in catalog
            if wanted in {_isin(row.get("isin")), _isin(row.get("isin2"))}
        ]
        return _choose(hits, preferred)

    query = normalize_name(holding.get("name"))
    if not query:
        return None
    exact = []
    partial = []
    for row in catalog:
        names = {normalize_name(row.get("scheme_name")), normalize_name(row.get("fund_name_latest"))}
        names.discard("")
        code = int(row["scheme_code"])
        if query in names:
            exact.append(code)
        elif len(query) >= 12 and any(query in name for name in names):
            partial.append(code)
    if exact:
        return _choose(exact, preferred)
    return _choose(partial, preferred)
