"""Uniform package model and backend contract shared by every source."""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class State(str, Enum):
    """Where a package stands on this machine."""

    INSTALLED = "installed"
    AVAILABLE = "available"
    UPGRADABLE = "upgradable"


@dataclass(slots=True)
class Package:
    """One package, normalized across every backend.

    `key` is unique per backend and is what transactions are built from.
    """

    key: str
    name: str
    version: str
    summary: str
    source: str
    origin: str
    state: State = State.AVAILABLE
    arch: str = ""
    installed_version: str = ""
    size: int = 0
    license: str = ""
    url: str = ""
    description: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def upgradable(self) -> bool:
        return self.state is State.UPGRADABLE

    @property
    def installed(self) -> bool:
        return self.state in (State.INSTALLED, State.UPGRADABLE)

    @property
    def version_diff(self) -> str:
        """Human readable transition, used by the list and the details pane."""
        if self.state is State.UPGRADABLE and self.installed_version:
            return f"{self.installed_version}  >  {self.version}"
        return self.version

    def matches(self, needle: str) -> bool:
        needle = needle.lower()
        return needle in self.name.lower() or needle in self.summary.lower()


@dataclass(slots=True)
class Source:
    """A place packages come from: a dnf repo, a flatpak remote, a copr project."""

    key: str
    name: str
    backend: str
    enabled: bool
    description: str = ""
    url: str = ""
    removable: bool = False


class Backend(ABC):
    """Contract every source implements.

    Read paths run in worker threads and must not touch Qt. Write paths return
    an argv list so the transaction runner can stream output and, where needed,
    escalate through pkexec.
    """

    id: str = ""
    label: str = ""
    icon: str = "package-x-generic"
    needs_root: bool = False

    @property
    def available(self) -> bool:
        """False disables the backend and greys out its filter chip."""
        return True

    @abstractmethod
    def load(self) -> list[Package]:
        """Return everything this backend knows about, installed or not."""

    def search_remote(self, query: str) -> list[Package]:
        """Hit a network catalog that is too large to hold in memory.

        Backends that load everything up front leave this empty.
        """
        return []

    def search_deep(self, query: str) -> list[Package]:
        """Local index lookups beyond the name: files, provides, descriptions.

        Cheap enough to run on every keystroke, unlike `search_remote`.
        """
        return []

    def sources(self) -> list[Source]:
        return []

    def set_source_enabled(self, key: str, enabled: bool) -> list[str]:
        raise NotImplementedError

    def remove_source(self, key: str) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def install_cmd(self, pkgs: list[Package]) -> list[str]: ...

    @abstractmethod
    def remove_cmd(self, pkgs: list[Package]) -> list[str]: ...

    @abstractmethod
    def upgrade_cmd(self, pkgs: list[Package]) -> list[str]: ...

    @staticmethod
    def has(binary: str) -> bool:
        return shutil.which(binary) is not None
