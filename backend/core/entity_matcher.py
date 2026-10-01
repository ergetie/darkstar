"""Independent weighted matching for profile entities and shared setup roles."""

import re
from typing import Any, cast

WEIGHTS = {
    "integration": 40,
    "device_class": 20,
    "unit": 15,
    "entity_id_regex": 15,
    "name_regex": 10,
    "default_entity": 50,
    "lifetime": 10,
    "daily": -15,
}
MIN_SCORE = 25


def rank_candidates(
    entities: list[dict[str, Any]],
    rules: dict[str, Any],
    *,
    default_entity: str | None = None,
    cumulative: bool = False,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for entity in entities:
        if entity.get("domain") not in rules.get("domain", []):
            continue
        if cumulative and (
            entity.get("device_class") != "energy"
            or entity.get("unit_of_measurement") not in ("kWh", "Wh", "MWh")
            or entity.get("state_class") not in ("total", "total_increasing")
        ):
            continue
        score = 0
        reasons: list[str] = []
        for rule, attribute in (
            ("integration", "platform"),
            ("device_class", "device_class"),
            ("unit", "unit_of_measurement"),
        ):
            if entity.get(attribute) is not None and entity[attribute] in rules.get(rule, []):
                score += WEIGHTS[rule]
                reasons.append(rule)
        for rule, attribute in (("entity_id_regex", "entity_id"), ("name_regex", "friendly_name")):
            if rules.get(rule) and re.search(
                rules[rule], str(entity.get(attribute) or ""), re.IGNORECASE
            ):
                score += WEIGHTS[rule]
                reasons.append(rule)
        if default_entity and entity.get("entity_id") == default_entity:
            score += WEIGHTS["default_entity"]
            reasons.append("default_entity")
        if cumulative:
            name = f"{entity.get('entity_id', '')} {entity.get('friendly_name', '')}"
            for rule, pattern in (("lifetime", r"total|lifetime"), ("daily", r"today|daily")):
                if re.search(pattern, name, re.IGNORECASE):
                    score += WEIGHTS[rule]
                    reasons.append(rule)
        if score >= MIN_SCORE:
            candidates.append(
                {"entity_id": entity["entity_id"], "score": score, "reasons": reasons}
            )
    candidates.sort(key=lambda item: (-item["score"], item["entity_id"]))
    for index, candidate in enumerate(candidates):
        competitor = max(
            (other["score"] for i, other in enumerate(candidates) if i != index), default=0
        )
        candidate["confidence"] = (
            "high"
            if candidate["score"] >= 70 and candidate["score"] - competitor >= 20
            else "medium"
            if candidate["score"] >= 50
            else "low"
        )
    return candidates[:5]


def rank_brands(entities: list[dict[str, Any]], profiles: list[Any]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for profile in profiles:
        detect = profile.metadata.detect
        integrations = {str(x).casefold() for x in detect.get("integrations", [])}
        manufacturers = {str(x).casefold() for x in detect.get("manufacturers", [])}
        reasons: list[str] = []
        if any(str(e.get("platform") or "").casefold() in integrations for e in entities):
            reasons.append("integration")
        if any(str(e.get("manufacturer") or "").casefold() in manufacturers for e in entities):
            reasons.append("manufacturer")
        if reasons:
            ranked.append(
                {"name": profile.metadata.name, "score": 40 * len(reasons), "reasons": reasons}
            )
    ranked.sort(key=lambda item: (-item["score"], item["name"]))
    for index, item in enumerate(ranked):
        competitor = max(
            (other["score"] for i, other in enumerate(ranked) if i != index), default=0
        )
        item["confidence"] = "high" if item["score"] - competitor >= 20 else "medium"
    return ranked


def value_at_path(config: dict[str, Any], path: str) -> Any:
    value: Any = config
    for part in path.split("."):
        if isinstance(value, dict):
            value = cast("dict[str, Any]", value).get(part)
        elif (
            isinstance(value, list) and part.isdigit() and int(part) < len(cast("list[Any]", value))
        ):
            value = cast("list[Any]", value)[int(part)]
        else:
            return None
    return value


def set_patch_path(patch: dict[str, Any], path: str, value: str) -> None:
    parts = path.split(".")
    node: Any = patch
    for index, part in enumerate(parts[:-1]):
        next_is_list = parts[index + 1].isdigit()
        if isinstance(node, list):
            while len(cast("list[Any]", node)) <= int(part):
                cast("list[Any]", node).append({})
            node = cast("list[Any]", node)[int(part)]
        else:
            node = cast("dict[str, Any]", node).setdefault(part, [] if next_is_list else {})
    if isinstance(node, list):
        while len(cast("list[Any]", node)) <= int(parts[-1]):
            cast("list[Any]", node).append(None)
        node[int(parts[-1])] = value
    else:
        node[parts[-1]] = value


def build_suggestions(
    config: dict[str, Any], entities: list[dict[str, Any]], definitions: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    candidates: dict[str, list[dict[str, Any]]] = {}
    current: dict[str, Any] = {}
    missing: list[str] = []
    for path, definition in definitions.items():
        ranked = rank_candidates(
            entities,
            definition["rules"],
            default_entity=definition.get("default_entity"),
            cumulative=definition.get("cumulative", False),
        )
        candidates[path], current[path] = ranked, value_at_path(config, path)
        if ranked and ranked[0]["confidence"] == "high":
            set_patch_path(patch, path, ranked[0]["entity_id"])
        if definition.get("required") and not ranked:
            missing.append(path)
    return {
        "patch": patch,
        "candidates": candidates,
        "current": current,
        "missing_required": missing,
    }
