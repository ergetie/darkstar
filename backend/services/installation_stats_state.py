"""Durable channel-scoped identity and schedule state for telemetry sender."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from backend.core.atomic_json import write_json_atomic


class InstallationStatsStateError(Exception):
    """Persistent sender state is missing, corrupt, or cannot be written safely."""


class InstallationStatsState:
    """Load or create a persisted UUID and atomically record sender schedule state."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.installation_id: str | None = None
        self.last_attempt: datetime | None = None
        self.last_success: datetime | None = None
        self.next_attempt_due: datetime | None = None

    def load(self) -> None:
        if not self.path.exists():
            self.installation_id = str(uuid.uuid4())
            self.last_attempt = None
            self.last_success = None
            self.next_attempt_due = None
            self._write()
            return

        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InstallationStatsStateError("state could not be read") from exc
        if not isinstance(raw, dict):
            raise InstallationStatsStateError("state has an invalid shape")
        state = cast("dict[str, object]", raw)
        legacy_fields = {"installation_id", "last_attempt_utc"}
        current_fields = legacy_fields | {"last_success_utc", "next_attempt_due_utc"}
        if set(state) not in (legacy_fields, current_fields):
            raise InstallationStatsStateError("state has an invalid shape")

        identifier = state.get("installation_id")
        try:
            parsed = uuid.UUID(identifier) if isinstance(identifier, str) else None
        except ValueError as exc:
            raise InstallationStatsStateError("state ID is invalid") from exc
        if parsed is None or parsed.version != 4 or parsed.variant != uuid.RFC_4122:
            raise InstallationStatsStateError("state ID is invalid")

        last_attempt = self._parse_timestamp(state.get("last_attempt_utc"), "attempt")
        last_success = self._parse_timestamp(state.get("last_success_utc"), "success")
        next_attempt_due = self._parse_timestamp(state.get("next_attempt_due_utc"), "due")
        if next_attempt_due is not None and last_success is None:
            raise InstallationStatsStateError("state schedule has no confirmed success")

        self.installation_id = str(parsed)
        self.last_attempt = last_attempt
        self.last_success = last_success
        self.next_attempt_due = next_attempt_due

    def record_attempt(self, attempted_at: datetime) -> None:
        if attempted_at.tzinfo is None:
            raise ValueError("attempt time must be timezone-aware")
        normalized = attempted_at.astimezone(UTC)
        self._write(normalized, self.last_success, None)
        self.last_attempt = normalized
        self.next_attempt_due = None

    def record_success(self, confirmed_at: datetime, next_attempt_due: datetime) -> None:
        """Persist a confirmed HTTP 204 and its stable daily schedule atomically."""
        if confirmed_at.tzinfo is None or next_attempt_due.tzinfo is None:
            raise ValueError("success schedule timestamps must be timezone-aware")
        normalized_success = confirmed_at.astimezone(UTC)
        normalized_due = next_attempt_due.astimezone(UTC)
        if normalized_due < normalized_success:
            raise ValueError("next attempt cannot precede confirmed success")
        if self.last_attempt is None:
            raise InstallationStatsStateError("state has no recorded attempt")
        self._write(self.last_attempt, normalized_success, normalized_due)
        self.last_success = normalized_success
        self.next_attempt_due = normalized_due

    def _parse_timestamp(self, value: object, field: str) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise InstallationStatsStateError(f"state {field} timestamp is invalid")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise InstallationStatsStateError(f"state {field} timestamp is invalid") from exc
        if parsed.tzinfo is None:
            raise InstallationStatsStateError(f"state {field} timestamp has no timezone")
        return parsed.astimezone(UTC)

    def _write(
        self,
        last_attempt: datetime | None = None,
        last_success: datetime | None = None,
        next_attempt_due: datetime | None = None,
    ) -> None:
        if self.installation_id is None:
            raise InstallationStatsStateError("state ID is unavailable")
        payload = {
            "installation_id": self.installation_id,
            "last_attempt_utc": last_attempt.isoformat() if last_attempt is not None else None,
            "last_success_utc": last_success.isoformat() if last_success is not None else None,
            "next_attempt_due_utc": (
                next_attempt_due.isoformat() if next_attempt_due is not None else None
            ),
        }
        try:
            write_json_atomic(self.path, payload)
        except (OSError, TypeError, ValueError) as exc:
            raise InstallationStatsStateError("state could not be saved") from exc
