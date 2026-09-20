"""Breeze aware styling.

Every colour is derived from the active palette, so Breeze light, Breeze dark
and any other Qt theme all render correctly with no hardcoded values.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication

SOURCE_ICONS = {
    "dnf": "package-x-generic",
    "flatpak": "flatpak",
    "copr": "applications-development",
    "appimage": "application-x-executable",
}

SOURCE_LABELS = {
    "dnf": "DNF",
    "flatpak": "Flatpak",
    "copr": "COPR",
    "appimage": "AppImage",
}

# Hue per source, blended into the palette so it works in light and dark.
SOURCE_HUES = {
    "dnf": 210,
    "flatpak": 145,
    "copr": 280,
    "appimage": 30,
}


def is_dark() -> bool:
    palette = QApplication.palette()
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def source_color(source: str) -> QColor:
    hue = SOURCE_HUES.get(source, 0)
    if is_dark():
        return QColor.fromHsl(hue, 120, 175)
    return QColor.fromHsl(hue, 150, 95)


def source_tint(source: str) -> QColor:
    hue = SOURCE_HUES.get(source, 0)
    if is_dark():
        return QColor.fromHsl(hue, 110, 58)
    return QColor.fromHsl(hue, 160, 232)


def state_color(state: str) -> QColor:
    palette = QApplication.palette()
    if state == "upgradable":
        return QColor.fromHsl(35, 170, 130 if is_dark() else 90)
    if state == "installed":
        return QColor.fromHsl(140, 130, 150 if is_dark() else 85)
    return palette.color(QPalette.ColorRole.PlaceholderText)


def icon(name: str, fallback: str = "package-x-generic") -> QIcon:
    result = QIcon.fromTheme(name)
    if result.isNull():
        result = QIcon.fromTheme(fallback)
    return result


def source_icon(source: str) -> QIcon:
    return icon(SOURCE_ICONS.get(source, "package-x-generic"))


def human_size(num: int) -> str:
    if not num:
        return ""
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""
