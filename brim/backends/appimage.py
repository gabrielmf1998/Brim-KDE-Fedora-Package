"""AppImage backend, fed by the public AppImageHub catalog.

Catalog metadata is cached on disk for a day. Installing resolves the real
asset URL from the upstream GitHub release, drops the file in ~/Applications,
marks it executable and writes a desktop entry so it shows up in the launcher.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path

from .base import Backend, Package, Source, State

FEED = "https://appimage.github.io/feed.json"
UA = {"User-Agent": "Brim/1.0 (Fedora package manager)"}
TIMEOUT = 20
CACHE_TTL = 86400

APPS_DIR = Path.home() / "Applications"
DESKTOP_DIR = Path.home() / ".local/share/applications"
STATE_DIR = Path.home() / ".local/share/brim"
MANIFEST = STATE_DIR / "appimages.json"
CACHE = STATE_DIR / "appimage-feed.json"


def _slug(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", name).strip("-").lower()


def _github_from_url(url: str) -> str:
    """Pull owner/repo out of any github.com URL, releases page included."""
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", url or "")
    if not m:
        return ""
    owner, repo = m.group(1), m.group(2)
    return f"{owner}/{repo.removesuffix('.git')}"


class AppImageBackend(Backend):
    id = "appimage"
    label = "AppImage"
    icon = "application-x-executable"
    needs_root = False

    def __init__(self) -> None:
        self._catalog: list[dict] = []

    def _load_catalog(self) -> list[dict]:
        if self._catalog:
            return self._catalog
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if CACHE.exists() and time.time() - CACHE.stat().st_mtime < CACHE_TTL:
            try:
                self._catalog = json.loads(CACHE.read_text()).get("items", [])
                return self._catalog
            except Exception:
                pass
        try:
            req = urllib.request.Request(FEED, headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
            CACHE.write_bytes(raw)
            self._catalog = json.loads(raw).get("items", [])
        except Exception:
            self._catalog = []
        return self._catalog

    @staticmethod
    def _manifest() -> dict:
        try:
            return json.loads(MANIFEST.read_text())
        except Exception:
            return {}

    def load(self) -> list[Package]:
        """Only installed AppImages up front. The catalog is search driven."""
        man = self._manifest()
        out: list[Package] = []
        for key, rec in man.items():
            path = Path(rec.get("path", ""))
            if not path.exists():
                continue
            out.append(
                Package(
                    key=key,
                    name=rec.get("name", key),
                    version=rec.get("version", "installed"),
                    installed_version=rec.get("version", "installed"),
                    summary=rec.get("summary", "AppImage"),
                    source=self.id,
                    origin=rec.get("origin", "appimage"),
                    state=State.INSTALLED,
                    size=path.stat().st_size,
                    url=rec.get("url", ""),
                    extra={"path": str(path)},
                )
            )
        return out

    def search_remote(self, query: str) -> list[Package]:
        if len(query) < 2:
            return []
        q = query.lower()
        man = self._manifest()
        out: list[Package] = []
        for item in self._load_catalog():
            name = item.get("name") or ""
            desc = (item.get("description") or "").strip()
            in_name = q in name.lower()
            if not in_name and q not in desc.lower():
                continue
            key = _slug(name)
            gh, dl = "", ""
            for link in item.get("links") or []:
                kind = (link.get("type") or "").lower()
                if kind == "github" and not gh:
                    gh = link.get("url") or ""
                elif kind in ("download", "install") and not dl:
                    dl = link.get("url") or ""
            if not gh and dl:
                gh = _github_from_url(dl)
            out.append(
                Package(
                    key=key,
                    name=name,
                    version="latest release",
                    summary=desc[:160] or "AppImage",
                    source=self.id,
                    origin="AppImageHub",
                    state=State.INSTALLED if key in man else State.AVAILABLE,
                    description=desc,
                    license=item.get("license") or "",
                    url=f"https://github.com/{gh}" if gh else "",
                    extra={
                        "github": gh,
                        "download": dl,
                        "catalog_name": name,
                        "installable": bool(gh),
                    },
                )
            )
            if len(out) >= 60:
                break
        def rank(p: Package) -> tuple:
            low = p.name.lower()
            return (
                0 if low == q else 1 if low.startswith(q) else 2 if q in low else 3,
                0 if p.extra.get("installable") else 1,
                low,
            )

        out.sort(key=rank)
        return out

    def sources(self) -> list[Source]:
        return [
            Source(
                key="appimagehub",
                name="AppImageHub catalog",
                backend=self.id,
                enabled=True,
                description=f"{len(self._load_catalog())} apps, community maintained",
                url=FEED,
            )
        ]

    def set_source_enabled(self, key: str, enabled: bool) -> list[str]:
        raise NotImplementedError("The AppImage catalog cannot be disabled")

    def resolve_download(self, pkg: Package) -> tuple[str, str]:
        """Return (url, filename) for the newest AppImage asset upstream."""
        gh = pkg.extra.get("github") or ""
        if not gh:
            raise RuntimeError(
                f"{pkg.name} has no automatic download source in the catalog. "
                "Open its page and grab the AppImage by hand."
            )
        # Monorepos often ship the AppImage a few releases back, so walk the
        # recent list instead of trusting /releases/latest alone.
        api = f"https://api.github.com/repos/{gh}/releases?per_page=15"
        req = urllib.request.Request(api, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            releases = json.load(r)
        if isinstance(releases, dict):
            releases = [releases]

        arch_pref = ("x86_64", "amd64")
        for rel in releases:
            if rel.get("draft"):
                continue
            assets = [
                a
                for a in rel.get("assets", [])
                if a.get("name", "").lower().endswith(".appimage")
                and "arm" not in a.get("name", "").lower()
                and "aarch64" not in a.get("name", "").lower()
                and "i386" not in a.get("name", "").lower()
            ]
            if not assets:
                continue
            assets.sort(
                key=lambda a: (
                    0 if any(x in a["name"].lower() for x in arch_pref) else 1,
                    -a.get("size", 0),
                )
            )
            best = assets[0]
            return best["browser_download_url"], best["name"]

        raise RuntimeError(
            f"No x86_64 AppImage found in the last {len(releases)} releases of {gh}"
        )

    def record_install(self, pkg: Package, path: Path, version: str) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        man = self._manifest()
        man[pkg.key] = {
            "name": pkg.name,
            "summary": pkg.summary,
            "version": version,
            "path": str(path),
            "origin": "AppImageHub",
            "url": pkg.url,
        }
        MANIFEST.write_text(json.dumps(man, indent=2))

    def forget(self, key: str) -> None:
        man = self._manifest()
        man.pop(key, None)
        MANIFEST.write_text(json.dumps(man, indent=2))

    def desktop_entry(self, pkg: Package, path: Path) -> Path:
        DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
        dest = DESKTOP_DIR / f"brim-{pkg.key}.desktop"
        dest.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={pkg.name}\n"
            f"Comment={pkg.summary[:120]}\n"
            f"Exec={path} %U\n"
            "Icon=application-x-executable\n"
            "Terminal=false\n"
            "Categories=Utility;\n"
            "X-Brim-Managed=true\n"
        )
        os.chmod(dest, 0o755)
        return dest

    def install_cmd(self, pkgs: list[Package]) -> list[str]:
        """Handled natively by the transaction runner, not through a shell."""
        raise NotImplementedError("AppImage installs run in process")

    def remove_cmd(self, pkgs: list[Package]) -> list[str]:
        raise NotImplementedError("AppImage removals run in process")

    def upgrade_cmd(self, pkgs: list[Package]) -> list[str]:
        raise NotImplementedError("AppImage upgrades run in process")
