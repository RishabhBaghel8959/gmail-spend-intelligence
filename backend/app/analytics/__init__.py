"""Analytics package: spending profile + natural-language insights."""
from __future__ import annotations

from .insights import build_insights, money
from .profile import build_profile, detect_recurring, is_spend

__all__ = [
    "build_insights",
    "money",
    "build_profile",
    "detect_recurring",
    "is_spend",
]
