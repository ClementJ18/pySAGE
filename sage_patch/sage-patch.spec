# -*- mode: python ; coding: utf-8 -*-
# Build the sage_patch CLI into a single standalone binary, so patching / verifying a ROTWK
# `game.dat` needs no Python and no checkout:
#   pyinstaller sage_patch/sage-patch.spec
# The result is dist/sage_patch(.exe). One binary serves every subcommand, including the
# per-patch `apply`/`verify` sub-commands the registry grows and `sagepatch`, which writes the
# `.sagepatch` engine description sage_ini and sage_lint read back. Every patch is imported
# statically by sage_patch.registry, so PyInstaller's bytecode analysis finds them all; the
# `docs/` write-ups are reading material rather than runtime data and are left out.
# The entry point is cli.py rather than a __main__.py because that is where this package's
# console script points. Build once per OS you support; PyInstaller binaries are not
# cross-platform.

import os

# This spec lives in sage_patch/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'sage_patch', 'cli.py')],
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
    name='sage_patch',
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
