"""Main window: browse, sources, settings, tray, and the update loop."""

from __future__ import annotations

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QWidget,
)

from ..backends.base import Package
from ..core.transaction import Action, CommandRunner, TransactionRunner
from . import theme
from .browse_page import BrowsePage
from .output_dialog import OutputDialog
from .settings_page import SettingsPage
from .sources_page import SourcesPage

PAGE_BROWSE, PAGE_SOURCES, PAGE_SETTINGS = range(3)


class CatalogLoader(QThread):
    done = Signal(list, dict)

    def __init__(self, catalog, enabled: set[str]) -> None:
        super().__init__()
        self.catalog = catalog
        self.enabled = enabled

    def run(self) -> None:
        packages = self.catalog.reload(self.enabled)
        self.done.emit(packages, dict(self.catalog.errors))


class MainWindow(QMainWindow):
    def __init__(self, catalog, config) -> None:
        super().__init__()
        self.catalog = catalog
        self.config = config
        self.tray = None
        self._loader: CatalogLoader | None = None
        self._runner = None

        self.setWindowTitle("Brim")
        self.setWindowIcon(theme.icon("brim", "system-software-install"))
        self.resize(1240, 780)

        self.browse = BrowsePage(catalog, config, self)
        self.sources = SourcesPage(catalog, config, self)
        self.settings = SettingsPage(catalog, config, self)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.browse)
        self.stack.addWidget(self.sources)
        self.stack.addWidget(self.settings)
        self.setCentralWidget(self.stack)

        self._build_toolbar()
        self._build_statusbar()
        self._wire()

        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(lambda: self.reload(quiet=True))
        self._arm_timer()

    # construction

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(bar)

        self.act_browse = QAction(theme.icon("search"), "Browse", self)
        self.act_browse.setCheckable(True)
        self.act_browse.setChecked(True)
        self.act_browse.triggered.connect(lambda: self.go(PAGE_BROWSE))
        bar.addAction(self.act_browse)

        self.act_sources = QAction(theme.icon("folder-remote"), "Sources", self)
        self.act_sources.setCheckable(True)
        self.act_sources.triggered.connect(lambda: self.go(PAGE_SOURCES))
        bar.addAction(self.act_sources)

        self.act_settings = QAction(theme.icon("configure"), "Settings", self)
        self.act_settings.setCheckable(True)
        self.act_settings.triggered.connect(lambda: self.go(PAGE_SETTINGS))
        bar.addAction(self.act_settings)

        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding, spacer.sizePolicy().verticalPolicy())
        bar.addWidget(spacer)

        self.act_updates = QAction(
            theme.icon("system-software-update"), "Updates", self
        )
        self.act_updates.setToolTip("Show only packages with an update pending")
        self.act_updates.triggered.connect(self._show_updates)
        bar.addAction(self.act_updates)

        self.act_apply_all = QAction(theme.icon("download"), "Update all", self)
        self.act_apply_all.setEnabled(False)
        self.act_apply_all.triggered.connect(self.apply_all_updates)
        bar.addAction(self.act_apply_all)

        self.act_reload = QAction(theme.icon("view-refresh"), "Reload", self)
        self.act_reload.setShortcut(QKeySequence("F5"))
        self.act_reload.triggered.connect(lambda: self.reload())
        bar.addAction(self.act_reload)

    def _build_statusbar(self) -> None:
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_label = QLabel("Starting")
        self.status.addWidget(self.status_label, 1)
        self.update_label = QLabel("")
        self.status.addPermanentWidget(self.update_label)

    def _wire(self) -> None:
        self.browse.install_requested.connect(
            lambda pkgs: self.run_transaction(Action.INSTALL, pkgs)
        )
        self.browse.remove_requested.connect(
            lambda pkgs: self.run_transaction(Action.REMOVE, pkgs)
        )
        self.browse.upgrade_requested.connect(
            lambda pkgs: self.run_transaction(Action.UPGRADE, pkgs)
        )
        self.sources.run_command.connect(self.run_command)
        self.sources.refresh_requested.connect(lambda: self.reload())
        self.settings.backends_changed.connect(self._on_backends_changed)

    def attach_tray(self, tray) -> None:
        self.tray = tray
        tray.open_requested.connect(self.show_window)
        tray.updates_requested.connect(self._show_updates)
        tray.check_requested.connect(lambda: self.reload())
        tray.apply_all_requested.connect(self.apply_all_updates)
        tray.quit_requested.connect(self._really_quit)

    # navigation

    def go(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        self.act_browse.setChecked(page == PAGE_BROWSE)
        self.act_sources.setChecked(page == PAGE_SOURCES)
        self.act_settings.setChecked(page == PAGE_SETTINGS)
        if page == PAGE_SOURCES:
            self.sources.reload()

    def _show_updates(self) -> None:
        self.show_window()
        self.go(PAGE_BROWSE)
        self.browse.search.clear()
        self.browse.set_status("updates")

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # loading

    def enabled_backends(self) -> set[str]:
        return {
            bid
            for bid, backend in self.catalog.backends.items()
            if self.config.backend_enabled(bid) and backend.available
        }

    def reload(self, quiet: bool = False) -> None:
        if self._loader and self._loader.isRunning():
            return
        self.act_reload.setEnabled(False)
        if not quiet:
            self.status_label.setText("Reading every enabled source")
        self._loader = CatalogLoader(self.catalog, self.enabled_backends())
        self._loader.done.connect(lambda pkgs, errs: self._on_loaded(pkgs, errs, quiet))
        self._loader.start()

    def _on_loaded(self, packages: list, errors: dict, quiet: bool) -> None:
        self.act_reload.setEnabled(True)
        self.browse.set_packages(packages)

        updates = self.catalog.upgradable()
        count = len(updates)
        self.act_apply_all.setEnabled(bool(count))

        counts = self.catalog.counts()
        bits = [
            f"{theme.SOURCE_LABELS.get(bid, bid)} {slot['total']}"
            for bid, slot in sorted(counts.items())
        ]
        self.status_label.setText(
            f"{len(packages)} packages across {len(counts)} sources"
            + (f"  ({', '.join(bits)})" if bits else "")
        )

        if count:
            plural = "s" if count != 1 else ""
            self.update_label.setText(f"{count} update{plural}")
            self.update_label.setStyleSheet(
                f"color: {theme.state_color('upgradable').name()}; font-weight: 600;"
            )
        else:
            self.update_label.setText("Up to date")
            self.update_label.setStyleSheet("opacity: 0.7;")

        if self.tray:
            self.tray.set_update_count(count)
            if quiet and count and self.config.get("notify_updates"):
                self.tray.notify_updates(count)

        if errors:
            detail = "; ".join(f"{k}: {v[:80]}" for k, v in errors.items())
            self.status.showMessage(f"Some sources failed: {detail}", 12000)

        if quiet and count and self.config.get("auto_apply_updates"):
            self.apply_all_updates(unattended=True)

    def _on_backends_changed(self) -> None:
        for bid, chip in self.browse.chips.items():
            chip.blockSignals(True)
            chip.setChecked(self.config.backend_enabled(bid))
            chip.blockSignals(False)
        self.reload()

    def _arm_timer(self) -> None:
        minutes = int(self.config.get("check_interval_minutes") or 0)
        self.check_timer.stop()
        if minutes > 0:
            self.check_timer.start(minutes * 60 * 1000)

    # transactions

    def run_transaction(self, action: str, packages: list[Package]) -> None:
        packages = [p for p in packages if p]
        if not packages:
            return
        if self.config.get("confirm_transactions") and not self._confirm(action, packages):
            return

        dialog = OutputDialog(f"{action.title()} packages", self)
        self._runner = TransactionRunner(action, packages, self.catalog.backends, self)
        dialog.attach(self._runner)
        dialog.exec()
        self.browse.clear_selection()
        self.reload()

    def _confirm(self, action: str, packages: list[Package]) -> bool:
        names = "\n".join(
            f"  {p.name}  ({theme.SOURCE_LABELS.get(p.source, p.source)})"
            for p in packages[:14]
        )
        if len(packages) > 14:
            names += f"\n  and {len(packages) - 14} more"

        box = QMessageBox(self)
        box.setWindowTitle(f"{action.title()} {len(packages)} package(s)")
        box.setIcon(
            QMessageBox.Icon.Warning
            if action == Action.REMOVE
            else QMessageBox.Icon.Question
        )
        box.setText(f"{action.title()} the following?")
        box.setInformativeText(names)
        if any(self.catalog.backends[p.source].needs_root for p in packages):
            box.setDetailedText(
                "Anything from DNF or COPR runs through pkexec, so you will be "
                "asked to authenticate. Your dnf.conf rules, excludepkgs included, "
                "still apply."
            )
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        return box.exec() == QMessageBox.StandardButton.Yes

    def apply_all_updates(self, unattended: bool = False) -> None:
        updates = self.catalog.upgradable()
        if not updates:
            return
        if unattended:
            updates = [p for p in updates if not self.catalog.backends[p.source].needs_root]
            if not updates:
                return
        self.run_transaction(Action.UPGRADE, updates)

    def run_command(self, cmd: list, needs_root: bool, title: str) -> None:
        dialog = OutputDialog(title, self)
        self._runner = CommandRunner(cmd, needs_root, self)
        dialog.attach(self._runner)
        dialog.exec()
        self.sources.reload()
        self.reload()

    # lifecycle

    def closeEvent(self, event) -> None:
        if self.tray and self.config.get("close_to_tray") and self.tray.isVisible():
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "Brim",
                "Still running in the tray. Quit from the tray menu to exit.",
                theme.icon("brim", "system-software-install"),
                4000,
            )
            return
        event.accept()
        QApplication.quit()

    def _really_quit(self) -> None:
        if self.tray:
            self.tray.hide()
        QApplication.quit()
