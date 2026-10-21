"""Time-current interpolation, heat integration and lifecycle regressions."""

import math
from datetime import datetime, timedelta

import pytest

from executor.config import FuseCustomPoint, LoadBalancingConfig
from executor.fuse_model import DIAZED_GG_POINTS, TYP_C_POINTS, FuseHeatModel, Relief, trip_time_s

T0 = datetime(2026, 1, 1)


def model(**kwargs):
    return FuseHeatModel(LoadBalancingConfig(main_fuse_a=20, **kwargs), 15)


def tick(m, seconds, amps=30, phase=1, stale=False):
    return m.relief_needed(phase, amps, T0 + timedelta(seconds=seconds), stale)


@pytest.mark.parametrize("multiple,seconds", TYP_C_POINTS)
def test_typ_c_anchors(multiple, seconds):
    assert trip_time_s(multiple) == pytest.approx(seconds)


@pytest.mark.parametrize("multiple,seconds", DIAZED_GG_POINTS)
def test_diazed_anchors(multiple, seconds):
    assert trip_time_s(multiple, DIAZED_GG_POINTS, instantaneous=False) == pytest.approx(seconds)


def test_worst_phase_has_independent_heat_and_relief():
    m = model()
    for second in (0, 60, 120, 180, 240):
        cool_relief = tick(m, second, 21, phase=1)
        hot_relief = tick(m, second, 30, phase=3)
    assert cool_relief == Relief()
    assert hot_relief == Relief(13, False)
    assert m.heat(1) == 0
    assert m.heat(3) == pytest.approx(0.8)
    assert m.cooled([1, 2])
    assert not m.cooled([1, 2, 3])


def test_interpolation_and_extensions():
    assert trip_time_s(math.sqrt(1.5 * 2)) == pytest.approx(math.sqrt(300 * 30))
    assert trip_time_s(1.05) == math.inf
    assert trip_time_s(10) == 0.1
    assert trip_time_s(8, DIAZED_GG_POINTS, instantaneous=False) < 10


def test_build_hold_cool_and_repeat():
    m = model()
    tick(m, 0)
    tick(m, 100)
    tick(m, 150)
    assert m.heat(1) == pytest.approx(0.5)
    tick(m, 200, 21)
    assert m.heat(1) == pytest.approx(0.5)
    tick(m, 250, 19)
    assert m.heat(1) == pytest.approx(1 / 3)
    tick(m, 350)
    assert m.heat(1) == pytest.approx(2 / 3)
    relief = tick(m, 400)
    assert relief == Relief(13, False)
    assert m.heat(1) >= 0.8
    assert not m.cooled([1]) and m.cooled([2, 3])
    tick(m, 500, 17)
    assert m.heat(1) == pytest.approx(0.5)
    tick(m, 501, 17)
    assert m.cooled([1])


def test_below_curve_never_builds():
    m = model()
    for second in range(0, 3601, 100):
        assert tick(m, second, 21) == Relief()
    assert m.heat(1) == 0


def test_urgent_floor_requires_real_cooling():
    m = model()
    relief = tick(m, 0, 60)
    assert relief == Relief(43, True)
    assert m.heat(1) == 0.8
    assert not m.cooled([1])
    tick(m, 1, 17)
    assert not m.cooled([1])
    tick(m, 2, 17)
    assert m.cooled([1])


def test_stale_freeze_and_gap_guard():
    m = model()
    tick(m, 0)
    tick(m, 100)
    heat = m.heat(1)
    assert tick(m, 110, 100, stale=True) == Relief()
    tick(m, 200, 17, stale=True)
    tick(m, 210, 17)
    assert m.heat(1) == heat
    tick(m, 400, 17)
    assert m.heat(1) == heat
    tick(m, 410, 17)
    assert m.heat(1) < heat


def test_configured_interval_sets_gap_guard_and_urgent():
    m = FuseHeatModel(LoadBalancingConfig(main_fuse_a=20), 300)
    tick(m, 0)
    assert tick(m, 150).urgent
    tick(m, 450, 17)
    assert m.heat(1) < 0.5
    m.reset()
    tick(m, 0, 21)
    tick(m, 601, 30)
    assert m.heat(1) == 0.8  # gap holds; urgent floor still applies


def test_custom_curve_and_safety_defaults():
    m = model(
        fuse_preset="custom",
        fuse_custom_points=[FuseCustomPoint(130, 1200), FuseCustomPoint(300, 4)],
    )
    assert trip_time_s(3, m.points, instantaneous=False) == pytest.approx(4)
    assert trip_time_s(6, m.points, instantaneous=False) < 4
    assert model(fuse_preset="diazed_gg").safety_percent == 65
    assert model(fuse_preset="diazed_gg", fuse_safety_percent=70).safety_percent == 70


def test_lifecycle_signature_resets_curve_not_threshold():
    m = model()
    tick(m, 0, 60)
    assert model().heat(1) == 0
    cfg = LoadBalancingConfig(main_fuse_a=20, fuse_safety_percent=90)
    m.configure(cfg, 10)
    assert m.heat(1) == 0.8
    cfg = LoadBalancingConfig(main_fuse_a=16)
    m.configure(cfg, 10)
    assert m.heat(1) == 0
    tick(m, 0, 60)
    m.configure(LoadBalancingConfig(main_fuse_a=16, fuse_preset="custom"), 10)
    assert m.heat(1) == 0
    tick(m, 0, 60)
    m.configure(
        LoadBalancingConfig(
            main_fuse_a=16,
            fuse_preset="custom",
            fuse_custom_points=[FuseCustomPoint(140, 100), FuseCustomPoint(300, 3)],
        ),
        10,
    )
    assert m.heat(1) == 0


def test_heat_state_tracks_actual_changes_and_resets():
    m = model()
    assert m.heat_state(1) == "unavailable"
    tick(m, 0)
    assert m.heat_state(1) == "cold"  # no interval has been integrated
    tick(m, 100)
    assert m.heat_state(1) == "heating"
    tick(m, 110, 21)
    assert m.heat_state(1) == "holding"  # under first anchor, but not below rating
    tick(m, 120, 19)
    assert m.heat_state(1) == "cooling"
    tick(m, 220, 19)
    assert m.heat(1) == 0
    assert m.heat_state(1) == "cooling"  # this sample actually reached zero
    tick(m, 230, 19)
    assert m.heat_state(1) == "cold"
    tick(m, 240, 60)
    assert m.heat_state(1) == "heating"  # urgent floor counts as a model heat increase
    m.configure(LoadBalancingConfig(main_fuse_a=16), 15)
    assert m.heat_state(1) == "unavailable"


def test_heat_state_stale_recovery_and_gap_hold_instead_of_claiming_cooling():
    m = model()
    tick(m, 0)
    tick(m, 100)
    heat = m.heat(1)
    tick(m, 110, 17, stale=True)
    assert m.heat_state(1) == "stale"
    assert m.heat(1) == heat
    tick(m, 120, 17)
    assert m.heat_state(1) == "holding"
    tick(m, 300, 17)
    assert m.heat_state(1) == "holding"
    assert m.heat(1) == heat
    tick(m, 310, 17)
    assert m.heat_state(1) == "cooling"
    tick(m, 320, float("nan"))
    assert m.heat_state(1) == "unavailable"
    m.reset()
    assert m.heat_state(1) == "unavailable"


def test_heat_state_unconfigured_rating_is_unavailable():
    m = FuseHeatModel(LoadBalancingConfig(main_fuse_a=None), 15)
    tick(m, 0)
    assert m.heat_state(1) == "unavailable"
