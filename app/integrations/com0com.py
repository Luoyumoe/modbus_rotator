"""com0com setupc discovery and non-blocking pair creation."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Com0ComStatus:
    executable: Path | None
    message: str
    can_create: bool


class Com0ComManager:
    def __init__(self, *, env: dict[str, str] | None = None, which=shutil.which) -> None:
        self.env = env if env is not None else os.environ
        self.which = which

    def find_setupc(self) -> Path | None:
        path_hit = self.which("setupc.exe") or self.which("setupc")
        if path_hit:
            return Path(path_hit)
        for key in ("ProgramFiles", "ProgramFiles(x86)"):
            root = self.env.get(key)
            if root:
                candidate = Path(root) / "com0com" / "setupc.exe"
                if candidate.exists():
                    return candidate
        return None

    def status(self) -> Com0ComStatus:
        executable = self.find_setupc()
        if executable is None:
            return Com0ComStatus(None, "com0com setupc.exe not found; install com0com first", False)
        if not os.access(executable, os.X_OK) and os.name != "nt":
            return Com0ComStatus(executable, "com0com setupc.exe is not executable", False)
        return Com0ComStatus(executable, "com0com is ready", True)

    def create_pair(self, left: str = "COM10", right: str = "COM11") -> subprocess.CompletedProcess[str]:
        status = self.status()
        if not status.can_create or status.executable is None:
            raise RuntimeError(status.message)
        return subprocess.run(
            [str(status.executable), "install", f"PortName={left}", f"PortName={right}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )


__all__ = ["Com0ComManager", "Com0ComStatus"]
