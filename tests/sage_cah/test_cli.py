"""CLI-level tests for `sage-cah`, driven through `main([...])` (style: tests/sage_asset/
test_cli.py) rather than via subprocess: `info`'s summary, `check`'s round-trip/checksum
verdicts over a single file and a directory, and the `fix` -> `check` repair loop."""

import json

import pytest

from sage_cah.__main__ import main
from sage_cah.cah import (
    CahBling,
    CahPower,
    CustomHero,
    compute_checksum,
    parse_cah_from_path,
    write_cah_to_path,
)


def _build_hero(name: str = "Test Hero") -> CustomHero:
    real_powers = [
        CahPower(command_button=f"Command_Power{i}", exp_level=i, button_index=(i % 5) + 1)
        for i in range(10)
    ]
    empty_powers = [CahPower(command_button="", exp_level=-1, button_index=0) for _ in range(5)]
    blings = [CahBling(group_name=f"CreateAHero_Group{i}", bling_index=i) for i in range(12)]

    return CustomHero(
        header_unk1=1,
        header_unk2=0,
        version=8,
        obj_id=19,
        name=name,
        class_index=4,
        sub_class_index=1,
        reserved1=0,
        reserved2=0,
        color1=0x11223344,
        color2=0x55667788,
        color3=0x99AABBCC,
        powers=real_powers + empty_powers,
        blings=blings,
        guid="47C6206B5C124324A54A2DA3",
        is_system_hero=1,
        checksum=0,
    )


def _color1_offset(name: str) -> int:
    """Byte offset of `color1` inside a written .cah, from the fixed-size fields ahead of it:
    magic(8) + header_unk1/2(4+4) + version(1) + obj_id(4) + name_len(1) + name (2 bytes/unit)
    + class_index/sub_class_index/reserved1/reserved2 (4 each)."""
    return 8 + 4 + 4 + 1 + 4 + 1 + 2 * len(name) + 4 + 4 + 4 + 4


def _write_valid_hero(path, name: str = "Test Hero"):
    hero = _build_hero(name=name)
    write_cah_to_path(hero, path, refresh_checksum=True)
    return hero


class TestInfo:
    def test_reports_mapped_class_name_and_checksum_ok(self, tmp_path, capsys):
        cah_path = tmp_path / "hero.cah"
        _write_valid_hero(cah_path)

        assert main(["info", str(cah_path)]) == 0

        out = capsys.readouterr().out
        assert "Servant of Sauron" in out
        assert "Uruk" in out
        assert "checksum OK" in out
        assert "Test Hero" in out
        assert "level 1: Command_Power0" in out


class TestCheck:
    def test_directory_of_valid_files_exits_zero(self, tmp_path, capsys):
        _write_valid_hero(tmp_path / "a.cah", name="A")
        _write_valid_hero(tmp_path / "b.cah", name="B")

        assert main(["check", str(tmp_path)]) == 0

        out = capsys.readouterr().out
        assert "2 file(s), 0 failure(s)" in out

    def test_checksum_corruption_exits_one_and_is_reported(self, tmp_path, capsys):
        cah_path = tmp_path / "hero.cah"
        hero = _write_valid_hero(cah_path)

        data = bytearray(cah_path.read_bytes())
        offset = _color1_offset(hero.name)
        data[offset] ^= 0xFF  # flip a byte inside the checksum-covered color1 field
        cah_path.write_bytes(bytes(data))

        assert main(["check", str(cah_path)]) == 1

        out = capsys.readouterr().out
        assert "checksum mismatch" in out
        assert "1 file(s), 1 failure(s)" in out

    def test_fix_repairs_a_corrupted_checksum_so_check_passes_again(self, tmp_path, capsys):
        cah_path = tmp_path / "hero.cah"
        hero = _write_valid_hero(cah_path)

        data = bytearray(cah_path.read_bytes())
        offset = _color1_offset(hero.name)
        data[offset] ^= 0xFF
        cah_path.write_bytes(bytes(data))
        assert main(["check", str(cah_path)]) == 1
        capsys.readouterr()

        fixed_path = tmp_path / "hero_fixed.cah"
        assert main(["fix", str(cah_path), "-o", str(fixed_path)]) == 0
        fix_out = capsys.readouterr().out
        assert "checksum" in fix_out
        assert "wrote" in fix_out

        assert main(["check", str(fixed_path)]) == 0
        check_out = capsys.readouterr().out
        assert "1 file(s), 0 failure(s)" in check_out

        fixed_hero = parse_cah_from_path(fixed_path)
        assert fixed_hero.checksum == compute_checksum(fixed_hero)
        # the corrupted color1 survives - fix refreshes the checksum, it doesn't undo edits.
        assert fixed_hero.color1 == hero.color1 ^ 0xFF


class TestJson:
    def test_out_writes_a_loadable_json_document(self, tmp_path):
        cah_path = tmp_path / "hero.cah"
        hero = _write_valid_hero(cah_path)
        out_path = tmp_path / "hero.json"

        assert main(["json", str(cah_path), "--out", str(out_path)]) == 0

        document = json.loads(out_path.read_text(encoding="utf-8"))
        assert document["name"] == hero.name
        assert document["obj_id"] == hero.obj_id
        assert len(document["powers"]) == 15
        assert len(document["blings"]) == 12
        assert document["guid"] == hero.guid

    @pytest.mark.parametrize("compact", [False, True])
    def test_stdout_output_is_valid_json(self, tmp_path, capsys, compact):
        cah_path = tmp_path / "hero.cah"
        _write_valid_hero(cah_path)

        args = ["json", str(cah_path)] + (["--compact"] if compact else [])
        assert main(args) == 0

        out = capsys.readouterr().out
        document = json.loads(out)
        assert document["is_system_hero"] == 1
