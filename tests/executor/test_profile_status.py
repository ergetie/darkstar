"""metadata.status (tested | community) parsing, validation and API exposure."""

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.api.routers import executor as executor_router
from backend.core.secrets import load_yaml
from executor.profiles import PROFILE_STATUSES, list_profiles, load_profile, parse_profile

SHIPPED = ["deye", "fronius", "sungrow", "generic"]


def _data(status: Any = None, *, drop: bool = False) -> dict[str, Any]:
    data = load_yaml("profiles/deye.yaml")
    data["metadata"].pop("status", None)
    if not drop:
        data["metadata"]["status"] = status
    return data


def test_absent_status_defaults_to_community():
    profile = parse_profile(_data(drop=True))
    assert profile.metadata.status == "community"
    valid, errors = profile.validate()
    assert valid, errors


@pytest.mark.parametrize("status", PROFILE_STATUSES)
def test_declared_status_is_loaded(status):
    profile = parse_profile(_data(status))
    assert profile.metadata.status == status
    valid, errors = profile.validate()
    assert valid, errors


@pytest.mark.parametrize("status", ["verified", "Tested", "", None, 1])
def test_invalid_status_rejected(status):
    valid, errors = parse_profile(_data(status)).validate()
    assert not valid
    assert any("metadata.status" in e and "tested, community" in e for e in errors)


def test_list_profiles_includes_status():
    listed = list_profiles()
    assert listed
    assert all(p["status"] in PROFILE_STATUSES for p in listed)


@pytest.mark.parametrize("name", SHIPPED)
def test_shipped_profiles_are_tested(name):
    assert load_profile(name).metadata.status == "tested"


def test_shipped_profiles_pass_validate_script():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "scripts/validate_profiles.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
async def test_profiles_api_returns_status():
    result = await executor_router.get_profiles()
    by_name = {p["name"]: p for p in result}
    assert {by_name[n]["status"] for n in SHIPPED} == {"tested"}
