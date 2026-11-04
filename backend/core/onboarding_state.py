"""Validated, atomically persisted onboarding progress."""

import contextlib
import json
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

logger = logging.getLogger(__name__)
STATE_FILE_PATH = Path("data/onboarding_state.json")


class OnboardingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["not_started", "in_progress", "dismissed", "completed"] = "not_started"
    current_step: str | None = Field(default=None, max_length=100)
    completed_steps: list[str] = Field(default_factory=list, max_length=100)


NoticeId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_.:-]{1,100}$")]


class OnboardingState(OnboardingUpdate):
    version: Literal[1] = 1
    updated_at: datetime | None = None
    # Setup notices the user dismissed (e.g. "deye.program_times_unverified").
    # Not part of OnboardingUpdate so progress saves never clobber it.
    dismissed_notices: list[NoticeId] = Field(default_factory=list, max_length=100)
    # Acknowledged informational warnings: id -> measured value (e.g. a ratio) at the time
    # of acknowledgement, so they only reappear when it gets clearly worse.
    acknowledged_warnings: dict[NoticeId, float] = Field(default_factory=dict, max_length=100)


def read_state() -> OnboardingState:
    try:
        return OnboardingState.model_validate_json(STATE_FILE_PATH.read_text())
    except FileNotFoundError:
        return OnboardingState()
    except (ValueError, OSError):
        logger.warning("Could not read onboarding state; returning default")
        return OnboardingState()


def write_state(update: OnboardingUpdate) -> OnboardingState:
    current = read_state()
    state = OnboardingState(
        **update.model_dump(),
        dismissed_notices=current.dismissed_notices,
        acknowledged_warnings=current.acknowledged_warnings,
        updated_at=datetime.now(UTC),
    )
    return _persist(state)


def dismiss_notice(notice_id: str) -> OnboardingState:
    """Persist a dismissed setup notice id, keeping onboarding progress intact."""
    current = read_state()
    dismissed = current.dismissed_notices
    if notice_id not in dismissed:
        dismissed = [*dismissed, notice_id]
    state = OnboardingState.model_validate(
        {**current.model_dump(), "dismissed_notices": dismissed, "updated_at": datetime.now(UTC)}
    )
    return _persist(state)


def acknowledge_warning(warning_id: str, value: float) -> OnboardingState:
    """Persist that a warning was acknowledged at ``value``, replacing any earlier value."""
    current = read_state()
    state = OnboardingState.model_validate(
        {
            **current.model_dump(),
            "acknowledged_warnings": {**current.acknowledged_warnings, warning_id: value},
            "updated_at": datetime.now(UTC),
        }
    )
    return _persist(state)


def clear_acknowledged_warning(warning_id: str) -> OnboardingState:
    """Forget an acknowledgement so a later recurrence of the warning is shown again."""
    current = read_state()
    if warning_id not in current.acknowledged_warnings:
        return current
    remaining = {k: v for k, v in current.acknowledged_warnings.items() if k != warning_id}
    state = OnboardingState.model_validate(
        {
            **current.model_dump(),
            "acknowledged_warnings": remaining,
            "updated_at": datetime.now(UTC),
        }
    )
    return _persist(state)


def _persist(state: OnboardingState) -> OnboardingState:
    STATE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=STATE_FILE_PATH.parent,
            prefix=".onboarding.",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_path = Path(f.name)
            json.dump(state.model_dump(mode="json"), f, indent=2)
        tmp_path.replace(STATE_FILE_PATH)
    finally:
        if tmp_path is not None:
            with contextlib.suppress(FileNotFoundError):
                tmp_path.unlink()
    return state
