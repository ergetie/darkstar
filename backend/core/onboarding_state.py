"""Validated, atomically persisted onboarding progress."""

import contextlib
import json
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)
STATE_FILE_PATH = Path("data/onboarding_state.json")


class OnboardingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["not_started", "in_progress", "dismissed", "completed"] = "not_started"
    current_step: str | None = Field(default=None, max_length=100)
    completed_steps: list[str] = Field(default_factory=list, max_length=100)


class OnboardingState(OnboardingUpdate):
    version: Literal[1] = 1
    updated_at: datetime | None = None


def read_state() -> OnboardingState:
    try:
        return OnboardingState.model_validate_json(STATE_FILE_PATH.read_text())
    except FileNotFoundError:
        return OnboardingState()
    except (ValueError, OSError):
        logger.warning("Could not read onboarding state; returning default")
        return OnboardingState()


def write_state(update: OnboardingUpdate) -> OnboardingState:
    state = OnboardingState(**update.model_dump(), updated_at=datetime.now(UTC))
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
