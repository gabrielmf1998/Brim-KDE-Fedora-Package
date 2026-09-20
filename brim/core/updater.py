"""Self update.

Brim can be installed three ways and updates itself correctly in each:

  rpm       replace the package with the release RPM through pkexec
  appimage  swap the running AppImage file in place
  git       fast forward the checkout

Releases are read from GitHub first and GitLab second, so publishing to
either host is enough to reach everyone.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..version import (
    GITHUB_API,
    GITHUB_REPO,
    GITLAB_API,
    GITLAB_REPO,
    __version__,
    is_newer,
)

ROOT = Path(__file__).resolve().parent.parent.parent
UA = {"User-Agent": f"Brim/{__version__}"}
TIMEOUT = 20

KIND_RPM = "rpm"
KIND_APPIMAGE = "appimage"
KIND_GIT = "git"
KIND_UNKNOWN = "unknown"


@dataclass
class Release:
    version: str
    notes: str
    host: str
    url: str
    rpm_url: str = ""
    rpm_name: str = ""
    appimage_url: str = ""
    appimage_name: str = ""


def _get_json(url: str) -> object:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return json.load(response)


def _git(*args: str, cwd: Path = ROOT, timeout: int = 60) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def appimage_path() -> Path | None:
    """Set by the AppImage runtime when Brim runs from a bundle."""
    value = os.environ.get("APPIMAGE")
    return Path(value) if value and Path(value).exists() else None


def install_kind() -> str:
    if appimage_path():
        return KIND_APPIMAGE
    if (ROOT / ".git").exists():
        return KIND_GIT
    try:
        proc = subprocess.run(
            ["rpm", "-qf", str(Path(__file__).resolve())],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0 and "brim" in proc.stdout.lower():
            return KIND_RPM
    except Exception:
        pass
    return KIND_UNKNOWN


def install_kind_label() -> str:
    return {
        KIND_RPM: "installed as an RPM package",
        KIND_APPIMAGE: "running from an AppImage",
        KIND_GIT: "running from a git checkout",
        KIND_UNKNOWN: "running from a plain directory",
    }[install_kind()]


def current_describe() -> str:
    if (ROOT / ".git").exists():
        code, out = _git("describe", "--tags", "--always", "--dirty")
        if code == 0 and out:
            return f"{__version__} ({out})"
    return __version__


def _pick_assets(names_urls: list[tuple[str, str]], release: Release) -> None:
    for name, url in names_urls:
        low = name.lower()
        if low.endswith(".rpm") and not release.rpm_url:
            release.rpm_url, release.rpm_name = url, name
        elif low.endswith(".appimage") and not release.appimage_url:
            release.appimage_url, release.appimage_name = url, name


def fetch_github() -> Release | None:
    data = _get_json(f"{GITHUB_API}/repos/{GITHUB_REPO}/releases/latest")
    if not isinstance(data, dict) or not data.get("tag_name"):
        return None
    release = Release(
        version=data["tag_name"],
        notes=(data.get("body") or "").strip(),
        host="GitHub",
        url=data.get("html_url", ""),
    )
    _pick_assets(
        [(a.get("name", ""), a.get("browser_download_url", "")) for a in data.get("assets", [])],
        release,
    )
    return release


def fetch_gitlab() -> Release | None:
    slug = urllib.parse.quote(GITLAB_REPO, safe="")
    data = _get_json(f"{GITLAB_API}/projects/{slug}/releases")
    if not isinstance(data, list) or not data:
        return None
    entry = data[0]
    release = Release(
        version=entry.get("tag_name", ""),
        notes=(entry.get("description") or "").strip(),
        host="GitLab",
        url=entry.get("_links", {}).get("self", ""),
    )
    links = entry.get("assets", {}).get("links", []) or []
    _pick_assets([(l.get("name", ""), l.get("url", "")) for l in links], release)
    if not release.rpm_url:
        sources = entry.get("assets", {}).get("sources", []) or []
        _pick_assets([(s.get("format", ""), s.get("url", "")) for s in sources], release)
    return release


def latest_release() -> tuple[Release | None, str]:
    """Try GitHub, then GitLab. Returns the release and any error text."""
    problems = []
    for name, fetch in (("GitHub", fetch_github), ("GitLab", fetch_gitlab)):
        try:
            release = fetch()
            if release and release.version:
                return release, ""
            problems.append(f"{name}: no releases published yet")
        except urllib.error.HTTPError as exc:
            problems.append(f"{name}: HTTP {exc.code}")
        except Exception as exc:
            problems.append(f"{name}: {str(exc)[:60]}")
    return None, "; ".join(problems)




class UpdateCheck(QThread):
    """Reports whether a newer release exists, without touching anything."""

    result = Signal(bool, object, str)

    def run(self) -> None:
        kind = install_kind()
        if kind == KIND_GIT:
            ok, behind, message = self._check_git()
            if ok and behind:
                release = Release(
                    version=f"{behind} new commit{'s' if behind > 1 else ''}",
                    notes=message,
                    host="git",
                    url="",
                )
                self.result.emit(True, release, "")
                return
            self.result.emit(ok, None, message)
            return

        release, error = latest_release()
        if release is None:
            self.result.emit(False, None, error or "Could not reach either host")
            return
        if is_newer(release.version):
            self.result.emit(True, release, "")
        else:
            self.result.emit(True, None, f"Brim {__version__} is the latest release")

    @staticmethod
    def _check_git() -> tuple[bool, int, str]:
        code, remotes = _git("remote")
        if code != 0 or not remotes.strip():
            return False, 0, "No git remote configured"
        code, out = _git("fetch", "--quiet", timeout=90)
        if code != 0:
            return False, 0, f"Fetch failed: {out[:160]}"
        code, branch = _git("rev-parse", "--abbrev-ref", "HEAD")
        if code != 0:
            return False, 0, "Could not read the current branch"
        code, out = _git("rev-list", "--count", f"HEAD..origin/{branch}")
        if code != 0:
            return False, 0, f"No upstream branch for {branch}"
        behind = int(out.strip() or "0")
        if not behind:
            return True, 0, "Brim is up to date"
        _, log = _git("log", "--oneline", f"HEAD..origin/{branch}", "-6")
        return True, behind, log


class UpdateApply(QThread):
    """Applies an update the right way for how Brim was installed."""

    line = Signal(str)
    finished_ok = Signal(bool, str)

    def __init__(self, release: Release | None = None, parent=None) -> None:
        super().__init__(parent)
        self.release = release

    def run(self) -> None:
        kind = install_kind()
        try:
            if kind == KIND_GIT:
                self._apply_git()
            elif kind == KIND_APPIMAGE:
                self._apply_appimage()
            elif kind == KIND_RPM:
                self._apply_rpm()
            else:
                self.finished_ok.emit(
                    False,
                    "Brim is running from a plain directory. Reinstall it with the "
                    "RPM, the AppImage or a git clone to get automatic updates.",
                )
        except Exception as exc:
            self.line.emit(f"error: {exc}")
            self.finished_ok.emit(False, str(exc)[:200])

    def _download(self, url: str, dest: Path) -> None:
        self.line.emit(f"Downloading {url}")
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as response:
            size = int(response.headers.get("Content-Length") or 0)
            done = mark = 0
            with open(dest, "wb") as handle:
                while True:
                    chunk = response.read(262144)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if size:
                        pct = int(done / size * 100)
                        if pct >= mark + 20:
                            mark = pct
                            self.line.emit(f"  {pct}%")
        self.line.emit(f"Saved {dest}")

    def _apply_git(self) -> None:
        code, dirty = _git("status", "--porcelain")
        if code == 0 and dirty.strip():
            self.finished_ok.emit(
                False, "Local changes present. Commit or stash them first."
            )
            return
        self.line.emit("Fast forwarding the checkout")
        code, out = _git("pull", "--ff-only", timeout=120)
        for raw in out.splitlines():
            if raw.strip():
                self.line.emit(raw)
        if code != 0:
            self.finished_ok.emit(False, "Pull failed, see the log above")
            return
        self.finished_ok.emit(True, f"Updated to {current_describe()}. Restart Brim.")

    def _apply_appimage(self) -> None:
        current = appimage_path()
        if not self.release or not self.release.appimage_url:
            self.finished_ok.emit(False, "That release has no AppImage attached.")
            return

        # The file name carries the version, so keeping the old name would
        # leave a 1.0.0 file holding 1.0.1. Land it under the new name and
        # repoint everything that referred to the old one.
        new_name = self.release.appimage_name or current.name
        target = current.parent / new_name
        staged = target.with_suffix(target.suffix + ".part")

        self._download(self.release.appimage_url, staged)
        os.chmod(staged, 0o755)

        if target.exists():
            target.unlink()
        staged.replace(target)

        if current != target and current.exists():
            current.unlink()
            self.line.emit(f"Removed {current.name}")

        self._repoint(current, target)
        self.line.emit(f"Installed {target}")
        self.finished_ok.emit(
            True, f"Updated to {self.release.version}. Restart Brim to run it."
        )

    def _repoint(self, old: Path, new: Path) -> None:
        """Follow the launcher and the desktop entry over to the new file."""
        if old == new:
            return

        link = Path.home() / ".local/bin/brim"
        try:
            if link.is_symlink() and Path(os.readlink(link)) == old:
                link.unlink()
                link.symlink_to(new)
                self.line.emit(f"Relinked {link}")
        except OSError as exc:
            self.line.emit(f"Could not update {link}: {exc}")

        entry = Path.home() / ".local/share/applications/brim.desktop"
        try:
            if entry.exists():
                text = entry.read_text()
                if str(old) in text:
                    entry.write_text(text.replace(str(old), str(new)))
                    self.line.emit(f"Updated {entry}")
        except OSError as exc:
            self.line.emit(f"Could not update {entry}: {exc}")

    def _apply_rpm(self) -> None:
        if not self.release or not self.release.rpm_url:
            self.finished_ok.emit(False, "That release has no RPM attached.")
            return
        cache = Path.home() / ".cache/brim"
        cache.mkdir(parents=True, exist_ok=True)
        rpm_file = cache / (self.release.rpm_name or "brim-update.rpm")
        self._download(self.release.rpm_url, rpm_file)

        cmd = ["pkexec", "dnf", "install", "-y", str(rpm_file)]
        self.line.emit(f"$ {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=dict(os.environ, LC_ALL="C.UTF-8"),
        )
        assert proc.stdout is not None
        for raw in proc.stdout:
            if raw.strip():
                self.line.emit(raw.rstrip())
        code = proc.wait()
        rpm_file.unlink(missing_ok=True)
        if code == 0:
            self.finished_ok.emit(
                True, f"Updated to {self.release.version}. Restart Brim."
            )
        elif code == 126:
            self.finished_ok.emit(False, "Authorization dismissed")
        else:
            self.finished_ok.emit(False, f"dnf exited with status {code}")
