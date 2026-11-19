"""Static checks on the CI workflow, the local CI gate and docker-compose logging limits."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_compose_services_have_container_log_limits():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for service in ("darkstar", "updater"):
        logging_cfg = compose["services"][service]["logging"]
        assert logging_cfg["driver"] == "json-file"
        assert logging_cfg["options"] == {"max-size": "10m", "max-file": "3"}


def test_frontend_ci_job_runs_typecheck_and_build_in_order():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    runs = [s.get("run") for s in workflow["jobs"]["lint-frontend"]["steps"] if "run" in s]
    order = ["pnpm lint", "pnpm typecheck", "pnpm test", "pnpm build"]
    assert [r for r in runs if r in order] == order


def test_frontend_typecheck_script_defined():
    import json

    pkg = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    assert pkg["scripts"]["typecheck"] == "tsc --noEmit"
