from pathlib import Path

import pytest
import yaml

try:
    from webapp import (
        _normalise_theme,
        _parse_legacy_theme_format,
        app,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - handled via skip
    pytestmark = pytest.mark.skip(reason=f"webapp import failed: {exc}")


def test_parse_legacy_theme_format_to_normalised():
    palette_lines = [f"palette = {idx}=#{idx:06x}" for idx in range(16)]
    theme_text = "\n".join(palette_lines + ["background = #000000", "foreground = #ffffff"])

    raw_theme = _parse_legacy_theme_format(theme_text)
    assert isinstance(raw_theme["palette"], list)
    assert len(raw_theme["palette"]) == 16
    assert raw_theme["palette"][5] == "#000005"

    normalised = _normalise_theme("Test Theme", raw_theme)
    assert normalised["name"] == "Test Theme"
    assert normalised["background"] == "#000000"
    assert normalised["foreground"] == "#ffffff"
    assert normalised["palette"][15] == "#00000f"


@pytest.mark.usefixtures("restore_config_after_test")
def test_theme_api_list_and_select_updates_config():
    client = app.test_client()

    response = client.get("/api/themes")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["themes"], "expected at least one theme from /api/themes"
    assert "accent_index" in payload

    selected_name = payload["themes"][0]["name"]
    desired_index = 5
    post_response = client.post(
        "/api/theme", json={"theme": selected_name, "accent_index": desired_index}
    )
    assert post_response.status_code == 200
    result_payload = post_response.get_json()
    assert result_payload["accent_index"] == desired_index

    config_path = Path("config.yaml")
    config_data = yaml.safe_load(config_path.read_text())
    ui_cfg = config_data.get("ui", {})
    assert ui_cfg.get("theme") == selected_name
    assert ui_cfg.get("theme_accent_index") == desired_index


@pytest.fixture
def restore_config_after_test():
    config_path = Path("config.yaml")
    original = config_path.read_text()
    try:
        yield
    finally:
        config_path.write_text(original)
