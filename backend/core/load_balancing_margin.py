"""Shared load-balancing fuse margin resolution.

Single source of truth for ``load_balancing.target_margin_percent`` so the
planner's per-phase fuse constraint and the executor's runtime balancer use the
same margin for every config, including a legacy ``resume_margin_percent``.
"""

from __future__ import annotations

import math
from typing import Any

DEFAULT_TARGET_MARGIN_PERCENT = 85.0
TARGET_MARGIN_RANGE: tuple[float, float] = (50.0, 100.0)
# The shipped default of the superseded load_balancing.resume_margin_percent.
# A config still carrying exactly this value was never tuned by the user (the
# template merge wrote it into every config), so it migrates to the new, more
# protective target default instead of pinning 90 %.
LEGACY_RESUME_MARGIN_DEFAULT = 90.0


def resolve_target_margin_percent(lb_data: dict[str, Any]) -> Any:
    """target_margin_percent, else a user-tuned legacy resume_margin_percent, else 85."""
    if lb_data.get("target_margin_percent") is not None:
        return lb_data["target_margin_percent"]
    legacy = lb_data.get("resume_margin_percent")
    if legacy is not None:
        try:
            if float(legacy) != LEGACY_RESUME_MARGIN_DEFAULT:
                return legacy
        except (TypeError, ValueError):
            pass
    return DEFAULT_TARGET_MARGIN_PERCENT


def effective_target_margin_percent(lb_data: dict[str, Any] | None) -> float:
    """Resolved margin as a float within the valid range, else the default (85)."""
    try:
        value = float(resolve_target_margin_percent(lb_data or {}))
    except (TypeError, ValueError):
        return DEFAULT_TARGET_MARGIN_PERCENT
    if math.isnan(value) or not TARGET_MARGIN_RANGE[0] <= value <= TARGET_MARGIN_RANGE[1]:
        return DEFAULT_TARGET_MARGIN_PERCENT
    return value
