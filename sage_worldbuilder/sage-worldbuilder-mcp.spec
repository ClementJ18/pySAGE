# -*- mode: python ; coding: utf-8 -*-
# Build the map editor's MCP server into a single console exe:
#   pyinstaller sage_worldbuilder/sage-worldbuilder-mcp.spec
# The result is dist/sage-worldbuilder-mcp.exe, which `tools/build_mcpb.py` packs into the
# Claude Desktop extension (SageWorldBuilder.mcpb), so a mapper connects Claude to WorldbuilderV2
# without Python. Building needs the [worldbuilder-mcp] extra installed.
# It talks MCP over stdin/stdout, so it must stay a console build; the client starts it with no
# window. It needs none of the editor's Qt, OpenGL or image stack, so they are left out.

import os

from PyInstaller.utils.hooks import copy_metadata

ROOT = os.path.dirname(SPECPATH)
PACKAGE = os.path.join(ROOT, 'sage_worldbuilder')

# The shared pySAGE icon, carried by every console binary these specs build.
CLI_ICON = os.path.join(ROOT, 'tools', 'icon.ico')

# The MCP SDK reads its own version from its distribution's metadata, and the bug-report and
# version strings read pySAGE's; a bundle carries neither unless asked.
METADATA = []
for distribution in ('mcp', 'pysage-tools'):
    try:
        METADATA += copy_metadata(distribution)
    except Exception:  # not installed (a source-tree build)
        pass

a = Analysis(
    [os.path.join(PACKAGE, 'mcp_server', '__main__.py')],
    pathex=[ROOT],
    binaries=[],
    datas=METADATA,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt6', 'OpenGL', 'PIL', 'tkinter'],
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
    name='sage-worldbuilder-mcp',
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
    icon=[CLI_ICON],
)
