"""com0com setupc 查找与非阻塞虚拟串口对创建。"""

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
    def __init__(
        self,
        *,
        setupc_path: str | os.PathLike[str] | None = None,
        env: dict[str, str] | None = None,
        which=shutil.which,
    ) -> None:
        self.setupc_path = Path(setupc_path).expanduser() if setupc_path else None
        self.env = env if env is not None else os.environ
        self.which = which

    def set_setupc_path(self, setupc_path: str | os.PathLike[str] | None) -> None:
        """Set explicit setupc path; empty value restores automatic discovery."""
        self.setupc_path = Path(setupc_path).expanduser() if setupc_path else None

    def find_setupc(self, setupc_path: str | os.PathLike[str] | None = None) -> Path | None:
        explicit = setupc_path if setupc_path is not None else self.setupc_path
        if explicit:
            candidate = Path(explicit).expanduser()
            if candidate.is_dir():
                candidate /= "setupc.exe"
            return candidate
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

    def status(self, setupc_path: str | os.PathLike[str] | None = None) -> Com0ComStatus:
        executable = self.find_setupc() if setupc_path is None else self.find_setupc(setupc_path)
        if executable is None:
            return Com0ComStatus(None, "未找到 com0com setupc.exe，请先安装或选择路径", False)
        if not executable.exists() or not executable.is_file():
            return Com0ComStatus(executable, f"setupc.exe 不存在：{executable}", False)
        if not os.access(executable, os.X_OK) and os.name != "nt":
            return Com0ComStatus(executable, f"setupc.exe 无执行权限：{executable}", False)
        return Com0ComStatus(executable, f"com0com 可用：{executable}", True)

    def create_pair(
        self,
        left: str = "COM10",
        right: str = "COM11",
        setupc_path: str | os.PathLike[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if not left.strip() or not right.strip():
            raise ValueError("com0com 端口名称不能为空")
        status = self.status() if setupc_path is None else self.status(setupc_path)
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
