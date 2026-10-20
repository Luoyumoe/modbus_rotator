"""Minimal Hamlib rotctld TCP protocol."""

from __future__ import annotations

import socket
import threading
from typing import Callable


def _parse_float(value: str) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if 0.0 <= result <= 360.0 else None


def parse_hamlib_command(
    line: str,
    *,
    get_azimuth: Callable[[], float],
    set_azimuth: Callable[[float], None],
    stop: Callable[[], None],
) -> str:
    command = line.strip()
    if command == "p":
        return f"{float(get_azimuth()) % 360.0:.3f}\n0.000\n"
    if command.startswith("P"):
        parts = command.split()
        if len(parts) != 3:
            return "RPRT -1\n"
        angle = _parse_float(parts[1])
        if angle is None:
            return "RPRT -1\n"
        # Elevation is deliberately ignored for azimuth-only rotor.
        set_azimuth(angle)
        return "RPRT 0\n"
    if command == "S":
        stop()
        return "RPRT 0\n"
    return "RPRT -4\n"


handle_hamlib_command = parse_hamlib_command


class HamlibServer(threading.Thread):
    def __init__(
        self,
        get_azimuth: Callable[[], float],
        set_azimuth: Callable[[float], None],
        stop: Callable[[], None],
        host: str = "127.0.0.1",
        port: int = 4533,
        error_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(name="rotctld", daemon=True)
        self.get_azimuth = get_azimuth
        self.set_azimuth = set_azimuth
        self.stop_callback = stop
        self.host, self.port = host, int(port)
        self.error_callback = error_callback or (lambda _: None)
        self._stop_event = threading.Event()
        self._server: socket.socket | None = None

    def stop(self) -> None:
        self._stop_event.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass

    def _serve_client(self, client: socket.socket) -> None:
        with client:
            stream = b""
            client.settimeout(0.5)
            while not self._stop_event.is_set():
                try:
                    chunk = client.recv(1024)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                stream += chunk
                while b"\n" in stream:
                    raw, stream = stream.split(b"\n", 1)
                    response = parse_hamlib_command(
                        raw.decode("ascii", errors="replace"),
                        get_azimuth=self.get_azimuth,
                        set_azimuth=self.set_azimuth,
                        stop=self.stop_callback,
                    )
                    try:
                        client.sendall(response.encode("ascii"))
                    except OSError:
                        return

    def run(self) -> None:  # pragma: no cover - socket lifecycle
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server = server
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.settimeout(0.25)
        try:
            server.bind((self.host, self.port))
        except (OSError, ValueError, OverflowError) as exc:
            self.error_callback(f"rotctld {self.host}:{self.port}: {exc}")
            server.close()
            return
        server.listen(4)
        try:
            while not self._stop_event.is_set():
                try:
                    client, _ = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                threading.Thread(target=self._serve_client, args=(client,), daemon=True).start()
        finally:
            try:
                server.close()
            except OSError:
                pass


__all__ = ["HamlibServer", "parse_hamlib_command", "parse_command"]

parse_command = parse_hamlib_command

