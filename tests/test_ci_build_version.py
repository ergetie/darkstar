import os
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / ".github/workflows/build-addon.yml").read_text()
)
DEV_VERSION = "dev-261022.1234"


def build_step(name):
    return next(step for step in WORKFLOW["jobs"]["build"]["steps"] if step.get("name") == name)


@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/heads/dev", "refs/tags/v2.8.0"])
def test_ci_setup_versions(tmp_path, ref):
    """Both architectures consume one version; stable builds retain release metadata."""
    test_job = WORKFLOW["jobs"]["test"]
    assert test_job["outputs"]["dev_version"] == "${{ steps.version.outputs.dev_version }}"
    step = build_step("Setup environment")
    assert step["env"]["DEV_VERSION"] == "${{ needs.test.outputs.dev_version }}"
    (tmp_path / "darkstar-dev").mkdir()
    (tmp_path / "darkstar-dev/config.yaml").write_text('version: "old"\n')
    (tmp_path / "VERSION").write_text("v2.8.0\n")
    output = tmp_path / "output"
    subprocess.run(
        ["bash", "-ec", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "DEV_VERSION": DEV_VERSION,
            "GITHUB_REF": ref,
            "GITHUB_OUTPUT": str(output),
        },
        check=True,
    )
    stable = ref.startswith("refs/tags/")
    assert (tmp_path / "VERSION").read_text().strip() == ("v2.8.0" if stable else DEV_VERSION)
    assert f"version={'2.8.0' if stable else DEV_VERSION}\n" in output.read_text()
    addon = yaml.safe_load((tmp_path / "darkstar-dev/config.yaml").read_text())
    assert addon["version"] == ("old" if stable else DEV_VERSION)


def test_published_version_is_persisted_for_local_builds(tmp_path):
    """Exercise the bump script with Git stubbed to keep the test repository untouched."""
    (tmp_path / "darkstar-dev").mkdir()
    (tmp_path / "darkstar-dev/config.yaml").write_text('version: "old"\n')
    (tmp_path / "VERSION").write_text("v2.7.1-beta\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$GIT_CALLS"\n')
    git.chmod(0o755)
    calls = tmp_path / "git-calls"
    step = build_step("Update Repository Version (Dev only)")
    script = step["run"].replace("${{ github.ref_name }}", "dev")
    script = script.replace("${{ steps.setup.outputs.version }}", DEV_VERSION)
    subprocess.run(
        ["bash", "-ec", script],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GIT_CALLS": str(calls)},
        check=True,
    )
    assert (tmp_path / "VERSION").read_text().strip() == DEV_VERSION
    addon = yaml.safe_load((tmp_path / "darkstar-dev/config.yaml").read_text())
    assert addon["version"] == DEV_VERSION
    assert "add darkstar-dev/config.yaml VERSION" in calls.read_text().splitlines()
