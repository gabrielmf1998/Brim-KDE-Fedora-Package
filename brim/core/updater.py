"""Self update.

Brim keeps itself current straight from its git checkout, so shipping a new
version is a push. Works both for a clone the user runs in place and for one
Brim manages under the XDG data dir.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, Signal

ROOT = Path(__file__).resolve().parent.parent.parent


def _git(*args: str, cwd: Path = ROOT, timeout: int = 60) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def is_git_checkout() -> bool:
    return (ROOT / ".git").exists()


def has_remote() -> bool:
    code, out = _git("remote")
    return code == 0 and bool(out.strip())


def current_revision() -> str:
    code, out = _git("rev-parse", "--short", "HEAD")
    return out if code == 0 else "unknown"


def current_describe() -> str:
    code, out = _git("describe", "--tags", "--always", "--dirty")
    return out if code == 0 else current_revision()


class UpdateCheck(QThread):
    """Fetches and reports how many commits upstream is ahead."""

    result = Signal(bool, int, str)

    def run(self) -> None:
        if not is_git_checkout():
            self.result.emit(False, 0, "Not running from a git checkout")
            return
        if not has_remote():
            self.result.emit(False, 0, "No git remote configured")
            return

        code, out = _git("fetch", "--quiet", timeout=90)
        if code != 0:
            self.result.emit(False, 0, f"Fetch failed: {out[:200]}")
            return

        code, branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        if code != 0:
            self.result.emit(False, 0, "Could not read the current branch")
            return

        code, out = _git("rev-list", "--count", f"HEAD..origin/{branch}")
        if code != 0:
            self.result.emit(False, 0, f"No upstream branch for {branch}")
            return

        try:
            behind = int(out.strip() or "0")
        except ValueError:
            behind = 0

        if behind:
            _, log = _git("log", "--oneline", f"HEAD..origin/{branch}", "-5")
            self.result.emit(True, behind, log)
        else:
            self.result.emit(True, 0, "Brim is up to date")


class UpdateApply(QThread):
    """Fast forwards the checkout. Refuses to clobber local edits."""

    line = Signal(str)
    finished_ok = Signal(bool, str)

    def run(self) -> None:
        code, dirty = _git("status", "--porcelain")
        if code == 0 and dirty.strip():
            self.finished_ok.emit(
                False, "Local changes present. Commit or stash them first."
            )
            return

        self.line.emit("Pulling the latest revision")
        code, out = _git("pull", "--ff-only", timeout=120)
        for raw in out.splitlines():
            if raw.strip():
                self.line.emit(raw)
        if code != 0:
            self.finished_ok.emit(False, "Pull failed, see the log above")
            return
        self.finished_ok.emit(True, f"Updated to {current_describe()}. Restart Brim.")
