"""Shared EV charger power model.

Single source of truth for an EV charger's plannable power limits, used by the
planner adapter, pipeline diagnostics, preflight, the load registration
service and the executor's kW<->A conversion.

- ``type: current`` chargers derive their limits from the electrical config:
  ``max_kw = max_current_a x len(phases) x V / 1000`` and
  ``min_kw = min_current_a x len(phases) x V / 1000 x 1.01``. The 1% margin
  keeps the executor's kW->A conversion from rounding a planned minimum below
  ``min_current_a``.
- ``type: binary`` chargers use their explicit ``rated_power_kw`` for both.

``V`` is ``system.grid.nominal_voltage_v`` (default 230 V, EU standard, when
unset). It is the single nominal grid voltage used for every kW<->A
conversion in the planner, the executor and the load balancer.
"""

from __future__ import annotations

from typing import Any, cast

DEFAULT_NOMINAL_VOLTAGE_V = 230.0
DEFAULT_MIN_CURRENT_A = 6.0
MIN_POWER_ROUNDING_MARGIN = 1.01


def nominal_voltage_v(config: dict[str, Any] | None) -> float:
    """Nominal grid voltage (``system.grid.nominal_voltage_v``) for kW<->A conversion."""
    if not isinstance(config, dict):
        return DEFAULT_NOMINAL_VOLTAGE_V
    system: Any = config.get("system")
    grid: Any = cast("dict[str, Any]", system).get("grid") if isinstance(system, dict) else None
    raw: Any = (
        cast("dict[str, Any]", grid).get("nominal_voltage_v") if isinstance(grid, dict) else None
    )
    try:
        value = float(raw) if raw is not None else DEFAULT_NOMINAL_VOLTAGE_V
    except (TypeError, ValueError):
        return DEFAULT_NOMINAL_VOLTAGE_V
    return value if value > 0 else DEFAULT_NOMINAL_VOLTAGE_V


def _positive_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _phase_count(phases: Any) -> int:
    if isinstance(phases, list | tuple):
        return len(phases)  # type: ignore[arg-type]
    return 0


def charger_power_limits(cfg: dict[str, Any], voltage: float) -> tuple[float, float]:
    """Return ``(min_kw, max_kw)`` for one ``ev_chargers[]`` entry.

    Returns ``(0.0, 0.0)`` when the limits cannot be derived (missing or
    non-positive amps/phases for a current charger, missing or non-positive
    ``rated_power_kw`` for a binary charger). Callers treat ``max_kw <= 0`` as
    an invalid charger.
    """
    control_type = str(cfg.get("type", "binary") or "binary").lower()

    if control_type == "current":
        max_a = _positive_float(cfg.get("max_current_a"))
        phase_count = _phase_count(cfg.get("phases"))
        if max_a is None or phase_count <= 0 or voltage <= 0:
            return 0.0, 0.0
        min_a = _positive_float(cfg.get("min_current_a")) or DEFAULT_MIN_CURRENT_A
        min_a = min(min_a, max_a)
        max_kw = max_a * phase_count * voltage / 1000.0
        min_kw = min_a * phase_count * voltage / 1000.0 * MIN_POWER_ROUNDING_MARGIN
        return min(min_kw, max_kw), max_kw

    rated = _positive_float(cfg.get("rated_power_kw"))
    if rated is None:
        return 0.0, 0.0
    return rated, rated


def charger_max_kw(cfg: dict[str, Any], voltage: float) -> float:
    """Convenience: derived maximum kW (0.0 when invalid)."""
    return charger_power_limits(cfg, voltage)[1]


def charger_disabled_reason(cfg: dict[str, Any], voltage: float) -> tuple[str, str] | None:
    """Why a charger's power cannot be derived, as ``(code, message)``.

    Returns ``None`` when the charger has valid power limits. The message names
    the charger by its configured ``name`` (falling back to its ``id``) so it
    can be shown verbatim on the EV card and settings page.

    Codes: ``missing_phases`` / ``missing_max_current`` (current chargers),
    ``missing_rated_power`` (binary chargers).
    """
    if charger_max_kw(cfg, voltage) > 0:
        return None
    name = str(cfg.get("name") or cfg.get("id") or "this charger")
    control_type = str(cfg.get("type", "binary") or "binary").lower()
    if control_type == "current":
        if _phase_count(cfg.get("phases")) <= 0:
            return "missing_phases", f"Configure phases for {name} to enable planning"
        return "missing_max_current", f"Configure max current for {name} to enable planning"
    return "missing_rated_power", f"Configure rated power for {name} to enable planning"
