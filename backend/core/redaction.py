"""Redaction of text that leaves the system in a diagnostics bundle or log download.

``redact_text`` removes what identifies the installation or grants access: URL
credentials, paths and queries, token-like values, public hosts and IPv4 addresses
and numeric coordinates. Private addresses, local names, known public services,
entity ids and prices stay readable so the output remains useful for debugging.
"""

import io
import ipaddress
import re
import sqlite3
from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from backend.core.exception_text import mask_secret_params, scrub_urls

REDACTED = "<redacted>"
REDACTED_HOST = "<redacted-host>"
REDACTED_IP = "<redacted-ip>"
UNPARSEABLE_CONFIG_VERSION = "<unparseable config version redacted>"

# Public services Darkstar itself talks to. A host equal to one of these, or a
# subdomain of it, is kept.
_ALLOWED_HOSTS = frozenset(
    {
        "api.open-meteo.com",
        "historical-forecast-api.open-meteo.com",
        "archive-api.open-meteo.com",
        "telemetry.wxl.se",
        "openrouter.ai",
        "github.com",
        "discord.com",
        "discordapp.com",
    }
)
_LOCAL_SUFFIXES = (".local", ".internal", ".localhost")

# A URL as it appears in plain text or inside a JSON string: ``\/`` (one or more
# backslashes before a slash) and ``\uXXXX`` are part of the URL, while a bare
# backslash (the one before an escaped quote) ends it.
_URL_RE = re.compile(
    r"\b(?:https?|wss?):(?:\\*/){2}(?:\\+/|\\u[0-9a-fA-F]{4}|[^\s<>\"'`\\])+",
    re.IGNORECASE,
)
_ESCAPED_SLASH_RE = re.compile(r"(\\+)/")
_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
_URL_HOST_RE = re.compile(r"^(?P<scheme>[a-z]+://)(?P<host>\[[^\]]*\]|[^/?#:\s]*)", re.IGNORECASE)

# Bare IPv4: four dot-separated octets, not glued to other word characters or to a
# further ``.digit`` group (so ``1.2.3.4.5`` is not an address).
#
# A valid public quad such as ``1.2.3.4`` cannot be told apart from a four-part
# version string by shape alone. Decision: redact it (the safe side for a bundle
# posted publicly), except when an explicit version marker (``v``, ``version``,
# ``==``, ``>=``, ...) directly precedes it. Octets above 255 and octets with
# leading zeros are not addresses and are left alone. Non-global addresses
# (private, loopback, link-local, CGNAT, documentation) stay readable.
_IPV4_RE = re.compile(r"(?<![\w.])(?P<ip>(?:\d{1,3}\.){3}\d{1,3})(?![\w]|\.\d)")
_VERSION_CONTEXT_RE = re.compile(
    r"(?:\bv|\bver|\bversion|==|>=|<=|~=|!=|\bsince|\bbuild)\s*[:=]?\s*$", re.I
)

# Latitude/longitude assigned a decimal number, in plain text, JSON (also escaped
# quotes), YAML, key=value or Python repr form. Integers are left alone.
_COORDINATE_RE = re.compile(
    r"(?P<key>\b(?:latitude|longitude|lat|lon|lng)\b(?:\\*[\"'])?\s*[:=]\s*(?:\\*[\"'])?)"
    r"-?\d+\.\d+",
    re.IGNORECASE,
)

# A JSON object key (closing quote, possibly escaped) followed by ``:`` with an unquoted
# value. The replacement must itself be a JSON string to keep the document valid.
_JSON_BARE_VALUE_RE = re.compile(r"(?P<esc>\\*)\"\s*:\s*$")


def _redact_coordinate(match: re.Match[str]) -> str:
    key = match.group("key")
    quoted = _JSON_BARE_VALUE_RE.search(key)
    if quoted is not None:
        # ``\"`` marks a JSON document nested in a string: quote with the same escaping.
        quote = quoted.group("esc") + '"'
        return f"{key}{quote}{REDACTED}{quote}"
    return f"{key}{REDACTED}"


def _is_kept_host(host: str) -> bool:
    """True when ``host`` is loopback, private/local, a single-label name or an allowed service."""
    bare = host.strip("[]").rstrip(".").lower()
    if not bare:
        return True
    try:
        return not ipaddress.ip_address(bare.split("%", 1)[0]).is_global
    except ValueError:
        pass
    if "." not in bare or bare.endswith(_LOCAL_SUFFIXES):
        return True
    return any(bare == allowed or bare.endswith("." + allowed) for allowed in _ALLOWED_HOSTS)


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    escape = _ESCAPED_SLASH_RE.search(raw)
    plain = _ESCAPED_SLASH_RE.sub("/", raw)
    plain = _UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), plain)

    result = scrub_urls(plain)
    parts = _URL_HOST_RE.match(result)
    if parts is not None and not _is_kept_host(parts.group("host")):
        result = result[: parts.start("host")] + REDACTED_HOST + result[parts.end("host") :]

    if escape is not None:
        result = result.replace("/", escape.group(1) + "/")
    return result


def _redact_ip(match: re.Match[str]) -> str:
    text = match.string
    if _VERSION_CONTEXT_RE.search(text[max(0, match.start() - 12) : match.start()]):
        return match.group(0)
    octets = match.group("ip").split(".")
    if any(int(o) > 255 or (len(o) > 1 and o.startswith("0")) for o in octets):
        return match.group(0)
    if not ipaddress.IPv4Address(match.group("ip")).is_global:
        return match.group(0)
    return REDACTED_IP


def redact_text(text: str) -> str:
    """Return ``text`` with identifying and secret-bearing values removed.

    Applies, in order: URL reduction (credentials, path, query) with masking of hosts
    that are not private, local or known public services; ``token=``/bearer masking;
    public IPv4 addresses; numeric latitude/longitude values (``"latitude": 1.5`` becomes
    ``"latitude": "<redacted>"`` so JSON documents stay valid). Idempotent, and safe on
    JSON-escaped lines (``http:\\/\\/host``, ``\\"``), which keep their escaping.
    """
    text = _URL_RE.sub(_redact_url, text)
    text = mask_secret_params(text)
    text = _IPV4_RE.sub(_redact_ip, text)
    return _COORDINATE_RE.sub(_redact_coordinate, text)


# --- Config redaction -------------------------------------------------------------

# Single source of the secret-key rule, shared by ``redact_config`` and
# ``mask_config_versions``.
_SECRET_KEY_RE = re.compile(
    r"token|secret|password|passwd|api_?key|webhook|credential|authorization|bearer|private_?key",
    re.IGNORECASE,
)
_COORDINATE_KEYS = frozenset({"latitude", "longitude", "lat", "lon", "lng"})


class RedactionError(Exception):
    """Raised when content cannot be redacted safely (for example unparseable YAML)."""


def is_secret_key(key: object) -> bool:
    """True when a config key name denotes a secret (matched at any depth)."""
    return _SECRET_KEY_RE.search(str(key)) is not None


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value
    if isinstance(value, (list, dict, tuple)):
        return len(cast("list[Any]", value)) == 0
    return False


def _new_yaml() -> YAML:
    yaml = YAML()  # round-trip: keeps comments and key order
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _redact_node(node: Any, *, full: bool, seen: set[int] | None = None) -> bool:
    """Redact ``node`` in place and return True when anything changed.

    ``full=False`` applies only the secret-key rule (stored config versions);
    ``full=True`` also rounds coordinates and passes strings through ``redact_text``.
    """
    seen = set() if seen is None else seen
    if id(node) in seen:  # YAML anchors/aliases may share nodes
        return False
    if isinstance(node, dict):
        mapping = cast("dict[Any, Any]", node)
        seen.add(id(mapping))
        changed = False
        for key in list(mapping.keys()):
            value: Any = mapping[key]
            if is_secret_key(key):
                if not _is_empty(value) and value != REDACTED:
                    mapping[key] = REDACTED
                    changed = True
                continue
            if (
                full
                and str(key).lower() in _COORDINATE_KEYS
                and isinstance(value, float)
                and round(value, 1) != value
            ):
                mapping[key] = round(float(value), 1)
                changed = True
            elif isinstance(value, str):
                if full and (new := redact_text(value)) != value:
                    mapping[key] = new
                    changed = True
            elif _redact_node(value, full=full, seen=seen):
                changed = True
        return changed
    if isinstance(node, list):
        items = cast("list[Any]", node)
        seen.add(id(items))
        changed = False
        for index, item in enumerate(items):
            if isinstance(item, str):
                if full and (new := redact_text(item)) != item:
                    items[index] = new
                    changed = True
            elif _redact_node(item, full=full, seen=seen):
                changed = True
        return changed
    return False


def _dump(yaml: YAML, data: Any) -> str:
    buffer = io.StringIO()
    cast("Any", yaml).dump(data, buffer)
    return buffer.getvalue()


def redact_config(yaml_text: str) -> str:
    """Return ``yaml_text`` with secrets, coordinates and identifying URLs redacted.

    Comments and key order are kept. Keys matching the shared secret rule become
    ``<redacted>`` when non-empty (empty stays empty); ``latitude``/``longitude``
    are rounded to one decimal; string values go through ``redact_text``. When
    nothing needs redacting the input is returned unchanged, byte for byte.

    Raises:
        RedactionError: the text is not parseable YAML. Never falls back to the raw text.
    """
    yaml = _new_yaml()
    try:
        data: Any = cast("Any", yaml).load(yaml_text)
    except (YAMLError, ValueError) as exc:
        raise RedactionError("config is not valid YAML") from exc
    if not _redact_node(data, full=True):
        return yaml_text
    try:
        return _dump(yaml, data)
    except (YAMLError, ValueError) as exc:
        raise RedactionError("config could not be serialised") from exc


def _mask_blob(blob: str) -> str:
    """Apply the secret-key rule to one stored config version."""
    yaml = _new_yaml()
    try:
        data: Any = cast("Any", yaml).load(blob)
        if not _redact_node(data, full=False):
            return blob
        return _dump(yaml, data)
    except (YAMLError, ValueError):
        return UNPARSEABLE_CONFIG_VERSION


def mask_config_versions(db_copy_path: str | Path) -> int:
    """Mask secrets in ``config_versions.yaml_blob`` of a database *copy*.

    Only that column is rewritten, using the secret-key rule of ``redact_config``;
    a blob that cannot be parsed is replaced by a placeholder. Other columns and
    tables are untouched. Must only be called on a snapshot copy, never on the live
    database. Returns the number of rows rewritten (0 when the table is absent).
    """
    connection = sqlite3.connect(str(db_copy_path))
    try:
        has_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='config_versions'"
        ).fetchone()
        if has_table is None:
            return 0
        rows = connection.execute("SELECT id, yaml_blob FROM config_versions").fetchall()
        updates: list[tuple[str, int]] = []
        for row_id, blob in rows:
            if not isinstance(blob, str):
                continue
            masked = _mask_blob(blob)
            if masked != blob:
                updates.append((masked, row_id))
        with connection:
            connection.executemany("UPDATE config_versions SET yaml_blob = ? WHERE id = ?", updates)
        return len(updates)
    finally:
        connection.close()
