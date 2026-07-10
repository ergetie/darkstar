from __future__ import annotations

import json
import threading

from backend.core import ev_state


def test_read_ev_state_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", tmp_path / "missing.json")
    assert ev_state.read_ev_state() == {}


def test_write_then_read_round_trips(tmp_path, monkeypatch):
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)
    ev_state.write_ev_state({"ev1": {"target_soc_percent": 80}})
    assert ev_state.read_ev_state() == {"ev1": {"target_soc_percent": 80}}
    # Atomic write leaves no temp file behind.
    assert list(tmp_path.glob("*.tmp")) == []


def test_update_ev_state_mutator_persists(tmp_path, monkeypatch):
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    def _mutate(state):
        state["ev1"] = {"target_soc_percent": 90}

    result = ev_state.update_ev_state(_mutate)
    assert result == {"ev1": {"target_soc_percent": 90}}
    assert ev_state.read_ev_state() == {"ev1": {"target_soc_percent": 90}}


def test_concurrent_writers_no_lost_update(tmp_path, monkeypatch):
    """Many concurrent update_ev_state calls each incrementing a counter must
    not lose any update, and the file must always be valid JSON."""
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    ev_state.write_ev_state({"counter": {"n": 0}})

    N_THREADS = 20
    N_INCREMENTS = 25

    def _worker():
        for _ in range(N_INCREMENTS):

            def _mutate(state):
                state["counter"]["n"] += 1

            ev_state.update_ev_state(_mutate)

    threads = [threading.Thread(target=_worker) for _ in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = json.loads(state_file.read_text())
    assert final["counter"]["n"] == N_THREADS * N_INCREMENTS


def test_write_ev_state_failure_does_not_leave_temp_file(tmp_path, monkeypatch):
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    class Unserializable:
        def __repr__(self):
            raise RuntimeError("boom")

    import pytest

    with pytest.raises(Exception):
        ev_state.write_ev_state({"bad": Unserializable()})

    assert list(tmp_path.glob("*.tmp")) == []
