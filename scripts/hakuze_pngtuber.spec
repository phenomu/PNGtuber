# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Hakuze PNGtuber (one-folder Windows build).
# Build:  .wvenv\Scripts\python.exe -m PyInstaller scripts\hakuze_pngtuber.spec
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    (os.path.join(ROOT, "assets"), "assets"),
    (os.path.join(ROOT, "config"), "config"),
]

a = Analysis(
    [os.path.join(ROOT, "run_app.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HakuzePNGtuber",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "assets", "icons", "app.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="HakuzePNGtuber",
)
