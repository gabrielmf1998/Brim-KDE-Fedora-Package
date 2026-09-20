"""Application bootstrap."""

from __future__ import annotations

import argparse
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QStyleFactory, QSystemTrayIcon

from .backends.appimage import AppImageBackend
from .backends.copr import CoprBackend
from .backends.dnf import DnfBackend
from .backends.flatpak import FlatpakBackend
from .core.catalog import Catalog
from .core.config import Config
from .core.launcher import repair as repair_launchers
from .ui.main_window import MainWindow
from .ui.threads import any_running, exit_now, stop_registered
from .ui.tray import Tray


def build_catalog() -> Catalog:
    dnf = DnfBackend()
    copr = CoprBackend()

    # COPR needs to know which of its projects are already wired into dnf so it
    # can say so instead of offering to enable them twice.
    def sync_copr_state() -> None:
        try:
            copr.enabled_repo_ids = {s.key for s in dnf.sources() if s.enabled}
        except Exception:
            copr.enabled_repo_ids = set()

    catalog = Catalog([dnf, FlatpakBackend(), copr, AppImageBackend()])
    catalog.sync_copr_state = sync_copr_state
    return catalog


def apply_style(app: QApplication) -> None:
    """Prefer Breeze so Brim matches the rest of Plasma out of the box."""
    if "Breeze" in QStyleFactory.keys():
        app.setStyle("Breeze")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="brim", description="Unified package manager for Fedora"
    )
    parser.add_argument(
        "--tray", action="store_true", help="start hidden in the system tray"
    )
    parser.add_argument(
        "--version", action="store_true", help="print the revision and exit"
    )
    args = parser.parse_args(argv)

    if args.version:
        from .core import updater

        print(f"brim {updater.current_describe()}")
        return 0

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setApplicationName("Brim")
    app.setApplicationDisplayName("Brim")
    app.setDesktopFileName("brim")
    app.setQuitOnLastWindowClosed(False)
    apply_style(app)

    # A launcher left pointing at a deleted AppImage fails before Brim even
    # starts, so the one place that can fix it is the copy that did start.
    for cleared in repair_launchers():
        print(f"brim: removed a broken launcher at {cleared}", file=sys.stderr)

    config = Config()
    catalog = build_catalog()
    window = MainWindow(catalog, config)

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = Tray(window)
        window.attach_tray(tray)
        tray.show()
    else:
        app.setQuitOnLastWindowClosed(True)

    start_hidden = args.tray or config.get("start_in_tray")
    if not (start_hidden and QSystemTrayIcon.isSystemTrayAvailable()):
        window.show()

    QTimer.singleShot(60, lambda: window.reload(quiet=start_hidden))
    if config.get("self_update_mode") in ("startup", "interval"):
        QTimer.singleShot(4500, lambda: window.settings.check_self_update(silent=True))

    def shutdown() -> None:
        window.shutdown()
        # Catches workers owned by dialogs, which the window cannot see.
        stop_registered()

    app.aboutToQuit.connect(shutdown)
    code = app.exec()

    # If a worker is still stuck inside a C call, letting Qt tear down would
    # abort on ~QThread. Exiting directly is the safe way out; every setting
    # was already written when it changed.
    if any_running():
        exit_now(code)
    return code
