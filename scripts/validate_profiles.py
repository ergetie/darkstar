#!/usr/bin/env python3
"""
validate_profiles.py — Validate Darkstar inverter profile YAML files.

Usage:
    uv run python scripts/validate_profiles.py profiles/your_brand.yaml
    uv run python scripts/validate_profiles.py profiles/           # validate all
    uv run python scripts/validate_profiles.py                     # validate all in profiles/

Exit codes:
    0 — All profiles valid
    1 — One or more validation errors
"""

import sys
from pathlib import Path

# Ensure repo root is on path so executor package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from executor.profiles import (
    PROFILE_STATUSES,
    REQUIRED_MODES,
    VALID_CATEGORIES,
    VALID_DOMAINS,
    VALID_TEMPLATES,
    load_profile,
)


def validate_file(path: Path) -> list[str]:
    """Validate a single profile YAML file. Returns list of error strings."""
    errors: list[str] = []

    try:
        profile = load_profile(path.stem, profiles_dir=path.parent)
    except Exception as e:
        return [f"  ✗ Failed to load: {e}"]

    # 1. Schema version
    if profile.metadata.schema_version != 2:
        errors.append(f"  ✗ schema_version must be 2, got {profile.metadata.schema_version!r}")

    # 2. Required metadata
    if not profile.metadata.name:
        errors.append("  ✗ metadata.name is required")
    elif profile.metadata.name != path.stem:
        errors.append(
            f"  ✗ metadata.name '{profile.metadata.name}' does not match filename '{path.stem}'"
        )

    if not profile.metadata.version:
        errors.append("  ✗ metadata.version is required")

    if not profile.metadata.supported_brands:
        errors.append("  ✗ metadata.supported_brands must list at least one brand")

    if profile.metadata.status not in PROFILE_STATUSES:
        errors.append(
            f"  ✗ metadata.status '{profile.metadata.status}' is invalid "
            f"(valid: {list(PROFILE_STATUSES)})"
        )

    # 3. Required modes
    for mode_name in REQUIRED_MODES:
        if mode_name not in profile.modes:
            errors.append(f"  ✗ Missing required mode: '{mode_name}'")
        else:
            mode = profile.get_mode(mode_name)
            if not mode.description:
                errors.append(f"  ✗ modes.{mode_name}.description is required")
            if not mode.actions:
                errors.append(f"  ✗ modes.{mode_name} has no actions")

    # 4. Entity registry
    if not profile.entities:
        errors.append("  ✗ entities registry is empty — at least one entity required")

    for key, entity in profile.entities.items():
        if entity.domain not in VALID_DOMAINS:
            errors.append(
                f"  ✗ entities.{key}.domain '{entity.domain}' is invalid "
                f"(valid: {sorted(VALID_DOMAINS)})"
            )
        if entity.category not in VALID_CATEGORIES:
            errors.append(
                f"  ✗ entities.{key}.category '{entity.category}' is invalid "
                f"(valid: {sorted(VALID_CATEGORIES)})"
            )
        if not entity.description:
            errors.append(f"  ✗ entities.{key}.description is required")

    # 5. Mode actions reference valid entity keys
    entity_keys = set(profile.entities.keys())
    for mode_name, mode in profile.modes.items():
        for i, action in enumerate(mode.actions):
            if action.entity not in entity_keys:
                errors.append(
                    f"  ✗ modes.{mode_name}.actions[{i}].entity '{action.entity}' "
                    f"not found in entity registry"
                )
            if action.value is None:  # type: ignore[reportUnnecessaryComparison]
                errors.append(f"  ✗ modes.{mode_name}.actions[{i}].value is required")
            # Validate template strings
            if isinstance(action.value, str) and "{{" in action.value:
                template_inner = action.value.strip("{} ")
                if template_inner not in VALID_TEMPLATES:
                    errors.append(
                        f"  ✗ modes.{mode_name}.actions[{i}].value "
                        f"'{action.value}' is not a known template "
                        f"(valid: {sorted(VALID_TEMPLATES)})"
                    )

    # 6. Behavior
    if profile.behavior.control_unit not in ("A", "W"):
        errors.append(
            f"  ✗ behavior.control_unit '{profile.behavior.control_unit}' is invalid (use 'A' or 'W')"
        )

    return errors


def main() -> int:
    """Run validation on the given paths. Returns exit code."""
    args = sys.argv[1:]

    if not args:
        # Default: validate everything in profiles/
        paths = sorted(Path("profiles").glob("*.yaml"))
        paths = [p for p in paths if p.name != "schema.yaml"]
    else:
        paths: list[Path] = []
        for arg in args:
            p = Path(arg)
            if p.is_dir():
                found = sorted(p.glob("*.yaml"))
                paths.extend(x for x in found if x.name != "schema.yaml")
            elif p.is_file():
                if p.name != "schema.yaml":
                    paths.append(p)
            else:
                print(f"[ERROR] Path not found: {arg}", file=sys.stderr)
                return 1

    if not paths:
        print("[ERROR] No profile YAML files found.", file=sys.stderr)
        return 1

    all_ok = True

    for path in paths:
        errors = validate_file(path)
        if errors:
            all_ok = False
            print(f"❌ {path.name}:")
            for err in errors:
                print(err)
        else:
            print(f"✅ {path.name}: OK")

    if all_ok:
        print(f"\n✅ All {len(paths)} profile(s) valid.")
        return 0
    else:
        print("\n❌ Validation failed. See errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
