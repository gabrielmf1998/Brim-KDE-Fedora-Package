"""Let the user say where a hand installed package actually comes from."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class SideloadMapDialog(QDialog):
    def __init__(self, mapping: dict, skipped: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Where these packages come from")
        self.setMinimumSize(680, 420)
        self._mapping = dict(mapping)

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Brim could not work out a project page for these. Give it one and "
            "it will check them from then on.<br>"
            "Use <code>github:owner/repo</code> or <code>gitlab:owner/repo</code>. "
            "Leave a row blank to keep ignoring it."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(intro)

        names = sorted(set(skipped) | set(self._mapping))
        self.table = QTableWidget(len(names), 3, self)
        self.table.setHorizontalHeaderLabels(["Package", "Repository", "Why it was skipped"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        for row, name in enumerate(names):
            locked = QTableWidgetItem(name)
            locked.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 0, locked)
            self.table.setItem(row, 1, QTableWidgetItem(self._mapping.get(name, "")))
            reason = QTableWidgetItem(skipped.get(name, ""))
            reason.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 2, reason)

        layout.addWidget(self.table, 1)

        if not names:
            layout.addWidget(
                QLabel(
                    "Nothing needs mapping. Every hand installed package either "
                    "records its project page or is deliberately left alone."
                )
            )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def mapping(self) -> dict:
        out = {}
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text()
            value = (self.table.item(row, 1).text() or "").strip()
            if value:
                out[name] = value
        return out
