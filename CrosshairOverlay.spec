# -*- mode: python ; coding: utf-8 -*-
import os
import shutil


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['crosshair_model', 'presets', 'storage', 'hotkeys', 'pixel_editor', 'ui_widgets', 'control', 'overlay'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CrosshairOverlay',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_uiaccess=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='CrosshairOverlay',
)

# Папку crosshairs программа ищет рядом с exe, а не в _internal
_src = os.path.join(SPECPATH, 'crosshairs')
if os.path.isdir(_src):
    shutil.copytree(_src, os.path.join(DISTPATH, 'CrosshairOverlay', 'crosshairs'),
                    dirs_exist_ok=True)
