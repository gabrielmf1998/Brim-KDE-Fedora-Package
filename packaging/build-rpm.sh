#!/usr/bin/env bash
# Builds brim-<version>-<release>.noarch.rpm into dist/
set -euo pipefail

SRC="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/brim/version.py")"
NAME="brim-$VERSION"
TOP="$(mktemp -d)"
trap 'rm -rf "$TOP"' EXIT

echo "Building $NAME"

mkdir -p "$TOP"/{SOURCES,SPECS,BUILD,RPMS,SRPMS,BUILDROOT} "$TOP/$NAME"

# Only what the package ships. No .git, no caches, no build output.
tar --exclude-vcs --exclude='__pycache__' --exclude='dist' --exclude='*.pyc' \
    -C "$SRC" -cf - brim data README.md LICENSE \
  | tar -C "$TOP/$NAME" -xf -

tar -C "$TOP" -czf "$TOP/SOURCES/$NAME.tar.gz" "$NAME"
sed "s/^Version:.*/Version:        $VERSION/" "$SRC/packaging/brim.spec" \
    > "$TOP/SPECS/brim.spec"

rpmbuild --define "_topdir $TOP" -bb "$TOP/SPECS/brim.spec"

mkdir -p "$SRC/dist"
find "$TOP/RPMS" -name '*.rpm' -exec cp -v {} "$SRC/dist/" \;

echo
echo "Done:"
ls -la "$SRC/dist/"*.rpm
