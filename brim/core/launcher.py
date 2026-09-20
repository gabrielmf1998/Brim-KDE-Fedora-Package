"""Keeping the menu entry honest.

A user level desktop entry shadows the system one, because XDG searches
~/.local/share/applications first. Install the RPM over an older AppImage
setup, or delete an AppImage by hand, and the menu keeps pointing at a file
that is no longer there:

    Launching Brim (Failed)
    Could not find the program '/home/you/Applications/Brim-1.0.2-x86_64.AppImage'

Brim checks its own launcher on startup and clears it when, and only when,
the target does not exist. A working entry is never touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

USER_DESKTOP = Path.home() / ".local/share/applications/brim.desktop"
USER_BIN = Path.home() / ".local/bin/brim"
AUTOSTART = Path.home() / ".config/autostart/brim.desktop"


def _exec_target(entry: Path) -> Path | None:
    """The program a desktop entry would actually run."""
    try:
        for line in entry.read_text().splitlines():
            if line.startswith("Exec="):
                command = line[5:].strip()
                # Drop the field codes desktop entries carry: %U, %f, and so on.
                parts = [p for p in command.split() if not p.startswith("%")]
                if parts:
                    return Path(parts[0])
    except OSError:
        return None
    return None


def _broken(entry: Path) -> bool:
    if not entry.exists():
        return False
    target = _exec_target(entry)
    if target is None:
        return False
    if target.is_absolute():
        return not target.exists()
    return shutil.which(str(target)) is None


def repair() -> list[str]:
    """Remove launchers whose target is gone. Returns what was cleared."""
    cleared: list[str] = []

    for entry in (USER_DESKTOP, AUTOSTART):
        if _broken(entry):
            try:
                entry.unlink()
                cleared.append(str(entry))
            except OSError:
                pass

    # A dangling symlink in ~/.local/bin shadows /usr/bin on most setups.
    try:
        if USER_BIN.is_symlink() and not USER_BIN.exists():
            USER_BIN.unlink()
            cleared.append(str(USER_BIN))
    except OSError:
        pass

    if cleared and shutil.which("update-desktop-database"):
        try:
            subprocess.run(
                ["update-desktop-database", str(USER_DESKTOP.parent)],
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    return cleared
