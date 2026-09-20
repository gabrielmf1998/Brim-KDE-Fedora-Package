"""Table model over the merged package list.

Filtering rebuilds a visible index list rather than going through a proxy,
which keeps a 76000 row catalog responsive while typing.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

from ..backends.base import Package, State
from . import theme

COLUMNS = ["", "Name", "Version", "Source", "Origin", "Status", "Size"]
COL_CHECK, COL_NAME, COL_VERSION, COL_SOURCE, COL_ORIGIN, COL_STATUS, COL_SIZE = range(7)

STATUS_TEXT = {
    State.INSTALLED: "Installed",
    State.AVAILABLE: "Available",
    State.UPGRADABLE: "Update",
}


class PackageModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._all: list[Package] = []
        self._rows: list[Package] = []
        self._checked: set[str] = set()

    # data plumbing

    def set_packages(self, packages: list[Package]) -> None:
        self.beginResetModel()
        self._all = packages
        self._rows = packages
        self.endResetModel()

    def all_packages(self) -> list[Package]:
        return self._all

    def package_at(self, row: int) -> Package | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def flags(self, index):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_CHECK:
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        pkg = self._rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.CheckStateRole and col == COL_CHECK:
            return (
                Qt.CheckState.Checked
                if self.unique_key(pkg) in self._checked
                else Qt.CheckState.Unchecked
            )

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                return pkg.name
            if col == COL_VERSION:
                return pkg.version_diff
            if col == COL_SOURCE:
                return theme.SOURCE_LABELS.get(pkg.source, pkg.source)
            if col == COL_ORIGIN:
                return pkg.origin
            if col == COL_STATUS:
                return STATUS_TEXT.get(pkg.state, "")
            if col == COL_SIZE:
                return theme.human_size(pkg.size)
            return None

        if role == Qt.ItemDataRole.DecorationRole and col == COL_SOURCE:
            return theme.source_icon(pkg.source)

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == COL_SOURCE:
                return theme.source_color(pkg.source)
            if col == COL_STATUS:
                return theme.state_color(pkg.state.value)
            if col == COL_VERSION and pkg.upgradable:
                return theme.state_color("upgradable")

        if role == Qt.ItemDataRole.FontRole and col == COL_NAME:
            if pkg.installed:
                font = QFont()
                font.setBold(True)
                return font

        if role == Qt.ItemDataRole.ToolTipRole:
            bits = [f"<b>{pkg.name}</b>", pkg.summary]
            if pkg.upgradable:
                bits.append(f"Update: {pkg.installed_version} to {pkg.version}")
            bits.append(f"From {pkg.origin}")
            return "<br>".join(b for b in bits if b)

        if role == Qt.ItemDataRole.TextAlignmentRole and col == COL_SIZE:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == COL_CHECK:
            pkg = self._rows[index.row()]
            key = self.unique_key(pkg)
            if Qt.CheckState(value) == Qt.CheckState.Checked:
                self._checked.add(key)
            else:
                self._checked.discard(key)
            self.dataChanged.emit(index, index, [role])
            return True
        return False

    # selection

    @staticmethod
    def unique_key(pkg: Package) -> str:
        return f"{pkg.source}::{pkg.key}"

    def checked_packages(self) -> list[Package]:
        return [p for p in self._all if self.unique_key(p) in self._checked]

    def clear_checks(self) -> None:
        if not self._checked:
            return
        self._checked.clear()
        if self._rows:
            top = self.index(0, COL_CHECK)
            bottom = self.index(len(self._rows) - 1, COL_CHECK)
            self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.CheckStateRole])

    def check_all_visible(self) -> None:
        for pkg in self._rows:
            self._checked.add(self.unique_key(pkg))
        if self._rows:
            top = self.index(0, COL_CHECK)
            bottom = self.index(len(self._rows) - 1, COL_CHECK)
            self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.CheckStateRole])

    # filtering

    def apply_filter(
        self,
        text: str,
        sources: set[str],
        status: str,
        extra: list[Package] | None = None,
    ) -> int:
        """Rebuild the visible rows. `extra` carries live network results."""
        needle = text.strip().lower()
        pool = self._all if not extra else self._all + extra

        rows: list[Package] = []
        for pkg in pool:
            if pkg.source not in sources:
                continue
            if status == "installed" and not pkg.installed:
                continue
            if status == "available" and pkg.installed:
                continue
            if status == "updates" and not pkg.upgradable:
                continue
            if needle:
                if needle not in pkg.name.lower() and needle not in pkg.summary.lower():
                    continue
            rows.append(pkg)

        if needle:
            def rank(p: Package) -> tuple:
                low = p.name.lower()
                return (
                    0 if low == needle else 1 if low.startswith(needle) else 2,
                    0 if p.installed else 1,
                    low,
                )

            rows.sort(key=rank)
        else:
            rows.sort(key=lambda p: (0 if p.upgradable else 1, p.name.lower()))

        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        return len(rows)
