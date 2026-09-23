"""Tests for building `sage_accel.dll`.

The module is 32-bit and this suite's Python usually is not, so the built DLL is never loaded here.
It is checked as a file instead: the machine type the game can load, the one export the
`accel-module` cave resolves, undecorated, and imports limited to what every Windows 10+ install
carries. What the export *does* is exercised through the cave in
`tests/sage_patch/test_accel_module.py` and, beyond that, only in a running game.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_accel.__main__ import main
from sage_accel.build import (
    DLL_NAME,
    EXPORT_NAME,
    SOURCES,
    TARGET,
    build,
    compile_command,
    have_toolchain,
    install,
)

_I386 = 0x14C
#: What the module may import. `api-ms-win-crt-*` is the Universal CRT, part of Windows since 10;
#: `winmm.dll` is already one of game.dat's own imports.
_ALLOWED_IMPORT_PREFIXES = ("kernel32.dll", "user32.dll", "winmm.dll", "api-ms-win-crt-")


class TestTheGeneratedHeader:
    def test_is_current(self) -> None:
        """`src/vtables.h` is what `python -m sage_accel.gen` writes today."""
        if not have_toolchain():
            pytest.skip("needs the accel extra (ziglang)")
        from sage_accel.gen import HEADER, render  # noqa: PLC0415

        assert HEADER.read_text(encoding="utf-8") == render(), "run python -m sage_accel.gen"


class TestTheCommand:
    def test_targets_32_bit_windows(self) -> None:
        cmd = compile_command(Path("out.dll"))
        assert cmd[cmd.index("-target") + 1] == TARGET == "x86-windows-gnu"
        assert "-shared" in cmd

    def test_warnings_are_errors(self) -> None:
        cmd = compile_command(Path("out.dll"))
        assert {"-Wall", "-Wextra", "-Werror"} <= set(cmd)

    def test_compiles_every_source(self) -> None:
        cmd = compile_command(Path("out.dll"))
        for source in SOURCES:
            assert source.is_file()
            assert str(source) in cmd


class TestInstall:
    def test_copies_beside_game_dat(self, tmp_path: Path) -> None:
        game = tmp_path / "game"
        game.mkdir()
        (game / "game.dat").write_bytes(b"MZ")
        dll = tmp_path / DLL_NAME
        dll.write_bytes(b"built")
        assert install(dll, game) == game / DLL_NAME
        assert (game / DLL_NAME).read_bytes() == b"built"

    def test_refuses_a_directory_without_game_dat(self, tmp_path: Path) -> None:
        dll = tmp_path / DLL_NAME
        dll.write_bytes(b"built")
        with pytest.raises(FileNotFoundError, match=r"game\.dat"):
            install(dll, tmp_path)

    def test_cli_reports_a_missing_game_dat(self, tmp_path: Path, capsys) -> None:
        dll = tmp_path / DLL_NAME
        dll.write_bytes(b"built")
        assert main(["install", str(tmp_path), "--dll", str(dll)]) == 1
        assert "game.dat" in capsys.readouterr().err


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not have_toolchain():
        pytest.skip("needs the accel extra (ziglang)")
    pefile = pytest.importorskip("pefile", reason="needs the patch extra (pefile)")
    del pefile
    return build(tmp_path_factory.mktemp("accel"))


class TestTheBuiltModule:
    def test_is_a_32_bit_dll(self, built: Path) -> None:
        import pefile  # noqa: PLC0415

        pe = pefile.PE(str(built))
        assert pe.FILE_HEADER.Machine == _I386
        assert pe.is_dll()

    def test_exports_the_arming_entry_undecorated(self, built: Path) -> None:
        import pefile  # noqa: PLC0415

        pe = pefile.PE(str(built))
        names = {symbol.name for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols}
        assert names == {EXPORT_NAME.encode()}

    def test_imports_only_what_windows_carries(self, built: Path) -> None:
        import pefile  # noqa: PLC0415

        pe = pefile.PE(str(built))
        dlls = {entry.dll.decode().lower() for entry in pe.DIRECTORY_ENTRY_IMPORT}
        assert all(dll.startswith(_ALLOWED_IMPORT_PREFIXES) for dll in dlls), dlls
        assert "d3d9.dll" not in dlls, "d3d9 must come from the engine's own resolve, not an import"
