"""Safe standalone builds use verified inputs and never publish partial or sidecar outputs."""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_patch.patches import combo_horde_recruitment as payload
from sage_patch.patches import horde_herobar as herobar
from sage_patch.patches.experimental import hero_horde_death as death
from sage_patch.utils import file_offset, find_section
from tools import build_hero_horde_patch as builder

from .synthetic import _sparse_image


@pytest.fixture
def verified_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "game.dat.backup"
    source.write_bytes(
        _sparse_image(
            {
                **death.ANCHORS,
                **herobar.ANCHORS,
                **payload.ANCHORS,
                death.HOOK: death.ORIGINAL,
                herobar.HOOK: herobar.ORIGINAL,
                payload.HORDE_CONTAIN_PRODUCED_GATE: payload.HORDE_CONTAIN_PRODUCED_GATE_BYTES,
            }
        )
    )
    monkeypatch.setattr(builder, "SOURCE_SHA256", builder.digest(source.read_bytes()))
    return source


def run_build(monkeypatch: pytest.MonkeyPatch, source: Path, target: Path, *flags: str) -> None:
    monkeypatch.setattr("sys.argv", ["build", "--in", str(source), "--out", str(target), *flags])
    builder.main()


@pytest.mark.parametrize(
    "flags,selected",
    [
        ([], {"hero-horde-death"}),
        (["--payload"], {"hero-horde-death", "combo-horde-recruitment"}),
        (["--herobar"], {"hero-horde-death", "horde-herobar"}),
        (
            ["--payload", "--herobar"],
            {"hero-horde-death", "combo-horde-recruitment", "horde-herobar"},
        ),
        (["--only-herobar"], {"horde-herobar"}),
    ],
)
def test_build_selections_are_verified_without_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verified_source: Path,
    flags: list[str],
    selected: set[str],
) -> None:
    target = tmp_path / "patched" / "game.dat"
    original = verified_source.read_bytes()
    run_build(monkeypatch, verified_source, target, *flags)
    data = target.read_bytes()
    sites = (
        (death.HeroHordeDeathPatch(), death.HOOK, death.ORIGINAL),
        (
            payload.ComboHordeRecruitmentPatch(),
            payload.HORDE_CONTAIN_PRODUCED_GATE,
            payload.HORDE_CONTAIN_PRODUCED_GATE_BYTES,
        ),
        (herobar.HordeHerobarPatch(), herobar.HOOK, herobar.ORIGINAL),
    )
    for patch, hook, stock in sites:
        if patch.name in selected:
            assert not patch.verify(data)
        else:
            offset = file_offset(data, hook)
            assert data[offset : offset + len(stock)] == stock
    assert verified_source.read_bytes() == original
    assert {p for p in tmp_path.rglob("*") if p.is_file()} == {verified_source, target}
    mtime = target.stat().st_mtime_ns
    run_build(monkeypatch, verified_source, target, *flags)
    assert target.read_bytes() == data
    assert target.stat().st_mtime_ns == mtime


def test_restore_copies_verified_source_without_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verified_source: Path
) -> None:
    target = tmp_path / "restored" / "game.dat"
    original = verified_source.read_bytes()
    run_build(monkeypatch, verified_source, target, "--restore")
    assert target.read_bytes() == original == verified_source.read_bytes()
    assert {p for p in tmp_path.rglob("*") if p.is_file()} == {verified_source, target}
    mtime = target.stat().st_mtime_ns
    run_build(monkeypatch, verified_source, target, "--restore")
    assert target.stat().st_mtime_ns == mtime


@pytest.mark.parametrize("flags", [[], ["--restore"]])
def test_refuses_different_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verified_source: Path,
    flags: list[str],
) -> None:
    target = tmp_path / "game.dat"
    target.write_bytes(b"keep this output")
    original = verified_source.read_bytes()
    with pytest.raises(ValueError, match="Output exists with different content"):
        run_build(monkeypatch, verified_source, target, *flags)
    assert target.read_bytes() == b"keep this output"
    assert verified_source.read_bytes() == original
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("name", ["game.dat.backup", "other.backup", "other.BACKUP"])
def test_refuses_source_and_backup_destinations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verified_source: Path, name: str
) -> None:
    target = tmp_path / name
    original = verified_source.read_bytes()
    with pytest.raises(ValueError, match="separate file"):
        run_build(monkeypatch, verified_source, target)
    assert verified_source.read_bytes() == original
    if target != verified_source:
        assert not target.exists()


@pytest.mark.parametrize("flags", [[], ["--restore"]])
def test_rejects_unverified_source_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verified_source: Path,
    flags: list[str],
) -> None:
    target = tmp_path / "patched" / "game.dat"
    original = verified_source.read_bytes()
    monkeypatch.setattr(builder, "SOURCE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="Input SHA256"):
        run_build(monkeypatch, verified_source, target, *flags)
    assert verified_source.read_bytes() == original
    assert not target.parent.exists()


@pytest.mark.parametrize(
    "flags,hook",
    [
        ([], death.HOOK),
        (["--payload"], payload.HORDE_CONTAIN_PRODUCED_GATE),
        (["--only-herobar"], herobar.HOOK),
    ],
)
def test_bad_signature_does_not_publish_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verified_source: Path,
    flags: list[str],
    hook: int,
) -> None:
    target = tmp_path / "patched" / "game.dat"
    broken = bytearray(verified_source.read_bytes())
    broken[file_offset(broken, hook)] ^= 1
    verified_source.write_bytes(broken)
    monkeypatch.setattr(builder, "SOURCE_SHA256", builder.digest(broken))
    with pytest.raises(ValueError):
        run_build(monkeypatch, verified_source, target, *flags)
    assert verified_source.read_bytes() == broken
    assert not target.parent.exists()


def test_later_patch_cannot_invalidate_earlier_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verified_source: Path
) -> None:
    target = tmp_path / "patched" / "game.dat"
    original = verified_source.read_bytes()
    apply_payload = payload.ComboHordeRecruitmentPatch.apply

    def corrupt_earlier_patch(self: payload.ComboHordeRecruitmentPatch, data: bytearray) -> None:
        apply_payload(self, data)
        located = find_section(data, death.SECTION_NAME)
        assert located is not None
        data[located[1]] ^= 1

    monkeypatch.setattr(payload.ComboHordeRecruitmentPatch, "apply", corrupt_earlier_patch)
    with pytest.raises(ValueError, match="hero-horde-death"):
        run_build(monkeypatch, verified_source, target, "--payload")
    assert verified_source.read_bytes() == original
    assert not target.parent.exists()


@pytest.mark.parametrize(
    "flags",
    [
        ["--only-herobar", "--herobar"],
        ["--only-herobar", "--payload"],
        ["--restore", "--payload"],
        ["--restore", "--herobar"],
        ["--restore", "--only-herobar"],
    ],
)
def test_invalid_selections_fail_before_reading_or_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: list[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        run_build(monkeypatch, tmp_path / "absent", tmp_path / "output", *flags)
    assert exc.value.code == 2
    assert not list(tmp_path.iterdir())
