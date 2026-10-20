from app.motion import MotionPlanner


def test_360_stop_requires_long_reverse_path():
    planner = MotionPlanner(current_angle_deg=350, rotation_span_deg=360, stop_point_deg=0)
    plan = planner.plan(10)
    assert plan.accepted
    assert plan.direction == "ccw"
    assert plan.distance_deg == 340


def test_450_span_uses_overlap():
    planner = MotionPlanner(current_angle_deg=350, rotation_span_deg=450, stop_point_deg=0)
    plan = planner.plan(10)
    assert plan.accepted
    assert plan.direction == "cw"
    assert plan.distance_deg == 20


def test_power_cycle_offset_restore_and_calibration():
    planner = MotionPlanner(last_true_azimuth_deg=123)
    assert planner.restore_from_power_cycle(0, 123)
    assert planner.true_azimuth_deg == 123
    planner.set_hardware_coord(20)
    planner.calibrate_current(200)
    assert planner.true_azimuth_deg == 200


def test_first_connection_restores_saved_angle():
    planner = MotionPlanner(hardware_coord_deg=0, last_true_azimuth_deg=123)
    assert planner.on_first_connection(0)
    assert planner.software_offset_deg == 123
    assert planner.true_azimuth_deg == 123


def test_no_equivalent_target_outside_interval():
    planner = MotionPlanner(current_angle_deg=0, rotation_span_deg=90, stop_point_deg=100)
    assert not planner.plan(250).accepted


def test_span_is_limited_to_supported_450_degrees():
    import pytest

    with pytest.raises(ValueError):
        MotionPlanner(rotation_span_deg=451)

