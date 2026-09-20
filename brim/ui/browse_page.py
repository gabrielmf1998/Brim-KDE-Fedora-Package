"""The browse screen: search, source chips, results, details."""

from __future__ import annotations

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..backends.base import Package
from . import theme
from .details import DetailsPane
from .models import COL_CHECK, COL_NAME, COL_ORIGIN, COL_SIZE, PackageModel

STATUSES = [
    ("all", "All", "view-list-details"),
    ("installed", "Installed", "dialog-ok"),
    ("available", "Not installed", "list-add"),
    ("updates", "Updates", "system-software-update"),
]


class RemoteSearch(QThread):
    """Queries the network catalogs without blocking typing."""

    done = Signal(str, list)

    def __init__(self, catalog, query: str, sources: set[str]) -> None:
        super().__init__()
        self.catalog = catalog
        self.query = query
        self.sources = sources

    def run(self) -> None:
        try:
            found = self.catalog.search_remote(self.query, self.sources)
        except Exception:
            found = []
        self.done.emit(self.query, found)


class SourceChip(QPushButton):
    """One toggleable source filter, tinted with that source's hue."""

    def __init__(self, source_id: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self.source_id = source_id
        self.base_label = label
        self.setCheckable(True)
        self.setChecked(True)
        self.setIcon(theme.source_icon(source_id))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(30)
        self.set_count(0, 0)
        self.restyle()

    def set_count(self, total: int, updates: int) -> None:
        text = self.base_label
        if total:
            text += f"  {total}"
        if updates:
            text += f"  ({updates} new)"
        self.setText(text)

    def set_unavailable(self, reason: str) -> None:
        self.setEnabled(False)
        self.setChecked(False)
        self.setToolTip(reason)

    def restyle(self) -> None:
        tint = theme.source_tint(self.source_id)
        fg = theme.source_color(self.source_id)
        self.setStyleSheet(
            f"""
            QPushButton {{
                border: 1px solid palette(mid);
                border-radius: 15px;
                padding: 4px 14px;
                background: transparent;
            }}
            QPushButton:checked {{
                background: {tint.name()};
                border-color: {fg.name()};
                color: {fg.name()};
                font-weight: 600;
            }}
            QPushButton:disabled {{ opacity: 0.4; }}
            """
        )


class BrowsePage(QWidget):
    selection_changed = Signal(int)
    install_requested = Signal(list)
    remove_requested = Signal(list)
    upgrade_requested = Signal(list)

    def __init__(self, catalog, config, parent=None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.config = config
        self.status = "all"
        self._remote: list[Package] = []
        self._search_thread: RemoteSearch | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addLayout(self._build_search())
        root.addLayout(self._build_chips())
        root.addLayout(self._build_status())

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self._build_table())
        self.details = DetailsPane()
        self.splitter.addWidget(self.details)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([760, 420])
        root.addWidget(self.splitter, 1)

        root.addLayout(self._build_actions())

        self.details.install_requested.connect(lambda p: self.install_requested.emit([p]))
        self.details.remove_requested.connect(lambda p: self.remove_requested.emit([p]))
        self.details.upgrade_requested.connect(lambda p: self.upgrade_requested.emit([p]))

        QShortcut(QKeySequence("Ctrl+F"), self, self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+L"), self, self.search.clear)

    # construction helpers

    def _build_search(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Search every source at once. Try steam, obs, prismlauncher"
        )
        self.search.setClearButtonEnabled(True)
        self.search.addAction(
            theme.icon("search"), QLineEdit.ActionPosition.LeadingPosition
        )
        self.search.setMinimumHeight(36)
        font = self.search.font()
        font.setPointSize(font.pointSize() + 1)
        self.search.setFont(font)
        row.addWidget(self.search, 1)

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(220)
        self.debounce.timeout.connect(self.refilter)
        self.search.textChanged.connect(lambda _: self.debounce.start())

        self.remote_timer = QTimer(self)
        self.remote_timer.setSingleShot(True)
        self.remote_timer.setInterval(650)
        self.remote_timer.timeout.connect(self._start_remote_search)
        self.search.textChanged.connect(lambda _: self.remote_timer.start())
        return row

    def _build_chips(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("Sources")
        label.setStyleSheet("opacity: 0.7;")
        row.addWidget(label)

        self.chips: dict[str, SourceChip] = {}
        for bid, backend in self.catalog.backends.items():
            chip = SourceChip(bid, backend.label)
            chip.setChecked(self.config.backend_enabled(bid))
            if not backend.available:
                chip.set_unavailable(f"{backend.label} is not installed on this system")
            chip.toggled.connect(self._on_chip_toggled)
            self.chips[bid] = chip
            row.addWidget(chip)

        row.addStretch(1)
        self.remote_note = QLabel("")
        self.remote_note.setStyleSheet("opacity: 0.7;")
        row.addWidget(self.remote_note)
        return row

    def _build_status(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self.status_group = QButtonGroup(self)
        self.status_group.setExclusive(True)
        for key, label, icon_name in STATUSES:
            btn = QPushButton(label)
            btn.setIcon(theme.icon(icon_name))
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("status_key", key)
            btn.setMinimumHeight(28)
            self.status_group.addButton(btn)
            row.addWidget(btn)
        self.status_group.buttonClicked.connect(self._on_status_clicked)

        row.addStretch(1)
        self.result_label = QLabel("")
        self.result_label.setStyleSheet("opacity: 0.7;")
        row.addWidget(self.result_label)
        return row

    def _build_table(self) -> QWidget:
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)

        self.model = PackageModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setFrameShape(QFrame.Shape.StyledPanel)
        self.table.setWordWrap(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_ORIGIN, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(COL_CHECK, 28)
        self.table.setColumnWidth(COL_SIZE, 80)

        self.table.selectionModel().selectionChanged.connect(self._on_row_selected)
        self.model.dataChanged.connect(self._emit_selection_count)
        box.addWidget(self.table)
        return holder

    def _build_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.count_label = QLabel("Nothing selected")
        self.count_label.setStyleSheet("opacity: 0.8;")
        row.addWidget(self.count_label)
        row.addStretch(1)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setIcon(theme.icon("edit-clear"))
        self.btn_clear.clicked.connect(self.clear_selection)

        self.btn_install = QPushButton("Install selected")
        self.btn_install.setIcon(theme.icon("download"))
        self.btn_install.clicked.connect(
            lambda: self.install_requested.emit(self._checked_by(installed=False))
        )

        self.btn_remove = QPushButton("Remove selected")
        self.btn_remove.setIcon(theme.icon("edit-delete"))
        self.btn_remove.clicked.connect(
            lambda: self.remove_requested.emit(self._checked_by(installed=True))
        )

        for btn in (self.btn_clear, self.btn_remove, self.btn_install):
            btn.setMinimumHeight(32)
            btn.setEnabled(False)
            row.addWidget(btn)
        self.btn_install.setDefault(True)
        return row

    # behaviour

    def enabled_sources(self) -> set[str]:
        return {bid for bid, chip in self.chips.items() if chip.isChecked()}

    def _on_chip_toggled(self, _checked: bool) -> None:
        for bid, chip in self.chips.items():
            self.config.set_backend_enabled(bid, chip.isChecked())
        self.refilter()

    def _on_status_clicked(self, button) -> None:
        self.status = button.property("status_key")
        self.refilter()

    def set_status(self, key: str) -> None:
        for btn in self.status_group.buttons():
            if btn.property("status_key") == key:
                btn.setChecked(True)
                self.status = key
                break
        self.refilter()

    def set_packages(self, packages: list[Package]) -> None:
        self.model.set_packages(packages)
        self.refresh_chip_counts()
        self.refilter()

    def refresh_chip_counts(self) -> None:
        counts = self.catalog.counts()
        for bid, chip in self.chips.items():
            slot = counts.get(bid, {})
            chip.set_count(slot.get("total", 0), slot.get("updates", 0))

    def refilter(self) -> None:
        text = self.search.text()
        sources = self.enabled_sources()
        extra = [p for p in self._remote if p.source in sources] if text.strip() else []
        shown = self.model.apply_filter(text, sources, self.status, extra)

        total = len(self.model.all_packages())
        if text.strip():
            note = f"{shown} matches"
            if extra:
                note += f", {len(extra)} from the network"
            self.result_label.setText(note)
        else:
            self.result_label.setText(f"{shown} of {total} packages")

        if shown and not self.table.currentIndex().isValid():
            self.table.selectRow(0)

    def _start_remote_search(self) -> None:
        query = self.search.text().strip()
        if len(query) < 3:
            self._remote = []
            self.remote_note.setText("")
            return
        if self._search_thread and self._search_thread.isRunning():
            return
        self.remote_note.setText("Searching COPR and the app catalogs")
        self._search_thread = RemoteSearch(self.catalog, query, self.enabled_sources())
        self._search_thread.done.connect(self._on_remote_done)
        self._search_thread.start()

    def _on_remote_done(self, query: str, found: list) -> None:
        if query != self.search.text().strip():
            return
        known = {(p.source, p.key) for p in self.model.all_packages()}
        self._remote = [p for p in found if (p.source, p.key) not in known]
        self.remote_note.setText(
            f"{len(self._remote)} extra from the network" if self._remote else ""
        )
        self.refilter()

    def _on_row_selected(self) -> None:
        index = self.table.currentIndex()
        self.details.set_package(self.model.package_at(index.row()) if index.isValid() else None)

    def _checked_by(self, installed: bool) -> list[Package]:
        picked = self.model.checked_packages()
        if not picked:
            index = self.table.currentIndex()
            pkg = self.model.package_at(index.row()) if index.isValid() else None
            picked = [pkg] if pkg else []
        return [p for p in picked if p.installed == installed]

    def _emit_selection_count(self) -> None:
        picked = self.model.checked_packages()
        count = len(picked)
        to_install = sum(1 for p in picked if not p.installed)
        to_remove = sum(1 for p in picked if p.installed)

        if count:
            bits = []
            if to_install:
                bits.append(f"{to_install} to install")
            if to_remove:
                bits.append(f"{to_remove} installed")
            self.count_label.setText(f"{count} selected: " + ", ".join(bits))
        else:
            self.count_label.setText("Nothing selected")

        self.btn_clear.setEnabled(bool(count))
        self.btn_install.setEnabled(bool(to_install))
        self.btn_remove.setEnabled(bool(to_remove))
        self.selection_changed.emit(count)

    def clear_selection(self) -> None:
        self.model.clear_checks()
        self._emit_selection_count()
