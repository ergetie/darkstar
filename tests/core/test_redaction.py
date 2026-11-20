import json
import sqlite3
from pathlib import Path

import pytest

from backend.core.redaction import (
    UNPARSEABLE_CONFIG_VERSION,
    RedactionError,
    mask_config_versions,
    redact_config,
    redact_text,
)


@pytest.mark.parametrize(
    ("line", "gone"),
    [
        (
            "GET https://myhome.ui.nabu.casa/api/states?token=abc failed",
            ["myhome", "abc", "states"],
        ),
        ("connect http://myhome.duckdns.org:8123 refused", ["duckdns", "myhome"]),
        ("connect http://203.0.113.9/x https://8.8.8.8:8123/", ["8.8.8.8"]),
    ],
)
def test_public_hosts_are_masked(line: str, gone: list[str]) -> None:
    out = redact_text(line)
    for item in gone:
        assert item not in out


def test_public_host_keeps_port_and_scheme() -> None:
    assert (
        redact_text("connect http://myhome.duckdns.org:8123 refused")
        == "connect http://<redacted-host>:8123 refused"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.0.100:8123",
        "http://10.1.2.3",
        "http://172.16.0.5:8123",
        "http://169.254.1.1",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://[::1]:8123",
        "http://homeassistant:8123",
        "http://supervisor/core",
        "http://ha.local:8123",
        "http://nas.internal",
        "http://host.docker.internal:8123",
    ],
)
def test_local_hosts_are_kept(url: str) -> None:
    host_only = url.split("/core")[0]
    out = redact_text(f"url={url} ok")
    assert host_only in out


@pytest.mark.parametrize(
    "host",
    [
        "api.open-meteo.com",
        "historical-forecast-api.open-meteo.com",
        "archive-api.open-meteo.com",
        "telemetry.wxl.se",
        "openrouter.ai",
        "github.com",
        "discord.com",
        "discordapp.com",
    ],
)
def test_allowlisted_service_hosts_are_kept(host: str) -> None:
    assert f"https://{host}" in redact_text(f"fetch https://{host}/v1/thing?a=1 done")
    assert redact_text(f"fetch https://{host}") == f"fetch https://{host}"


def test_url_path_query_and_credentials_removed() -> None:
    out = redact_text("https://user:pw@192.168.0.2:8123/api/states/x?a=1")
    assert out == "https://192.168.0.2:8123/<redacted>"


def test_public_ip_is_masked_and_local_kept() -> None:
    out = redact_text("peer 8.8.8.8:8123 and 192.168.1.5 and 10.0.0.1 and 127.0.0.1")
    assert out == "peer <redacted-ip>:8123 and 192.168.1.5 and 10.0.0.1 and 127.0.0.1"


@pytest.mark.parametrize(
    "text",
    [
        "300.1.1.1",
        "256.256.256.256",
        "08.8.8.8",
        "1.2.3.4.5",
        "1.2.3",
        "pkg==1.2.3.4",
        "version 1.2.3.4",
        "v1.2.3.4",
        "2026-11-20T10:11:12.123456+00:00",
        "abc1.2.3.4",
    ],
)
def test_not_an_address_is_left_alone(text: str) -> None:
    assert redact_text(text) == text


def test_valid_public_quad_without_version_marker_is_masked() -> None:
    assert redact_text("seen 1.2.3.4 here") == "seen <redacted-ip> here"


def test_json_escaped_line() -> None:
    line = json.dumps({"msg": "connect http://myhome.duckdns.org:8123/api?token=abc ok"})
    assert "\\/" not in line  # json.dumps does not escape slashes
    line = line.replace("/", "\\/")
    out = redact_text(line)
    assert "duckdns" not in out and "abc" not in out
    assert "http:\\/\\/<redacted-host>:8123\\/<redacted>" in out
    assert json.loads(out)["msg"].startswith("connect http://<redacted-host>:8123/")


def test_json_escaped_quotes_keep_structure() -> None:
    inner = json.dumps({"url": "http://myhome.duckdns.org:8123", "ha": "http://192.168.0.100:8123"})
    line = json.dumps({"msg": inner})
    out = redact_text(line)
    assert "duckdns" not in out
    parsed = json.loads(json.loads(out)["msg"])
    assert parsed == {"url": "http://<redacted-host>:8123", "ha": "http://192.168.0.100:8123"}


def test_json_escaped_token_and_unicode_query() -> None:
    line = json.dumps({"msg": "x token=secret123 y"})
    assert redact_text(line) == json.dumps({"msg": "x token=<redacted> y"})
    escaped = '"http:\\/\\/ex.example.org\\/a?b=1\\u0026token=zzz"'
    out = redact_text(escaped)
    assert out == '"http:\\/\\/<redacted-host>\\/<redacted>"'


def test_token_value_in_escaped_quotes() -> None:
    line = json.dumps({"msg": 'cfg token="abc123" end'})
    out = redact_text(line)
    assert "abc123" not in out
    json.loads(out)


@pytest.mark.parametrize(
    "text",
    [
        '"latitude": 55.123',
        "latitude=55.123",
        "lat: -33.8688",
        "lon=13.4567, lng=13.4567",
        "{'longitude': 13.456}",
        '{"latitude": "55.123"}',
    ],
)
def test_coordinates_masked(text: str) -> None:
    out = redact_text(text)
    assert not any(ch.isdigit() for ch in out.replace("<redacted>", ""))
    assert "<redacted>" in out


def test_coordinates_in_escaped_json() -> None:
    out = redact_text(json.dumps({"msg": json.dumps({"latitude": 55.123, "longitude": 13.456})}))
    assert "55.123" not in out and "13.456" not in out
    inner = json.loads(json.loads(out)["msg"])
    assert inner == {"latitude": "<redacted>", "longitude": "<redacted>"}


def test_coordinates_in_json_document_stay_valid_json() -> None:
    doc = {
        "schedule": [{"slot": 1, "lat": 1.5}],
        "system": {"latitude": 55.123, "longitude": -13.456, "nested": {"lng": 0.25}},
        "tag": "latitude: 55.123",
    }
    for text in (
        json.dumps(doc),
        json.dumps(doc, indent=2),
        json.dumps(doc, separators=(",", ":")),
    ):
        out = redact_text(text)
        parsed = json.loads(out)
        assert parsed["system"]["latitude"] == "<redacted>"
        assert parsed["system"]["nested"]["lng"] == "<redacted>"
        assert parsed["schedule"][0]["lat"] == "<redacted>"
        assert parsed["tag"] == "latitude: <redacted>"
        assert "55.123" not in out
        assert redact_text(out) == out


def test_coordinates_in_text_forms_keep_bare_placeholder() -> None:
    assert redact_text("latitude=55.123 lat: 1.5") == "latitude=<redacted> lat: <redacted>"
    assert redact_text("{'longitude': 13.456}") == "{'longitude': <redacted>}"


def test_coordinate_lookalikes_untouched() -> None:
    text = "latency: 5.5 ms, plan: 12.5, slat=3, lat=55"
    assert redact_text(text) == text


def test_token_and_bearer_masked() -> None:
    out = redact_text("GET /x?token=abc&y=1 Authorization: Bearer abc.def-123 password=hunter2")
    assert "abc" not in out and "hunter2" not in out
    assert "Bearer <redacted>" in out


def test_discord_webhook_redacted_host_kept() -> None:
    out = redact_text("post https://discord.com/api/webhooks/123/secret-token done")
    assert out == "post https://discord.com/api/webhooks/<redacted> done"


def test_ordinary_log_line_unchanged() -> None:
    line = (
        "2026-11-20 10:11:12,123 INFO executor: set sensor.battery_soc=57.5 "
        "price=1.234 kr/kWh via http://192.168.0.100:8123"
    )
    assert redact_text(line) == line


def test_idempotent() -> None:
    text = (
        "https://myhome.ui.nabu.casa/x?token=a 8.8.8.8 latitude=55.123 "
        '{"u": "http:\\/\\/foo.example.org\\/p"}'
    )
    once = redact_text(text)
    assert redact_text(once) == once


# --- redact_config ---------------------------------------------------------------

_CONFIG = """\
# top comment
system:
  latitude: 55.123   # keep me
  longitude: 13.456
  api_key: abc
  empty_token: ""
  unset_password:
notifications:
  discord_webhook: "https://discord.com/api/webhooks/1/x"
  nested:
    - name: a
      Secret_Value: s3
sensor: sensor.battery_soc
ha_url: http://myhome.duckdns.org:8123
local_url: http://192.168.0.100:8123
zeta: 1
alpha: 2
"""


def test_redact_config_rules() -> None:
    out = redact_config(_CONFIG)
    assert "api_key: <redacted>" in out
    assert 'discord_webhook: "<redacted>"' in out
    assert "Secret_Value: <redacted>" in out
    assert 'empty_token: ""' in out
    assert "unset_password:" in out and "<redacted>" not in out.split("unset_password:")[1][:3]
    assert "latitude: 55.1" in out and "# keep me" in out
    assert "longitude: 13.5" in out
    assert "sensor: sensor.battery_soc" in out
    assert "http://<redacted-host>:8123" in out
    assert "http://192.168.0.100:8123" in out
    assert "abc" not in out and "s3" not in out.replace("sensor", "")


def test_redact_config_keeps_comments_and_order() -> None:
    out = redact_config(_CONFIG)
    assert out.startswith("# top comment\n")
    assert "# keep me" in out
    assert out.index("zeta") < out.index("alpha")
    assert out.index("system:") < out.index("notifications:") < out.index("sensor:")


def test_redact_config_nothing_to_redact_is_byte_identical() -> None:
    text = "# c\nb: 2   # odd   spacing\na:\n    - x\n    -   y\nlatitude: 55.1\nname: 'q'\n"
    assert redact_config(text) == text


def test_redact_config_is_idempotent() -> None:
    once = redact_config(_CONFIG)
    assert redact_config(once) == once


def test_redact_config_integer_coordinates_untouched() -> None:
    assert redact_config("latitude: 55\nlongitude: 13\n") == "latitude: 55\nlongitude: 13\n"


@pytest.mark.parametrize("bad", ["a: [1, 2\n", "a: b: c\n", "\tfoo: 1\n"])
def test_redact_config_unparseable_raises(bad: str) -> None:
    with pytest.raises(RedactionError):
        redact_config(bad)


def test_redact_config_default_yaml_redacts_cleanly() -> None:
    text = (Path(__file__).resolve().parents[2] / "config.default.yaml").read_text(encoding="utf-8")
    out = redact_config(text)
    assert "latitude: 55.1 " in out and "55.123" not in out
    # Only coordinates and URL text change; ruamel re-emits an explicit ``null`` as an
    # empty scalar, which parses identically.
    diff = [(a, b) for a, b in zip(text.splitlines(), out.splitlines(), strict=True) if a != b]
    for before, after in diff:
        code_before, code_after = before.split("#")[0], after.split("#")[0]
        assert (
            "latitude" in before
            or "longitude" in before
            or "endpoint" in before
            or code_before.replace("null", "").split() == code_after.split()
        ), before


# --- mask_config_versions --------------------------------------------------------


def _make_db(path: Path, blobs: list[str]) -> None:
    con = sqlite3.connect(path)
    with con:
        con.execute(
            "CREATE TABLE config_versions (id INTEGER PRIMARY KEY, yaml_blob TEXT NOT NULL,"
            " reason TEXT, applied BOOLEAN)"
        )
        con.execute("CREATE TABLE other (id INTEGER PRIMARY KEY, note TEXT)")
        for i, blob in enumerate(blobs, start=1):
            con.execute(
                "INSERT INTO config_versions VALUES (?, ?, ?, ?)", (i, blob, f"r{i}", i % 2)
            )
        con.execute("INSERT INTO other VALUES (1, 'api_key: keep')")
    con.close()


def _dump_db(path: Path) -> dict[str, list[tuple[object, ...]]]:
    con = sqlite3.connect(path)
    try:
        return {
            t: con.execute(f"SELECT * FROM {t} ORDER BY id").fetchall()
            for t in ("config_versions", "other")
        }
    finally:
        con.close()


def test_mask_config_versions(tmp_path: Path) -> None:
    db = tmp_path / "copy.db"
    blobs = [
        "# c\nlatitude: 55.123\napi_key: abc\nname: x\n",
        "name: only\nvalue: 1\n",
        "a: b: c: [\n",
    ]
    _make_db(db, blobs)
    before = _dump_db(db)

    assert mask_config_versions(db) == 2
    after = _dump_db(db)

    rows = after["config_versions"]
    assert "abc" not in str(rows)
    assert rows[0][1] == "# c\nlatitude: 55.123\napi_key: <redacted>\nname: x\n"
    assert rows[1] == before["config_versions"][1]  # nothing to mask: untouched
    assert rows[2][1] == UNPARSEABLE_CONFIG_VERSION
    assert [r[2:] for r in rows] == [r[2:] for r in before["config_versions"]]
    assert after["other"] == before["other"]

    con = sqlite3.connect(db)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        con.close()


def test_mask_config_versions_without_table(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    assert mask_config_versions(db) == 0
