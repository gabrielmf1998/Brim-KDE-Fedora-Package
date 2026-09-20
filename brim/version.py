"""Single source of truth for the version.

The RPM spec, the AppImage build and the update checker all read this.
"""

__version__ = "1.0.4"

APP_ID = "io.github.gabrielmf1998.brim"
APP_NAME = "Brim"

# Where releases are published. Either host can serve an update.
GITHUB_REPO = "gabrielmf1998/brim"
GITLAB_REPO = "gabriel17166/brim"

GITHUB_API = "https://api.github.com"
GITLAB_API = "https://gitlab.com/api/v4"


def version_tuple(text: str) -> tuple:
    """Turn 1.2.3 or v1.2.3 into something comparable, ignoring junk."""
    cleaned = (text or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    parts = []
    for chunk in cleaned.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])


def is_newer(candidate: str, current: str = __version__) -> bool:
    return version_tuple(candidate) > version_tuple(current)
