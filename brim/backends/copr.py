"""COPR backend.

This is the piece no other Fedora frontend gives you: search across every
public COPR project, not just the ones already enabled on the machine.
A result here is an offer to enable a repo and pull a package from it.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import Backend, Package, Source, State

API = "https://copr.fedorainfracloud.org/api_3"
UA = {"User-Agent": "Brim/1.0 (Fedora package manager)"}
TIMEOUT = 12
MAX_PROJECTS = 12


def _get(path: str, **params) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


class CoprBackend(Backend):
    id = "copr"
    label = "COPR"
    icon = "applications-development"
    needs_root = True

    def __init__(self, enabled_repo_ids: set[str] | None = None) -> None:
        self.enabled_repo_ids = enabled_repo_ids or set()

    def load(self) -> list[Package]:
        """Nothing up front. COPR is far too large to mirror locally."""
        return []

    def _is_enabled(self, owner: str, project: str) -> bool:
        needle = f"copr:copr.fedorainfracloud.org:{owner}:{project}".lower()
        return needle in {r.lower() for r in self.enabled_repo_ids}

    def search_remote(self, query: str) -> list[Package]:
        if len(query) < 3:
            return []
        try:
            data = _get("project/search", query=query)
        except Exception:
            return []

        projects = data.get("items", [])[:MAX_PROJECTS]
        if not projects:
            return []

        out: list[Package] = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(self._packages_of, p): p for p in projects
            }
            for fut in as_completed(futures, timeout=TIMEOUT + 4):
                proj = futures[fut]
                owner = proj.get("ownername", "")
                name = proj.get("name", "")
                desc = (proj.get("description") or "").strip().replace("\n", " ")
                try:
                    names = fut.result()
                except Exception:
                    names = []

                enabled = self._is_enabled(owner, name)
                hits = [n for n in names if query.lower() in n.lower()] or names[:1]
                for pkg_name in hits[:4]:
                    out.append(
                        Package(
                            key=f"{owner}/{name}#{pkg_name}",
                            name=pkg_name,
                            version="copr build",
                            summary=desc[:160] or f"From COPR {owner}/{name}",
                            source=self.id,
                            origin=f"{owner}/{name}",
                            state=State.AVAILABLE,
                            description=desc,
                            url=f"https://copr.fedorainfracloud.org/coprs/{owner}/{name}/",
                            extra={
                                "owner": owner,
                                "project": name,
                                "pkg": pkg_name,
                                "repo_enabled": enabled,
                            },
                        )
                    )
        out.sort(key=lambda p: (not p.extra.get("repo_enabled"), p.name.lower()))
        return out

    @staticmethod
    def _packages_of(project: dict) -> list[str]:
        try:
            data = _get(
                "package/list",
                ownername=project.get("ownername", ""),
                projectname=project.get("name", ""),
            )
            return [i["name"] for i in data.get("items", [])]
        except Exception:
            return []

    def sources(self) -> list[Source]:
        """Enabled COPRs are reported by the dnf backend, not duplicated here."""
        return []

    def install_cmd(self, pkgs: list[Package]) -> list[str]:
        """Enable each project, then install the packages in one dnf call."""
        parts: list[str] = []
        projects = {f"{p.extra['owner']}/{p.extra['project']}" for p in pkgs}
        for proj in sorted(projects):
            parts.append(f"dnf copr enable -y {proj}")
        names = " ".join(sorted({p.extra["pkg"] for p in pkgs}))
        parts.append(f"dnf install -y {names}")
        return ["sh", "-c", " && ".join(parts)]

    def remove_cmd(self, pkgs: list[Package]) -> list[str]:
        return ["dnf", "remove", "-y", *[p.extra["pkg"] for p in pkgs]]

    def upgrade_cmd(self, pkgs: list[Package]) -> list[str]:
        return ["dnf", "upgrade", "-y", *[p.extra["pkg"] for p in pkgs]]
