"""Help: what each source is, what it costs you, and how Brim behaves.

The COPR section is deliberately blunt. Community builds are genuinely
useful and genuinely unreviewed, and a package manager that hides that is
doing the user a disservice.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..version import __version__
from . import theme


def _palette_css() -> str:
    warn = theme.state_color("upgradable").name()
    good = theme.state_color("installed").name()
    return f"""
    <style>
      h2 {{ margin-top: 22px; margin-bottom: 4px; }}
      h3 {{ margin-top: 16px; margin-bottom: 2px; }}
      p, li {{ line-height: 145%; }}
      code {{ background: rgba(127,127,127,0.18); padding: 1px 4px; border-radius: 3px; }}
      .warn {{ color: {warn}; font-weight: 600; }}
      .good {{ color: {good}; font-weight: 600; }}
      .muted {{ opacity: 0.75; }}
      table {{ border-collapse: collapse; margin: 8px 0; }}
      td, th {{ padding: 5px 16px 5px 0; text-align: left; vertical-align: top; }}
    </style>
    """


def _source_color(source: str) -> str:
    return theme.source_color(source).name()


def build_html() -> str:
    dnf = _source_color("dnf")
    flatpak = _source_color("flatpak")
    copr = _source_color("copr")
    appimage = _source_color("appimage")

    return f"""{_palette_css()}
<h1>Brim {__version__}</h1>
<p>One window over every place Fedora gets software from. Brim is
<b>for Fedora only</b>. It talks to <code>dnf5</code> and <code>libdnf5</code>
directly, so it will not work on Debian, Arch, or anything that is not
RPM and DNF based.</p>

<h2>The four sources</h2>

<h3 style="color:{dnf};">DNF</h3>
<p>Every repository already enabled on your system: Fedora itself, RPM Fusion,
any COPR you have turned on, and vendor repos such as Google Chrome. This is
the safest source. Packages here are built by Fedora or by a repository you
chose to trust, and they integrate properly with the rest of the system.</p>

<h3 style="color:{flatpak};">Flatpak</h3>
<p>Sandboxed applications from Flathub and any other remote you add. Good for
desktop apps that want to be newer than Fedora ships, and for anything you
would rather keep away from the rest of the system. Costs more disk, and each
app carries its own runtime.</p>

<h3 style="color:{copr};">COPR <span class="warn">read this part</span></h3>
<p>COPR is Fedora's community build service. Anyone with a Fedora account can
publish a repository there. Brim searches <b>all of COPR</b>, not just what you
have enabled, which is powerful and is also the part that deserves care.</p>

<table>
  <tr>
    <th class="good">What it gives you</th>
    <th class="warn">What you take on</th>
  </tr>
  <tr>
    <td>
      Software Fedora cannot or will not ship<br>
      Newer versions than the official repos<br>
      Niche and hardware specific tools<br>
      Often the only packaged option that exists
    </td>
    <td>
      <b>No review by Fedora.</b> Nobody audits the code or the spec<br>
      <b>No security promise.</b> Updates arrive only if the owner cares<br>
      <b>Projects get abandoned</b> and quietly stop building<br>
      <b>Packages can conflict</b> with official ones and break upgrades<br>
      <b>Full root at install time</b>, like any RPM
    </td>
  </tr>
</table>

<p><b>Before enabling a COPR, look at the project page.</b> Brim links to it in
the details pane. Check that builds are recent, that the chroot for your Fedora
release is actually there, and that the owner looks like someone maintaining it
rather than someone who pushed once in 2021.</p>

<p class="muted">Rule of thumb: prefer Fedora, then RPM Fusion, then Flatpak,
then COPR. Reach for COPR when the thing you want exists nowhere else.</p>

<h3 style="color:{appimage};">AppImage</h3>
<p>Single file applications from the community AppImageHub catalog. Nothing is
installed system wide: Brim downloads the file to <code>~/Applications</code>,
marks it executable and writes a launcher entry. Same caution as COPR applies,
since these come straight from upstream with no distribution in between. Some
catalog entries have no download link at all, and Brim labels those rather than
guessing.</p>

<h2>How the search works</h2>
<p>Typing runs three passes that fill in as they finish:</p>
<table>
  <tr><td><b>Instant</b></td><td>Name and summary across everything already indexed</td></tr>
  <tr><td><b>By content</b></td><td>Packages that ship a matching command, provide a
      matching library, or describe themselves that way. Searching
      <code>screen record</code> finds <code>wf-recorder</code>; searching
      <code>ffmpeg</code> finds everything that links against it</td></tr>
  <tr><td><b>Network</b></td><td>All of COPR, the Flatpak remotes and the AppImage
      catalog</td></tr>
</table>

<h2>Transactions</h2>
<p>Anything touching RPM runs through <code>pkexec</code>, so you get the normal
authentication prompt and the real <code>dnf</code> output streamed live. Your
<code>/etc/dnf/dnf.conf</code> stays in charge: <code>excludepkgs</code> and
every other rule you set still applies. Brim never works around your own
configuration.</p>

<h2>Updates</h2>
<p>Brim checks its own sources on the schedule you pick in Settings, and it can
update itself from the project release page. You choose whether that check is
manual, on startup, or on an interval. Automatic application only runs
unattended for Flatpak and AppImage, because anything RPM needs an
authentication prompt by design.</p>

<h2>Keyboard</h2>
<table>
  <tr><td><code>Ctrl+F</code></td><td>Focus the search box</td></tr>
  <tr><td><code>Ctrl+L</code></td><td>Clear the search</td></tr>
  <tr><td><code>F5</code></td><td>Reload every source</td></tr>
</table>
"""


class HelpPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.view.document().setDocumentMargin(22)
        layout.addWidget(self.view)
        self.refresh()

    def refresh(self) -> None:
        """Rebuilt on show so the colours follow the current palette."""
        self.view.setHtml(build_html())
