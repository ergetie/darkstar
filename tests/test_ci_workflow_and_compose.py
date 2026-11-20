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


def test_e2e_smoke_ci_job_installs_chromium_and_runs_e2e_script():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["e2e-smoke"]["steps"]
    runs = [s["run"] for s in steps if "run" in s]
    install = "pnpm exec playwright install --with-deps chromium"
    assert [r for r in runs if r in (install, "pnpm test:e2e")] == [install, "pnpm test:e2e"]
    assert any(
        s.get("if") == "failure()" and "playwright-report" in s["with"]["path"] for s in steps
    )


def test_e2e_script_is_separate_from_vitest_run():
    import json

    pkg = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    assert pkg["scripts"]["test:e2e"] == "pnpm build && playwright test"
    assert pkg["devDependencies"]["@playwright/test"] == "1.64.0"
    vitest_config = (ROOT / "frontend/vitest.config.ts").read_text(encoding="utf-8")
    assert "include: ['src/**/*.test.{ts,tsx}']" in vitest_config
