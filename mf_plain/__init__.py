"""mf_plain: turns mutual fund analytics into plain-language findings for ordinary investors."""
from .engine import analyze, to_dict
from .models import Fund, Portfolio, Thresholds, Weights, quartile_from_rank
from .render import render_markdown

__all__ = ["analyze", "to_dict", "render_markdown", "Fund", "Portfolio", "Thresholds", "Weights", "quartile_from_rank"]
