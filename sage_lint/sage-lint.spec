# -*- mode: python ; coding: utf-8 -*-
# Build both standalone sage_lint applications in one run:
#   pyinstaller sage_lint/sage-lint.spec
# The result is two independent single-file binaries in dist/:
#   - sage_lint(.exe) - the CLI, console-subsystem, Qt-free (the Sublime plugin ships it, so
#     the package needs no Python and no checkout; copy it into the package's bin/ folder or
#     bin/<platform>/ - see plugins/sublime/README.md). One binary serves every subcommand,
#     `serve` included.
#   - SAGE Lint(.exe) - the PyQt6 window a teammate runs without Python, windowed-subsystem.
# Each has its own Analysis, so the CLI stays small while only the UI bundles PyQt6; building
# therefore needs the [lint-ui] extra installed even if you only want the CLI binary.
# Build once per OS you support; PyInstaller binaries are not cross-platform.

import os

# This spec lives in sage_lint/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(SPECPATH)

# ----------------------------------------------------------------- CLI: dist/sage_lint(.exe)

cli_a = Analysis(
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
cli_pyz = PYZ(cli_a.pure)

cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    cli_a.binaries,
    cli_a.datas,
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

# ----------------------------------------------------------------- UI: dist/SAGE Lint(.exe)
# The model registry is populated by ordinary imports from sage_lint.cli, so PyInstaller's
# static analysis finds it - no hiddenimports needed beyond tomllib.

ui_a = Analysis(
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
ui_pyz = PYZ(ui_a.pure)

ui_exe = EXE(
    ui_pyz,
    ui_a.scripts,
    ui_a.binaries,
    ui_a.datas,
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
