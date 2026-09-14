# -*- mode: python ; coding: utf-8 -*-
# Build the map editor into a single windowed exe:
#   pyinstaller sage_worldbuilder/sage-worldbuilder.spec
# The result is dist/Worldbuilder.exe, which a mapper runs without Python. Building needs
# the [worldbuilder] extra installed (PyQt6, pyBIG, numpy, PyOpenGL, pillow), since the bundle
# is only as complete as the environment it is analysed in.
# Build once per OS you support; PyInstaller binaries are not cross-platform.

import os

# This spec lives in sage_worldbuilder/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(SPECPATH)
PACKAGE = os.path.join(ROOT, 'sage_worldbuilder')
SHARED = os.path.join(ROOT, 'sage_utils', 'assets')

# WorldBuilder's own application icon, the one `sage_worldbuilder.ui.window.ICON_FILE` names.
ICON = os.path.join(PACKAGE, 'assets', 'worldbuilder_icons', 'icons', '128.ico')

# The native RefPack compressor. reversebox resolves its DLL beside its own package folder
# (`reversebox/libs/`), so it has to land there in the bundle; without it map saving falls back
# to the pure-Python compressor, which takes tens of seconds on a large map.
try:
    import reversebox

    REFPACK = [(
        os.path.join(os.path.dirname(reversebox.__file__), 'libs', 'refpack.dll'),
        os.path.join('reversebox', 'libs'),
    )]
except ImportError:
    REFPACK = []

a = Analysis(
    [os.path.join(PACKAGE, 'ui', 'app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # Read through `importlib.resources.files("sage_worldbuilder")`, so they belong under
        # the package folder rather than the bundle root.
        (os.path.join(PACKAGE, 'keymap.json'), 'sage_worldbuilder'),
        (os.path.join(PACKAGE, 'script_templates.json'), 'sage_worldbuilder'),
        # WorldBuilder's extracted icons, cursors and toolbar bitmaps. `resource_path` looks
        # under the bundle root, which is where the whole tree goes.
        (os.path.join(PACKAGE, 'assets', 'worldbuilder_icons'), os.path.join('assets', 'worldbuilder_icons')),
        # The shared theme's glyphs (sage_utils.styles builds the stylesheet from these paths).
        (os.path.join(SHARED, 'check.svg'), 'assets'),  # checkbox check mark
        (os.path.join(SHARED, 'dock_close_dark.svg'), 'assets'),  # dock title bars
        (os.path.join(SHARED, 'dock_close_light.svg'), 'assets'),
        (os.path.join(SHARED, 'dock_float_dark.svg'), 'assets'),
        (os.path.join(SHARED, 'dock_float_light.svg'), 'assets'),
    ] + REFPACK,
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
    name='Worldbuilder',
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
    icon=[ICON],
)
