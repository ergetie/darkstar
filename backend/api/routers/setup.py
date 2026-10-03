"""Backend services for guided setup, without controlling hardware."""

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.core.onboarding_state import OnboardingState, OnboardingUpdate, read_state, write_state

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/onboarding")
async def get_onboarding() -> OnboardingState:
    return read_state()


@router.put("/onboarding")
async def put_onboarding(body: OnboardingUpdate) -> OnboardingState:
    return write_state(body)


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
