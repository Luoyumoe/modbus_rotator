"""N1MM Rotor UDP XML integration."""

from __future__ import annotations

import socket
import threading
import xml.etree.ElementTree as ET
from typing import Callable


def parse_n1mm_datagram(payload: bytes | str) -> float | None:
    try:
        root = ET.fromstring(payload)
    except (ET.ParseError, ValueError, TypeError):
        return None
    tag = root.tag.rsplit("}", 1)[-1]
    if tag != "N1MMRotor":
        return None
    node = next((child for child in root if child.tag.rsplit("}", 1)[-1] == "goazi"), None)
    if node is None or node.text is None:
        return None
    try:
        angle = float(node.text.strip())
    except ValueError:
        return None
    if not 0.0 <= angle <= 360.0:
        return None
    return angle % 360.0


class N1MMListener(threading.Thread):
    def __init__(
        self,
        callback: Callable[[float], None],
        host: str = "127.0.0.1",
        port: int = 12040,
        *,
        socket_factory: Callable[..., socket.socket] = socket.socket,
        error_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(name="N1MM-UDP", daemon=True)
        self.callback = callback
        self.host, self.port = host, int(port)
        self.socket_factory = socket_factory
        self.error_callback = error_callback or (lambda _: None)
        self._stop_event = threading.Event()
        self._socket: socket.socket | None = None

    def stop(self) -> None:
        self._stop_event.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass

    def run(self) -> None:  # pragma: no cover - socket lifecycle
        sock = self.socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket = sock
        sock.settimeout(0.25)
        try:
            sock.bind((self.host, self.port))
        except (OSError, ValueError, OverflowError) as exc:
            self.error_callback(f"N1MM UDP {self.host}:{self.port}: {exc}")
            sock.close()
            return
        try:
            while not self._stop_event.is_set():
                try:
                    payload, _ = sock.recvfrom(8192)
                except socket.timeout:
                    continue
                except OSError:
                    break
                angle = parse_n1mm_datagram(payload)
                if angle is not None:
                    self.callback(angle)
        finally:
            try:
                sock.close()
            except OSError:
                pass


__all__ = ["N1MMListener", "parse_n1mm_datagram", "parse_n1mm_xml"]

parse_n1mm_xml = parse_n1mm_datagram
parse_goazi = parse_n1mm_datagram

