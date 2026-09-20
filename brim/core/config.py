"""Persisted settings, kept in plain JSON under the XDG config dir."""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "brim"
CONFIG_FILE = CONFIG_DIR / "config.json"
AUTOSTART_DIR = Path.home() / ".config/autostart"
AUTOSTART_FILE = AUTOSTART_DIR / "brim.desktop"

DEFAULTS: dict = {
    "backends": {"dnf": True, "flatpak": True, "copr": True, "appimage": True},
    "start_in_tray": False,
    "close_to_tray": True,
    "check_updates_on_start": True,
    "check_interval_minutes": 180,
    "notify_updates": True,
    "auto_apply_updates": False,
    "self_update_url": "",
    "self_update_check": True,
    "confirm_transactions": True,
}


class Config:
    def __init__(self) -> None:
        self._data = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            stored = json.loads(CONFIG_FILE.read_text())
            for key, value in stored.items():
                if key in DEFAULTS and isinstance(value, type(DEFAULTS[key])):
                    self._data[key] = value
        except Exception:
            pass

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self._data, indent=2))

    def get(self, key: str, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self.save()

    def backend_enabled(self, backend_id: str) -> bool:
        return bool(self.get("backends", {}).get(backend_id, True))

    def set_backend_enabled(self, backend_id: str, value: bool) -> None:
        backends = dict(self.get("backends", {}))
        backends[backend_id] = value
        self.set("backends", backends)

    @property
    def autostart(self) -> bool:
        return AUTOSTART_FILE.exists()

    def set_autostart(self, enabled: bool, exec_path: str) -> None:
        if not enabled:
            AUTOSTART_FILE.unlink(missing_ok=True)
            return
        AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
        AUTOSTART_FILE.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Brim\n"
            "Comment=Unified package manager for Fedora\n"
            f"Exec={exec_path} --tray\n"
            "Icon=brim\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
