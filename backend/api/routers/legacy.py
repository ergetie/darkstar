import asyncio
import contextlib
import logging
import sys
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger("darkstar.api.legacy")

router = APIRouter(tags=["legacy"])


@router.post("/api/run_planner")
async def run_planner() -> dict[str, str]:
    """Manually trigger the planner via subprocess (non-blocking)."""

    try:
        # Run synchronous/blocking so the UI waits for completion
        # fast-api will run this in a threadpool if defined as def, but here it is async def
        # so we await the subprocess directly.
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "backend/scheduler.py",
            "--once",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            logger.warning("Planner timed out after 30s")
            return {"status": "error", "message": "Planner timed out after 30s"}

        if proc.returncode != 0:
            err_msg = stderr.decode().strip()
            logger.error(f"Planner failed: {err_msg}")
            return {"status": "error", "message": f"Planner failed: {err_msg}"}

        return {"status": "ok", "message": "Planner completed successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/initial_state")
async def initial_state() -> dict[str, Any]:
    """Bootstrap state for frontend."""
    # Simplified version
    return {"user": {"name": "User"}, "config": {}, "notifications": []}
