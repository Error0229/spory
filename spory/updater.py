"""Find a newer release on GitHub, download its installer, verify it, run it."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from spory import __version__

REPO = "Error0229/spory"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALLER_PREFIX = "spory-setup-"
# Silent upgrade: closes spory, keeps settings, relaunches it afterwards.
SILENT_ARGS = "/SILENT /SP- /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS"


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    installer_url: str
    installer_name: str
    checksum_url: str | None
    page_url: str


def parse_version(text: str) -> tuple[int, ...]:
    parts = []
    for piece in text.strip().lstrip("vV").split("."):
        digits = ""
        for ch in piece:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
        if not piece.isdigit():
            break  # stop at suffixes like "1rc1"
    return tuple(parts)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def parse_release(data: dict) -> Release | None:
    """Pick the installer and its .sha256 from a GitHub release payload."""
    if data.get("draft") or data.get("prerelease"):
        return None
    assets = {a.get("name", ""): a.get("browser_download_url", "") for a in data.get("assets", [])}
    installer = next(
        (name for name in assets if name.startswith(INSTALLER_PREFIX) and name.endswith(".exe")), None
    )
    if not installer:
        return None
    return Release(
        version=str(data.get("tag_name", "")).lstrip("vV"),
        installer_url=assets[installer],
        installer_name=installer,
        checksum_url=assets.get(installer + ".sha256"),
        page_url=data.get("html_url", ""),
    )


def _get(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": f"spory/{__version__}", "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def latest_release(timeout: float = 10) -> Release | None:
    """The newest published release, or None if none is reachable."""
    try:
        return parse_release(json.loads(_get(LATEST_URL, timeout)))
    except (urllib.error.URLError, OSError, ValueError):
        return None  # offline, rate-limited, private repo or no releases yet


def check() -> Release | None:
    release = latest_release()
    return release if release and is_newer(release.version) else None


def verify_checksum(path: Path, checksum_text: str) -> None:
    expected = checksum_text.strip().split()[0].lower() if checksum_text.strip() else ""
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if len(expected) != 64 or actual != expected:
        raise UpdateError("downloaded installer failed its checksum; not running it")


def download(release: Release, timeout: float = 120) -> Path:
    """Download the installer to a temp folder and verify its SHA-256."""
    if not release.checksum_url:
        raise UpdateError("release has no checksum; not running an unverified installer")
    folder = Path(tempfile.mkdtemp(prefix="spory-update-"))
    target = folder / release.installer_name
    try:
        target.write_bytes(_get(release.installer_url, timeout))
        verify_checksum(target, _get(release.checksum_url, timeout).decode("ascii", "replace"))
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(f"download failed: {exc}") from exc
    return target


def launch_installer(path: Path) -> None:
    """Start the installer; Windows shows a UAC prompt because it needs admin rights."""
    os.startfile(str(path), "open", SILENT_ARGS)
