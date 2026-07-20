# -*- mode: python ; coding: utf-8 -*-
# Build the sage_map CLI into a single standalone binary, so parsing / inspecting / diffing
# .map files needs no Python and no checkout:
#   pyinstaller sage_map/sage-map.spec
# The result is dist/sage_map(.exe). One binary serves every subcommand (info / json / diff).
# The refpack (de)compression of BFME's compressed maps runs through `reversebox`, whose lazy
# import inside sage_map.map is found by PyInstaller's bytecode analysis and bundled.
# The engine-generic package: mod-specific map checks live in sage_edain, game-aware linting in
# sage_lint. Build once per OS you support; PyInstaller binaries are not cross-platform.

import os

# This spec lives in sage_map/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'sage_map', '__main__.py')],
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
    name='sage_map',
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
