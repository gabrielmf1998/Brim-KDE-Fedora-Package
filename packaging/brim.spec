%global appname brim
%global appdir  %{_prefix}/lib/%{appname}

Name:           brim
Version:        1.0.4
Release:        1%{?dist}
Summary:        Unified package manager for Fedora: DNF, Flatpak, COPR and AppImage in one window

License:        GPL-3.0-or-later
URL:            https://github.com/gabrielmf1998/brim
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  desktop-file-utils

Requires:       python3 >= 3.9
Requires:       python3-pyside6
Requires:       python3-libdnf5 >= 5.4.0
Requires:       hicolor-icon-theme

Recommends:     flatpak
Recommends:     polkit
Recommends:     breeze-icon-theme

%description
Brim searches DNF, Flatpak, COPR and AppImage from a single box, shows what is
installed and exactly what a transaction will change, and applies it.

It reads libdnf5 directly rather than going through a daemon, so a full index
of every enabled repository is ready in well under a second. COPR is searched
across every public project, not only the ones already enabled, and AppImages
are resolved from the community catalog.

Transactions touching RPM run through pkexec, so the usual authentication
prompt appears and every rule in dnf.conf, excludepkgs included, still applies.

Brim is for Fedora and other DNF5 based systems only.

%prep
%autosetup -n %{name}-%{version}

%build
# Pure Python, nothing to compile.

%install
install -d %{buildroot}%{appdir}
cp -a brim %{buildroot}%{appdir}/brim

install -d %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/%{appname} <<'LAUNCH'
#!/usr/bin/sh
exec /usr/bin/python3 -P -c 'import sys; sys.path.insert(0, "/usr/lib/brim"); from brim.app import main; sys.exit(main())' "$@"
LAUNCH
chmod 0755 %{buildroot}%{_bindir}/%{appname}

install -d %{buildroot}%{_datadir}/applications
sed 's|BRIM_EXEC|%{_bindir}/%{appname}|' data/brim.desktop \
    > %{buildroot}%{_datadir}/applications/%{appname}.desktop

install -d %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
install -m 0644 data/icons/brim.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{appname}.svg

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/%{appname}.desktop
/usr/bin/python3 -m compileall -q %{buildroot}%{appdir}/brim

%files
%license LICENSE
%doc README.md
%{appdir}
%{_bindir}/%{appname}
%{_datadir}/applications/%{appname}.desktop
%{_datadir}/icons/hicolor/scalable/apps/%{appname}.svg

%changelog
* Sun Sep 20 2026 kxinha <gabriel17166@gmail.com> - 1.0.4-1
- Show a progress bar and a per source report while searching, so it is
  obvious which sources were reached and when the search finished
- Source chips now count what is on screen rather than the catalogue, and
  say "off" instead of zero when a source is not being searched
- Status filters carry their own counts
- Table columns are resizable, movable and can be hidden from a right click
  on the header, and the layout is remembered
- Switching a source back on reloads it instead of sitting at zero
- Sources page lists every source, groups COPR projects under COPR, and
  explains that searching COPR needs no setup

* Sat Sep 19 2026 kxinha <gabriel17166@gmail.com> - 1.0.3-1
- Show the resolved dependency list, sizes and reasons before a transaction
- Package detail now carries build date, install date, packager, source RPM,
  requirements and recent changelog
- Check hand installed RPMs against their upstream releases, verifying each
  one locally before installing and never touching kernel modules or
  anything held back by excludepkgs
- Fix two crashes on exit caused by workers outliving the application

* Sat Sep 19 2026 kxinha <gabriel17166@gmail.com> - 1.0.2-1
- AppImage self update lands under the new version's file name and follows
  the launcher symlink and desktop entry over to it

* Sat Sep 19 2026 kxinha <gabriel17166@gmail.com> - 1.0.1-1
- Installer escalates with pkexec when run without a terminal, which is how
  the documented one line install actually runs

* Sat Sep 19 2026 kxinha <gabriel17166@gmail.com> - 1.0.0-1
- First release: DNF, Flatpak, COPR and AppImage in one window
- Universal search across names, shipped commands, provides and descriptions
- Self update from the project release page, manual or scheduled
