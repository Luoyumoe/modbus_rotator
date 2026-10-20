"""GS-232B ASCII parser and serial listener."""

from __future__ import annotations

import re
import threading
from typing import Any, Callable

try:
    import serial  # type: ignore
except ImportError:  # pragma: no cover
    serial = None


class GS232Parser:
    def __init__(
        self,
        get_azimuth: Callable[[], float],
        set_azimuth: Callable[[float], None],
        stop: Callable[[], None],
        raw_log: Callable[[str], None] | None = None,
    ) -> None:
        self.get_azimuth = get_azimuth
        self.set_azimuth = set_azimuth
        self.stop_callback = stop
        self.raw_log = raw_log or (lambda _: None)

    @staticmethod
    def _format_angle(angle: float) -> str:
        return f"{float(angle) % 360.0:03.0f}"

    def handle(self, command: str) -> str:
        text = command.strip().upper()
        if text == "C":
            return self._format_angle(self.get_azimuth()) + "\r\n"
        if text == "C2":
            return self._format_angle(self.get_azimuth()) + " 000\r\n"
        if text == "S":
            self.stop_callback()
            return "\r\n"
        if text.startswith("M"):
            match = re.fullmatch(r"M(\d{1,3})", text)
            if match is None or float(match.group(1)) > 360:
                self.raw_log(command)
                return "?\r\n"
            self.set_azimuth(float(match.group(1)))
            return "\r\n"
        # GS-232B A/R/L variants are accepted as aliases for azimuth actions.
        if text.startswith("A"):
            value = text[1:]
            if value.isdigit() and float(value) <= 360:
                self.set_azimuth(float(value))
                return "\r\n"
        if text == "R":
            self.set_azimuth((self.get_azimuth() + 1.0) % 360.0)
            return "\r\n"
        if text == "L":
            self.set_azimuth((self.get_azimuth() - 1.0) % 360.0)
            return "\r\n"
        self.raw_log(command)
        return "?\r\n"

    def feed(self, data: bytes | str) -> list[str]:
        text = data.decode("ascii", errors="replace") if isinstance(data, bytes) else data
        commands = [part for part in re.split(r"[\r\n]+", text) if part]
        return [self.handle(command) for command in commands]

    handle_command = handle


class GS232SerialWorker(threading.Thread):
    def __init__(
        self,
        port: str,
        parser: GS232Parser,
        baudrate: int = 9600,
        *,
        serial_factory: Callable[..., Any] | None = None,
        error_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(name="GS-232B", daemon=True)
        self.port = port
        self.parser = parser
        self.baudrate = int(baudrate)
        self.serial_factory = serial_factory or (serial.Serial if serial is not None else None)
        self.error_callback = error_callback or self.parser.raw_log
        self._stop_event = threading.Event()
        self._serial: Any = None

    def stop(self) -> None:
        self._stop_event.set()
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001
                pass

    def run(self) -> None:  # pragma: no cover - hardware lifecycle
        if self.serial_factory is None:
            self.error_callback("pyserial is not installed")
            return
        try:
            self._serial = self.serial_factory(self.port, self.baudrate, timeout=0.25)
        except Exception as exc:  # noqa: BLE001 - hardware errors become diagnostics
            self.error_callback(f"GS-232B {self.port}: {exc}")
            return
        try:
            while not self._stop_event.is_set():
                data = self._serial.readline()
                if not data:
                    continue
                for response in self.parser.feed(data):
                    self._serial.write(response.encode("ascii"))
        finally:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001
                pass


__all__ = ["GS232Parser", "GS232SerialWorker", "GS232CommandParser"]

GS232CommandParser = GS232Parser

