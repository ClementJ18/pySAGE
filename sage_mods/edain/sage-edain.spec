# -*- mode: python ; coding: utf-8 -*-
# Build both standalone Edain applications in one run:
#   pyinstaller sage_mods/edain/sage-edain.spec
# The result is two independent single-file binaries in dist/:
#   - sage_edain(.exe) - the `sage-edain` CLI, console-subsystem, Qt-free: every subcommand
#     (factions/explore/report/diff/schema/serve/replay-aggregate/install-skill), the Edain
#     map linter (`lint-maps`) included. The web-UI assets (ui/), faction icons (icons/) and
#     the bundled skill (skill_assets/) are packed in so `serve`, `replay-aggregate` and
#     `install-skill` work frozen.
#   - Edain Linter(.exe) - the tabbed window (SAGE Lint's ini checks + the Edain map checks)
#     a modder runs without Python, windowed-subsystem.
# Each has its own Analysis, so the CLI stays small while only the window bundles PyQt6;
# building therefore needs the [edain-ui] extra installed even if you only want the CLI.
# Build once per OS you support; PyInstaller binaries are not cross-platform.

import os

# This spec lives in sage_mods/edain/; anchor paths to the repo root so it builds from any cwd.
ROOT = os.path.dirname(os.path.dirname(SPECPATH))
EDAIN = os.path.join(ROOT, 'sage_mods', 'edain')

# ---------------------------------------------------------------- CLI: dist/sage_edain(.exe)

cli_a = Analysis(
    [os.path.join(EDAIN, '__main__.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # Bundled at their package-relative paths: the modules find them via `__file__` /
        # `importlib.resources`, which resolve into the extraction dir when frozen.
        (os.path.join(EDAIN, 'ui'), os.path.join('sage_mods', 'edain', 'ui')),
        (os.path.join(EDAIN, 'icons'), os.path.join('sage_mods', 'edain', 'icons')),
        (os.path.join(EDAIN, 'skill_assets'), os.path.join('sage_mods', 'edain', 'skill_assets')),
    ],
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
    name='sage_edain',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # a CLI driven over stdin/stdout; no console window pops up
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ------------------------------------------------------------ UI: dist/Edain Linter(.exe)
# The checks are ordinary imports from the runners, so PyInstaller's static analysis finds
# them - no hiddenimports needed.

ui_a = Analysis(
    [os.path.join(EDAIN, 'map_checks', 'ui', 'app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(EDAIN, 'map_checks', 'ui', 'icon.ico'), '.'),  # window/taskbar icon, found via sys._MEIPASS
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
    icon=[os.path.join(EDAIN, 'map_checks', 'ui', 'icon.ico')],
)
