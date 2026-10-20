import time

from app.config import ConfigStore, RotatorConfig
from app.main import create_runtime
from app.motion import MotionPlanner
from app.workers.modbus_worker import ModbusWorker, SimulatedBackend


class FailingBackend:
    def __init__(self):
        self.calls = 0

    def read_telemetry(self):
        self.calls += 1
        raise OSError("timeout")


def test_worker_retry_backoff_and_offline():
    backend = FailingBackend()
    delays = []
    worker = ModbusWorker(backend, sleep_fn=delays.append)
    for _ in range(5):
        worker.poll_once()
    assert backend.calls == 20
    assert delays[:3] == [0.1, 0.2, 0.4]
    assert worker.offline


def test_emergency_stop_has_priority_over_queued_motion():
    backend = SimulatedBackend()
    worker = ModbusWorker(backend, sleep_fn=lambda _: None)
    worker.submit("move_degrees", 45, "cw")
    worker.request_stop(0)
    assert worker.process_one()
    assert backend.history[0] == ("stop", 0)


def test_worker_only_reports_online_after_success():
    events = []
    backend = SimulatedBackend()
    worker = ModbusWorker(backend, sleep_fn=lambda _: None)
    worker.online_changed.connect(events.append)
    assert events == []
    worker.poll_once()
    assert events == [True]
    worker.shutdown()


def test_shutdown_discards_queued_motion_after_emergency_stop():
    backend = SimulatedBackend()
    worker = ModbusWorker(backend, sleep_fn=lambda _: None)
    worker.submit("move_degrees", 45, "cw")
    worker.shutdown()
    worker.run()
    assert backend.history == [("stop", 0)]


def test_hard_stop_violation_queues_emergency_stop():
    backend = SimulatedBackend(initial_angle=91)
    planner = MotionPlanner(current_angle_deg=90, rotation_span_deg=90)
    worker = ModbusWorker(backend, planner=planner, sleep_fn=lambda _: None)
    worker.poll_once()
    assert worker.process_one()
    assert backend.history[0] == ("stop", 0)


def test_network_target_callback_drives_simulated_backend(tmp_path):
    config = RotatorConfig(simulate=True)
    store = ConfigStore(config, tmp_path / "config.json")
    planner, worker, services = create_runtime(store, simulate=True)
    services.set_azimuth(20)
    assert worker.process_one()
    time.sleep(0.03)
    telemetry = worker.poll_once()
    assert telemetry is not None
    assert telemetry["hardware_angle"] > 0
    assert worker.backend.history[-1][0] == "move"
    services.stop_all()
    worker.shutdown()
    worker.run()
    store.close()

