# -*- mode: python ; coding: utf-8 -*-
# Build the object browser into a single windowed exe:
#   pyinstaller sage_ui/sage-ui.spec
# The result is dist/BfMe Searcher.exe.

import os

# This spec lives in sage_ui/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'sage_ui', 'app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'sage_ui', 'icon.ico'), '.'),
        (os.path.join(ROOT, 'sage_utils', 'assets', 'background.png'), 'assets'),  # parchment behind portraits
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
    name='BfMe Searcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(ROOT, 'sage_ui', 'icon.ico')],
)
