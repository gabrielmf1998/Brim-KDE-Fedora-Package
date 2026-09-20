"""Preferences, autostart, and the self update controls."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from ..core.config import SELF_UPDATE_MODES
from . import theme


class SettingsPage(QWidget):
    backends_changed = Signal()
    update_available = Signal(bool, str)
    update_mode_changed = Signal()

    def __init__(self, catalog, config, parent=None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.config = config
        self._check_thread = None
        self._apply_thread = None
        self._pending = None

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
        self.lbl_version.setWordWrap(True)
        layout.addWidget(self.lbl_version)

        form = QFormLayout()
        self.combo_mode = QComboBox()
        for key, label in SELF_UPDATE_MODES:
            self.combo_mode.addItem(label, key)
        current = self.config.get("self_update_mode")
        index = self.combo_mode.findData(current)
        self.combo_mode.setCurrentIndex(index if index >= 0 else 1)
        self.combo_mode.currentIndexChanged.connect(self._mode_changed)
        form.addRow("Check for a new Brim", self.combo_mode)

        self.spin_self = QSpinBox()
        self.spin_self.setRange(1, 720)
        self.spin_self.setSuffix(" hours")
        self.spin_self.setValue(int(self.config.get("self_update_interval_hours")))
        self.spin_self.valueChanged.connect(
            lambda v: self.config.set("self_update_interval_hours", v)
        )
        form.addRow("Every", self.spin_self)
        layout.addLayout(form)

        self.chk_self_notify = QCheckBox("Tell me in the tray when a new Brim is out")
        self.chk_self_notify.setChecked(self.config.get("self_update_notify"))
        self.chk_self_notify.toggled.connect(
            lambda v: self.config.set("self_update_notify", v)
        )
        layout.addWidget(self.chk_self_notify)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_status.setOpenExternalLinks(True)
        self.lbl_status.setStyleSheet("opacity: 0.85;")
        layout.addWidget(self.lbl_status)

        row = QHBoxLayout()
        self.btn_check = QPushButton("Check now")
        self.btn_check.setIcon(theme.icon("view-refresh"))
        self.btn_check.clicked.connect(lambda: self.check_self_update(False))
        row.addWidget(self.btn_check)

        self.btn_apply = QPushButton("Update Brim")
        self.btn_apply.setIcon(theme.icon("system-software-update"))
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.apply_self_update)
        row.addWidget(self.btn_apply)
        row.addStretch(1)
        layout.addLayout(row)

        self._mode_changed()
        return box

    def _mode_changed(self) -> None:
        mode = self.combo_mode.currentData()
        self.config.set("self_update_mode", mode)
        self.spin_self.setEnabled(mode == "interval")
        self.update_mode_changed.emit()

    def _refresh_version(self) -> None:
        self.lbl_version.setText(
            f"Brim <b>{updater.current_describe()}</b>, "
            f"{updater.install_kind_label()}."
        )

    def check_self_update(self, silent: bool = True) -> None:
        if self._check_thread and self._check_thread.isRunning():
            return
        self.btn_check.setEnabled(False)
        if not silent:
            self.lbl_status.setText("Checking GitHub, then GitLab")
        self._check_thread = updater.UpdateCheck()
        self._check_thread.result.connect(
            lambda ok, release, msg: self._on_check(ok, release, msg, silent)
        )
        self._check_thread.start()

    def _on_check(self, ok: bool, release, message: str, silent: bool) -> None:
        self.btn_check.setEnabled(True)
        self._pending = release

        if not ok:
            self.lbl_status.setText(
                "" if silent else f"<span style='opacity:0.8'>{message}</span>"
            )
            self.btn_apply.setEnabled(False)
            return

        if release is None:
            self.lbl_status.setText(message)
            self.btn_apply.setEnabled(False)
            self.update_available.emit(False, "")
            return

        colour = theme.state_color("upgradable").name()
        notes = (release.notes or "").strip()
        if len(notes) > 600:
            notes = notes[:600] + "..."
        safe = notes.replace("<", "&lt;").replace(">", "&gt;").replace(chr(10), "<br>")
        link = (
            f"<br><a href='{release.url}'>Release page</a>" if release.url else ""
        )
        self.lbl_status.setText(
            f"<span style='color:{colour};font-weight:600;'>"
            f"Brim {release.version} is available</span>"
            f" <span style='opacity:0.7'>via {release.host}</span>"
            f"{'<br>' + safe if safe else ''}{link}"
        )
        self.btn_apply.setEnabled(True)
        self.update_available.emit(True, str(release.version))

    def apply_self_update(self) -> None:
        from .output_dialog import OutputDialog

        dialog = OutputDialog("Updating Brim", self)
        self._apply_thread = updater.UpdateApply(self._pending)
        dialog.attach(self._apply_thread)
        dialog.exec()
        self._refresh_version()
        self.btn_apply.setEnabled(False)
