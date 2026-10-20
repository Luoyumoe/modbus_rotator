from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .config import ConfigStore
from .integrations.services import NetworkServiceManager
from .motion import MotionPlanner
from .protocols.modbus import ModbusController
from .ui.main_window import MainWindow, apply_dark_theme
from .workers.modbus_worker import ModbusWorker, SimulatedBackend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Modbus 转台控制台")
    parser.add_argument("--simulate", action="store_true", help="使用模拟设备，不打开串口")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="日志级别")
    return parser


def create_runtime(config_store: ConfigStore, simulate: bool = False):
    config = config_store.config
    use_simulation = bool(simulate or config.simulate)
    planner = MotionPlanner(
        hardware_coord_deg=config.hardware_coord_deg,
        software_offset_deg=config.software_offset_deg,
        rotation_span_deg=config.rotation_span_deg,
        stop_point_deg=config.stop_point_deg,
        last_true_azimuth_deg=config.last_true_azimuth_deg,
    )
    if use_simulation:
        backend = SimulatedBackend(config.hardware_coord_deg)
    else:
        backend = ModbusController(
            port=config.serial_port,
            baudrate=config.baudrate,
            slave_id=config.slave_id,
            timeout=config.timeout_s,
        )
    worker = ModbusWorker(backend, planner=planner)

    def set_target(angle: float) -> None:
        plan = planner.plan(angle)
        if plan.accepted:
            planner.mark_motion_started(plan)
            registers = config.registers
            worker.submit(
                "move_degrees",
                plan.distance_deg,
                plan.direction,
                stop_trigger=registers.stop_trigger,
                forward_trigger=registers.forward_trigger,
                reverse_trigger=registers.reverse_trigger,
            )

    services = NetworkServiceManager(
        get_azimuth=lambda: planner.display_angle_deg,
        set_azimuth=set_target,
        stop=lambda: worker.request_stop(config.registers.stop_trigger),
    )
    if config.network.n1mm_enabled:
        services.start_n1mm(config.network.n1mm_host, config.network.n1mm_port)
    if config.network.hamlib_enabled:
        services.start_hamlib(config.network.hamlib_host, config.network.hamlib_port)
    if config.network.gs232_enabled and config.network.gs232_port:
        services.start_gs232(config.network.gs232_port, config.network.gs232_baudrate)
    return planner, worker, services


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    apply_dark_theme(app)
    store = ConfigStore()
    try:
        planner, worker, services = create_runtime(store, args.simulate)
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(None, "Modbus 转台", str(exc))
        store.close()
        return 2
    window = MainWindow(store, worker, planner, services=services)
    window.show()
    worker.start()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

