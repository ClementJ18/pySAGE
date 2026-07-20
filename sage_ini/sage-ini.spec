# -*- mode: python ; coding: utf-8 -*-
# Build the sage_ini CLI into a single standalone binary, so the query commands and - above
# all - the git merge driver need no Python and no checkout:
#   pyinstaller sage_ini/sage-ini.spec
# The result is dist/sage_ini(.exe). One binary serves every subcommand; `merge --install`
# run from the frozen binary registers the binary's own absolute path as the driver command
# (see `_driver_command` in __main__.py), so a plain exe download is enough for structure-
# aware ini merges. The bundled skill (skill_assets/) is packed in so `install-skill` works
# frozen. Build once per OS you support; PyInstaller binaries are not cross-platform.

import os

# This spec lives in sage_ini/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'sage_ini', '__main__.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # Bundled at its package-relative path: `importlib.resources` resolves it into the
        # extraction dir when frozen.
        (os.path.join(ROOT, 'sage_ini', 'skill_assets'), os.path.join('sage_ini', 'skill_assets')),
    ],
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
    name='sage_ini',
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
