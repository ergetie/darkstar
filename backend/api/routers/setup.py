"""Backend services for guided setup, without controlling hardware."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from backend.core.onboarding_state import (
    NoticeId,
    OnboardingState,
    OnboardingUpdate,
    dismiss_notice,
    read_state,
    write_state,
)

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SensorUnitsRequest(BaseModel):
    """Draft (unsaved) configuration whose power sensors are checked for a missing unit."""

    config: dict[str, Any]


@router.get("/onboarding")
async def get_onboarding() -> OnboardingState:
    return read_state()


@router.put("/onboarding")
async def put_onboarding(body: OnboardingUpdate) -> OnboardingState:
    return write_state(body)


class DismissNoticeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: NoticeId


@router.post("/onboarding/dismissed-notices")
async def post_dismissed_notice(body: DismissNoticeBody) -> OnboardingState:
    return dismiss_notice(body.id)


@router.get("/program-times")
async def get_program_times(soc_target: str | None = None) -> dict[str, Any]:
    """Verify Deye program times for ``soc_target`` (defaults to the saved config)."""
    from backend.core.ha_client import get_ha_entity_state
    from backend.core.program_times import configured_soc_target, verify_program_times
    from backend.core.secrets import load_yaml

    entity = soc_target or configured_soc_target(load_yaml("config.yaml"))
    return await verify_program_times(entity, get_ha_entity_state)


@router.get("/suggestions")
async def get_setup_suggestions(roles: str | None = None) -> dict[str, Any]:
    from backend.core.entity_matcher import build_suggestions, rank_brands
    from backend.core.entity_roles import ROLE_PATHS, ROLE_RULES
    from backend.core.ha_registry import discover_entities
    from backend.core.secrets import load_yaml
    from executor.profiles import get_profile_from_config, list_profiles, load_profile

    selected = (
        list(ROLE_RULES) if roles is None else [x.strip() for x in roles.split(",") if x.strip()]
    )
    if set(selected) - ROLE_RULES.keys():
        raise HTTPException(422, "Unknown entity role")
    config = load_yaml("config.yaml")
    profile = get_profile_from_config(config)
    definitions: dict[str, dict[str, Any]] = {}
    for role in selected:
        rules = {**ROLE_RULES[role], **profile.metadata.role_overrides.get(role, {})}
        if not role.startswith(("ev_", "water_heater_")) and profile.metadata.detect.get(
            "integrations"
        ):
            rules.setdefault("integration", profile.metadata.detect["integrations"])
        definitions[ROLE_PATHS[role]] = {
            "rules": rules,
            "required": role in ("load_power", "battery_soc", "grid_power"),
            "exclude_phase_specific": role == "load_power",
        }
    try:
        discovery = await discover_entities()
    except Exception as exc:
        raise HTTPException(502, "Could not discover Home Assistant entities") from exc
    entities = discovery["entities"]
    brands = rank_brands(entities, [load_profile(p["name"]) for p in list_profiles()])
    return {
        **build_suggestions(config, entities, definitions),
        "brands": brands,
        "suggested_profile": brands[0]["name"] if brands else None,
        "fallback_profile": "generic",
        "registry_available": discovery["registry_available"],
    }


@router.get("/readiness")
async def get_readiness() -> dict[str, Any]:
    from backend.core.readiness import check_readiness
    from backend.core.secrets import load_yaml

    return await check_readiness(load_yaml("config.yaml"))


@router.post("/sensor-units")
async def post_sensor_units(body: SensorUnitsRequest) -> dict[str, Any]:
    """List the draft config's power sensors that need a W or kW choice.

    Reads only the referenced entities' live states from Home Assistant (one request
    each, concurrently). It never runs the planner and saves nothing.
    """
    from backend.core.ha_client import get_ha_entity_state, reported_unit_of
    from backend.core.power_sensors import compute_unit_needed, referenced_power_sensors

    entity_ids = sorted(
        {
            entity_id
            for _, _, entity_id in referenced_power_sensors(
                body.config, unitless_reportable_only=True
            )
        }
    )
    fetched = await asyncio.gather(*(get_ha_entity_state(entity_id) for entity_id in entity_ids))
    states: dict[str, dict[str, Any]] = {}
    for entity_id, state in zip(entity_ids, fetched, strict=True):
        if state:
            states[entity_id] = {
                "state": state.get("state"),
                "unit_of_measurement": reported_unit_of(state),
            }
    return {"unit_needed": compute_unit_needed(body.config, states)}
