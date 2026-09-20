"""Update checking for RPMs installed by hand.

A package installed from a downloaded .rpm has no repository behind it, so
dnf will never offer it an update. It just sits there getting older. Brim
finds those packages, works out where they came from, and checks upstream.

Where it looks, in order:

  1. a mapping the user set themselves, which always wins
  2. the URL tag in the RPM itself, when it points at GitHub or GitLab
  3. a small built in map for projects whose homepage is not their forge

Nothing is installed without the same resolution check a normal transaction
gets, so an update that would break the system is reported rather than run.
"""

from __future__ import annotations

import fnmatch
import json
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

UA = {"User-Agent": "Brim (Fedora package manager)"}
TIMEOUT = 15

# Repos that never appear as a real source for an installed package.
UNMANAGED_REPOS = frozenset({"@commandline", "", "unknown", "@System", "@Local"})

# Never offered an upstream update, whatever their URL says.
#
# Kernel modules are rebuilt by akmods against the running kernel, so an
# upstream RPM would fight the thing that is already managing them. Brim is
# excluded because it has its own updater. gpg-pubkey is not a package.
SKIP_PREFIXES = ("kmod-", "akmod-", "kernel-", "gpg-pubkey", "brim")

# Projects whose homepage is not their forge. Kept deliberately short: this
# is a convenience, not a registry, and the user mapping overrides it.
KNOWN_PROJECTS = {
    "vesktop": "github:Vencord/Vesktop",
    "heroic": "github:Heroic-Games-Launcher/HeroicGamesLauncher",
    "obsidian": "github:obsidianmd/obsidian-releases",
    "rustdesk": "github:rustdesk/rustdesk",
    "localsend": "github:localsend/localsend",
    "ventoy": "github:ventoy/Ventoy",
}

FORGE_RE = re.compile(
    r"(?P<host>github\.com|gitlab\.com)/(?P<owner>[^/\s]+)/(?P<repo>[^/\s#?]+)"
)


@dataclass
class Upstream:
    """A newer build found upstream for a hand installed package."""

    name: str
    installed_version: str
    new_version: str
    rpm_url: str
    rpm_name: str
    release_url: str
    forge: str


def parse_forge(url: str) -> str | None:
    """Turn any forge URL into 'github:owner/repo' or 'gitlab:owner/repo'."""
    match = FORGE_RE.search(url or "")
    if not match:
        return None
    host = "github" if "github" in match.group("host") else "gitlab"
    repo = match.group("repo").removesuffix(".git")
    return f"{host}:{match.group('owner')}/{repo}"


def resolve_source(name: str, url: str, user_map: dict) -> str | None:
    if name in user_map and user_map[name]:
        return user_map[name]
    from_url = parse_forge(url)
    if from_url:
        return from_url
    return KNOWN_PROJECTS.get(name.lower())


def _get(url: str) -> object:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        return json.load(response)


def _rpm_assets_github(slug: str) -> tuple[str, list[tuple[str, str]]]:
    data = _get(f"https://api.github.com/repos/{slug}/releases/latest")
    tag = data.get("tag_name", "")
    assets = [
        (a.get("name", ""), a.get("browser_download_url", ""))
        for a in data.get("assets", [])
    ]
    return tag, assets


def _rpm_assets_gitlab(slug: str) -> tuple[str, list[tuple[str, str]]]:
    encoded = urllib.parse.quote(slug, safe="")
    data = _get(f"https://gitlab.com/api/v4/projects/{encoded}/releases")
    if not isinstance(data, list) or not data:
        return "", []
    entry = data[0]
    links = entry.get("assets", {}).get("links", []) or []
    return entry.get("tag_name", ""), [
        (l.get("name", ""), l.get("url", "")) for l in links
    ]


def _pick_rpm(assets: list[tuple[str, str]], arch: str) -> tuple[str, str]:
    """Prefer this machine's arch, then noarch, and never a source RPM."""
    candidates = [
        (n, u) for n, u in assets if n.lower().endswith(".rpm") and ".src." not in n.lower()
    ]
    if not candidates:
        return "", ""
    for wanted in (arch, "noarch"):
        for name, url in candidates:
            if wanted and wanted in name:
                return name, url
    return candidates[0]


def version_of_tag(tag: str) -> str:
    return (tag or "").strip().lstrip("vV")


def newer(candidate: str, current: str) -> bool:
    """RPM version comparison, so 1.10 beats 1.9 the way rpm sees it."""
    try:
        import libdnf5

        return libdnf5.rpm.rpmvercmp(candidate, current) > 0
    except Exception:
        def parts(text):
            return [int(c) if c.isdigit() else c for c in re.split(r"[._-]", text) if c]
        try:
            return parts(candidate) > parts(current)
        except TypeError:
            return candidate != current


class SideloadChecker:
    """Checks every hand installed package against its upstream release page."""

    def __init__(
        self, user_map: dict | None = None, excludes: list[str] | None = None
    ) -> None:
        self.user_map = user_map or {}
        # Whatever excludepkgs says in dnf.conf is law here too. If the user
        # pinned something deliberately, Brim does not go around them.
        self.excludes = list(excludes or [])
        self.skipped: dict[str, str] = {}

    def _excluded(self, name: str) -> bool:
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in self.excludes)

    def candidates(self, packages: list) -> list:
        """Installed packages that no repository is looking after."""
        out = []
        for pkg in packages:
            if not pkg.installed or pkg.source != "dnf":
                continue
            if pkg.origin not in UNMANAGED_REPOS:
                continue
            if pkg.name.startswith(SKIP_PREFIXES):
                continue
            if self._excluded(pkg.name):
                self.skipped[pkg.name] = (
                    "Held back by excludepkgs in your dnf.conf. Brim respects that."
                )
                continue
            out.append(pkg)
        return out

    def check(self, packages: list) -> list[Upstream]:
        found: list[Upstream] = []
        self.skipped.clear()
        # candidates() records its own skip reasons, so clear first.

        targets = []
        for pkg in self.candidates(packages):
            source = resolve_source(pkg.name, pkg.url, self.user_map)
            if not source:
                self.skipped[pkg.name] = (
                    "No project page recorded. Point it at a repository in Settings."
                )
                continue
            targets.append((pkg, source))

        if not targets:
            return found

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(self._one, p, s): p for p, s in targets}
            for future in as_completed(futures, timeout=TIMEOUT + 10):
                pkg = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    self.skipped[pkg.name] = str(exc)[:120]
                    continue
                if result:
                    found.append(result)
        return found

    def _one(self, pkg, source: str) -> Upstream | None:
        forge, slug = source.split(":", 1)
        if forge == "github":
            tag, assets = _rpm_assets_github(slug)
        else:
            tag, assets = _rpm_assets_gitlab(slug)

        if not tag:
            self.skipped[pkg.name] = f"No releases published at {slug}"
            return None

        upstream_version = version_of_tag(tag)
        installed = pkg.installed_version or pkg.version
        installed_base = installed.split("-")[0]

        if not newer(upstream_version, installed_base):
            return None

        rpm_name, rpm_url = _pick_rpm(assets, pkg.arch)
        if not rpm_url:
            self.skipped[pkg.name] = (
                f"{tag} is newer but that release ships no RPM for {pkg.arch}"
            )
            return None

        base = "https://github.com" if forge == "github" else "https://gitlab.com"
        return Upstream(
            name=pkg.name,
            installed_version=installed,
            new_version=upstream_version,
            rpm_url=rpm_url,
            rpm_name=rpm_name,
            release_url=f"{base}/{slug}/releases",
            forge=forge,
        )
