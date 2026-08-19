# -*- mode: python ; coding: utf-8 -*-
# Build the standalone Worldbuilder launcher:
#   pyinstaller sage_mods/edain/sage-edain-worldbuilder.spec
# The result is one single-file binary in dist/:
#   - Edain Worldbuilder(.exe) - drops into the Edain-Mod folder, one level above `_mod`, and
#     launches the editor against the mod's loose files. Console subsystem on purpose: it reports
#     which install it found, whether it had to patch the editor, and which subtree it is serving,
#     and those messages are the difference between "the mod did not load" and "the mod is fine".
# It needs no UI extra - only the pure-Python `sage_patch` and `sage_utils` packages come along.
# Build once per OS you support; PyInstaller binaries are not cross-platform, and this one is
# Windows-only anyway (registry lookup, junctions, an MFC editor).
#
# Run it from the mod folder with the subtree being edited, e.g.
#   "Edain Worldbuilder.exe" --subtree data/ini/object/civilian
# `--root` overrides the folder it thinks `_mod` is in, which is what makes it testable from
# anywhere; frozen, the default is the folder the exe itself sits in.

import os

# This spec lives in sage_mods/edain/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(os.path.dirname(SPECPATH))
ENTRY = os.path.join(ROOT, 'sage_mods', 'edain', 'worldbuilder.py')
# Worldbuilder's own icon, lifted from group 128 of the shipped Worldbuilder.exe (32/48px, 8 and
# 32 bpp) so the launcher looks like the thing it launches in the taskbar and on the desktop.
ICON = os.path.join(ROOT, 'sage_mods', 'edain', 'worldbuilder.ico')


a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    # sage_patch.registry pulls every patch in by name rather than by import site, so the ones
    # this launcher never mentions are invisible to the dependency scan.
    hiddenimports=['sage_patch.registry'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt6', 'matplotlib', 'numpy', 'pandas'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Edain Worldbuilder',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[ICON],
)
