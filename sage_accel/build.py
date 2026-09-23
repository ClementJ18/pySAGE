"""Build `sage_accel.dll` with the `ziglang` package's clang, and copy it beside a `game.dat`.

The toolchain is `ziglang` from PyPI (the `accel` extra) so that building needs nothing outside the
venv: it carries mingw-w64's `d3d9.h` and `d3dx9*.h` and targets 32-bit Windows from any host.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

__all__ = [
    "DLL_NAME",
    "EXPORT_NAME",
    "SOURCES",
    "TARGET",
    "build",
    "compile_command",
    "have_toolchain",
    "install",
]

#: The file the `accel-module` patch's cave asks `LoadLibraryA` for, from the game's directory.
DLL_NAME = "sage_accel.dll"
#: The one export the cave resolves; see the contract in `src/sage_accel.c`.
EXPORT_NAME = "sage_accel_arm"
#: `game.dat` is a 32-bit image, so the module is too.
TARGET = "x86-windows-gnu"

_SRC = Path(__file__).resolve().parent / "src"
SOURCES = (_SRC / "sage_accel.c", _SRC / "census.c")
_LIBS = ("-luser32", "-lwinmm")


def have_toolchain() -> bool:
    return importlib.util.find_spec("ziglang") is not None


def compile_command(out: Path) -> list[str]:
    """The compiler invocation, as a list, so a caller can print or log exactly what ran."""
    return [
        sys.executable,
        "-m",
        "ziglang",
        "cc",
        "-target",
        TARGET,
        "-shared",
        "-O2",
        "-s",  # no symbols: the shipped DLL carries no debug info
        "-Wall",
        "-Wextra",
        "-Werror",
        "-o",
        str(out),
        *(str(source) for source in SOURCES),
        *_LIBS,
    ]


def build(out_dir: Path) -> Path:
    """Compile into `out_dir` and return the DLL's path. Raises if the toolchain is missing or the
    compiler fails; the compiler's own output reaches stderr unchanged."""
    if not have_toolchain():
        raise RuntimeError("ziglang is not installed - pip install 'pysage-tools[accel]'")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / DLL_NAME
    subprocess.run(compile_command(out), check=True)
    return out


def install(dll: Path, game_dir: Path) -> Path:
    """Copy a built module next to `game.dat`, where the cave's `LoadLibraryA` looks first."""
    if not (game_dir / "game.dat").is_file():
        raise FileNotFoundError(f"{game_dir} holds no game.dat")
    return Path(shutil.copy2(dll, game_dir / DLL_NAME))
