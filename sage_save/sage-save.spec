# -*- mode: python ; coding: utf-8 -*-
# Build the sage_save CLI into a single standalone binary, so inspecting / diagnosing / editing
# BFME save games needs no Python and no checkout:
#   pyinstaller sage_save/sage-save.spec
# The result is dist/sage_save(.exe). One binary serves every subcommand - the game-resolved
# ones (`check`, `diagnose --game`) included: the lazy `sage_ini.loader` import that resolves a
# save's references against a loaded game, and the `--game` mounting of a live install's .big
# archives (pyBIG), are found by PyInstaller's bytecode analysis and bundled.
# Build once per OS you support; PyInstaller binaries are not cross-platform.

import os

# This spec lives in sage_save/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'sage_save', '__main__.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name='sage_save',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # a CLI driven over stdin/stdout; no console window pops up
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
