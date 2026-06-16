from pathlib import Path


def test_production_entrypoint_does_not_launch_standalone_recorder():
    """Spec: Single Live Recorder Instance - entrypoint relies on in-process recorder."""
    entrypoint = Path("scripts/docker-entrypoint.sh").read_text(encoding="utf-8")

    assert "python -m backend.recorder" not in entrypoint
    assert "[RECORDER]" not in entrypoint
    assert entrypoint.count("uvicorn backend.main:app") == 1
