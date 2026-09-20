"""Right hand pane describing whatever package is selected."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..backends.base import Package, State
from . import theme


class DetailsPane(QWidget):
    install_requested = Signal(object)
    remove_requested = Signal(object)
    upgrade_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pkg: Package | None = None
        self.setMinimumWidth(320)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.title = QLabel("Nothing selected")
        title_font = self.title.font()
        title_font.setPointSize(title_font.pointSize() + 4)
        title_font.setBold(True)
        self.title.setFont(title_font)
        self.title.setWordWrap(True)
        root.addWidget(self.title)

        self.badges = QLabel("")
        self.badges.setTextFormat(Qt.TextFormat.RichText)
        self.badges.setWordWrap(True)
        root.addWidget(self.badges)

        self.summary = QLabel("Pick a package on the left to see what it is.")
        self.summary.setWordWrap(True)
        self.summary.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        root.addWidget(self.summary)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        self.body.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.body, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_primary = QPushButton("Install")
        self.btn_primary.setIcon(theme.icon("download"))
        self.btn_secondary = QPushButton("Remove")
        self.btn_secondary.setIcon(theme.icon("edit-delete"))
        for btn in (self.btn_primary, self.btn_secondary):
            btn.setMinimumHeight(32)
            actions.addWidget(btn)
        root.addLayout(actions)

        self.btn_primary.clicked.connect(self._primary)
        self.btn_secondary.clicked.connect(self._secondary)
        self.set_package(None)

    def _primary(self) -> None:
        if not self._pkg:
            return
        if self._pkg.state is State.UPGRADABLE:
            self.upgrade_requested.emit(self._pkg)
        else:
            self.install_requested.emit(self._pkg)

    def _secondary(self) -> None:
        if self._pkg:
            self.remove_requested.emit(self._pkg)

    def set_package(self, pkg: Package | None) -> None:
        self._pkg = pkg
        if pkg is None:
            self.title.setText("Nothing selected")
            self.badges.setText("")
            self.summary.setText("Pick a package on the left to see what it is.")
            self.body.setHtml("")
            self.btn_primary.setEnabled(False)
            self.btn_secondary.setEnabled(False)
            return

        self.title.setText(pkg.name)
        self.summary.setText(pkg.summary or "")
        self.badges.setText(self._badges(pkg))
        self.body.setHtml(self._html(pkg))

        installable = pkg.extra.get("installable", True)
        if pkg.state is State.UPGRADABLE:
            self.btn_primary.setText(f"Update to {pkg.version}")
            self.btn_primary.setIcon(theme.icon("system-software-update"))
            self.btn_primary.setEnabled(True)
        elif pkg.installed:
            self.btn_primary.setText("Installed")
            self.btn_primary.setEnabled(False)
        else:
            self.btn_primary.setText("Install")
            self.btn_primary.setIcon(theme.icon("download"))
            self.btn_primary.setEnabled(bool(installable))
        self.btn_secondary.setEnabled(pkg.installed)

    @staticmethod
    def _badges(pkg: Package) -> str:
        chips = []
        src = theme.source_color(pkg.source)
        chips.append(
            f'<span style="color:{src.name()};font-weight:600;">'
            f"{theme.SOURCE_LABELS.get(pkg.source, pkg.source)}</span>"
        )
        chips.append(f'<span style="opacity:0.75;">{pkg.origin}</span>')
        if pkg.state is State.UPGRADABLE:
            col = theme.state_color("upgradable")
            chips.append(f'<span style="color:{col.name()};font-weight:600;">Update</span>')
        elif pkg.installed:
            col = theme.state_color("installed")
            chips.append(f'<span style="color:{col.name()};font-weight:600;">Installed</span>')
        if pkg.extra.get("installable") is False:
            chips.append('<span style="opacity:0.75;">no automatic download</span>')
        if pkg.source == "copr" and not pkg.extra.get("repo_enabled", True):
            chips.append('<span style="opacity:0.75;">repo not enabled yet</span>')
        return " &nbsp;&middot;&nbsp; ".join(chips)

    @staticmethod
    def _html(pkg: Package) -> str:
        rows = []

        def row(label: str, value: str) -> None:
            if value:
                rows.append(
                    f'<tr><td style="padding:3px 14px 3px 0;opacity:0.7;white-space:nowrap;">'
                    f"{label}</td><td style='padding:3px 0;'>{value}</td></tr>"
                )

        if pkg.state is State.UPGRADABLE:
            up = theme.state_color("upgradable").name()
            row(
                "Change",
                f'{pkg.installed_version} <span style="color:{up};">to {pkg.version}</span>',
            )
        else:
            row("Version", pkg.version)
        row("Source", theme.SOURCE_LABELS.get(pkg.source, pkg.source))
        row("Origin", pkg.origin)
        if pkg.arch:
            row("Architecture", pkg.arch)
        if pkg.size:
            row("Size", theme.human_size(pkg.size))
        if pkg.license:
            row("License", pkg.license)
        if pkg.url:
            row("Homepage", f'<a href="{pkg.url}">{pkg.url}</a>')
        if pkg.extra.get("path"):
            row("Path", pkg.extra["path"])
        installed_versions = pkg.extra.get("installed_versions")
        if installed_versions:
            row(
                "Installed",
                f"{len(installed_versions)} versions: "
                + ", ".join(installed_versions),
            )

        table = f"<table style='border-collapse:collapse;'>{''.join(rows)}</table>"
        desc = (pkg.description or "").strip()
        if desc:
            safe = desc.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            table += f"<p style='margin-top:14px;'>{safe}</p>"
        return table
