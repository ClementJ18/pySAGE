"""Execute both added movie paths and preserve native updates, audio and caller state."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import HeroManaPatch, SpecialPowerMusicPatch, SpecialPowerPalantirMoviePatch
from sage_patch import addresses as ad
from sage_patch.__main__ import main
from sage_patch.patches.special_powers import special_power_palantir_movie as movie
from sage_patch.registry import PATCHES
from sage_patch.utils import file_offset, find_section

from .synthetic import _sparse_image


def image() -> bytearray:
    return _sparse_image({**ad.SPECIAL_POWER_PALANTIR_ANCHORS, **ad.SPECIAL_POWER_PALANTIR_WINDOWS})


def test_registration_apply_verify_and_exact_two_windows() -> None:
    assert PATCHES[SpecialPowerPalantirMoviePatch.name] is SpecialPowerPalantirMoviePatch
    patch, data = SpecialPowerPalantirMoviePatch(), image()
    before = bytes(data)
    assert patch.detect(data) is None
    patch.apply(data)
    assert patch.verify(data) == []
    assert isinstance(patch.detect(data), type(patch))
    windows = [
        (file_offset(data, va), len(b)) for va, b in ad.SPECIAL_POWER_PALANTIR_WINDOWS.items()
    ]
    assert all(
        a == b or any(off <= i < off + size for off, size in windows)
        for i, (a, b) in enumerate(
            zip(before[0x1000:], data[0x1000 : len(before)], strict=True), 0x1000
        )
    )
    saved = bytes(data)
    with pytest.raises(ValueError, match="already carries"):
        patch.apply(data)
    assert data == saved


@pytest.mark.parametrize(
    "va", [*ad.SPECIAL_POWER_PALANTIR_ANCHORS, *ad.SPECIAL_POWER_PALANTIR_WINDOWS]
)
def test_rejects_wrong_build_before_mutation(va: int) -> None:
    data = image()
    data[file_offset(data, va)] ^= 1
    before = bytes(data)
    with pytest.raises(ValueError, match="unexpected build"):
        SpecialPowerPalantirMoviePatch().apply(data)
    assert data == before


@pytest.mark.parametrize("site", [0, *ad.SPECIAL_POWER_PALANTIR_WINDOWS, ad.GET_FINAL_OVERRIDE])
def test_verify_checks_code_hooks_and_called_contracts(site: int) -> None:
    data, patch = image(), SpecialPowerPalantirMoviePatch()
    patch.apply(data)
    section = find_section(data, movie.SECTION_NAME)
    assert section is not None
    data[file_offset(data, site) if site else section[1]] ^= 1
    assert patch.verify(data)
    assert patch.detect(data) is None


def test_cli(tmp_path: Path) -> None:
    source, dest = tmp_path / "stock.dat", tmp_path / "movie.dat"
    source.write_bytes(image())
    assert (
        main(["apply", "special-power-palantir-movie", "--in", str(source), "--out", str(dest)])
        == 0
    )
    assert main(["verify", "special-power-palantir-movie", str(dest)]) == 0
    assert source.read_bytes() == image()


@pytest.mark.parametrize("configured,client", [(True, True), (False, True), (True, False)])
def test_request_borrows_final_name_and_restores_machine_state(
    configured: bool, client: bool
) -> None:
    pytest.importorskip("unicorn")
    pytest.importorskip("pefile")
    from unicorn import x86_const as x86  # noqa: PLC0415

    from .save_machine import Machine  # noqa: PLC0415

    data = image()
    SpecialPowerPalantirMoviePatch().apply(data)
    section = find_section(data, movie.SECTION_NAME)
    assert section is not None
    m = Machine(bytes(data))
    module, md, template = m.alloc(0x40), m.alloc(0x80), m.alloc(0x88)
    final = m.alloc(0x88)
    name = m.alloc(20, struct.pack("<IHH", 1, int(configured), 20) + b"TestMovie\0")
    m.write32(module + 4, md)
    m.write32(md + 8, template)
    m.write32(final + 0x5C, name)
    m.ensure(ad.SPECIAL_POWER_PALANTIR_GLOBAL)
    m.write32(ad.SPECIAL_POWER_PALANTIR_GLOBAL, 0x123456 if client else 0)
    requested = []

    def get_final(machine: Machine) -> None:
        assert machine.reg("ecx") == template
        machine.ret(value=final)

    def play(machine: Machine) -> None:
        requested.append((machine.reg("ecx"), machine.arg(0), machine.arg(1)))
        machine.uc.reg_write(x86.UC_X86_REG_XMM0, 0xABCDEF)
        machine.uc.reg_write(x86.UC_X86_REG_MXCSR, 0x3F80)
        machine.uc.reg_write(x86.UC_X86_REG_ECX, 0xDEADBEEF)
        machine.ret(8, 0xCAFE)

    m.stub(ad.GET_FINAL_OVERRIDE, get_final)
    m.stub(ad.SPECIAL_POWER_PALANTIR_CLIENT, play)
    m.uc.reg_write(x86.UC_X86_REG_XMM0, 0x12345678)
    m.uc.reg_write(x86.UC_X86_REG_MXCSR, 0x1F80)
    m.uc.reg_write(x86.UC_X86_REG_EFLAGS, 0x202)
    registers = dict(eax=123, ecx=module, edx=345, ebx=456, esi=567, edi=678, ebp=789)
    m.call(movie._assemble(section[0]).label_va("request"), **registers)
    assert not m.faults
    assert requested == ([(0x123456, final + 0x5C, 0)] if configured and client else [])
    assert {r: m.reg(r) for r in registers} == registers
    assert m.uc.reg_read(x86.UC_X86_REG_EFLAGS) == 0x202
    assert m.uc.reg_read(x86.UC_X86_REG_XMM0) == 0x12345678
    assert m.uc.reg_read(x86.UC_X86_REG_MXCSR) == 0x1F80


def reference_image() -> bytes:
    path = Path(__file__).resolve().parents[2] / "tools/BFME-FILES/game.dat.backup"
    if not path.exists():
        pytest.skip("RotWK reference backup unavailable")
    return path.read_bytes()


@pytest.mark.parametrize(
    "matched,starts", [(False, False), (True, False), (False, True), (True, True)]
)
def test_native_base_path_requests_exactly_one_movie(matched: bool, starts: bool) -> None:
    pefile = pytest.importorskip("pefile")
    pytest.importorskip("unicorn")
    from .palantir_machine import World  # noqa: PLC0415

    data = bytearray(reference_image())
    SpecialPowerPalantirMoviePatch().apply(data)
    w = World(
        pefile.PE(data=bytes(data)).get_memory_mapped_image(), matched=matched, update_starts=starts
    )
    w.put(ad.SPECIAL_POWER_PALANTIR_GLOBAL, w.player)
    events = w.run(0x89816C, [w.pos, 0], interface=True)
    names = [k for k, _ in events]
    assert names.count("movie-request") == int(matched or not starts)
    assert names.count("initiate-fx") == int(matched)
    assert names.count("trigger-location") == int(not starts)
    if not starts:
        assert events[-1] == ("trigger-location", w.pos)


@pytest.mark.parametrize(
    "matched,disabled,valid",
    [(False, False, True), (True, False, True), (False, True, True), (False, False, False)],
)
def test_native_player_upgrade_success_and_abort_paths(
    matched: bool, disabled: bool, valid: bool
) -> None:
    pefile = pytest.importorskip("pefile")
    pytest.importorskip("unicorn")
    from .palantir_machine import World  # noqa: PLC0415

    data = bytearray(reference_image())
    SpecialPowerPalantirMoviePatch().apply(data)
    w = World(
        pefile.PE(data=bytes(data)).get_memory_mapped_image(),
        matched=matched,
        disabled=disabled,
        valid_upgrade=valid,
    )
    w.put(ad.SPECIAL_POWER_PALANTIR_GLOBAL, w.player)
    events = w.run(0x8CC0CC, [0], interface=True)
    names = [k for k, _ in events]
    assert names.count("movie-request") == int(not disabled and valid)
    assert names.count("trigger-location") == int(not disabled and valid)
    if not disabled and valid:
        assert (
            names.index("grant-upgrade")
            < names.index("movie-request")
            < names.index("trigger-location")
        )
        assert events[-1] == ("trigger-location", 0)


@pytest.mark.parametrize("reverse", [False, True])
def test_real_composition_preserves_music_mana_and_audio(reverse: bool) -> None:
    data = bytearray(reference_image())
    audio_off = file_offset(data, 0x89713F)
    audio = bytes(data[audio_off : audio_off + 0x10C])
    patches = [SpecialPowerPalantirMoviePatch(), HeroManaPatch(), SpecialPowerMusicPatch()]
    if reverse:
        patches.reverse()
    for patch in patches:
        patch.apply(data)
    assert all(not p.verify(data) for p in patches)
    # Only the music patch owns the pre-existing five-byte audio hook.
    audio_after = bytes(data[audio_off : audio_off + len(audio)])
    assert all(
        a == b or 0x4D <= n < 0x52 for n, (a, b) in enumerate(zip(audio, audio_after, strict=True))
    )
