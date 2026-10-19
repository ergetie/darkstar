"""metadata.setup_notice parsing, validation and list_profiles() exposure."""

from typing import Any

import pytest

from backend.core.secrets import load_yaml
from executor.profiles import list_profiles, load_profile, parse_profile


def _deye_data(notice: Any) -> dict[str, Any]:
    data = load_yaml("profiles/deye.yaml")
    if notice is None:
        data["metadata"].pop("setup_notice", None)
    else:
        data["metadata"]["setup_notice"] = notice
    return data


def test_deye_ships_valid_setup_notice():
    notice = load_profile("deye").metadata.setup_notice
    assert notice["severity"] == "info"
    text = " ".join(notice["items"])
    assert "00:00" in text and "program 6" in text and "helper" in text


def test_absent_notice_is_valid():
    valid, errors = parse_profile(_deye_data(None)).validate()
    assert valid, errors


@pytest.mark.parametrize(
    "notice",
    [
        "text",
        {"title": "T", "severity": "critical", "items": ["a"]},
        {"title": 1, "severity": "info", "items": ["a"]},
        {"title": "T", "severity": "info", "items": "a"},
        {"title": "T", "severity": "info", "items": [1]},
        {"title": "T", "severity": "info", "items": []},
        {"title": "T", "severity": "info", "items": ["a"], "link": "x"},
    ],
)
def test_invalid_notice_rejected(notice):
    valid, errors = parse_profile(_deye_data(notice)).validate()
    assert not valid
    assert any("setup_notice" in e for e in errors)


def test_list_profiles_exposes_setup_notice():
    by_name = {p["name"]: p for p in list_profiles()}
    assert by_name["deye"]["setup_notice"]["title"]
    assert by_name["deye"]["setup_notice"]["severity"] == "info"
    assert by_name["generic"]["setup_notice"] is None
