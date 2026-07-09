# -*- mode: python ; coding: utf-8 -*-
# Build the sage_lint CLI into a single standalone binary the Sublime plugin can ship, so the
# package needs no Python and no checkout:
#   pyinstaller sage_lint/sage-lint-cli.spec
# The result is dist/sage_lint(.exe). One binary serves every subcommand, `serve` included.
# Copy it into the package's bin/ folder (or bin/<platform>/) - see plugins/sublime/README.md.
# Build once per OS you support; PyInstaller binaries are not cross-platform.

import os

# This spec lives in sage_lint/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'sage_lint', '__main__.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[],
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
    name='sage_lint',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # a CLI the plugin drives over stdin/stdout; no console window pops up
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
