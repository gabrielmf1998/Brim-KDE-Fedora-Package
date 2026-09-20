"""Preferences, autostart, and the self update controls."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core import updater
from . import theme


class SettingsPage(QWidget):
    backends_changed = Signal()

    def __init__(self, catalog, config, parent=None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.config = config
        self._check_thread = None
        self._apply_thread = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        layout.addWidget(self._build_sources())
        layout.addWidget(self._build_window())
        layout.addWidget(self._build_updates())
        layout.addWidget(self._build_self_update())
        layout.addStretch(1)

    def _build_sources(self) -> QGroupBox:
        box = QGroupBox("Sources Brim watches")
        layout = QVBoxLayout(box)
        self.backend_boxes = {}
        for bid, backend in self.catalog.backends.items():
            check = QCheckBox(f"{backend.label}")
            check.setIcon(theme.source_icon(bid))
            check.setChecked(self.config.backend_enabled(bid))
            if not backend.available:
                check.setEnabled(False)
                check.setChecked(False)
                check.setText(f"{backend.label} (not installed on this system)")
            check.toggled.connect(
                lambda value, key=bid: self._set_backend(key, value)
            )
            self.backend_boxes[bid] = check
            layout.addWidget(check)
        return box

    def _set_backend(self, bid: str, value: bool) -> None:
        self.config.set_backend_enabled(bid, value)
        self.backends_changed.emit()

    def _build_window(self) -> QGroupBox:
        box = QGroupBox("Window and startup")
        layout = QVBoxLayout(box)

        self.chk_autostart = QCheckBox("Start Brim when I log in")
        self.chk_autostart.setChecked(self.config.autostart)
        self.chk_autostart.toggled.connect(self._toggle_autostart)
        layout.addWidget(self.chk_autostart)

        self.chk_tray = QCheckBox("Start minimised to the tray")
        self.chk_tray.setChecked(self.config.get("start_in_tray"))
        self.chk_tray.toggled.connect(lambda v: self.config.set("start_in_tray", v))
        layout.addWidget(self.chk_tray)

        self.chk_close = QCheckBox("Closing the window keeps Brim in the tray")
        self.chk_close.setChecked(self.config.get("close_to_tray"))
        self.chk_close.toggled.connect(lambda v: self.config.set("close_to_tray", v))
        layout.addWidget(self.chk_close)

        self.chk_confirm = QCheckBox("Ask before applying a transaction")
        self.chk_confirm.setChecked(self.config.get("confirm_transactions"))
        self.chk_confirm.toggled.connect(
            lambda v: self.config.set("confirm_transactions", v)
        )
        layout.addWidget(self.chk_confirm)
        return box

    def _toggle_autostart(self, value: bool) -> None:
        launcher = Path(__file__).resolve().parent.parent.parent / "brim.sh"
        exec_path = str(launcher) if launcher.exists() else f"{sys.executable} -m brim"
        self.config.set_autostart(value, exec_path)

    def _build_updates(self) -> QGroupBox:
        box = QGroupBox("Package updates")
        layout = QVBoxLayout(box)

        self.chk_check_start = QCheckBox("Check for updates when Brim starts")
        self.chk_check_start.setChecked(self.config.get("check_updates_on_start"))
        self.chk_check_start.toggled.connect(
            lambda v: self.config.set("check_updates_on_start", v)
        )
        layout.addWidget(self.chk_check_start)

        form = QFormLayout()
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(0, 1440)
        self.spin_interval.setSuffix(" minutes")
        self.spin_interval.setSpecialValueText("Never")
        self.spin_interval.setValue(int(self.config.get("check_interval_minutes")))
        self.spin_interval.valueChanged.connect(
            lambda v: self.config.set("check_interval_minutes", v)
        )
        form.addRow("Check again every", self.spin_interval)
        layout.addLayout(form)

        self.chk_notify = QCheckBox("Show a tray notification when updates arrive")
        self.chk_notify.setChecked(self.config.get("notify_updates"))
        self.chk_notify.toggled.connect(lambda v: self.config.set("notify_updates", v))
        layout.addWidget(self.chk_notify)

        self.chk_auto = QCheckBox("Apply updates automatically in the background")
        self.chk_auto.setChecked(self.config.get("auto_apply_updates"))
        self.chk_auto.toggled.connect(self._toggle_auto_apply)
        layout.addWidget(self.chk_auto)

        warn = QLabel(
            "Automatic mode still raises a polkit prompt for anything touching RPM, "
            "so it only runs unattended for Flatpak and AppImage."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("opacity: 0.7;")
        layout.addWidget(warn)
        return box

    def _toggle_auto_apply(self, value: bool) -> None:
        self.config.set("auto_apply_updates", value)

    def _build_self_update(self) -> QGroupBox:
        box = QGroupBox("Brim itself")
        layout = QVBoxLayout(box)

        self.lbl_version = QLabel()
        self._refresh_version()
        layout.addWidget(self.lbl_version)

        self.chk_self_check = QCheckBox("Check for a new Brim on startup")
        self.chk_self_check.setChecked(self.config.get("self_update_check"))
        self.chk_self_check.toggled.connect(
            lambda v: self.config.set("self_update_check", v)
        )
        layout.addWidget(self.chk_self_check)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("opacity: 0.8;")
        layout.addWidget(self.lbl_status)

        row = QHBoxLayout()
        self.btn_check = QPushButton("Check for updates")
        self.btn_check.setIcon(theme.icon("view-refresh"))
        self.btn_check.clicked.connect(self.check_self_update)
        row.addWidget(self.btn_check)

        self.btn_apply = QPushButton("Update Brim")
        self.btn_apply.setIcon(theme.icon("system-software-update"))
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.apply_self_update)
        row.addWidget(self.btn_apply)
        row.addStretch(1)
        layout.addLayout(row)
        return box

    def _refresh_version(self) -> None:
        if updater.is_git_checkout():
            self.lbl_version.setText(
                f"Running from a git checkout at revision <b>{updater.current_describe()}</b>"
            )
        else:
            self.lbl_version.setText(
                "Not running from a git checkout, so self update is unavailable."
            )

    def check_self_update(self, silent: bool = False) -> None:
        if self._check_thread and self._check_thread.isRunning():
            return
        self.btn_check.setEnabled(False)
        self.lbl_status.setText("Checking the remote")
        self._check_thread = updater.UpdateCheck()
        self._check_thread.result.connect(
            lambda ok, behind, msg: self._on_check(ok, behind, msg, silent)
        )
        self._check_thread.start()

    def _on_check(self, ok: bool, behind: int, message: str, silent: bool) -> None:
        self.btn_check.setEnabled(True)
        if not ok:
            self.lbl_status.setText(message)
            self.btn_apply.setEnabled(False)
            return
        if behind:
            self.lbl_status.setText(
                f"<b>{behind} new commit{'s' if behind > 1 else ''} upstream</b><br>"
                f"<code>{message.replace(chr(10), '<br>')}</code>"
            )
            self.btn_apply.setEnabled(True)
        else:
            self.lbl_status.setText(message)
            self.btn_apply.setEnabled(False)

    def apply_self_update(self) -> None:
        from .output_dialog import OutputDialog

        dialog = OutputDialog("Updating Brim", self)
        self._apply_thread = updater.UpdateApply()
        dialog.attach(self._apply_thread)
        dialog.exec()
        self._refresh_version()
        self.btn_apply.setEnabled(False)
