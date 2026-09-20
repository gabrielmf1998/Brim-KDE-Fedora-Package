"""DNF5 backend.

Reads go straight through libdnf5, which is why Brim starts in well under a
second where PackageKit frontends take tens of seconds. Writes shell out to
dnf under pkexec so the user sees a real transaction and a real password
prompt, and so every dnf.conf rule (excludepkgs included) still applies.
"""

from __future__ import annotations

import libdnf5

from .base import Backend, Package, Source, State

# Source RPMs are never installed as ordinary packages, so they are noise here.
SRC_ARCHES = frozenset({"src", "nosrc"})

# Preferred when the same name exists for several architectures.
PRIMARY_ARCHES = frozenset({"x86_64", "noarch", "aarch64"})


class DnfBackend(Backend):
    id = "dnf"
    label = "DNF"
    icon = "fedora-logo-icon"
    needs_root = True

    def __init__(self) -> None:
        self._base: libdnf5.base.Base | None = None

    def _fresh_base(self, load_available: bool = True) -> libdnf5.base.Base:
        base = libdnf5.base.Base()
        base.load_config()
        base.setup()
        sack = base.get_repo_sack()
        sack.create_repos_from_system_configuration()
        # load_repos may only be called once per Base. With no argument it
        # pulls in the installed set and every enabled repo in one pass.
        if load_available:
            sack.load_repos()
        else:
            sack.load_repos(libdnf5.repo.Repo.Type_SYSTEM)
        self._base = base
        return base

    def load(self) -> list[Package]:
        base = self._fresh_base()

        # A name+arch can be installed several times over: kernels and akmod
        # built modules both do it. Keep the newest as the visible row and
        # remember the rest so the details pane can report them.
        installed: dict[tuple[str, str], object] = {}
        versions: dict[tuple[str, str], list[str]] = {}
        q = libdnf5.rpm.PackageQuery(base)
        q.filter_installed()
        for p in q:
            if p.get_arch() in SRC_ARCHES:
                continue
            kt = (p.get_name(), p.get_arch())
            versions.setdefault(kt, []).append(p.get_evr())
            current = installed.get(kt)
            if current is None or libdnf5.rpm.rpmvercmp(p.get_evr(), current.get_evr()) > 0:
                installed[kt] = p

        upgrades: dict[tuple[str, str], object] = {}
        try:
            qu = libdnf5.rpm.PackageQuery(base)
            qu.filter_upgrades()
            qu.filter_latest_evr(1)
            for p in qu:
                upgrades[(p.get_name(), p.get_arch())] = p
        except Exception:
            pass

        out: list[Package] = []
        seen: set[tuple[str, str]] = set()

        # Installed first, so their state wins over the available copy.
        for (name, arch), p in installed.items():
            up = upgrades.get((name, arch))
            state = State.UPGRADABLE if up else State.INSTALLED
            newest = up.get_evr() if up else p.get_evr()
            out.append(
                Package(
                    key=f"{name}.{arch}",
                    name=name,
                    version=newest,
                    installed_version=p.get_evr(),
                    summary=p.get_summary() or "",
                    source=self.id,
                    origin=(up.get_repo_id() if up else p.get_from_repo_id()) or "unknown",
                    state=state,
                    arch=arch,
                    size=p.get_install_size(),
                    license=p.get_license() or "",
                    url=p.get_url() or "",
                    description=p.get_description() or "",
                    extra=(
                        {"installed_versions": sorted(versions[(name, arch)])}
                        if len(versions.get((name, arch), [])) > 1
                        else {}
                    ),
                )
            )
            seen.add((name, arch))

        qa = libdnf5.rpm.PackageQuery(base)
        qa.filter_available()
        qa.filter_latest_evr(1)
        for p in qa:
            if p.get_arch() in SRC_ARCHES:
                continue
            kt = (p.get_name(), p.get_arch())
            if kt in seen:
                continue
            seen.add(kt)
            out.append(
                Package(
                    key=f"{kt[0]}.{kt[1]}",
                    name=kt[0],
                    version=p.get_evr(),
                    summary=p.get_summary() or "",
                    source=self.id,
                    origin=p.get_repo_id() or "unknown",
                    state=State.AVAILABLE,
                    arch=kt[1],
                    size=p.get_download_size(),
                    license=p.get_license() or "",
                    url=p.get_url() or "",
                    description=p.get_description() or "",
                )
            )
        return out

    def search_deep(self, query: str) -> list[Package]:
        """Find packages that the plain name search would miss.

        Matches a binary on disk, a provided capability such as a shared
        library, or wording buried in the description. All three are index
        lookups in libdnf5 and come back in well under a tenth of a second.
        """
        if len(query) < 3 or self._base is None:
            return []
        base = self._base
        # filter_provides and filter_file only accept a case sensitive GLOB.
        # Passing IGLOB trips a C++ assertion that aborts the process, so the
        # comparison type per filter below is deliberate, not incidental.
        cmp_glob = libdnf5.common.QueryCmp_GLOB
        cmp_iglob = libdnf5.common.QueryCmp_IGLOB
        glob = f"*{query}*"
        found: dict[str, tuple[object, str]] = {}

        def collect(build, reason: str) -> None:
            try:
                q = libdnf5.rpm.PackageQuery(base)
                build(q)
                q.filter_latest_evr(1)
                for pkg in q:
                    arch = pkg.get_arch()
                    if arch in SRC_ARCHES:
                        continue
                    # Deep hits are keyed by name alone: showing nss twice
                    # because of a 32 bit companion is noise, not detail.
                    name = pkg.get_name()
                    previous = found.get(name)
                    if previous is None or (
                        previous[0].get_arch() not in PRIMARY_ARCHES
                        and arch in PRIMARY_ARCHES
                    ):
                        found[name] = (pkg, reason)
            except Exception:
                pass

        collect(
            lambda q: q.filter_file([f"*/bin/{query}", f"*/sbin/{query}"], cmp_glob),
            "ships this command",
        )
        collect(lambda q: q.filter_provides([glob], cmp_glob), "provides this")
        collect(lambda q: q.filter_summary([glob], cmp_iglob), "summary mentions this")
        collect(lambda q: q.filter_description([glob], cmp_iglob), "described as this")

        out: list[Package] = []
        low = query.lower()
        for name, (pkg, reason) in found.items():
            if low in name.lower():
                continue  # the plain name filter already shows it
            arch = pkg.get_arch()
            out.append(
                Package(
                    key=f"{name}.{arch}",
                    name=name,
                    version=pkg.get_evr(),
                    summary=pkg.get_summary() or "",
                    source=self.id,
                    origin=pkg.get_repo_id() or "unknown",
                    state=State.INSTALLED if pkg.is_installed() else State.AVAILABLE,
                    arch=arch,
                    size=pkg.get_download_size(),
                    license=pkg.get_license() or "",
                    url=pkg.get_url() or "",
                    description=pkg.get_description() or "",
                    extra={"match_reason": reason},
                )
            )
        return out

    def sources(self) -> list[Source]:
        base = self._base or self._fresh_base(load_available=False)
        out: list[Source] = []
        try:
            rq = libdnf5.repo.RepoQuery(base)
            for r in rq:
                rid = r.get_id()
                if rid == "@System":
                    continue
                out.append(
                    Source(
                        key=rid,
                        name=r.get_name() or rid,
                        backend=self.id,
                        enabled=r.is_enabled(),
                        description=self._describe(rid),
                        url=(list(r.get_config().get_baseurl_option().get_value()) or [""])[0]
                        if hasattr(r.get_config(), "get_baseurl_option")
                        else "",
                        removable=rid.startswith("copr:"),
                    )
                )
        except Exception:
            pass
        return sorted(out, key=lambda s: (not s.enabled, s.key))

    @staticmethod
    def _describe(rid: str) -> str:
        low = rid.lower()
        if "rpmfusion" in low and "nonfree" in low:
            return "RPM Fusion Nonfree: Steam, NVIDIA, unrar, emulators"
        if "rpmfusion" in low:
            return "RPM Fusion Free: codecs, ffmpeg extras, VLC"
        if low.startswith("copr:"):
            return "COPR community build"
        if "openh264" in low:
            return "Cisco licensed H.264 decoder"
        if low in ("rawhide", "fedora", "updates", "updates-testing"):
            return "Official Fedora repository"
        if "debuginfo" in low:
            return "Debug symbols"
        if "source" in low:
            return "Source RPMs"
        return ""

    def set_source_enabled(self, key: str, enabled: bool) -> list[str]:
        return ["dnf", "config-manager", "setopt", f"{key}.enabled={1 if enabled else 0}"]

    def remove_source(self, key: str) -> list[str]:
        if key.startswith("copr:"):
            # copr:copr.fedorainfracloud.org:owner:project  ->  owner/project
            parts = key.split(":")
            if len(parts) >= 4:
                return ["dnf", "copr", "remove", "-y", f"{parts[2]}/{parts[3]}"]
        raise NotImplementedError(f"cannot remove repo {key}")

    @staticmethod
    def _spec(p: Package) -> str:
        return f"{p.name}.{p.arch}" if p.arch and p.arch != "noarch" else p.name

    def install_cmd(self, pkgs: list[Package]) -> list[str]:
        return ["dnf", "install", "-y", *[self._spec(p) for p in pkgs]]

    def remove_cmd(self, pkgs: list[Package]) -> list[str]:
        return ["dnf", "remove", "-y", *[self._spec(p) for p in pkgs]]

    def upgrade_cmd(self, pkgs: list[Package]) -> list[str]:
        if not pkgs:
            return ["dnf", "upgrade", "-y"]
        return ["dnf", "upgrade", "-y", *[self._spec(p) for p in pkgs]]

    def enable_copr(self, owner_project: str) -> list[str]:
        return ["dnf", "copr", "enable", "-y", owner_project]
