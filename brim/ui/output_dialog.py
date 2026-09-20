"""Live transaction log.

Shows the real command and its real output. Nothing is hidden behind a
spinner, which is the point: you always know what touched your system.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
)

from . import theme


class OutputDialog(QDialog):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(760, 460)
        self._runner = None
        self._done = False

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.step = QLabel("Starting")
        font = self.step.font()
        font.setBold(True)
        self.step.setFont(font)
        layout.addWidget(self.step)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(6)
        layout.addWidget(self.bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("monospace", 9))
        self.log.setMaximumBlockCount(6000)
        layout.addWidget(self.log, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.rejected.connect(self._on_cancel)
        self.buttons.accepted.connect(self.accept)
        layout.addWidget(self.buttons)

    def attach(self, runner) -> None:
        """Wire a TransactionRunner or CommandRunner and start it."""
        self._runner = runner
        runner.line.connect(self.append)
        if hasattr(runner, "step"):
            runner.step.connect(self.step.setText)
        if hasattr(runner, "progress"):
            runner.progress.connect(self._on_progress)
        runner.finished_ok.connect(self._on_finished)
        runner.start()

    def append(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    def _on_progress(self, value: int) -> None:
        self.bar.setRange(0, 100)
        self.bar.setValue(value)

    def _on_cancel(self) -> None:
        if self._done:
            self.reject()
            return
        if self._runner and hasattr(self._runner, "cancel"):
            self.append("Cancelling")
            self._runner.cancel()

    def _on_finished(self, ok: bool, message: str) -> None:
        self._done = True
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        colour = theme.state_color("installed" if ok else "upgradable")
        self.step.setText(message)
        self.step.setStyleSheet(f"color: {colour.name()};")
        self.append("")
        self.append(message)
        self.buttons.setStandardButtons(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        self.setResult(QDialog.DialogCode.Accepted if ok else QDialog.DialogCode.Rejected)

    def succeeded(self) -> bool:
        return self.result() == QDialog.DialogCode.Accepted
