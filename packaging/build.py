"""Build the Windows installer.

    uv run --extra gui --group build python packaging/build.py

Produces dist/spory/ (the app), dist/spory-setup-<version>.exe and its .sha256,
which the in-app updater requires before running a downloaded installer.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
sys.path.insert(0, str(ROOT))

from spory import __version__  # noqa: E402


def find_iscc() -> str:
    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    sys.exit("Inno Setup not found: scoop install extras/inno-setup")


def main() -> None:
    if not (PACKAGING / "spory.ico").exists():
        subprocess.run([sys.executable, str(PACKAGING / "make_icon.py")], check=True)
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--distpath", str(DIST), "--workpath", str(ROOT / "build"),
            str(PACKAGING / "spory.spec"),
        ],
        check=True,
    )
    subprocess.run([find_iscc(), f"/DAppVersion={__version__}", str(PACKAGING / "installer.iss")], check=True)

    setup = DIST / f"spory-setup-{__version__}.exe"
    digest = hashlib.sha256(setup.read_bytes()).hexdigest()
    (DIST / f"{setup.name}.sha256").write_text(f"{digest}  {setup.name}\n", encoding="ascii", newline="\n")
    print(f"built {setup} ({setup.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
