"""Flatpak backend, covering every configured remote in both installations."""

from __future__ import annotations

import subprocess

from .base import Backend, Package, Source, State

TIMEOUT = 90


def _parse_size(text: str) -> int:
    """flatpak prints sizes as text, so turn '1.2 MB' back into bytes."""
    text = (text or "").strip()
    if not text or text == "-":
        return 0
    units = {"b": 1, "kb": 1000, "mb": 1000**2, "gb": 1000**3,
             "kib": 1024, "mib": 1024**2, "gib": 1024**3}
    parts = text.replace("\u00a0", " ").split()
    try:
        value = float(parts[0].replace(",", "."))
    except (ValueError, IndexError):
        return 0
    unit = parts[1].lower() if len(parts) > 1 else "b"
    return int(value * units.get(unit, 1))


def _run(args: list[str]) -> str:
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


class FlatpakBackend(Backend):
    id = "flatpak"
    label = "Flatpak"
    icon = "flatpak"
    needs_root = False

    @property
    def available(self) -> bool:
        return self.has("flatpak")

    def load(self) -> list[Package]:
        if not self.available:
            return []

        installed: dict[str, Package] = {}
        cols = "application,name,description,version,branch,origin,installation,size"
        for line in _run(["flatpak", "list", "--app", f"--columns={cols}"]).splitlines():
            f = [x.strip() for x in line.split("\t")]
            if len(f) < 7:
                continue
            appid, name, desc, ver, branch, origin, inst = f[:7]
            size = _parse_size(f[7]) if len(f) > 7 else 0
            installed[appid] = Package(
                key=appid,
                name=name or appid,
                version=ver or branch,
                installed_version=ver or branch,
                summary=desc if desc and desc != "-" else appid,
                source=self.id,
                origin=origin or "unknown",
                state=State.INSTALLED,
                size=size,
                description=desc if desc and desc != "-" else "",
                url=f"https://flathub.org/apps/{appid}" if origin == "flathub" else "",
                extra={
                    "branch": branch,
                    "installation": inst or "system",
                    "appid": appid,
                },
            )

        # Pending updates promote an installed entry to upgradable.
        for line in _run(
            ["flatpak", "remote-ls", "--updates", "--app", "--columns=application,version"]
        ).splitlines():
            f = line.split("\t")
            appid = f[0].strip()
            if appid in installed:
                installed[appid].state = State.UPGRADABLE
                if len(f) > 1 and f[1].strip():
                    installed[appid].version = f[1].strip()

        return list(installed.values())

    def search_remote(self, query: str) -> list[Package]:
        """flatpak search already spans every enabled remote."""
        if not self.available or len(query) < 2:
            return []
        out: list[Package] = []
        cols = "application,name,description,version,remotes"
        for line in _run(["flatpak", "search", f"--columns={cols}", query]).splitlines():
            f = [x.strip() for x in line.split("\t")]
            if len(f) < 5 or f[0] in ("", "-"):
                continue
            appid, name, desc, ver, remotes = f[:5]
            out.append(
                Package(
                    key=appid,
                    name=name or appid,
                    version=ver if ver != "-" else "",
                    summary=desc if desc != "-" else appid,
                    source=self.id,
                    origin=remotes.split(",")[0] if remotes else "flathub",
                    state=State.AVAILABLE,
                    description=desc if desc != "-" else "",
                    url=f"https://flathub.org/apps/{appid}",
                    extra={"appid": appid},
                )
            )

        # flatpak search matches descriptions too, which buries the real hit
        # under themes and add ons. Rank name matches up and cap the tail.
        low = query.lower()

        def rank(pkg: Package) -> tuple:
            name_low = pkg.name.lower()
            app_low = pkg.key.lower()
            return (
                0 if name_low == low else
                1 if name_low.startswith(low) else
                2 if low in name_low else
                3 if low in app_low else 4,
                name_low,
            )

        out.sort(key=rank)
        return out[:40]

    def sources(self) -> list[Source]:
        if not self.available:
            return []
        out: list[Source] = []
        for line in _run(
            ["flatpak", "remotes", "--columns=name,url,title,options"]
        ).splitlines():
            f = [x.strip() for x in line.split("\t")]
            if not f or not f[0]:
                continue
            name = f[0]
            opts = f[3] if len(f) > 3 else ""
            out.append(
                Source(
                    key=name,
                    name=f[2] if len(f) > 2 and f[2] not in ("", "-") else name,
                    backend=self.id,
                    enabled="disabled" not in opts,
                    description=f"Flatpak remote ({'user' if 'user' in opts else 'system'})",
                    url=f[1] if len(f) > 1 else "",
                    removable=True,
                )
            )
        return out

    def set_source_enabled(self, key: str, enabled: bool) -> list[str]:
        flag = "--enable" if enabled else "--disable"
        return ["flatpak", "remote-modify", flag, key]

    def remove_source(self, key: str) -> list[str]:
        return ["flatpak", "remote-delete", "--force", key]

    def add_remote_cmd(self, name: str, url: str) -> list[str]:
        return ["flatpak", "remote-add", "--if-not-exists", "--user", name, url]

    def _scope(self, p: Package) -> str:
        return "--user" if p.extra.get("installation") == "user" else "--system"

    def install_cmd(self, pkgs: list[Package]) -> list[str]:
        return ["flatpak", "install", "--user", "-y", *[p.key for p in pkgs]]

    def remove_cmd(self, pkgs: list[Package]) -> list[str]:
        return ["flatpak", "uninstall", "-y", *[p.key for p in pkgs]]

    def upgrade_cmd(self, pkgs: list[Package]) -> list[str]:
        return ["flatpak", "update", "-y", *[p.key for p in pkgs]]
