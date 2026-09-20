"""The browse screen: search, source chips, results, details."""

from __future__ import annotations

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..backends.base import Package
from . import theme
from .threads import Worker, stop_all
from .details import DetailsPane
from .models import (
    COL_CHECK,
    COL_NAME,
    COL_ORIGIN,
    COL_SIZE,
    COL_SOURCE,
    COL_STATUS,
    COL_VERSION,
    COLUMNS,
    PackageModel,
)

STATUSES = [
    ("all", "All", "view-list-details"),
    ("installed", "Installed", "dialog-ok"),
    ("available", "Available", "list-add"),
    ("updates", "Updates", "system-software-update"),
]

# Which phase covers which source, so the chips can say what is still working.
DEEP_SOURCES = frozenset({"dnf"})
REMOTE_SOURCES = frozenset({"copr", "flatpak", "appimage"})


class DeepSearch(Worker):
    """Local index lookups: binaries, provided libraries, descriptions."""

    done = Signal(str, list)

    def __init__(self, catalog, query: str, sources: set[str]) -> None:
        super().__init__()
        self.catalog = catalog
        self.query = query
        self.sources = sources

    def run(self) -> None:
        try:
            found = self.catalog.search_deep(self.query, self.sources)
        except Exception:
            found = []
        self.done.emit(self.query, found)


class RemoteSearch(Worker):
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
    """One toggleable source filter, tinted with that source's hue.

    The number is always what this source is contributing to the list in
    front of you, not a static catalogue size. During a search it counts
    matches; with no search it counts what the current filter shows.
    """

    def __init__(self, source_id: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self.source_id = source_id
        self.base_label = label
        self.setCheckable(True)
        self.setChecked(True)
        self.setIcon(theme.source_icon(source_id))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(30)
        self._busy = False
        self.set_state(0, 0, False, False)
        self.restyle()

    def set_state(
        self, shown: int, updates: int, busy: bool, searching: bool
    ) -> None:
        self._busy = busy

        if not self.isChecked():
            # A zero here would read as "found nothing" rather than "not asked".
            self.setText(f"{self.base_label}  off")
            self.setToolTip(
                f"{self.base_label} is switched off. Click to include it."
            )
            return

        text = self.base_label
        if busy:
            text += "  ..."
        elif searching or shown:
            text += f"  {shown}"
        if updates and not searching:
            text += f"  ({updates} new)"
        self.setText(text)

        if searching:
            if busy:
                self.setToolTip(f"Still searching {self.base_label}")
            elif shown:
                self.setToolTip(f"{shown} match(es) from {self.base_label}")
            else:
                self.setToolTip(f"Searched {self.base_label}, nothing matched")
        else:
            self.setToolTip(f"{shown} package(s) from {self.base_label}")

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
    sources_changed = Signal()
    reload_requested = Signal()
    install_requested = Signal(list)
    remove_requested = Signal(list)
    upgrade_requested = Signal(list)

    def __init__(self, catalog, config, parent=None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.config = config
        self.status = "all"
        self._remote: list[Package] = []
        self._deep: list[Package] = []
        self._busy_deep = False
        self._busy_remote = False
        self._searched_remote = False
        self._search_thread: RemoteSearch | None = None
        self._deep_thread: DeepSearch | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addLayout(self._build_search())
        root.addLayout(self._build_progress())
        root.addLayout(self._build_chips())
        root.addLayout(self._build_status())

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self._build_table())
        self.details = DetailsPane(self.catalog)
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

        self.deep_timer = QTimer(self)
        self.deep_timer.setSingleShot(True)
        self.deep_timer.setInterval(380)
        self.deep_timer.timeout.connect(self._start_deep_search)
        self.search.textChanged.connect(lambda _: self.deep_timer.start())

        self.remote_timer = QTimer(self)
        self.remote_timer.setSingleShot(True)
        self.remote_timer.setInterval(650)
        self.remote_timer.timeout.connect(self._start_remote_search)
        self.search.textChanged.connect(lambda _: self.remote_timer.start())
        return row

    def _build_progress(self) -> QVBoxLayout:
        """A visible finish line, so nobody wonders whether it is still going."""
        box = QVBoxLayout()
        box.setSpacing(3)
        box.setContentsMargins(0, 0, 0, 0)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setVisible(False)
        box.addWidget(self.progress)

        self.search_status = QLabel("")
        self.search_status.setTextFormat(Qt.TextFormat.RichText)
        self.search_status.setWordWrap(True)
        self.search_status.setVisible(False)
        box.addWidget(self.search_status)
        return box

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
        # Every column is draggable. Nothing is locked to its contents, which
        # is what stops a long origin name from pinning the layout.
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)
        header.setMinimumSectionSize(28)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._column_menu)
        header.sectionResized.connect(lambda *_: self._save_columns())
        self._apply_column_layout()

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

    # ---------------------------------------------------------- columns

    DEFAULT_WIDTHS = {
        COL_CHECK: 30,
        COL_NAME: 280,
        COL_VERSION: 150,
        COL_SOURCE: 100,
        COL_ORIGIN: 170,
        COL_STATUS: 95,
        COL_SIZE: 85,
    }

    def _apply_column_layout(self) -> None:
        stored = self.config.get("columns", {}) or {}
        widths = stored.get("widths", {})
        hidden = set(stored.get("hidden", []))

        header = self.table.horizontalHeader()
        header.blockSignals(True)
        for index in range(len(COLUMNS)):
            width = widths.get(str(index), self.DEFAULT_WIDTHS.get(index, 120))
            self.table.setColumnWidth(index, int(width))
            self.table.setColumnHidden(index, str(index) in hidden or index in hidden)
        header.blockSignals(False)

        # Whatever is left over goes to Name, so the table always fills out.
        if not self.table.isColumnHidden(COL_NAME):
            header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)

    def _save_columns(self) -> None:
        widths = {
            str(i): self.table.columnWidth(i)
            for i in range(len(COLUMNS))
            if not self.table.isColumnHidden(i)
        }
        hidden = [
            str(i) for i in range(len(COLUMNS)) if self.table.isColumnHidden(i)
        ]
        self.config.set("columns", {"widths": widths, "hidden": hidden})

    def _column_menu(self, point) -> None:
        menu = QMenu(self)
        menu.addAction(QAction("Columns", menu)).setEnabled(False)
        menu.addSeparator()

        for index, name in enumerate(COLUMNS):
            if index == COL_CHECK:
                continue
            action = QAction(name, menu)
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(index))
            action.toggled.connect(
                lambda visible, col=index: self._set_column_visible(col, visible)
            )
            menu.addAction(action)

        menu.addSeparator()
        fit = QAction("Size columns to fit contents", menu)
        fit.triggered.connect(self._fit_columns)
        menu.addAction(fit)

        reset = QAction("Reset to defaults", menu)
        reset.triggered.connect(self._reset_columns)
        menu.addAction(reset)

        menu.exec(self.table.horizontalHeader().mapToGlobal(point))

    def _set_column_visible(self, column: int, visible: bool) -> None:
        # Never let the last visible column disappear.
        if not visible:
            remaining = [
                i
                for i in range(len(COLUMNS))
                if i != COL_CHECK and not self.table.isColumnHidden(i)
            ]
            if len(remaining) <= 1:
                return
        self.table.setColumnHidden(column, not visible)
        self._save_columns()

    def _fit_columns(self) -> None:
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        widths = [self.table.columnWidth(i) for i in range(len(COLUMNS))]
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for index, width in enumerate(widths):
            self.table.setColumnWidth(index, width + 12)
        self._save_columns()

    def _reset_columns(self) -> None:
        self.config.set("columns", {})
        for index in range(len(COLUMNS)):
            self.table.setColumnHidden(index, False)
        self._apply_column_layout()

    # ---------------------------------------------------------- behaviour

    def enabled_sources(self) -> set[str]:
        return {bid for bid, chip in self.chips.items() if chip.isChecked()}

    def _on_chip_toggled(self, _checked: bool) -> None:
        """Switching a source on has to fetch it, not just unhide it.

        The catalogue only loads backends that were enabled at load time, so
        a chip turned on later would otherwise sit at zero until the next
        manual reload and look broken.
        """
        needs_load = False
        loaded = {p.source for p in self.model.all_packages()}
        for bid, chip in self.chips.items():
            was_on = self.config.backend_enabled(bid)
            now_on = chip.isChecked()
            self.config.set_backend_enabled(bid, now_on)
            backend = self.catalog.backends.get(bid)
            if (
                now_on
                and not was_on
                and bid not in loaded
                and backend is not None
                and backend.available
                and not isinstance(backend, type(None))
            ):
                # COPR holds nothing locally, so it never needs a reload.
                if bid != "copr":
                    needs_load = True

        self.refilter()
        self.sources_changed.emit()
        if needs_load:
            self.reload_requested.emit()

    def all_sources_on(self) -> bool:
        return all(c.isChecked() for c in self.chips.values() if c.isEnabled())

    def enable_all_sources(self) -> None:
        for chip in self.chips.values():
            if chip.isEnabled():
                chip.blockSignals(True)
                chip.setChecked(True)
                chip.blockSignals(False)
        self._on_chip_toggled(True)

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
        self.refilter()

    def refilter(self) -> None:
        text = self.search.text()
        searching = bool(text.strip())
        sources = self.enabled_sources()
        extra = (
            [p for p in (self._deep + self._remote) if p.source in sources]
            if searching
            else []
        )
        counts = self.model.apply_filter(text, sources, self.status, extra)
        shown = counts.get("_total", 0)

        self._update_chips(counts, searching)
        self._update_status_counts(text, sources)
        self._update_search_status(text, counts, sources, searching)

        total = len(self.model.all_packages())
        if searching:
            self.result_label.setText(f"{shown} shown")
        else:
            self.result_label.setText(f"{shown} of {total} packages")

        if shown and not self.table.currentIndex().isValid():
            self.table.selectRow(0)

    def _update_chips(self, counts: dict, searching: bool) -> None:
        """Every chip reports its share of what is on screen right now."""
        updates = self.catalog.counts()
        for bid, chip in self.chips.items():
            busy = (
                bid in DEEP_SOURCES and self._busy_deep
            ) or (bid in REMOTE_SOURCES and self._busy_remote)
            chip.set_state(
                counts.get(bid, 0),
                updates.get(bid, {}).get("updates", 0),
                busy and chip.isChecked(),
                searching,
            )

    def _update_status_counts(self, text: str, sources: set) -> None:
        """Put the size of each bucket on the filter itself."""
        pool = self.model.all_packages() + (
            self._deep + self._remote if text.strip() else []
        )
        needle = text.strip().lower()
        tally = {"all": 0, "installed": 0, "available": 0, "updates": 0}
        for pkg in pool:
            if pkg.source not in sources:
                continue
            if needle and needle not in pkg.name.lower() and needle not in pkg.summary.lower():
                continue
            tally["all"] += 1
            if pkg.upgradable:
                tally["updates"] += 1
            if pkg.installed:
                tally["installed"] += 1
            else:
                tally["available"] += 1

        for button in self.status_group.buttons():
            key = button.property("status_key")
            label = dict((k, lbl) for k, lbl, _ in STATUSES)[key]
            button.setText(f"{label}  {tally.get(key, 0)}")

    def _update_search_status(
        self, text: str, counts: dict, sources: set, searching: bool
    ) -> None:
        """Spell out which sources were searched and what each one gave back."""
        if not searching:
            self.progress.setVisible(False)
            self.search_status.setVisible(False)
            return

        self.search_status.setVisible(True)
        busy = self._busy_deep or self._busy_remote
        self.progress.setVisible(busy)

        parts = []
        for bid, chip in self.chips.items():
            label = theme.SOURCE_LABELS.get(bid, bid)
            if not chip.isEnabled():
                continue
            if bid not in sources:
                parts.append(
                    f"<span style='opacity:0.45;'>{label} off</span>"
                )
                continue
            source_busy = (bid in DEEP_SOURCES and self._busy_deep) or (
                bid in REMOTE_SOURCES and self._busy_remote
            )
            colour = theme.source_color(bid).name()
            if source_busy:
                parts.append(
                    f"<span style='opacity:0.7;'>{label} searching</span>"
                )
            else:
                found = counts.get(bid, 0)
                if found:
                    parts.append(
                        f"<span style='color:{colour};font-weight:600;'>{label} {found}</span>"
                    )
                else:
                    parts.append(f"<span style='opacity:0.5;'>{label} 0</span>")

        head = "Searching" if busy else "Searched"
        joined = " &nbsp;&middot;&nbsp; ".join(parts)
        off = [
            theme.SOURCE_LABELS.get(b, b)
            for b, c in self.chips.items()
            if c.isEnabled() and not c.isChecked()
        ]
        tail = ""
        if off and not busy:
            tail = (
                "<br><span style='opacity:0.7;'>Not searched: "
                f"{', '.join(off)}. Click a chip above to include it.</span>"
            )
        self.search_status.setText(
            f"<span style='opacity:0.7;'>{head}</span> &nbsp; {joined}{tail}"
        )

    def _start_deep_search(self) -> None:
        query = self.search.text().strip()
        if len(query) < 3:
            self._deep = []
            self._busy_deep = False
            self.refilter()
            return
        if self._deep_thread and self._deep_thread.isRunning():
            return
        self._busy_deep = True
        self.refilter()
        self._deep_thread = DeepSearch(self.catalog, query, self.enabled_sources())
        self._deep_thread.done.connect(self._on_deep_done)
        self._deep_thread.start()

    def _on_deep_done(self, query: str, found: list) -> None:
        self._busy_deep = False
        if query != self.search.text().strip():
            self.refilter()
            return
        known = {(p.source, p.key) for p in self.model.all_packages()}
        self._deep = [p for p in found if (p.source, p.key) not in known]
        self.refilter()

    def _start_remote_search(self) -> None:
        query = self.search.text().strip()
        if len(query) < 3:
            self._remote = []
            self._busy_remote = False
            self._searched_remote = False
            self.refilter()
            return
        if self._search_thread and self._search_thread.isRunning():
            return
        self._busy_remote = True
        self.refilter()
        self._search_thread = RemoteSearch(self.catalog, query, self.enabled_sources())
        self._search_thread.done.connect(self._on_remote_done)
        self._search_thread.start()

    def _on_remote_done(self, query: str, found: list) -> None:
        self._busy_remote = False
        self._searched_remote = True
        if query != self.search.text().strip():
            self.refilter()
            return
        known = {(p.source, p.key) for p in self.model.all_packages()}
        self._remote = [p for p in found if (p.source, p.key) not in known]
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

    def shutdown(self) -> None:
        """Called before the window goes away."""
        stop_all(self._deep_thread, self._search_thread)
        self.details.shutdown()

    def clear_selection(self) -> None:
        self.model.clear_checks()
        self._emit_selection_count()
