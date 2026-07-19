# -*- mode: python ; coding: utf-8 -*-
# Build the Edain Linter window (SAGE Lint's ini checks + the Edain map checks in one tabbed
# window) into a single standalone .exe a modder can run without Python:
#   pyinstaller sage_mods/edain/sage-edain-lint.spec
# The result is dist/Edain Linter.exe. The checks are ordinary imports from the runners, so
# PyInstaller's static analysis finds them - no hiddenimports needed.

import os

# This spec lives in sage_mods/edain/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(os.path.dirname(SPECPATH))

a = Analysis(
    [os.path.join(ROOT, 'sage_mods', 'edain', 'map_checks', 'ui', 'app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'sage_mods', 'edain', 'map_checks', 'ui', 'icon.ico'), '.'),  # window/taskbar icon, found via sys._MEIPASS
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
    name='Edain Linter',
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
    icon=[os.path.join(ROOT, 'sage_mods', 'edain', 'map_checks', 'ui', 'icon.ico')],
)
