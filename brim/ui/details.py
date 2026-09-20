"""Right hand pane describing whatever package is selected."""

from __future__ import annotations

from datetime import datetime

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
from .threads import Worker, stop_thread


def _when(stamp: int) -> str:
    """Absolute date plus how long ago, which is what people actually read."""
    if not stamp:
        return ""
    moment = datetime.fromtimestamp(stamp)
    days = (datetime.now() - moment).days
    if days < 0:
        ago = ""
    elif days == 0:
        ago = "today"
    elif days == 1:
        ago = "yesterday"
    elif days < 30:
        ago = f"{days} days ago"
    elif days < 365:
        ago = f"{days // 30} month{'s' if days // 30 > 1 else ''} ago"
    else:
        ago = f"{days // 365} year{'s' if days // 365 > 1 else ''} ago"
    stamped = moment.strftime("%d %b %Y")
    return f"{stamped} <span style='opacity:0.65'>{ago}</span>" if ago else stamped


class DetailsLoader(Worker):
    """Fetches the expensive metadata for one selected package."""

    done = Signal(str, dict)

    def __init__(self, backend, pkg) -> None:
        super().__init__()
        self.backend = backend
        self.pkg = pkg

    def run(self) -> None:
        try:
            info = self.backend.details(self.pkg)
        except Exception:
            info = {}
        self.done.emit(f"{self.pkg.source}::{self.pkg.key}", info)


class DetailsPane(QWidget):
    install_requested = Signal(object)
    remove_requested = Signal(object)
    upgrade_requested = Signal(object)

    def __init__(self, catalog=None, parent=None) -> None:
        super().__init__(parent)
        self._pkg: Package | None = None
        self._catalog = catalog
        self._loader: DetailsLoader | None = None
        self._info: dict = {}
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
        self._info = {}
        self.body.setHtml(self._html(pkg, {}))
        self._load_details(pkg)

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

    def _load_details(self, pkg: Package) -> None:
        if self._catalog is None:
            return
        backend = self._catalog.backends.get(pkg.source)
        if backend is None:
            return
        if self._loader and self._loader.isRunning():
            try:
                self._loader.done.disconnect()
            except RuntimeError:
                pass
            stop_thread(self._loader, grace_ms=200)
        self._loader = DetailsLoader(backend, pkg)
        self._loader.done.connect(self._on_details)
        self._loader.start()

    def shutdown(self) -> None:
        stop_thread(self._loader)

    def _on_details(self, key: str, info: dict) -> None:
        if not self._pkg or key != f"{self._pkg.source}::{self._pkg.key}":
            return
        self._info = info
        self.body.setHtml(self._html(self._pkg, info))

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
    def _html(pkg: Package, info: dict) -> str:
        rows = []

        def row(label: str, value: str) -> None:
            if value:
                rows.append(
                    f'<tr><td style="padding:3px 14px 3px 0;opacity:0.7;'
                    f'white-space:nowrap;vertical-align:top;">{label}</td>'
                    f"<td style='padding:3px 0;'>{value}</td></tr>"
                )

        if pkg.state is State.UPGRADABLE:
            up = theme.state_color("upgradable").name()
            row(
                "Change",
                f'{pkg.installed_version} <span style="color:{up};font-weight:600;">'
                f"to {pkg.version}</span>",
            )
        else:
            row("Version", pkg.version)

        row("Source", theme.SOURCE_LABELS.get(pkg.source, pkg.source))
        row("Origin", pkg.origin)
        if pkg.arch:
            row("Architecture", pkg.arch)

        built = _when(info.get("build_time", 0))
        if built:
            row("Built", built)
        installed_at = _when(info.get("install_time", 0))
        if installed_at:
            row("Installed", installed_at)

        size = info.get("install_size") or pkg.size
        if size:
            row("Size on disk" if pkg.installed else "Download", theme.human_size(size))
        if info.get("packager"):
            row("Packaged by", info["packager"])
        if pkg.license:
            row("License", pkg.license)
        if pkg.url:
            row("Homepage", f'<a href="{pkg.url}">{pkg.url}</a>')
        if info.get("source_rpm"):
            row("Source RPM", f"<code>{info['source_rpm']}</code>")
        if pkg.extra.get("path"):
            row("Path", pkg.extra["path"])
        if pkg.extra.get("match_reason"):
            row("Matched because it", pkg.extra["match_reason"])

        versions = pkg.extra.get("installed_versions")
        if versions:
            row("Installed versions", f"{len(versions)}: " + ", ".join(versions))

        html = f"<table style='border-collapse:collapse;'>{''.join(rows)}</table>"

        desc = (pkg.description or "").strip()
        if desc:
            safe = desc.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            html += f"<p style='margin-top:14px;'>{safe}</p>"

        requires = info.get("requires") or []
        recommends = info.get("recommends") or []
        if requires or recommends:
            html += "<p style='margin-top:16px;opacity:0.7;'><b>Needs</b></p>"
            if requires:
                shown = ", ".join(f"<code>{r}</code>" for r in requires[:24])
                more = (
                    f" <span style='opacity:0.6'>and {len(requires) - 24} more</span>"
                    if len(requires) > 24
                    else ""
                )
                html += f"<p style='margin:2px 0;'>{shown}{more}</p>"
            if recommends:
                shown = ", ".join(f"<code>{r}</code>" for r in recommends[:12])
                html += (
                    "<p style='margin:6px 0 0 0;opacity:0.75;'>"
                    f"Suggested alongside: {shown}</p>"
                )
            html += (
                "<p style='margin:6px 0 0 0;opacity:0.6;'>"
                "Anything missing is pulled in automatically. Brim shows you the "
                "full list before it runs.</p>"
            )

        changelog = info.get("changelog") or []
        if changelog:
            html += "<p style='margin-top:16px;opacity:0.7;'><b>Recent changes</b></p>"
            for entry in changelog:
                when = _when(entry.get("timestamp", 0))
                author = (entry.get("author") or "").split("<")[0].strip()
                text = (entry.get("text") or "").strip()
                text = (
                    text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                )
                if len(text) > 420:
                    text = text[:420] + "..."
                text = text.replace(chr(10), "<br>")
                html += (
                    "<p style='margin:8px 0 0 0;'>"
                    f"<span style='opacity:0.65;'>{when} &middot; {author}</span><br>"
                    f"<span style='font-size:small;'>{text}</span></p>"
                )
        return html
