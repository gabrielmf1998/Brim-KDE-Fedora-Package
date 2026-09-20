"""Confirmation that shows what a transaction will really do.

Nobody should have to guess what comes along with a package. This resolves
the transaction first and lists every extra, so the answer to "will it pull
the dependencies" is visible instead of assumed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QTextBrowser,
    QVBoxLayout,
)

from ..backends.base import Package, Preview
from . import theme
from .threads import Worker, stop_thread


class PreviewLoader(Worker):
    done = Signal(object)

    def __init__(self, backend, action: str, pkgs: list) -> None:
        super().__init__()
        self.backend = backend
        self.action = action
        self.pkgs = pkgs

    def run(self) -> None:
        try:
            self.done.emit(self.backend.preview(self.action, self.pkgs))
        except Exception:
            self.done.emit(None)


class PreviewDialog(QDialog):
    def __init__(self, action: str, packages: list[Package], catalog, parent=None):
        super().__init__(parent)
        self.action = action
        self.packages = packages
        self.catalog = catalog
        self._loader: PreviewLoader | None = None

        self.setWindowTitle(f"{action.title()} {len(packages)} package(s)")
        self.setMinimumSize(640, 460)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.heading = QLabel(self._heading())
        font = self.heading.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        self.heading.setFont(font)
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)

        self.subtitle = QLabel("Working out what this needs")
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet("opacity: 0.8;")
        layout.addWidget(self.subtitle)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(4)
        layout.addWidget(self.bar)

        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        self.body.document().setDocumentMargin(12)
        layout.addWidget(self.body, 1)

        bottom = QHBoxLayout()
        self.chk_skip = QCheckBox("Do not ask again")
        self.chk_skip.setToolTip(
            "Transactions will run straight away. You can turn this back on in Settings."
        )
        bottom.addWidget(self.chk_skip)
        bottom.addStretch(1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(action.title())
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        bottom.addWidget(self.buttons)
        layout.addLayout(bottom)

        self.body.setHtml(self._static_html())
        self._start()

    def skip_future(self) -> bool:
        return self.chk_skip.isChecked()

    def closeEvent(self, event) -> None:
        stop_thread(self._loader)
        super().closeEvent(event)

    def done(self, result: int) -> None:
        stop_thread(self._loader)
        super().done(result)

    def _heading(self) -> str:
        names = ", ".join(p.name for p in self.packages[:3])
        if len(self.packages) > 3:
            names += f" and {len(self.packages) - 3} more"
        return f"{self.action.title()} {names}"

    def _start(self) -> None:
        # Only the dnf backend can resolve ahead of time; the rest say so.
        dnf_pkgs = [p for p in self.packages if p.source in ("dnf",)]
        backend = self.catalog.backends.get("dnf")
        if not dnf_pkgs or backend is None:
            self.bar.hide()
            self.subtitle.setText(self._other_sources_note())
            return
        self._loader = PreviewLoader(backend, self.action, dnf_pkgs)
        self._loader.done.connect(self._on_preview)
        self._loader.start()

    def _other_sources_note(self) -> str:
        kinds = sorted({theme.SOURCE_LABELS.get(p.source, p.source) for p in self.packages})
        return (
            f"{', '.join(kinds)} resolves its own dependencies while it runs. "
            "The live output will show everything it pulls in."
        )

    def _on_preview(self, preview: Preview | None) -> None:
        self.bar.hide()
        if preview is None:
            self.subtitle.setText(
                "Could not resolve this in advance. The live output will show what happens."
            )
            return

        if preview.problems:
            warn = theme.state_color("upgradable").name()
            self.subtitle.setText("Resolved with problems, see below")
            self.subtitle.setStyleSheet(f"color: {warn}; font-weight: 600;")
        else:
            extra = preview.extra_count
            bits = []
            if preview.install:
                bits.append(f"{len(preview.install)} to install")
            if preview.upgrade:
                bits.append(f"{len(preview.upgrade)} to upgrade")
            if preview.remove:
                bits.append(f"{len(preview.remove)} to remove")
            note = ", ".join(bits) or "nothing to do"
            if extra:
                note += f", {extra} pulled in automatically"
            if preview.download_size:
                note += f". {theme.human_size(preview.download_size)} to download"
            self.subtitle.setText(note)

        self.body.setHtml(self._static_html() + self._preview_html(preview))

    def _static_html(self) -> str:
        rows = []
        for pkg in self.packages:
            colour = theme.source_color(pkg.source).name()
            label = theme.SOURCE_LABELS.get(pkg.source, pkg.source)
            version = pkg.version_diff
            rows.append(
                f"<tr><td style='padding:3px 14px 3px 0;'><b>{pkg.name}</b></td>"
                f"<td style='padding:3px 14px 3px 0;opacity:0.8;'>{version}</td>"
                f"<td style='padding:3px 0;color:{colour};'>{label}</td></tr>"
            )
        html = (
            "<p style='opacity:0.7;margin:0 0 4px 0;'><b>You asked for</b></p>"
            f"<table style='border-collapse:collapse;'>{''.join(rows)}</table>"
        )

        coprs = sorted({p.origin for p in self.packages if p.source == "copr"})
        if coprs and self.action == "install":
            warn = theme.state_color("upgradable").name()
            html += (
                f"<p style='margin-top:14px;color:{warn};'><b>This enables a "
                f"community repository: {', '.join(coprs)}</b></p>"
                "<p style='margin:2px 0 0 0;opacity:0.8;'>COPR builds are not "
                "reviewed by Fedora. Nobody audits the code or the packaging, and "
                "security updates arrive only if the owner keeps maintaining it. "
                "Press F1 for the full picture.</p>"
            )
        if any(p.source == "appimage" for p in self.packages) and self.action == "install":
            html += (
                "<p style='margin-top:14px;opacity:0.8;'>AppImages come straight "
                "from upstream with no distribution in between and no sandbox.</p>"
            )
        return html

    def _preview_html(self, preview: Preview) -> str:
        html = ""

        if preview.problems:
            warn = theme.state_color("upgradable").name()
            html += f"<p style='margin-top:16px;color:{warn};'><b>Problems</b></p>"
            for problem in preview.problems[:8]:
                safe = problem.replace("<", "&lt;").replace(">", "&gt;")
                html += f"<p style='margin:2px 0;font-size:small;'>{safe}</p>"

        def section(title: str, items: list, colour: str) -> str:
            if not items:
                return ""
            extras = [i for i in items if not i.wanted]
            head = (
                f"<p style='margin-top:16px;color:{colour};'><b>{title}</b> "
                f"<span style='opacity:0.7;font-weight:400;'>{len(items)} package"
                f"{'s' if len(items) != 1 else ''}"
                + (f", {len(extras)} pulled in automatically" if extras else "")
                + "</span></p>"
            )
            rows = []
            for item in items:
                tag = ""
                if not item.wanted:
                    tag = (
                        "<span style='opacity:0.55;'>optional</span>"
                        if item.weak
                        else "<span style='opacity:0.55;'>dependency</span>"
                    )
                rows.append(
                    f"<tr><td style='padding:2px 14px 2px 0;'>{item.name}</td>"
                    f"<td style='padding:2px 14px 2px 0;opacity:0.75;'>{item.version}</td>"
                    f"<td style='padding:2px 14px 2px 0;opacity:0.65;'>{item.origin}</td>"
                    f"<td style='padding:2px 14px 2px 0;opacity:0.75;text-align:right;'>"
                    f"{theme.human_size(item.size)}</td>"
                    f"<td style='padding:2px 0;'>{tag}</td></tr>"
                )
            return head + f"<table style='border-collapse:collapse;'>{''.join(rows)}</table>"

        html += section("Install", preview.install, theme.state_color("installed").name())
        html += section("Upgrade", preview.upgrade, theme.state_color("upgradable").name())
        html += section("Remove", preview.remove, theme.state_color("upgradable").name())

        if preview.empty:
            html += (
                "<p style='margin-top:16px;opacity:0.8;'>Nothing to do. "
                "Everything requested is already in the state you asked for.</p>"
            )
        return html
