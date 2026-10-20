"""Pure motion planning and angle bookkeeping."""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import math
import threading
from typing import Any, Callable


def _synchronized(method: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(method)
    def guarded(self: "MotionPlanner", *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return guarded


def normalize_angle(degrees: float) -> float:
    value = float(degrees) % 360.0
    return 0.0 if math.isclose(value, 360.0, abs_tol=1e-9) else value


def signed_angle(degrees: float) -> float:
    value = normalize_angle(degrees)
    return value - 360.0 if value > 180.0 else value


@dataclass(frozen=True)
class MotionPlan:
    accepted: bool
    current_deg: float
    requested_deg: float
    target_continuous_deg: float | None
    delta_deg: float
    direction: str
    distance_deg: float
    reason: str = ""


class MotionPlanner:
    """Plan legal shortest paths within a hard mechanical stop interval."""

    def __init__(
        self,
        hardware_coord_deg: float = 0.0,
        software_offset_deg: float = 0.0,
        rotation_span_deg: float = 360.0,
        stop_point_deg: float = 0.0,
        last_true_azimuth_deg: float = 0.0,
        current_angle_deg: float | None = None,
    ) -> None:
        self._lock = threading.RLock()
        if current_angle_deg is not None:
            hardware_coord_deg = current_angle_deg
        self.rotation_span_deg = float(rotation_span_deg)
        self.stop_point_deg = float(stop_point_deg)
        self.hardware_coord_deg = float(hardware_coord_deg)
        self.software_offset_deg = float(software_offset_deg)
        self.last_true_azimuth_deg = float(last_true_azimuth_deg)
        self.continuous_mechanical_deg = float(hardware_coord_deg)
        self.first_connection = True
        self.motion_running = False
        self._validate_limits()
        self.continuous_mechanical_deg = self._equivalent_in_boundary(self.continuous_mechanical_deg)

    def _validate_limits(self) -> None:
        if not 0.0 < self.rotation_span_deg <= 450.0:
            raise ValueError("rotation_span_deg must be within (0, 450]")

    @property
    @_synchronized
    def true_azimuth_deg(self) -> float:
        return normalize_angle(self.hardware_coord_deg + self.software_offset_deg)

    @property
    @_synchronized
    def display_angle_deg(self) -> float:
        return self.true_azimuth_deg

    @property
    @_synchronized
    def boundary_low_deg(self) -> float:
        return self.stop_point_deg

    @property
    @_synchronized
    def boundary_high_deg(self) -> float:
        return self.stop_point_deg + self.rotation_span_deg

    @_synchronized
    def set_limits(self, rotation_span_deg: float, stop_point_deg: float) -> None:
        self.rotation_span_deg = float(rotation_span_deg)
        self.stop_point_deg = float(stop_point_deg)
        self._validate_limits()

    @_synchronized
    def set_hardware_coord(self, hardware_coord_deg: float, *, continuous: float | None = None) -> None:
        self.hardware_coord_deg = float(hardware_coord_deg)
        if continuous is not None:
            self.continuous_mechanical_deg = float(continuous)
        else:
            # Telemetry may expose an overrun (for example 361 degrees). Keep
            # raw continuous value so hard-stop checks can reject it.
            raw = float(hardware_coord_deg)
            self.continuous_mechanical_deg = self._equivalent_in_boundary(raw) if 0.0 <= raw <= 360.0 else raw

    @_synchronized
    def _equivalent_in_boundary(self, value: float) -> float:
        candidates = [value + 360.0 * turn for turn in range(-4, 5)]
        legal = [candidate for candidate in candidates if self.boundary_low_deg - 1e-7 <= candidate <= self.boundary_high_deg + 1e-7]
        if not legal:
            return value
        return min(legal, key=lambda candidate: abs(candidate - self.continuous_mechanical_deg))

    @_synchronized
    def update_telemetry(self, hardware_coord_deg: float) -> bool:
        """Update telemetry. Return whether current position stays legal."""

        self.set_hardware_coord(hardware_coord_deg)
        return self.is_position_legal(self.continuous_mechanical_deg)

    @_synchronized
    def restore_from_power_cycle(
        self,
        hardware_coord_deg: float,
        last_true_azimuth_deg: float | None = None,
        tolerance_deg: float = 2.0,
    ) -> bool:
        """Restore offset when controller reset hardware coordinate to zero."""

        previous = self.last_true_azimuth_deg if last_true_azimuth_deg is None else float(last_true_azimuth_deg)
        self.set_hardware_coord(hardware_coord_deg)
        restored = abs(signed_angle(hardware_coord_deg)) <= tolerance_deg and abs(normalize_angle(previous)) > tolerance_deg
        if restored:
            self.software_offset_deg = previous - float(hardware_coord_deg)
        self.first_connection = False
        self.last_true_azimuth_deg = previous
        return restored

    @_synchronized
    def on_first_connection(self, hardware_coord_deg: float, last_true_azimuth_deg: float | None = None) -> bool:
        if not self.first_connection:
            self.set_hardware_coord(hardware_coord_deg)
            return False
        return self.restore_from_power_cycle(hardware_coord_deg, last_true_azimuth_deg)

    @_synchronized
    def calibrate_current(self, true_azimuth_deg: float) -> float:
        self.software_offset_deg = float(true_azimuth_deg) - self.hardware_coord_deg
        self.last_true_azimuth_deg = normalize_angle(true_azimuth_deg)
        return self.software_offset_deg

    @_synchronized
    def set_current_true_angle(self, true_azimuth_deg: float) -> float:
        return self.calibrate_current(true_azimuth_deg)

    @_synchronized
    def set_current_angle(self, hardware_coord_deg: float) -> None:
        self.set_hardware_coord(hardware_coord_deg)

    @_synchronized
    def get_display_angle(self) -> float:
        return self.display_angle_deg

    @property
    @_synchronized
    def true_azimuth(self) -> float:
        return self.true_azimuth_deg

    @_synchronized
    def is_position_legal(self, continuous_deg: float | None = None, tolerance_deg: float = 1e-7) -> bool:
        value = self.continuous_mechanical_deg if continuous_deg is None else float(continuous_deg)
        return self.boundary_low_deg - tolerance_deg <= value <= self.boundary_high_deg + tolerance_deg

    @_synchronized
    def plan(self, target_azimuth_deg: float) -> MotionPlan:
        requested = normalize_angle(target_azimuth_deg)
        current = float(self.continuous_mechanical_deg)
        if not self.is_position_legal(current):
            return MotionPlan(False, current, requested, None, 0.0, "stop", 0.0, "current position outside hard stop")

        low, high = self.boundary_low_deg, self.boundary_high_deg
        # Include enough turns for the supported 450 degree span.  Choosing by
        # absolute delta gives the shortest legal path; every path is monotonic
        # and therefore remains inside the hard interval.
        candidates: list[float] = []
        for turn in range(-4, 5):
            candidate = requested + 360.0 * turn
            if low - 1e-7 <= candidate <= high + 1e-7:
                candidates.append(candidate)
        if not candidates:
            return MotionPlan(False, current, requested, None, 0.0, "stop", 0.0, "no equivalent target inside hard stop")

        target = min(candidates, key=lambda candidate: (abs(candidate - current), candidate))
        delta = target - current
        if abs(delta) <= 1e-7:
            direction = "stop"
        elif delta > 0:
            direction = "cw"
        else:
            direction = "ccw"
        return MotionPlan(True, current, requested, target, delta, direction, abs(delta))

    @_synchronized
    def target_plan(self, target_azimuth_deg: float) -> MotionPlan:
        return self.plan(target_azimuth_deg)

    @_synchronized
    def plan_target(self, target_azimuth_deg: float) -> MotionPlan:
        return self.plan(target_azimuth_deg)

    plan_move = plan
    calculate_move = plan

    @_synchronized
    def check_hard_stop(self, continuous_deg: float | None = None) -> bool:
        return self.is_position_legal(continuous_deg)

    @property
    @_synchronized
    def current_angle_deg(self) -> float:
        return self.continuous_mechanical_deg

    @property
    @_synchronized
    def software_offset(self) -> float:
        return self.software_offset_deg

    @_synchronized
    def mark_motion_started(self, plan: MotionPlan) -> None:
        if not plan.accepted:
            raise ValueError(plan.reason)
        self.motion_running = abs(plan.delta_deg) > 1e-7

    @_synchronized
    def apply_motion(self, plan: MotionPlan) -> None:
        if not plan.accepted or plan.target_continuous_deg is None:
            raise ValueError(plan.reason or "invalid motion plan")
        self.continuous_mechanical_deg = plan.target_continuous_deg
        self.hardware_coord_deg = plan.target_continuous_deg
        self.motion_running = False
        self.last_true_azimuth_deg = self.true_azimuth_deg

    @_synchronized
    def update_position_during_motion(self, continuous_deg: float) -> bool:
        self.continuous_mechanical_deg = float(continuous_deg)
        self.hardware_coord_deg = float(continuous_deg)
        if not self.is_position_legal():
            self.motion_running = False
            return False
        return True

    @_synchronized
    def emergency_stop_required(self) -> bool:
        return not self.is_position_legal()

    @_synchronized
    def return_north(self) -> MotionPlan:
        return self.plan(0.0)

    @_synchronized
    def calibrate(self, true_azimuth_deg: float) -> float:
        return self.calibrate_current(true_azimuth_deg)

    @_synchronized
    def restore_power_cycle(self, hardware_coord_deg: float, last_true_azimuth_deg: float | None = None) -> bool:
        return self.restore_from_power_cycle(hardware_coord_deg, last_true_azimuth_deg)

    calibrate_position = calibrate_current
    recover_power_cycle = restore_from_power_cycle


__all__ = ["MotionPlan", "MotionPlanner", "normalize_angle", "signed_angle"]
