"""XY-SMH Modbus-RTU register codec and command adapter."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable

try:  # Optional during parser/unit tests; requirements install it for hardware use.
    import minimalmodbus  # type: ignore
except ImportError:  # pragma: no cover - exercised only on dependency-free hosts
    minimalmodbus = None


REGISTERS: dict[str, int] = {
    "run_mode": 0x0002,
    "hardware_angle": 0x0003,
    "acceleration_status": 0x0015,
    "forward_distance_high": 0x0100,
    "forward_distance_low": 0x0101,
    # Trigger addresses occupy the documented command slots adjacent to each
    # distance pair. Confirm against the exact XY-SMH firmware manual.
    "forward_trigger": 0x0102,
    "reverse_distance_high": 0x0103,
    "reverse_distance_low": 0x0104,
    "reverse_trigger": 0x0105,
    "cycle_count": 0x0106,
    "stop_trigger": 0x0107,
    "temperature": 0x0108,
    "limit_status": 0x0109,
    "alarm_status": 0x010A,
    "f02_high": 0x010E,
    "f02_low": 0x010F,
    "f08": 0x0110,
    "f04": 0x0111,
    "f05": 0x0112,
    "p2": 0x0113,
    "p4": 0x0114,
    "f13": 0x0115,
    "f14": 0x0116,
}

# XY-SMH distance/position values use milli-degrees.  Keep conversion at the
# adapter boundary; planner and UI stay in human-readable degrees.
ANGLE_UNITS_PER_DEGREE = 1000
ADDR_RUN_MODE = REGISTERS["run_mode"]
ADDR_ACCELERATION_STATUS = REGISTERS["acceleration_status"]
ADDR_FORWARD_DISTANCE_HIGH = REGISTERS["forward_distance_high"]
ADDR_FORWARD_DISTANCE_LOW = REGISTERS["forward_distance_low"]
ADDR_REVERSE_DISTANCE_HIGH = REGISTERS["reverse_distance_high"]
ADDR_REVERSE_DISTANCE_LOW = REGISTERS["reverse_distance_low"]
ADDR_CYCLE_COUNT = REGISTERS["cycle_count"]
ADDR_F02_HIGH = REGISTERS["f02_high"]
ADDR_F02_LOW = REGISTERS["f02_low"]


def encode_u16(value: int) -> int:
    value = int(value)
    if not 0 <= value <= 0xFFFF:
        raise ValueError("unsigned 16-bit value out of range")
    return value


def encode_s16(value: int) -> int:
    value = int(value)
    if not -0x8000 <= value <= 0x7FFF:
        raise ValueError("signed 16-bit value out of range")
    return value & 0xFFFF


def decode_s16(value: int) -> int:
    value = int(value) & 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def encode_u32(value: int) -> tuple[int, int]:
    value = int(value)
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("unsigned 32-bit value out of range")
    return (value >> 16) & 0xFFFF, value & 0xFFFF


def encode_s32(value: int) -> tuple[int, int]:
    value = int(value)
    if not -0x80000000 <= value <= 0x7FFFFFFF:
        raise ValueError("signed 32-bit value out of range")
    return encode_u32(value & 0xFFFFFFFF)


def decode_u32(high: int, low: int) -> int:
    return ((int(high) & 0xFFFF) << 16) | (int(low) & 0xFFFF)


def decode_s32(high: int, low: int) -> int:
    value = decode_u32(high, low)
    return value - 0x100000000 if value & 0x80000000 else value


# Explicit integer naming is convenient for callers and keeps wire order clear.
encode_int16 = encode_s16
decode_int16 = decode_s16
encode_uint16 = encode_u16
decode_uint16 = lambda value: int(value) & 0xFFFF
encode_int32 = encode_s32
decode_int32 = decode_s32
encode_uint32 = encode_u32
decode_uint32 = decode_u32


@dataclass(frozen=True)
class SafetyStatus:
    run_mode: int
    cycle_count: int
    f02_distance: int

    @property
    def is_safe(self) -> bool:
        return self.run_mode == 4 and self.cycle_count == 1 and self.f02_distance == 360000


class SafetyParameterMismatch(RuntimeError):
    """Motion is blocked until required XY-SMH parameters are applied."""

    def __init__(self, status: SafetyStatus):
        self.status = status
        super().__init__("安全参数映射不一致，请使用“应用安全参数”同步后再运动")


class ModbusController:
    """Serialised access to one minimalmodbus instrument.

    ``instrument`` may be a fake implementing ``read_register`` and
    ``write_register``.  This keeps codec and command tests independent of a
    physical serial port.
    """

    def __init__(
        self,
        port: str | None = None,
        baudrate: int = 115200,
        slave_id: int = 1,
        timeout: float = 1.0,
        instrument: Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if instrument is None:
            if minimalmodbus is None:
                raise RuntimeError("minimalmodbus is required for real hardware mode")
            if not port:
                raise ValueError("serial port is required")
            instrument = minimalmodbus.Instrument(port, int(slave_id), mode=minimalmodbus.MODE_RTU)
            instrument.serial.baudrate = int(baudrate)
            instrument.serial.bytesize = 8
            instrument.serial.parity = minimalmodbus.serial.PARITY_NONE
            instrument.serial.stopbits = 1
            instrument.serial.timeout = float(timeout)
            instrument.clear_buffers_before_each_transaction = True
        self.instrument = instrument
        self.sleep_fn = sleep_fn

    def _read_register(self, address: int, *, signed: bool = False) -> int:
        try:
            return int(self.instrument.read_register(address, 0, 3, signed=signed))
        except TypeError:
            return int(self.instrument.read_register(address, signed=signed))

    def _write_register(self, address: int, value: int) -> None:
        try:
            self.instrument.write_register(address, int(value) & 0xFFFF, 0, 6)
        except TypeError:
            self.instrument.write_register(address, int(value) & 0xFFFF)

    def read_u16(self, address: int) -> int:
        return encode_u16(self._read_register(address, signed=False))

    def read_s16(self, address: int) -> int:
        return decode_s16(self._read_register(address, signed=False))

    read_register16 = read_u16
    read_signed16 = read_s16

    def write_u16(self, address: int, value: int) -> None:
        self._write_register(address, encode_u16(value))

    def write_s16(self, address: int, value: int) -> None:
        self._write_register(address, encode_s16(value))

    write_register16 = write_u16
    write_signed16 = write_s16

    def read_u32(self, high_address: int, low_address: int) -> int:
        return decode_u32(self.read_u16(high_address), self.read_u16(low_address))

    def read_s32(self, high_address: int, low_address: int) -> int:
        return decode_s32(self.read_u16(high_address), self.read_u16(low_address))

    read_int32 = read_s32
    read_signed32 = read_s32

    def write_u32(self, high_address: int, low_address: int, value: int) -> None:
        high, low = encode_u32(value)
        self.write_u16(high_address, high)
        self.write_u16(low_address, low)

    def write_s32(self, high_address: int, low_address: int, value: int) -> None:
        high, low = encode_s32(value)
        self.write_u16(high_address, high)
        self.write_u16(low_address, low)

    write_int32 = write_s32
    write_signed32 = write_s32

    def read_safety_status(self) -> SafetyStatus:
        return SafetyStatus(
            run_mode=self.read_u16(REGISTERS["run_mode"]),
            cycle_count=self.read_u16(REGISTERS["cycle_count"]),
            f02_distance=self.read_u32(REGISTERS["f02_high"], REGISTERS["f02_low"]),
        )

    def validate_safety_parameters(self) -> SafetyStatus:
        status = self.read_safety_status()
        if not status.is_safe:
            raise SafetyParameterMismatch(status)
        return status

    def apply_safety_parameters(self) -> SafetyStatus:
        self.write_u16(REGISTERS["run_mode"], 4)
        self.write_u16(REGISTERS["cycle_count"], 1)
        self.write_u32(REGISTERS["f02_high"], REGISTERS["f02_low"], 360000)
        status = self.read_safety_status()
        if not status.is_safe:
            raise SafetyParameterMismatch(status)
        return status

    def stop(self, trigger_value: int = 0) -> None:
        self.write_u16(REGISTERS["stop_trigger"], trigger_value)

    def move_distance(
        self,
        distance: int,
        direction: str,
        *,
        stop_trigger: int = 0,
        forward_trigger: int = 1,
        reverse_trigger: int = 2,
        require_safe: bool = True,
    ) -> None:
        if require_safe:
            self.validate_safety_parameters()
        direction = direction.lower()
        if direction not in {"cw", "ccw", "forward", "reverse"}:
            raise ValueError("direction must be cw/ccw or forward/reverse")
        if int(distance) < 0:
            raise ValueError("distance must be non-negative")
        self.stop(stop_trigger)
        self.sleep_fn(0.1)
        if direction in {"cw", "forward"}:
            self.write_u32(REGISTERS["forward_distance_high"], REGISTERS["forward_distance_low"], int(distance))
            self.write_u16(REGISTERS["forward_trigger"], forward_trigger)
        else:
            self.write_u32(REGISTERS["reverse_distance_high"], REGISTERS["reverse_distance_low"], int(distance))
            self.write_u16(REGISTERS["reverse_trigger"], reverse_trigger)

    def read_telemetry(self) -> dict[str, int | float | bool]:
        angle_units = self.read_s32(REGISTERS["hardware_angle"], REGISTERS["hardware_angle"] + 1)
        acceleration_status = self.read_u16(REGISTERS["acceleration_status"])
        return {
            "hardware_angle": angle_units / ANGLE_UNITS_PER_DEGREE,
            "hardware_angle_units": angle_units,
            "acceleration_status": acceleration_status,
            "running": bool(acceleration_status & 0x0003),
            "temperature": self.read_s16(REGISTERS["temperature"]),
            "limit_status": self.read_u16(REGISTERS["limit_status"]),
            "alarm_status": self.read_u16(REGISTERS["alarm_status"]),
        }

    def move_degrees(self, distance_deg: float, direction: str, **kwargs: Any) -> None:
        units = int(round(abs(float(distance_deg)) * ANGLE_UNITS_PER_DEGREE))
        self.move_distance(units, direction, **kwargs)

    def read_angle(self) -> float:
        return self.read_s32(REGISTERS["hardware_angle"], REGISTERS["hardware_angle"] + 1) / ANGLE_UNITS_PER_DEGREE


__all__ = [
    "REGISTERS",
    "ModbusController",
    "SafetyParameterMismatch",
    "SafetyStatus",
    "decode_s16",
    "decode_s32",
    "decode_u32",
    "encode_s16",
    "encode_s32",
    "encode_u16",
    "encode_u32",
    "encode_int16",
    "decode_int16",
    "encode_uint16",
    "decode_uint16",
    "encode_int32",
    "decode_int32",
    "encode_uint32",
    "decode_uint32",
    "XYSMHModbus",
    "ModbusClient",
    "ANGLE_UNITS_PER_DEGREE",
    "ADDR_RUN_MODE",
    "ADDR_ACCELERATION_STATUS",
    "ADDR_FORWARD_DISTANCE_HIGH",
    "ADDR_FORWARD_DISTANCE_LOW",
    "ADDR_REVERSE_DISTANCE_HIGH",
    "ADDR_REVERSE_DISTANCE_LOW",
    "ADDR_CYCLE_COUNT",
    "ADDR_F02_HIGH",
    "ADDR_F02_LOW",
]

XYSMHModbus = ModbusController
ModbusClient = ModbusController
