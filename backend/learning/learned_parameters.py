"""Learned hardware parameters: lifecycle, lock, resolution and notification.

A learned value is evidenced, bounded, step-limited, visible, lockable and never silently
stale. Values live in the learning database (never in ``config.yaml``). The pure functions
here (``apply_estimate``, ``resolve_battery_parameters``, ``apply_to_config``) are shared by
the daily service, the planner, the benchmark and the offline evaluator, so every consumer
sees the same effective battery efficiencies.

Units (design D2a): the planner's charge and discharge are AC-side, so the effective pair is
``charge_efficiency = (1 - inverter_charge_loss) x sqrt(RTE)`` and
``discharge_efficiency = sqrt(RTE) x inverter_discharge_efficiency``.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select

from backend.learning.battery_estimators import (
    CHARGE_LOSS_BOUNDS,
    DISCHARGE_EFFICIENCY_BOUNDS,
    KEY_CHARGE_LOSS,
    KEY_DISCHARGE_EFFICIENCY,
    KEY_RTE,
    KEY_STANDBY_W,
    RTE_BOUNDS,
    STANDBY_W_BOUNDS,
    Estimate,
    estimate_inverter_loss,
    estimate_round_trip_efficiency,
)
from backend.learning.models import LearnedParameter, LearnedParameterHistory

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from backend.learning.store import LearningStore

logger = logging.getLogger("darkstar.learning.parameters")

EXPIRY_DAYS = 30
NOTIFY_RETRY_DAYS = 3
DEFAULT_DISCHARGE_EFFICIENCY = 0.97
CONFIG_DEFAULT_EFFICIENCY = 0.95  # what the planner assumes when the config key is absent
VALUE_DECIMALS = 6

SOURCE_LOCKED = "locked"
SOURCE_LEARNED = "learned"
SOURCE_DEFAULT = "default"
SOURCE_CONFIG = "config"
SOURCE_EXPIRED = "expired"

EVENT_LEARNED = "learned"
EVENT_EXPIRED = "expired"
EVENT_RECOVERED = "recovered"
EVENT_LOCKED = "locked"
EVENT_LOCK_CHANGED = "lock_changed"
EVENT_UNLOCKED = "unlocked"
NOTIFIED_EVENTS = frozenset({EVENT_LEARNED, EVENT_EXPIRED, EVENT_RECOVERED})

NOTIFY_PENDING = "pending"
NOTIFY_SENT = "sent"
NOTIFY_DISABLED = "disabled"
NOTIFY_NONE = "none"


@dataclass(frozen=True)
class ParameterSpec:
    key: str
    label: str
    unit: str  # "fraction" or "W"
    bounds: tuple[float, float]
    step: float
    deadband: float
    learnable: bool = True


PARAMETERS: dict[str, ParameterSpec] = {
    KEY_RTE: ParameterSpec(
        KEY_RTE, "Battery round-trip efficiency", "fraction", RTE_BOUNDS, 0.01, 0.002
    ),
    KEY_CHARGE_LOSS: ParameterSpec(
        KEY_CHARGE_LOSS, "Inverter charge loss", "fraction", CHARGE_LOSS_BOUNDS, 0.01, 0.002
    ),
    KEY_STANDBY_W: ParameterSpec(
        KEY_STANDBY_W, "Inverter standby power", "W", STANDBY_W_BOUNDS, 20.0, 5.0
    ),
    KEY_DISCHARGE_EFFICIENCY: ParameterSpec(
        KEY_DISCHARGE_EFFICIENCY,
        "Inverter discharge efficiency",
        "fraction",
        DISCHARGE_EFFICIENCY_BOUNDS,
        0.0,
        0.0,
        learnable=False,
    ),
}


# --- State --------------------------------------------------------------------------------


@dataclass(frozen=True)
class ParameterState:
    key: str
    learned_value: float | None = None
    confidence: float | None = None
    evidence: dict[str, Any] = field(default_factory=lambda: {})
    estimated_at: datetime | None = None
    applied_value: float | None = None
    applied_at: datetime | None = None
    status_note: str | None = None
    locked: bool = False
    locked_value: float | None = None


@dataclass(frozen=True)
class HistoryEvent:
    key: str
    at: datetime
    event: str
    old_value: float | None
    new_value: float | None
    confidence: float | None = None
    evidence: dict[str, Any] = field(default_factory=lambda: {})
    notify_state: str = NOTIFY_NONE


@dataclass(frozen=True)
class HistoryRow:
    id: int
    key: str
    at: datetime
    event: str
    old_value: float | None
    new_value: float | None
    confidence: float | None
    evidence: dict[str, Any]
    notify_state: str
    notified_at: datetime | None


@dataclass(frozen=True)
class ApplyResult:
    state: ParameterState
    events: list[HistoryEvent]


def _round(value: float) -> float:
    return round(value, VALUE_DECIMALS)


def apply_estimate(state: ParameterState, estimate: Estimate, now: datetime) -> ApplyResult:
    """Fold one estimate into a parameter state (design D3). Pure.

    Rejected or gated-out estimates leave the stored values and ``estimated_at`` untouched
    and only record why. An accepted estimate always refreshes the learned value; the
    applied value then moves only when unlocked, not already updated today, and outside the
    deadband, by at most one step.
    """
    spec = PARAMETERS[state.key]
    if not estimate.accepted or estimate.value is None:
        note = estimate.rejected_reason or "no estimate"
        rejection = {"at": now.isoformat(), "reason": note, "evidence": estimate.evidence}
        return ApplyResult(
            replace(
                state, status_note=note, evidence={**state.evidence, "last_rejection": rejection}
            ),
            [],
        )

    learned = _round(estimate.value)
    state = replace(
        state,
        learned_value=learned,
        confidence=estimate.confidence,
        evidence=dict(estimate.evidence),
        estimated_at=now,
        status_note=None,
    )
    if state.locked:
        return ApplyResult(state, [])

    old = state.applied_value
    if old is None:
        new = learned
    else:
        if state.applied_at is not None and (
            state.applied_at.astimezone(now.tzinfo).date() == now.date()
        ):
            return ApplyResult(state, [])
        difference = learned - old
        if abs(difference) < spec.deadband:
            return ApplyResult(state, [])
        new = _round(old + max(-spec.step, min(spec.step, difference)))
        if new == old:
            return ApplyResult(state, [])
    event = HistoryEvent(
        key=state.key,
        at=now,
        event=EVENT_LEARNED,
        old_value=old,
        new_value=new,
        confidence=estimate.confidence,
        evidence=dict(estimate.evidence),
        notify_state=NOTIFY_PENDING,
    )
    return ApplyResult(replace(state, applied_value=new, applied_at=now), [event])


# --- Resolution ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedParameter:
    key: str
    value: float | None
    source: str
    learned_value: float | None
    confidence: float | None
    evidence: dict[str, Any]
    estimated_at: datetime | None
    expires_at: datetime | None
    applied_at: datetime | None
    status_note: str | None
    bounds: tuple[float, float]
    config_fallback: float | None
    locked: bool
    locked_value: float | None


@dataclass(frozen=True)
class ResolvedBattery:
    """Effective battery parameters; ``learned`` says whether the pair was composed."""

    parameters: dict[str, ResolvedParameter]
    charge_efficiency: float
    discharge_efficiency: float
    learned: bool
    missing: list[str]
    config_charge_efficiency: float
    config_discharge_efficiency: float

    def archive_record(self) -> dict[str, Any]:
        """Plan-archive form: the effective pair and the source of every component."""
        return {
            "charge_efficiency": self.charge_efficiency,
            "discharge_efficiency": self.discharge_efficiency,
            "basis": "learned" if self.learned else "config",
            "sources": {key: p.source for key, p in self.parameters.items()},
            "values": {key: p.value for key, p in self.parameters.items()},
            "missing": list(self.missing),
            "config_charge_efficiency": self.config_charge_efficiency,
            "config_discharge_efficiency": self.config_discharge_efficiency,
        }


def battery_section(config: Mapping[str, Any]) -> dict[str, Any]:
    """The battery mapping the planner reads: ``system.battery`` if present, else ``battery``."""
    system = config.get("system")
    if isinstance(system, dict) and isinstance(cast("dict[str, Any]", system).get("battery"), dict):
        return cast("dict[str, Any]", cast("dict[str, Any]", system)["battery"])
    battery = config.get("battery")
    return cast("dict[str, Any]", battery) if isinstance(battery, dict) else {}


def config_capacity_kwh(config: Mapping[str, Any]) -> float:
    try:
        return float(battery_section(config).get("capacity_kwh", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _config_efficiency(config: Mapping[str, Any], key: str) -> float:
    try:
        return float(battery_section(config).get(key, CONFIG_DEFAULT_EFFICIENCY))
    except (TypeError, ValueError):
        return CONFIG_DEFAULT_EFFICIENCY


def _resolve_one(state: ParameterState | None, key: str, now: datetime) -> ResolvedParameter:
    spec = PARAMETERS[key]
    state = state or ParameterState(key=key)
    expires_at = state.estimated_at + timedelta(days=EXPIRY_DAYS) if state.estimated_at else None
    fallback = DEFAULT_DISCHARGE_EFFICIENCY if key == KEY_DISCHARGE_EFFICIENCY else None
    if state.locked and state.locked_value is not None:
        value, source = state.locked_value, SOURCE_LOCKED
    elif state.applied_value is not None and expires_at is not None and now <= expires_at:
        value, source = state.applied_value, SOURCE_LEARNED
    elif state.applied_value is not None:
        value, source = fallback, SOURCE_EXPIRED
    elif fallback is not None:
        value, source = fallback, SOURCE_DEFAULT
    else:
        value, source = None, SOURCE_CONFIG
    return ResolvedParameter(
        key=key,
        value=value,
        source=source,
        learned_value=state.learned_value,
        confidence=state.confidence,
        evidence=state.evidence,
        estimated_at=state.estimated_at,
        expires_at=expires_at,
        applied_at=state.applied_at,
        status_note=state.status_note,
        bounds=spec.bounds,
        config_fallback=fallback,
        locked=state.locked and state.locked_value is not None,
        locked_value=state.locked_value,
    )


def resolve_battery_parameters(
    config: Mapping[str, Any], states: Mapping[str, ParameterState], now: datetime
) -> ResolvedBattery:
    """Resolve every parameter and compose the planner's efficiency pair (design D4, D7).

    Expiry is judged here, at resolution time. The pair is learned-based only when RTE,
    charge loss and discharge efficiency are all available; otherwise both efficiencies come
    from the config. Standby never takes part.
    """
    parameters = {key: _resolve_one(states.get(key), key, now) for key in PARAMETERS}
    config_charge = _config_efficiency(config, "charge_efficiency")
    config_discharge = _config_efficiency(config, "discharge_efficiency")
    rte = parameters[KEY_RTE].value
    loss = parameters[KEY_CHARGE_LOSS].value
    eta = parameters[KEY_DISCHARGE_EFFICIENCY].value
    missing = [key for key, value in ((KEY_RTE, rte), (KEY_CHARGE_LOSS, loss)) if value is None]
    if rte is None or loss is None or eta is None:
        return ResolvedBattery(
            parameters,
            config_charge,
            config_discharge,
            False,
            missing,
            config_charge,
            config_discharge,
        )
    root = math.sqrt(rte)
    return ResolvedBattery(
        parameters,
        (1.0 - loss) * root,
        root * eta,
        True,
        [],
        config_charge,
        config_discharge,
    )


def apply_to_config(config: Mapping[str, Any], resolved: ResolvedBattery) -> dict[str, Any]:
    """Deep copy of ``config`` whose battery efficiencies are the effective ones.

    The keys are replaced in whichever mapping the planner reads. Without a learned pair
    the copy is identical to the input. The input is never mutated.
    """
    result = copy.deepcopy(dict(config))
    if not resolved.learned:
        return result
    system = result.get("system")
    if isinstance(system, dict) and isinstance(cast("dict[str, Any]", system).get("battery"), dict):
        target = cast("dict[str, Any]", cast("dict[str, Any]", system)["battery"])
    else:
        existing = result.get("battery")
        if not isinstance(existing, dict):
            existing = {}
            result["battery"] = existing
        target = cast("dict[str, Any]", existing)
    target["charge_efficiency"] = resolved.charge_efficiency
    target["discharge_efficiency"] = resolved.discharge_efficiency
    return result


def read_states_sync(db_path: str) -> dict[str, ParameterState]:
    """Stored parameter states read with plain sqlite (read-only); empty when absent.

    Used where a synchronous read off the event loop is needed (planner, benchmark,
    evaluator). A missing database or table is not an error: nothing has been learned.
    """
    uri = f"file:{db_path}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=10.0)
    except sqlite3.OperationalError:
        return {}
    try:
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute("SELECT * FROM learned_parameters").fetchall()
        except sqlite3.OperationalError:
            return {}
        return {
            str(row["key"]): ParameterState(
                key=str(row["key"]),
                learned_value=row["learned_value"],
                confidence=row["confidence"],
                evidence=_loads(row["evidence_json"]),
                estimated_at=_parse(row["estimated_at"]),
                applied_value=row["applied_value"],
                applied_at=_parse(row["applied_at"]),
                status_note=row["status_note"],
                locked=bool(row["locked"]),
                locked_value=row["locked_value"],
            )
            for row in rows
            if row["key"] in PARAMETERS
        }
    finally:
        connection.close()


async def resolve_effective_config(
    config: Mapping[str, Any], db_path: str, now: datetime | None = None
) -> tuple[dict[str, Any], ResolvedBattery]:
    """Config with the effective battery efficiencies, and how they were resolved.

    The single seam for planner, price reserve, benchmark and archive. Never raises: a read
    failure logs a warning and keeps the configured efficiencies.
    """
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    try:
        states = await asyncio.to_thread(read_states_sync, db_path)
    except Exception as exc:
        logger.warning("Learned battery parameters unavailable (%s); using config values", exc)
        states = {}
    resolved = resolve_battery_parameters(config, states, moment)
    return apply_to_config(config, resolved), resolved


def validate_lock_value(key: str, value: float) -> None:
    """Raise ``ValueError`` for an unknown key or a value outside the physical bounds."""
    spec = PARAMETERS.get(key)
    if spec is None:
        raise KeyError(key)
    if isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("value must be a finite number")
    low, high = spec.bounds
    if not low <= value <= high:
        raise ValueError(f"value must be between {low} and {high}")


# --- Persistence --------------------------------------------------------------------------


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return cast("dict[str, Any]", decoded) if isinstance(decoded, dict) else {}


def _state_from_row(row: LearnedParameter) -> ParameterState:
    return ParameterState(
        key=row.key,
        learned_value=row.learned_value,
        confidence=row.confidence,
        evidence=_loads(row.evidence_json),
        estimated_at=_parse(row.estimated_at),
        applied_value=row.applied_value,
        applied_at=_parse(row.applied_at),
        status_note=row.status_note,
        locked=bool(row.locked),
        locked_value=row.locked_value,
    )


def _history_from_row(row: LearnedParameterHistory) -> HistoryRow:
    return HistoryRow(
        id=row.id,
        key=row.key,
        at=cast("datetime", _parse(row.at)),
        event=row.event,
        old_value=row.old_value,
        new_value=row.new_value,
        confidence=row.confidence,
        evidence=_loads(row.evidence_json),
        notify_state=row.notify_state,
        notified_at=_parse(row.notified_at),
    )


class LearnedParameterStore:
    """Async access to ``learned_parameters`` and its history through a ``LearningStore``."""

    def __init__(self, store: LearningStore) -> None:
        self._store = store

    async def get_states(self) -> dict[str, ParameterState]:
        async with self._store.AsyncSession() as session:
            rows = (await session.execute(select(LearnedParameter))).scalars().all()
            return {row.key: _state_from_row(row) for row in rows}

    async def save_state(self, state: ParameterState, now: datetime) -> None:
        async with self._store.AsyncSession() as session:
            row = await session.get(LearnedParameter, state.key)
            if row is None:
                row = LearnedParameter(key=state.key)
                session.add(row)
            row.learned_value = state.learned_value
            row.confidence = state.confidence
            row.evidence_json = json.dumps(state.evidence, default=str)
            row.estimated_at = state.estimated_at.isoformat() if state.estimated_at else None
            row.applied_value = state.applied_value
            row.applied_at = state.applied_at.isoformat() if state.applied_at else None
            row.status_note = state.status_note
            row.locked = 1 if state.locked else 0
            row.locked_value = state.locked_value
            row.updated_at = now.isoformat()
            await session.commit()

    async def add_history(self, events: Sequence[HistoryEvent]) -> list[int]:
        if not events:
            return []
        async with self._store.AsyncSession() as session:
            rows = [
                LearnedParameterHistory(
                    key=event.key,
                    at=event.at.isoformat(),
                    event=event.event,
                    old_value=event.old_value,
                    new_value=event.new_value,
                    confidence=event.confidence,
                    evidence_json=json.dumps(event.evidence, default=str),
                    notify_state=event.notify_state,
                )
                for event in events
            ]
            session.add_all(rows)
            await session.flush()
            ids = [row.id for row in rows]
            await session.commit()
            return ids

    async def list_history(self, limit: int = 50, key: str | None = None) -> list[HistoryRow]:
        async with self._store.AsyncSession() as session:
            stmt = select(LearnedParameterHistory).order_by(
                LearnedParameterHistory.at.desc(), LearnedParameterHistory.id.desc()
            )
            if key is not None:
                stmt = stmt.where(LearnedParameterHistory.key == key)
            rows = (await session.execute(stmt.limit(limit))).scalars().all()
            return [_history_from_row(row) for row in rows]

    async def last_event(self, key: str) -> str | None:
        """Most recent applied-change event (learned, expired, recovered) of a parameter."""
        async with self._store.AsyncSession() as session:
            stmt = (
                select(LearnedParameterHistory.event)
                .where(
                    LearnedParameterHistory.key == key,
                    LearnedParameterHistory.event.in_(sorted(NOTIFIED_EVENTS)),
                )
                .order_by(LearnedParameterHistory.at.desc(), LearnedParameterHistory.id.desc())
                .limit(1)
            )
            return (await session.execute(stmt)).scalar_one_or_none()

    async def pending_history(self, since: datetime) -> list[HistoryRow]:
        """Rows waiting for a notification that are younger than the retry window."""
        async with self._store.AsyncSession() as session:
            stmt = (
                select(LearnedParameterHistory)
                .where(
                    LearnedParameterHistory.notify_state == NOTIFY_PENDING,
                    LearnedParameterHistory.at >= since.isoformat(),
                )
                .order_by(LearnedParameterHistory.at.asc(), LearnedParameterHistory.id.asc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_history_from_row(row) for row in rows]

    async def mark_notified(self, ids: Sequence[int], state: str, now: datetime) -> None:
        if not ids:
            return
        async with self._store.AsyncSession() as session:
            rows = (
                (
                    await session.execute(
                        select(LearnedParameterHistory).where(LearnedParameterHistory.id.in_(ids))
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                row.notify_state = state
                row.notified_at = now.isoformat() if state == NOTIFY_SENT else None
            await session.commit()

    async def set_lock(self, key: str, value: float, now: datetime) -> ParameterState:
        """Lock a parameter to ``value`` (validated against its bounds); records history."""
        validate_lock_value(key, value)
        states = await self.get_states()
        state = states.get(key) or ParameterState(key=key)
        was_locked = state.locked
        old = state.locked_value if was_locked else None
        if was_locked and state.locked_value == value:
            return state
        state = replace(state, locked=True, locked_value=value)
        await self.save_state(state, now)
        await self.add_history(
            [
                HistoryEvent(
                    key=key,
                    at=now,
                    event=EVENT_LOCK_CHANGED if was_locked else EVENT_LOCKED,
                    old_value=old,
                    new_value=value,
                    confidence=state.confidence,
                    evidence=state.evidence,
                )
            ]
        )
        return state

    async def clear_lock(self, key: str, now: datetime) -> ParameterState:
        if key not in PARAMETERS:
            raise KeyError(key)
        states = await self.get_states()
        state = states.get(key) or ParameterState(key=key)
        if not state.locked:
            return state
        old = state.locked_value
        state = replace(state, locked=False, locked_value=None)
        await self.save_state(state, now)
        await self.add_history(
            [
                HistoryEvent(
                    key=key,
                    at=now,
                    event=EVENT_UNLOCKED,
                    old_value=old,
                    new_value=None,
                    confidence=state.confidence,
                    evidence=state.evidence,
                )
            ]
        )
        return state


# --- Notification -------------------------------------------------------------------------


def _format_value(key: str, value: float | None) -> str:
    if value is None:
        return "configured value"
    return f"{value:.0f} W" if PARAMETERS[key].unit == "W" else f"{value:.3f}"


def _window_days(evidence: Mapping[str, Any]) -> str:
    for name in ("days", "span_days"):
        value = evidence.get(name)
        if isinstance(value, int | float):
            return f" ({value:.0f} days of data)"
    return ""


def format_change(row: HistoryRow) -> str:
    label = PARAMETERS[row.key].label if row.key in PARAMETERS else row.key
    if row.event == EVENT_EXPIRED:
        return f"{label}: expired, the configured value is used"
    old = _format_value(row.key, row.old_value) if row.old_value is not None else "none"
    suffix = " (recovered)" if row.event == EVENT_RECOVERED else ""
    return (
        f"{label}: {old} -> {_format_value(row.key, row.new_value)}"
        f"{_window_days(row.evidence)}{suffix}"
    )


async def notify_changes(
    store: LearnedParameterStore,
    rows: Sequence[HistoryRow],
    notifier: Callable[[str, str], Awaitable[bool]] | None,
    enabled: bool,
    now: datetime,
) -> str:
    """Send one message for every pending change; returns the resulting notify state.

    Lock events never appear here (they are written with ``notify_state = none``). With the
    toggle off the rows become ``disabled``; an undeliverable message leaves them ``pending``
    so the next run retries (rows older than the retry window are not selected).
    """
    pending = [row for row in rows if row.notify_state == NOTIFY_PENDING]
    if not pending:
        return NOTIFY_NONE
    ids = [row.id for row in pending]
    if not enabled:
        await store.mark_notified(ids, NOTIFY_DISABLED, now)
        return NOTIFY_DISABLED
    if notifier is None:
        return NOTIFY_PENDING
    message = "\n".join(f"- {format_change(row)}" for row in pending)
    try:
        delivered = await notifier("Darkstar learned parameters", message)
    except Exception:
        logger.warning("Learned-parameter notification failed", exc_info=True)
        return NOTIFY_PENDING
    if not delivered:
        return NOTIFY_PENDING
    await store.mark_notified(ids, NOTIFY_SENT, now)
    return NOTIFY_SENT


def notifications_enabled(config: Mapping[str, Any]) -> bool:
    executor = config.get("executor")
    notifications: Any = (
        cast("dict[str, Any]", executor).get("notifications")
        if isinstance(executor, dict)
        else None
    )
    if not isinstance(notifications, dict):
        return True
    return bool(cast("dict[str, Any]", notifications).get("on_learned_parameter_change", True))


# --- Daily run ----------------------------------------------------------------------------


@dataclass(frozen=True)
class AppliedChange:
    key: str
    event: str
    old_value: float | None
    new_value: float | None
    confidence: float | None
    notify: str = NOTIFY_NONE


async def run_once(
    store: LearnedParameterStore,
    rows: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    now: datetime,
    notifier: Callable[[str, str], Awaitable[bool]] | None = None,
    loss_sensor_values: Mapping[str, float] | None = None,
    run_estimators: bool = True,
) -> list[AppliedChange]:
    """Run every estimator (each fenced), apply results, record history, notify.

    Expiry and recovery events come from the change of the resolved source over the run, so
    a crash can never leave a stale value silently valid. With ``run_estimators`` false (learning
    switched off) no estimator runs, but expiry is still recorded and notified and pending
    notifications are still retried.
    """
    capacity = config_capacity_kwh(config)
    states = await store.get_states()
    before = resolve_battery_parameters(config, states, now)
    estimates: dict[str, Estimate] = {}

    def fenced(name: str, produce: Callable[[], dict[str, Estimate]]) -> None:
        try:
            estimates.update(produce())
        except Exception:
            logger.exception("Learned parameter estimator %s failed", name)

    def loss() -> dict[str, Estimate]:
        result = estimate_inverter_loss(rows, loss_sensor_values, capacity, now)
        return {KEY_CHARGE_LOSS: result.charge_loss, KEY_STANDBY_W: result.standby_w}

    if run_estimators:
        fenced("rte", lambda: {KEY_RTE: estimate_round_trip_efficiency(rows, capacity, now)})
        fenced("inverter_loss", loss)

    events: list[HistoryEvent] = []
    new_states = dict(states)
    for key, estimate in estimates.items():
        result = apply_estimate(new_states.get(key) or ParameterState(key=key), estimate, now)
        new_states[key] = result.state
        events.extend(result.events)
        await store.save_state(result.state, now)

    after = resolve_battery_parameters(config, new_states, now)
    for key in (KEY_RTE, KEY_CHARGE_LOSS, KEY_STANDBY_W):
        previous, current = before.parameters[key], after.parameters[key]
        last = await store.last_event(key)
        state = new_states.get(key)
        if current.source == SOURCE_EXPIRED and last != EVENT_EXPIRED:
            events.append(
                HistoryEvent(
                    key=key,
                    at=now,
                    event=EVENT_EXPIRED,
                    old_value=state.applied_value if state else None,
                    new_value=None,
                    confidence=state.confidence if state else None,
                    evidence=state.evidence if state else {},
                    notify_state=NOTIFY_PENDING,
                )
            )
        elif current.source == SOURCE_LEARNED and (
            last == EVENT_EXPIRED or previous.source == SOURCE_EXPIRED
        ):
            # A recovery replaces the plain "learned" event of the same run for this key.
            events = [e for e in events if not (e.key == key and e.event == EVENT_LEARNED)]
            events.append(
                HistoryEvent(
                    key=key,
                    at=now,
                    event=EVENT_RECOVERED,
                    old_value=state.applied_value if state else None,
                    new_value=current.value,
                    confidence=current.confidence,
                    evidence=current.evidence,
                    notify_state=NOTIFY_PENDING,
                )
            )
    await store.add_history(events)
    changes = [
        AppliedChange(e.key, e.event, e.old_value, e.new_value, e.confidence, e.notify_state)
        for e in events
    ]
    pending = await store.pending_history(now - timedelta(days=NOTIFY_RETRY_DAYS))
    await notify_changes(store, pending, notifier, notifications_enabled(config), now)
    return changes
