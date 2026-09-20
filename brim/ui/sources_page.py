"""Manage every source in one place: dnf repos, COPR projects, Flatpak remotes."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import theme

RPMFUSION = (
    "https://mirrors.rpmfusion.org/free/fedora/"
    "rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm "
    "https://mirrors.rpmfusion.org/nonfree/fedora/"
    "rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm"
)

FLATPAK_PRESETS = {
    "Flathub": "https://dl.flathub.org/repo/flathub.flatpakrepo",
    "Flathub beta": "https://dl.flathub.org/beta-repo/flathub-beta.flatpakrepo",
    "Fedora": "oci+https://registry.fedoraproject.org",
}


class AddCoprDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Enable a COPR project")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        layout.addWidget(
            QLabel(
                "Enter the project as <b>owner/project</b>, for example "
                "<code>ilyaz/LACT</code>."
            )
        )
        self.field = QLineEdit()
        self.field.setPlaceholderText("owner/project")
        layout.addWidget(self.field)

        note = QLabel(
            "COPR builds are community made and are not reviewed by Fedora."
        )
        note.setWordWrap(True)
        note.setStyleSheet("opacity: 0.7;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> str:
        return self.field.text().strip()


class AddRemoteDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a Flatpak remote")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.preset = QComboBox()
        self.preset.addItem("Custom")
        for name in FLATPAK_PRESETS:
            self.preset.addItem(name)
        self.preset.currentTextChanged.connect(self._apply_preset)
        form.addRow("Preset", self.preset)

        self.name = QLineEdit()
        self.name.setPlaceholderText("flathub")
        form.addRow("Name", self.name)

        self.url = QLineEdit()
        self.url.setPlaceholderText("https://dl.flathub.org/repo/flathub.flatpakrepo")
        form.addRow("URL", self.url)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_preset(self, text: str) -> None:
        if text in FLATPAK_PRESETS:
            self.name.setText(text.split()[0].lower())
            self.url.setText(FLATPAK_PRESETS[text])

    def values(self) -> tuple[str, str]:
        return self.name.text().strip(), self.url.text().strip()


class SourcesPage(QWidget):
    run_command = Signal(list, bool, str)
    refresh_requested = Signal()

    def __init__(self, catalog, config, parent=None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.config = config

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QLabel(
            "Everything Brim can pull from. Toggle a row to enable or disable it."
        )
        header.setStyleSheet("opacity: 0.8;")
        root.addWidget(header)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Source", "Status", "Detail"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.tree, 1)

        root.addWidget(self._build_quick_add())

        row = QHBoxLayout()
        self.show_disabled = QCheckBox("Show disabled repositories")
        self.show_disabled.setChecked(False)
        self.show_disabled.toggled.connect(self.reload)
        row.addWidget(self.show_disabled)
        row.addStretch(1)

        self.btn_remove = QPushButton("Remove source")
        self.btn_remove.setIcon(theme.icon("list-remove"))
        self.btn_remove.clicked.connect(self._remove_selected)
        row.addWidget(self.btn_remove)

        btn_refresh = QPushButton("Reload")
        btn_refresh.setIcon(theme.icon("view-refresh"))
        btn_refresh.clicked.connect(self.refresh_requested.emit)
        row.addWidget(btn_refresh)
        root.addLayout(row)

    def _build_quick_add(self) -> QWidget:
        box = QGroupBox("Quick add")
        layout = QHBoxLayout(box)
        layout.setSpacing(8)

        btn_copr = QPushButton("Enable a COPR")
        btn_copr.setIcon(theme.icon("applications-development"))
        btn_copr.clicked.connect(self._add_copr)

        btn_remote = QPushButton("Add a Flatpak remote")
        btn_remote.setIcon(theme.icon("flatpak"))
        btn_remote.clicked.connect(self._add_remote)

        btn_fusion = QPushButton("Install RPM Fusion")
        btn_fusion.setIcon(theme.icon("package-x-generic"))
        btn_fusion.setToolTip("Adds the free and nonfree RPM Fusion repositories")
        btn_fusion.clicked.connect(self._add_rpmfusion)

        for btn in (btn_copr, btn_remote, btn_fusion):
            btn.setMinimumHeight(32)
            layout.addWidget(btn)
        layout.addStretch(1)
        return box

    def reload(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()

        enabled_ids = {
            bid for bid in self.catalog.backends if self.config.backend_enabled(bid)
        }
        sources = self.catalog.sources(enabled_ids)

        grouped: dict[str, list] = {}
        for src in sources:
            grouped.setdefault(src.backend, []).append(src)

        for backend_id, items in grouped.items():
            backend = self.catalog.backends.get(backend_id)
            label = backend.label if backend else backend_id
            active = sum(1 for s in items if s.enabled)
            parent = QTreeWidgetItem([label, f"{active} of {len(items)} on", ""])
            parent.setIcon(0, theme.source_icon(backend_id))
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            self.tree.addTopLevelItem(parent)

            for src in items:
                if not src.enabled and not self.show_disabled.isChecked():
                    continue
                child = QTreeWidgetItem(
                    [src.key, "Enabled" if src.enabled else "Disabled", src.description]
                )
                child.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                child.setCheckState(
                    0,
                    Qt.CheckState.Checked if src.enabled else Qt.CheckState.Unchecked,
                )
                child.setForeground(1, theme.state_color("installed" if src.enabled else ""))
                child.setToolTip(0, src.url or src.key)
                child.setData(0, Qt.ItemDataRole.UserRole, src)
                parent.addChild(child)
            parent.setExpanded(True)

        self.tree.blockSignals(False)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        src = item.data(0, Qt.ItemDataRole.UserRole)
        if src is None:
            return
        wanted = item.checkState(0) == Qt.CheckState.Checked
        if wanted == src.enabled:
            return
        backend = self.catalog.backends.get(src.backend)
        if backend is None:
            return
        try:
            cmd = backend.set_source_enabled(src.key, wanted)
        except NotImplementedError as exc:
            QMessageBox.information(self, "Not supported", str(exc))
            self.reload()
            return
        verb = "Enabling" if wanted else "Disabling"
        self.run_command.emit(cmd, backend.needs_root, f"{verb} {src.key}")

    def _remove_selected(self) -> None:
        item = self.tree.currentItem()
        src = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if src is None:
            QMessageBox.information(self, "Remove source", "Pick a source first.")
            return
        if not src.removable:
            QMessageBox.information(
                self,
                "Remove source",
                f"{src.key} is provided by a package and cannot be removed here.\n"
                "Disable it instead, or remove the package that ships it.",
            )
            return
        confirm = QMessageBox.question(
            self,
            "Remove source",
            f"Remove {src.key}?\n\nPackages already installed from it stay installed.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        backend = self.catalog.backends.get(src.backend)
        cmd = backend.remove_source(src.key)
        self.run_command.emit(cmd, backend.needs_root, f"Removing {src.key}")

    def _add_copr(self) -> None:
        dialog = AddCoprDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        value = dialog.value()
        if "/" not in value:
            QMessageBox.warning(self, "COPR", "Use the owner/project form.")
            return
        backend = self.catalog.backends.get("dnf")
        self.run_command.emit(
            backend.enable_copr(value), True, f"Enabling COPR {value}"
        )

    def _add_remote(self) -> None:
        dialog = AddRemoteDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, url = dialog.values()
        if not name or not url:
            QMessageBox.warning(self, "Flatpak remote", "Name and URL are both required.")
            return
        backend = self.catalog.backends.get("flatpak")
        self.run_command.emit(
            backend.add_remote_cmd(name, url), False, f"Adding remote {name}"
        )

    def _add_rpmfusion(self) -> None:
        confirm = QMessageBox.question(
            self,
            "RPM Fusion",
            "Install the RPM Fusion free and nonfree repositories?\n\n"
            "These carry codecs, Steam, emulators and NVIDIA drivers that Fedora "
            "cannot ship itself.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.run_command.emit(
            ["sh", "-c", f"dnf install -y {RPMFUSION}"],
            True,
            "Installing RPM Fusion",
        )
