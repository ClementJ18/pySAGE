# -*- mode: python ; coding: utf-8 -*-
# Build the SAGE Lint window into a single standalone .exe a teammate can run without Python:
#   pyinstaller sage_lint/sage-lint-ui.spec
# The result is dist/SAGE Lint.exe. The model registry is populated by ordinary imports from
# sage_lint.cli, so PyInstaller's static analysis finds it - no hiddenimports needed.

import os

# This spec lives in sage_lint/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'sage_lint', 'plugins', 'ui', 'app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'sage_lint', 'plugins', 'ui', 'icon.ico'), '.'),  # window/taskbar icon, found via sys._MEIPASS
    ],
    hiddenimports=['tomllib'],  # .sagelint is TOML; ensure the stdlib parser is bundled
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
    name='SAGE Lint',
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
    icon=[os.path.join(ROOT, 'sage_lint', 'plugins', 'ui', 'icon.ico')],
)
