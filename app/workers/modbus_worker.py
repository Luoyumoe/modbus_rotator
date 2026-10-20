"""Threaded Modbus worker with retry, offline degradation, and simulation."""

from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
import time
from typing import Any, Callable

try:
    from PySide6.QtCore import QThread, Signal
except ImportError:  # pragma: no cover
    QThread = object  # type: ignore[misc,assignment]

    class Signal:  # type: ignore[no-redef]
        def __init__(self, *_: Any, **__: Any):
            self._slots: list[Callable[..., Any]] = []

        def connect(self, slot: Callable[..., Any]) -> None:
            self._slots.append(slot)

        def emit(self, *args: Any) -> None:
            for slot in list(self._slots):
                slot(*args)


@dataclass
class WorkerCommand:
    name: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] | None = None


class SimulatedBackend:
    """Small deterministic backend exposing same operations as ModbusController."""

    def __init__(self, initial_angle: float = 0.0) -> None:
        self.angle = float(initial_angle)
        self.target_angle = float(initial_angle)
        self.running = False
        self.temperature = 25
        self.limit_status = 0
        self.alarm_status = 0
        self.acceleration_status = 0
        self.history: list[tuple[str, Any]] = []
        self._lock = threading.RLock()
        self._motion_started_at = 0.0
        self._motion_start_angle = self.angle
        self._motion_speed_deg_s = 90.0

    def validate_safety_parameters(self) -> Any:
        self.history.append(("validate_safety", None))
        return True

    def apply_safety_parameters(self) -> Any:
        self.history.append(("apply_safety", None))
        return True

    def stop(self, trigger_value: int = 0) -> None:
        with self._lock:
            self.running = False
            self.target_angle = self.angle
            self.history.append(("stop", trigger_value))

    def move_distance(self, distance: int, direction: str, **kwargs: Any) -> None:
        with self._lock:
            sign = 1.0 if direction in {"cw", "forward"} else -1.0
            self.target_angle = self.angle + sign * float(distance)
            self._motion_start_angle = self.angle
            self._motion_started_at = time.monotonic()
            self.running = float(distance) > 0
            self.history.append(("move", (int(distance), direction, kwargs)))

    def move_degrees(self, distance_deg: float, direction: str, **kwargs: Any) -> None:
        self.move_distance(float(distance_deg), direction, **kwargs)

    def read_telemetry(self) -> dict[str, int | float]:
        with self._lock:
            if self.running:
                elapsed = time.monotonic() - self._motion_started_at
                travelled = min(abs(self.target_angle - self._motion_start_angle), elapsed * self._motion_speed_deg_s)
                sign = 1.0 if self.target_angle >= self._motion_start_angle else -1.0
                self.angle = self._motion_start_angle + sign * travelled
                if travelled >= abs(self.target_angle - self._motion_start_angle):
                    self.angle = self.target_angle
                    self.running = False
            return {
                "hardware_angle": self.angle,
                "acceleration_status": self.acceleration_status,
                "temperature": self.temperature,
                "limit_status": self.limit_status,
                "alarm_status": self.alarm_status,
                "running": self.running,
            }


class ModbusWorker(QThread):
    """Owns backend instance. UI and network integrations only enqueue commands."""

    telemetry = Signal(object)
    online_changed = Signal(bool)
    error = Signal(str)
    command_result = Signal(object)
    state_changed = Signal(str)

    def __init__(
        self,
        backend: Any,
        *,
        planner: Any | None = None,
        poll_interval: float = 0.5,
        max_retries: int = 3,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.planner = planner
        self.poll_interval = float(poll_interval)
        self.max_retries = int(max_retries)
        self.sleep_fn = sleep_fn
        self.commands: queue.Queue[WorkerCommand] = queue.Queue()
        self.emergency_commands: queue.Queue[WorkerCommand] = queue.Queue()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self.failure_count = 0
        self.offline = False
        self.online = False
        self.last_telemetry: dict[str, Any] = {}
        self._started = False

    def submit(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.commands.put(WorkerCommand(name, args, kwargs or None))
        self._wake_event.set()

    def submit_command(self, command: WorkerCommand) -> None:
        self.commands.put(command)
        self._wake_event.set()

    def request_stop(self, trigger_value: int = 0) -> None:
        self.emergency_commands.put(WorkerCommand("stop", (trigger_value,)))
        self._wake_event.set()

    stop_motion = request_stop

    def shutdown(self, stop_trigger: int = 0) -> None:
        self._stop_event.set()
        self.request_stop(stop_trigger)
        self._wake_event.set()

    def _execute_with_retry(self, command: WorkerCommand) -> Any:
        kwargs = command.kwargs or {}
        if self.offline and command.name not in {"stop", "read_telemetry", "apply_safety_parameters"}:
            raise RuntimeError("worker offline; new motion is disabled")
        last_error: Exception | None = None
        # max_retries counts retries after the initial attempt.  This gives the
        # documented 100/200/400 ms backoff sequence.
        for attempt in range(self.max_retries + 1):
            try:
                method = getattr(self.backend, command.name)
                result = method(*command.args, **kwargs)
                self.failure_count = 0
                if not self.online:
                    self.online = True
                    self.online_changed.emit(True)
                if self.offline:
                    self.offline = False
                return result
            except Exception as exc:  # noqa: BLE001 - backend errors become UI state
                last_error = exc
                if attempt < self.max_retries:
                    self.sleep_fn(0.1 * (2**attempt))
        self.failure_count += 1
        if self.failure_count >= 5 and not self.offline:
            self.offline = True
            if self.online:
                self.online = False
                self.online_changed.emit(False)
            self.state_changed.emit("offline")
        raise RuntimeError(str(last_error) if last_error else "backend operation failed")

    def process_one(self, *, poll: bool = False) -> bool:
        command: WorkerCommand | None = None
        try:
            command = self.emergency_commands.get_nowait()
        except queue.Empty:
            if not poll:
                try:
                    command = self.commands.get_nowait()
                except queue.Empty:
                    return False
        if command is None:
            return False
        try:
            result = self._execute_with_retry(command)
            self.command_result.emit((command.name, result))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
        return True

    def poll_once(self) -> dict[str, Any] | None:
        if self.offline:
            return self.last_telemetry or None
        try:
            telemetry = self._execute_with_retry(WorkerCommand("read_telemetry"))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return self.last_telemetry or None
        self.last_telemetry = dict(telemetry)
        if self.planner is not None and "hardware_angle" in self.last_telemetry:
            try:
                legal = self.planner.update_telemetry(float(self.last_telemetry["hardware_angle"]))
            except (TypeError, ValueError):
                legal = True
            if not legal:
                # Hard-stop violation gets emergency priority and motion state
                # is cleared before telemetry is published.
                self.emergency_commands.put(WorkerCommand("stop"))
                self.planner.motion_running = False
                self.state_changed.emit("hard-stop")
        self.telemetry.emit(self.last_telemetry)
        return self.last_telemetry

    def run(self) -> None:  # pragma: no cover - timing-heavy; process_one is unit-testable
        self._started = True
        next_poll = time.monotonic()
        while not self._stop_event.is_set():
            worked = self.process_one()
            if time.monotonic() >= next_poll:
                self.poll_once()
                next_poll = time.monotonic() + self.poll_interval
            if not worked:
                self._wake_event.wait(min(0.05, self.poll_interval))
                self._wake_event.clear()
        # Stop has priority during shutdown.  Drop queued normal commands so
        # close cannot start another move after the emergency stop.
        self.process_one()
        while True:
            try:
                self.commands.get_nowait()
            except queue.Empty:
                break
        if self.online:
            self.online = False
            self.online_changed.emit(False)


__all__ = ["ModbusWorker", "SimulatedBackend", "WorkerCommand"]
