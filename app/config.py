"""Persistent configuration for Modbus Rotator.

The configuration lives outside the PyInstaller bundle.  Writes are atomic so a
power loss cannot leave a partially written JSON document.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


LOGGER = logging.getLogger(__name__)


SCHEMA_VERSION = 2
CONFIG_SCHEMA_VERSION = SCHEMA_VERSION
SAVE_DELAY_SECONDS = 0.5


def get_config_path() -> Path:
    """Return the per-user configuration path.

    Windows exposes ``LOCALAPPDATA``.  The fallback keeps development and
    Linux simulation usable when the variable is absent.
    """

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data)
    elif os.name == "nt":
        root = Path.home() / "AppData" / "Local"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "ModbusRotator" / "rotator_config.json"


@dataclass
class NetworkConfig:
    n1mm_enabled: bool = False
    n1mm_host: str = "127.0.0.1"
    n1mm_port: int = 12040
    hamlib_enabled: bool = False
    hamlib_host: str = "127.0.0.1"
    hamlib_port: int = 4533
    gs232_enabled: bool = False
    gs232_port: str = ""
    gs232_baudrate: int = 9600


@dataclass
class RegisterConfig:
    run_mode: int = 4
    cycle_count: int = 1
    f02_distance: int = 360000
    smoothing_f08: int = 0
    max_frequency_f04: int = 0
    min_frequency_f05: int = 0
    forward_speed_p2: int = 0
    reverse_speed_p4: int = 0
    soft_stop_f13: int = 0
    enable_f14: int = 1
    stop_trigger: int = 0
    forward_trigger: int = 1
    reverse_trigger: int = 2


@dataclass
class RotatorConfig:
    schema_version: int = SCHEMA_VERSION
    serial_port: str = "COM1"
    baudrate: int = 115200
    slave_id: int = 1
    timeout_s: float = 1.0
    simulate: bool = False
    registers: RegisterConfig = field(default_factory=RegisterConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    rotation_span_deg: float = 360.0
    stop_point_deg: float = 0.0
    software_offset_deg: float = 0.0
    hardware_coord_deg: float = 0.0
    true_azimuth_deg: float = 0.0
    last_true_azimuth_deg: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schema_version"] = SCHEMA_VERSION
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RotatorConfig":
        """Load current and older schema documents with conservative defaults."""

        if not isinstance(data, dict):
            return cls()
        raw = dict(data)
        try:
            version = int(raw.get("schema_version", 1) or 1)
        except (TypeError, ValueError):
            version = 1
        registers = raw.get("registers")
        network = raw.get("network")
        # Version 1 stored register and network keys at the top level.
        if not isinstance(registers, dict):
            registers = None
        if registers is None:
            registers = {
                key: raw[key]
                for key in RegisterConfig.__dataclass_fields__
                if key in raw
            }
        if not isinstance(network, dict):
            network = None
        if network is None:
            network = {
                key: raw[key]
                for key in NetworkConfig.__dataclass_fields__
                if key in raw
            }
        register_obj = RegisterConfig()
        for key in RegisterConfig.__dataclass_fields__:
            if key in registers:
                setattr(register_obj, key, registers[key])
        network_obj = NetworkConfig()
        for key in NetworkConfig.__dataclass_fields__:
            if key in network:
                setattr(network_obj, key, network[key])

        values: dict[str, Any] = {}
        for key in cls.__dataclass_fields__:
            if key in {"schema_version", "registers", "network"}:
                continue
            if key in raw:
                values[key] = raw[key]
        values["registers"] = register_obj
        values["network"] = network_obj
        values["schema_version"] = SCHEMA_VERSION
        result = cls(**values)
        # Do not retain unknown or obsolete schema fields.
        _ = version
        return result


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def save_config(config: RotatorConfig, path: Path | str | None = None) -> Path:
    target = Path(path) if path is not None else get_config_path()
    payload = json.dumps(config.to_dict(), indent=2, sort_keys=True).encode("utf-8")
    _atomic_write(target, payload)
    return target


def load_config(path: Path | str | None = None) -> RotatorConfig:
    target = Path(path) if path is not None else get_config_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return RotatorConfig()
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        # Broken config must not prevent the application from starting.
        return RotatorConfig()
    return RotatorConfig.from_dict(raw)


class ConfigStore:
    """Thread-safe config holder with a bounded delayed-save queue."""

    def __init__(self, config: RotatorConfig | None = None, path: Path | str | None = None):
        self.path = Path(path) if path is not None else get_config_path()
        self.config = config if config is not None else load_config(self.path)
        self._timer: threading.Timer | None = None
        self._lock = threading.RLock()
        self._closed = False
        self.last_error: Exception | None = None

    def update(self, **changes: Any) -> RotatorConfig:
        with self._lock:
            for key, value in changes.items():
                if key == "registers" and isinstance(value, dict):
                    for nested_key, nested_value in value.items():
                        setattr(self.config.registers, nested_key, nested_value)
                elif key == "network" and isinstance(value, dict):
                    for nested_key, nested_value in value.items():
                        setattr(self.config.network, nested_key, nested_value)
                elif hasattr(self.config, key):
                    setattr(self.config, key, value)
            self.schedule_save()
            return self.config

    def update_coordinates(
        self,
        *,
        hardware_coord_deg: float | None = None,
        software_offset_deg: float | None = None,
        true_azimuth_deg: float | None = None,
        last_true_azimuth_deg: float | None = None,
    ) -> RotatorConfig:
        """Queue coordinate persistence; timer coalesces rapid telemetry updates."""
        changes = {
            key: value
            for key, value in {
                "hardware_coord_deg": hardware_coord_deg,
                "software_offset_deg": software_offset_deg,
                "true_azimuth_deg": true_azimuth_deg,
                "last_true_azimuth_deg": last_true_azimuth_deg,
            }.items()
            if value is not None
        }
        return self.update(**changes)

    def schedule_save(self) -> None:
        with self._lock:
            if self._closed:
                return
            # Keep first-change deadline bounded to SAVE_DELAY_SECONDS.  A
            # continuous telemetry stream must not postpone persistence forever.
            if self._timer is not None:
                return
            self._timer = threading.Timer(SAVE_DELAY_SECONDS, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> Path:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            try:
                result = save_config(self.config, self.path)
            except OSError as exc:
                # Timer callbacks must never surface an uncaught exception in
                # the Qt process.  UI can inspect ``last_error`` and retry.
                self.last_error = exc
                LOGGER.warning("Unable to save configuration at %s: %s", self.path, exc)
                return self.path
            self.last_error = None
            return result

    def close(self) -> Path:
        with self._lock:
            self._closed = True
        return self.flush()


# Friendly aliases for integrations that used the pre-dataclass API.
Config = RotatorConfig
ConfigManager = ConfigStore


__all__ = [
    "ConfigStore",
    "Config",
    "ConfigManager",
    "CONFIG_SCHEMA_VERSION",
    "NetworkConfig",
    "RegisterConfig",
    "RotatorConfig",
    "SCHEMA_VERSION",
    "get_config_path",
    "load_config",
    "save_config",
]
