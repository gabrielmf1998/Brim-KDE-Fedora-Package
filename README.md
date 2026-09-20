# Brim

One package manager for every source Fedora can pull from.

Brim searches DNF, Flatpak, COPR and AppImage in a single box, shows you what
is installed and what changes, and applies it. Built with PySide6 and libdnf5,
themed by Breeze, and it updates itself from git.

## Why

Fedora spreads its software across four worlds that do not talk to each other.
Discover hides the low level detail. dnfdragora only knows RPM. Nothing reaches
into COPR before you have already enabled a project, and nothing at all handles
AppImages. Brim covers all four in one window.

| Source | What Brim does |
| --- | --- |
| DNF | Reads every enabled repo through libdnf5, no PackageKit in the way |
| Flatpak | All remotes, user and system, with real descriptions and sizes |
| COPR | Searches every public project, not just the ones already enabled |
| AppImage | Searches the AppImageHub catalog, downloads and wires up a launcher |

## Speed

libdnf5 is read directly instead of through a daemon.

```
76000 packages indexed in 0.65s
```

## Install

No root needed. Nothing lands outside your home directory.

```sh
git clone <your remote> ~/Documents/brim
cd ~/Documents/brim
./install.sh
brim
```

`uninstall.sh` reverses it.

## What it does

**Browse.** One search box across every source. Filter by source with the chips
at the top, filter by state with All, Installed, Not installed and Updates.
Local results appear as you type and network catalogs fill in behind them.

**See the change.** An upgradable package shows `8.0.3 > 8.0.4` right in the
list, so you always know what a transaction will actually do.

**Sources.** Enable or disable any dnf repo, add a COPR, add a Flatpak remote,
or install RPM Fusion in one click. Disabled repos are hidden until you ask.

**Transactions.** Everything touching RPM goes through `pkexec`, so you get the
normal polkit prompt and the real dnf output streamed live. Your `dnf.conf`
stays in charge: `excludepkgs` and every other rule still applies.

**Tray.** Sits in the system tray with a badge for pending updates, checks on an
interval you pick, and can start with your session.

**Self update.** Brim tracks its own git checkout. Push a new commit, hit
Check for updates in Settings, and it fast forwards itself.

## Requirements

Already present on a normal Fedora KDE install:

- `python3-pyside6`
- `python3-libdnf5`
- `flatpak` (optional, the chip greys out without it)

## Layout

```
brim/
  backends/   one module per source, all speaking the same Package model
  core/       catalog aggregation, transactions, config, self update
  ui/         Qt widgets, Breeze aware theming
```

Adding a source means writing one `Backend` subclass in `backends/`. Nothing
else changes.

## Notes

- AppImage entries in the upstream catalog do not all carry a download link.
  Brim marks those as having no automatic source rather than guessing.
- Automatic update mode only runs unattended for Flatpak and AppImage, since
  anything RPM needs a polkit prompt by design.
- Packages installed with several versions at once, kernels and akmod built
  modules, show the newest in the list and report the full set in the details.
