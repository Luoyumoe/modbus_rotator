"""Lifecycle wrapper for N1MM, Hamlib, and GS-232 integrations."""

from __future__ import annotations

import logging
from typing import Callable

from .gs232 import GS232Parser, GS232SerialWorker
from .hamlib import HamlibServer
from .n1mm import N1MMListener


class NetworkServiceManager:
    def __init__(self, *, get_azimuth: Callable[[], float], set_azimuth: Callable[[float], None], stop: Callable[[], None], error_callback: Callable[[str], None] | None = None) -> None:
        self.get_azimuth = get_azimuth
        self.set_azimuth = set_azimuth
        self.stop_callback = stop
        self.error_callback = error_callback or (lambda message: logging.getLogger(__name__).warning("%s", message))
        self.services: list[object] = []

    def start_n1mm(self, host: str = "127.0.0.1", port: int = 12040) -> N1MMListener:
        service = N1MMListener(self.set_azimuth, host, port, error_callback=self.error_callback)
        service.start()
        self.services.append(service)
        return service

    def start_hamlib(self, host: str = "127.0.0.1", port: int = 4533) -> HamlibServer:
        service = HamlibServer(self.get_azimuth, self.set_azimuth, self.stop_callback, host, port, self.error_callback)
        service.start()
        self.services.append(service)
        return service

    def start_gs232(self, port: str, baudrate: int = 9600, raw_log: Callable[[str], None] | None = None) -> GS232SerialWorker:
        parser = GS232Parser(self.get_azimuth, self.set_azimuth, self.stop_callback, raw_log)
        service = GS232SerialWorker(port, parser, baudrate, error_callback=self.error_callback)
        service.start()
        self.services.append(service)
        return service

    def stop_all(self) -> None:
        for service in list(self.services):
            stop = getattr(service, "stop", None)
            if stop is not None:
                stop()
        for service in list(self.services):
            join = getattr(service, "join", None)
            if join is not None:
                join(timeout=1.5)
        self.services.clear()


__all__ = ["NetworkServiceManager"]
