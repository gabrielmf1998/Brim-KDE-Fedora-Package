"""Runs install, remove and upgrade work off the UI thread.

Anything touching the RPM database goes through pkexec so the user gets the
normal polkit prompt and sees the real dnf transaction. Flatpak user installs
and AppImage downloads need no escalation and run directly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..backends.appimage import APPS_DIR, AppImageBackend
from ..backends.base import Backend, Package

UA = {"User-Agent": "Brim/1.0 (Fedora package manager)"}


class Action:
    INSTALL = "install"
    REMOVE = "remove"
    UPGRADE = "upgrade"


class TransactionRunner(QThread):
    """One run covers one action across however many backends are involved."""

    line = Signal(str)
    step = Signal(str)
    progress = Signal(int)
    finished_ok = Signal(bool, str)

    def __init__(
        self,
        action: str,
        packages: list[Package],
        backends: dict[str, Backend],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.action = action
        self.packages = packages
        self.backends = backends
        self._proc: subprocess.Popen | None = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def run(self) -> None:
        groups: dict[str, list[Package]] = {}
        for p in self.packages:
            groups.setdefault(p.source, []).append(p)

        failures: list[str] = []
        total = len(groups)

        for index, (source, pkgs) in enumerate(groups.items(), start=1):
            if self._cancelled:
                failures.append("cancelled")
                break
            backend = self.backends.get(source)
            if backend is None:
                failures.append(f"{source}: backend not loaded")
                continue

            names = ", ".join(p.name for p in pkgs[:4])
            if len(pkgs) > 4:
                names += f" and {len(pkgs) - 4} more"
            self.step.emit(f"{self.action.title()} via {backend.label}: {names}")

            try:
                if source == "appimage":
                    ok = self._run_appimage(backend, pkgs)
                else:
                    ok = self._run_command(backend, pkgs)
            except Exception as exc:
                self.line.emit(f"error: {exc}")
                ok = False

            if not ok:
                failures.append(backend.label)
            self.progress.emit(int(index / total * 100))

        if failures:
            self.finished_ok.emit(False, "Failed: " + ", ".join(failures))
        else:
            self.finished_ok.emit(True, f"{self.action.title()} finished")

    def _build(self, backend: Backend, pkgs: list[Package]) -> list[str]:
        if self.action == Action.INSTALL:
            return backend.install_cmd(pkgs)
        if self.action == Action.REMOVE:
            return backend.remove_cmd(pkgs)
        return backend.upgrade_cmd(pkgs)

    def _run_command(self, backend: Backend, pkgs: list[Package]) -> bool:
        cmd = self._build(backend, pkgs)
        if backend.needs_root and os.geteuid() != 0:
            if not shutil.which("pkexec"):
                self.line.emit("pkexec not found, cannot escalate")
                return False
            cmd = ["pkexec", *cmd]

        self.line.emit(f"$ {' '.join(cmd)}")
        env = dict(os.environ, LC_ALL="C.UTF-8", DNF5_FORCE_INTERACTIVE="0")
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        assert self._proc.stdout is not None
        for raw in self._proc.stdout:
            if self._cancelled:
                break
            text = raw.rstrip()
            if text:
                self.line.emit(text)
        code = self._proc.wait()
        if code == 126:
            self.line.emit("Authorization dismissed")
        elif code != 0:
            self.line.emit(f"exited with status {code}")
        return code == 0

    def _run_appimage(self, backend: Backend, pkgs: list[Package]) -> bool:
        assert isinstance(backend, AppImageBackend)
        ok = True
        for pkg in pkgs:
            if self.action == Action.REMOVE:
                ok = self._appimage_remove(backend, pkg) and ok
            else:
                ok = self._appimage_install(backend, pkg) and ok
        return ok

    def _appimage_install(self, backend: AppImageBackend, pkg: Package) -> bool:
        self.line.emit(f"Resolving download for {pkg.name}")
        url, filename = backend.resolve_download(pkg)
        APPS_DIR.mkdir(parents=True, exist_ok=True)
        dest = APPS_DIR / filename
        tmp = dest.with_suffix(dest.suffix + ".part")
        self.line.emit(f"Downloading {url}")

        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as response:
            size = int(response.headers.get("Content-Length") or 0)
            done = 0
            mark = 0
            with open(tmp, "wb") as handle:
                while True:
                    if self._cancelled:
                        tmp.unlink(missing_ok=True)
                        return False
                    chunk = response.read(262144)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if size:
                        pct = int(done / size * 100)
                        if pct >= mark + 10:
                            mark = pct
                            self.line.emit(f"  {pct}%  {done // 1048576} MiB")

        tmp.replace(dest)
        os.chmod(dest, 0o755)
        version = filename
        backend.record_install(pkg, dest, version)
        entry = backend.desktop_entry(pkg, dest)
        self.line.emit(f"Installed {dest}")
        self.line.emit(f"Desktop entry {entry}")
        return True

    def _appimage_remove(self, backend: AppImageBackend, pkg: Package) -> bool:
        path = Path(pkg.extra.get("path", ""))
        if path.exists():
            path.unlink()
            self.line.emit(f"Deleted {path}")
        entry = Path.home() / f".local/share/applications/brim-{pkg.key}.desktop"
        if entry.exists():
            entry.unlink()
            self.line.emit(f"Deleted {entry}")
        backend.forget(pkg.key)
        return True


class CommandRunner(QThread):
    """One off commands: toggling a repo, adding a remote, enabling a COPR."""

    line = Signal(str)
    finished_ok = Signal(bool, str)

    def __init__(self, cmd: list[str], needs_root: bool, parent=None) -> None:
        super().__init__(parent)
        self.cmd = cmd
        self.needs_root = needs_root

    def run(self) -> None:
        cmd = list(self.cmd)
        if self.needs_root and os.geteuid() != 0:
            cmd = ["pkexec", *cmd]
        self.line.emit(f"$ {' '.join(cmd)}")
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=dict(os.environ, LC_ALL="C.UTF-8"),
                timeout=300,
            )
        except Exception as exc:
            self.finished_ok.emit(False, str(exc))
            return
        for stream in (proc.stdout, proc.stderr):
            for raw in (stream or "").splitlines():
                if raw.strip():
                    self.line.emit(raw.rstrip())
        if proc.returncode == 0:
            self.finished_ok.emit(True, "Done")
        else:
            self.finished_ok.emit(False, f"Exited with status {proc.returncode}")
