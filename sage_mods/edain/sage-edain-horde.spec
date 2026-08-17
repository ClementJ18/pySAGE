# -*- mode: python ; coding: utf-8 -*-
# Build the standalone Edain Horde Maker window:
#   pyinstaller sage_mods/edain/sage-edain-horde.spec
# The result is one single-file binary in dist/:
#   - Edain Horde Maker(.exe) - the window that draws a horde's formation on a grid and writes
#     the HordeContain block for it, windowed-subsystem, for whoever lays out the hordes to run
#     without Python.
# It bundles PyQt6, so building needs the [edain-ui] extra installed. Kept apart from
# sage-edain.spec (the CLI + the Edain Linter) so the horde window can be rebuilt and handed
# over on its own. Build once per OS you support; PyInstaller binaries are not cross-platform.

import os

# This spec lives in sage_mods/edain/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(os.path.dirname(SPECPATH))
UI = os.path.join(ROOT, 'sage_mods', 'edain', 'horde_maker', 'ui')


a = Analysis(
    [os.path.join(UI, 'app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(UI, 'icon.ico'), '.'),  # window/taskbar icon, found via sys._MEIPASS
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
    name='Edain Horde Maker',
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
    icon=[os.path.join(UI, 'icon.ico')],
)
