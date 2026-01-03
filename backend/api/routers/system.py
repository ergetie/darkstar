import subprocess

import yaml
from fastapi import APIRouter

router = APIRouter(tags=["system"])


def _get_git_version() -> str:
    """Get version from git tags, falling back to darkstar/config.yaml."""
    try:
        return (
            subprocess.check_output(
                ["git", "describe", "--tags", "--always", "--dirty"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        pass

    # Fallback: read from darkstar/config.yaml (add-on version)
    try:
        with open("darkstar/config.yaml") as f:
            addon_config = yaml.safe_load(f)
        if addon_config and addon_config.get("version"):
            return addon_config["version"]
    except Exception:
        pass

    return "dev"


@router.get("/api/version")
async def get_version():
    """Return the current system version."""
    return {"version": _get_git_version()}
