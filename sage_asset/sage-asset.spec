# -*- mode: python ; coding: utf-8 -*-
# Build both standalone sage_asset applications in one run:
#   pyinstaller sage_asset/sage-asset.spec
# The result is two independent single-file binaries in dist/:
#   - sage_asset(.exe) - the CLI, console-subsystem, Qt-free (parse/build/combine/check an
#     asset.dat). One binary serves every subcommand.
#   - SAGE Asset(.exe) - the PyQt6 window a teammate runs without Python, windowed-subsystem.
# Each has its own Analysis, so the CLI stays small while only the UI bundles PyQt6; building
# therefore needs the [asset-ui] extra installed even if you only want the CLI binary.
# Build once per OS you support; PyInstaller binaries are not cross-platform.

import os

# This spec lives in sage_asset/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(SPECPATH)

# ---------------------------------------------------------------- CLI: dist/sage_asset(.exe)

cli_a = Analysis(
    [os.path.join(ROOT, 'sage_asset', '__main__.py')],
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
cli_pyz = PYZ(cli_a.pure)

cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    cli_a.binaries,
    cli_a.datas,
    [],
    name='sage_asset',
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
)

# --------------------------------------------------------------- UI: dist/SAGE Asset(.exe)

ui_a = Analysis(
    [os.path.join(ROOT, 'sage_asset', 'ui', 'app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'sage_asset', 'ui', 'icon.ico'), '.'),  # window/taskbar icon, found via sys._MEIPASS
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
ui_pyz = PYZ(ui_a.pure)

ui_exe = EXE(
    ui_pyz,
    ui_a.scripts,
    ui_a.binaries,
    ui_a.datas,
    [],
    name='SAGE Asset',
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
    icon=[os.path.join(ROOT, 'sage_asset', 'ui', 'icon.ico')],
)
