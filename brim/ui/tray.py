"""System tray presence, update badge and quick actions."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import theme


class Tray(QSystemTrayIcon):
    open_requested = Signal()
    updates_requested = Signal()
    check_requested = Signal()
    apply_all_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._base = theme.icon("brim", "system-software-install")
        self.setIcon(self._base)
        self.setToolTip("Brim")

        menu = QMenu()
        self.act_open = QAction(theme.icon("window"), "Open Brim", menu)
        self.act_open.triggered.connect(self.open_requested.emit)
        menu.addAction(self.act_open)

        self.act_updates = QAction(
            theme.icon("system-software-update"), "No updates pending", menu
        )
        self.act_updates.setEnabled(False)
        self.act_updates.triggered.connect(self.updates_requested.emit)
        menu.addAction(self.act_updates)

        self.act_apply = QAction(theme.icon("download"), "Update everything", menu)
        self.act_apply.setEnabled(False)
        self.act_apply.triggered.connect(self.apply_all_requested.emit)
        menu.addAction(self.act_apply)

        menu.addSeparator()
        act_check = QAction(theme.icon("view-refresh"), "Check now", menu)
        act_check.triggered.connect(self.check_requested.emit)
        menu.addAction(act_check)

        menu.addSeparator()
        act_quit = QAction(theme.icon("application-exit"), "Quit", menu)
        act_quit.triggered.connect(self.quit_requested.emit)
        menu.addAction(act_quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()

    def set_update_count(self, count: int) -> None:
        if count:
            plural = "s" if count != 1 else ""
            self.act_updates.setText(f"{count} update{plural} available")
            self.act_updates.setEnabled(True)
            self.act_apply.setEnabled(True)
            self.setToolTip(f"Brim: {count} update{plural} available")
            self.setIcon(self._badged(count))
        else:
            self.act_updates.setText("No updates pending")
            self.act_updates.setEnabled(False)
            self.act_apply.setEnabled(False)
            self.setToolTip("Brim: everything is current")
            self.setIcon(self._base)

    def _badged(self, count: int) -> QIcon:
        """Paint a small counter over the tray icon."""
        size = 64
        pixmap = self._base.pixmap(size, size)
        if pixmap.isNull():
            return self._base
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = theme.state_color("upgradable")
        radius = size // 2.6
        painter.setBrush(colour)
        painter.setPen(colour)
        painter.drawEllipse(int(size - radius), 0, int(radius), int(radius))
        painter.setPen(theme.QColor("white") if colour.lightness() < 160 else theme.QColor("black"))
        font = painter.font()
        font.setPixelSize(int(radius * 0.78))
        font.setBold(True)
        painter.setFont(font)
        text = "9+" if count > 9 else str(count)
        painter.drawText(
            int(size - radius),
            0,
            int(radius),
            int(radius),
            0x0084,
            text,
        )
        painter.end()
        return QIcon(pixmap)

    def notify_updates(self, count: int) -> None:
        if not count:
            return
        plural = "s" if count != 1 else ""
        self.showMessage(
            "Brim",
            f"{count} update{plural} ready to install",
            theme.icon("system-software-update"),
            8000,
        )
