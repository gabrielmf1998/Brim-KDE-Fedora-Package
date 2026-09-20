#!/usr/bin/env bash
# Launcher that works from a plain git checkout with no install step.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
exec python3 -m brim "$@"
