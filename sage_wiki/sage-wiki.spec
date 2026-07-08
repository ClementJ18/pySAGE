# -*- mode: python ; coding: utf-8 -*-
# Build the Edain Wiki Assistant into a single windowed exe:
#     pyinstaller sage_wiki/sage-wiki.spec
# The result is dist/Edain Wiki Assistant.exe.

import os

# This spec lives in sage_wiki/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'sage_wiki', 'app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'sage_wiki', 'icon.ico'), '.'),  # bundled beside the code, found via sys._MEIPASS
        (os.path.join(ROOT, 'sage_utils', 'assets', 'background.png'), 'assets'),  # parchment behind portraits
    ],
    # keyring loads its backend dynamically via entry points; name the Windows
    # Credential Manager backend (and its win32ctypes dependency) explicitly so the
    # frozen exe can still store the remembered password.
    hiddenimports=[
        'mwclient',
        'mwparserfromhell',
        'keyring.backends.Windows',
        'win32ctypes.core',
    ],
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
    name='Edain Wiki Assistant',
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
    icon=[os.path.join(ROOT, 'sage_wiki', 'icon.ico')],
)
