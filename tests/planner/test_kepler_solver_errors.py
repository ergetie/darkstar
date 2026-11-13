"""Tests for PlannerError raised by Kepler on solver failure or invalid schedule."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from planner.errors import PlannerError, PlannerErrorCode
from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot


def _make_slots(n: int = 4) -> list[KeplerInputSlot]:
    start = datetime(2025, 6, 1, 10, 0)
    return [
        KeplerInputSlot(
            start_time=start + timedelta(hours=i),
            end_time=start + timedelta(hours=i + 1),
            load_kwh=0.5,
            pv_kwh=0.0,
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=0.5,
        )
        for i in range(n)
    ]


def _base_config() -> KeplerConfig:
    return KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=10.0,
        max_soc_percent=90.0,
        wear_cost_sek_per_kwh=0.01,
    )


def test_solver_infeasible_raises_planner_error():
    """When the solver returns Infeasible, KeplerSolver raises SOLVER_INFEASIBLE."""
    import pulp

    config = _base_config()
    input_data = KeplerInput(slots=_make_slots(2), initial_soc_kwh=5.0)

    # Patch prob.solve so it sets the infeasible status without running the LP
    solver = KeplerSolver()
    original_solve = solver.solve

    with patch("planner.solver.kepler.pulp.LpProblem.solve") as mock_solve:

        def fake_solve(self_or_cmd, *args, **kwargs):
            # If called as instance method the first arg is the solver cmd
            pass

        import pulp as _pulp

        with patch.object(_pulp.LpProblem, "solve") as mock_prob_solve:

            def set_infeasible(solver_cmd=None, **kw):
                return None  # will be called on prob

            # Instead, directly patch the prob.status after solve
            with patch(
                "planner.solver.kepler.pulp.LpStatus",
                {-1: "Infeasible", 1: "Optimal", 0: "Not Solved", -2: "Undefined"},
            ):
                with patch("planner.solver.kepler.pulp.constants.LpStatusInfeasible", -1):
                    # Patch prob so it returns infeasible
                    class FakeProb:
                        status = -1

                        def solve(self, *a, **kw):
                            pass

                        def __iadd__(self, expr):
                            return self

                        def writeLP(self, *a):
                            pass

                        def variables(self):
                            return []

                        @property
                        def constraints(self):
                            return {}

                    with patch("planner.solver.kepler.pulp.LpProblem", return_value=FakeProb()):
                        with pytest.raises(PlannerError) as exc:
                            original_solve(input_data, config)

    assert exc.value.code == PlannerErrorCode.SOLVER_INFEASIBLE
    assert "solver_status" in exc.value.details


def test_invalid_schedule_diagnostics():
    """INVALID_SCHEDULE error carries all four required diagnostic keys."""
    from planner.errors import PlannerError, PlannerErrorCode

    err = PlannerError(
        code=PlannerErrorCode.INVALID_SCHEDULE,
        details={
            "solver_status": "Optimal",
            "initial_soc_kwh": 5.0,
            "max_soc_kwh": 9.0,
            "capacity_kwh": 10.0,
        },
    )
    assert err.code == PlannerErrorCode.INVALID_SCHEDULE
    assert "solver_status" in err.details
    assert "initial_soc_kwh" in err.details
    assert "max_soc_kwh" in err.details
    assert "capacity_kwh" in err.details
