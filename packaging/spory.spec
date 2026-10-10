# PyInstaller spec: one folder holding spory.exe (no console) and spory-cli.exe.
# Build with: uv run --extra gui --group build python packaging/build.py
from pathlib import Path

root = Path(SPECPATH).parent
icon = str(root / "packaging" / "spory.ico")

a = Analysis(
    [str(root / "packaging" / "entry.py")],
    pathex=[str(root)],
    datas=[(str(root / "spory" / "gui" / "fonts"), "spory/gui/fonts")],
    hiddenimports=["spory.gui.app", "spory.cli", "PySide6.QtNetwork"],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)

gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="spory", console=False, icon=icon, upx=False)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="spory-cli", console=True, icon=icon, upx=False)

coll = COLLECT(gui, cli, a.binaries, a.datas, name="spory", upx=False)
