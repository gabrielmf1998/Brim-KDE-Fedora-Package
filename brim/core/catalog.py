"""Aggregates every backend into one searchable view."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ..backends.base import Backend, Package, Source, State


class Catalog:
    """Holds the merged package set and fans queries out to the backends."""

    def __init__(self, backends: list[Backend]) -> None:
        self.backends = {b.id: b for b in backends}
        self.packages: list[Package] = []
        self.errors: dict[str, str] = {}

    def active(self, enabled_ids: set[str]) -> list[Backend]:
        return [
            b
            for bid, b in self.backends.items()
            if bid in enabled_ids and b.available
        ]

    def reload(self, enabled_ids: set[str]) -> list[Package]:
        """Load every enabled backend at once. Slowest one sets the pace."""
        self.errors.clear()
        backends = self.active(enabled_ids)
        results: list[Package] = []

        def run(b: Backend) -> list[Package]:
            try:
                return b.load()
            except Exception as exc:
                self.errors[b.id] = str(exc)
                return []

        with ThreadPoolExecutor(max_workers=max(1, len(backends))) as pool:
            for chunk in pool.map(run, backends):
                results.extend(chunk)

        self.packages = results
        return results

    def search_remote(self, query: str, enabled_ids: set[str]) -> list[Package]:
        """Network catalogs that are too big to hold locally: COPR, AppImage, Flatpak."""
        backends = self.active(enabled_ids)
        found: list[Package] = []

        def run(b: Backend) -> list[Package]:
            try:
                return b.search_remote(query)
            except Exception as exc:
                self.errors[b.id] = str(exc)
                return []

        with ThreadPoolExecutor(max_workers=max(1, len(backends))) as pool:
            for chunk in pool.map(run, backends):
                found.extend(chunk)
        return found

    def sources(self, enabled_ids: set[str]) -> list[Source]:
        out: list[Source] = []
        for b in self.active(enabled_ids):
            try:
                out.extend(b.sources())
            except Exception as exc:
                self.errors[b.id] = str(exc)
        return out

    def upgradable(self) -> list[Package]:
        return [p for p in self.packages if p.state is State.UPGRADABLE]

    def counts(self) -> dict[str, dict[str, int]]:
        """Per backend tallies for the source chips at the top of the window."""
        out: dict[str, dict[str, int]] = {}
        for p in self.packages:
            slot = out.setdefault(p.source, {"total": 0, "installed": 0, "updates": 0})
            slot["total"] += 1
            if p.installed:
                slot["installed"] += 1
            if p.upgradable:
                slot["updates"] += 1
        return out
