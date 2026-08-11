"""Tests for the hero-bar-slots patch.

There is no assembly here: the patch is 38 immediates. So what the tests have to establish is
that the arithmetic is right and that nothing about it changes an instruction's *length* - the
single property that lets the array grow without a cave.

Four carry most of the weight. :meth:`TestShape.test_every_edit_keeps_its_length` is the
invariant the whole design rests on. :meth:`TestShape.test_stock_bytes_reproduce_the_stock_class`
is what says the tables describe a 16-slot bar rather than an arbitrary set of addresses - the
class size the sites imply has to be the ``0x1E0`` the engine allocates.
:meth:`TestShape.test_the_state_block_lands_inside_the_grown_class` is the memory-safety
statement: every re-based field still has to fit. And
:meth:`TestVerify.test_stock_is_not_reported_as_patched` is what keeps `detect` honest, since a
16-slot "patch" would compute exactly the stock bytes and pass its own verification.

The synthetic image is built from the patch's own tables and so cannot confirm the addresses are
the right ones; :class:`TestInstalledBinary` does that against the real `game.dat` when it is
present, and ``docs/hero-bar-slots.md`` records the derivation.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch.patcher import apply_patches
from sage_patch.patches.hero_bar_slots import (
    CLASS_SIZE_SITE,
    COUNT_SITES,
    FIELD_SITES,
    MAX_COUNT,
    MIN_COUNT,
    SLOT_ARRAY,
    SLOT_STRIDE,
    STATE_BLOCK,
    STATE_BLOCK_SIZE,
    STOCK_CLASS_SIZE,
    STOCK_SLOTS,
    HeroBarSlotsPatch,
    class_size,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import hero_bar_slots_image

_GAME_DAT = Path(r"C:\Program Files (x86)\Games\bfme\rotwk\game.dat")

#: A width other than the default, so a test that passes only because both sides used the same
#: fallback is not mistaken for one that checks the arithmetic.
_N = 21


@pytest.fixture(scope="module")
def image() -> bytes:
    return _GAME_DAT.read_bytes()


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


class TestShape:
    def test_every_edit_keeps_its_length(self) -> None:
        """The design in one assertion: nothing here re-encodes an instruction.

        The array can only grow in place because every site is a same-length immediate rewrite -
        a disp8 that had to become a disp32, or an imm8 that had to become an imm32, would need
        relocated code and a detour instead."""
        image = hero_bar_slots_image()
        for _off, old, new, note in HeroBarSlotsPatch(_N)._edits(image):
            assert len(old) == len(new), note

    def test_stock_bytes_reproduce_the_stock_class(self) -> None:
        """16 slots must imply the `0x1E0` the engine really allocates.

        This is what ties the tables to the actual class rather than to themselves: the array
        offset, the stride and the trailing state block are read off three different sites, and
        only the real layout makes them agree with the shipped `sizeof`."""
        assert class_size(STOCK_SLOTS) == STOCK_CLASS_SIZE
        assert SLOT_ARRAY + STOCK_SLOTS * SLOT_STRIDE == STATE_BLOCK

    def test_the_state_block_lands_inside_the_grown_class(self) -> None:
        """Every re-based field still has to fit in what the ctor allocates."""
        for count in (MIN_COUNT, _N, MAX_COUNT):
            size = class_size(count)
            moved = SLOT_ARRAY + count * SLOT_STRIDE
            assert moved + STATE_BLOCK_SIZE == size
            for field in FIELD_SITES:
                new = field.field + (count - STOCK_SLOTS) * SLOT_STRIDE
                assert moved <= new < size, f"{field.va:#010x} would land outside the class"

    def test_the_field_sites_all_address_the_state_block(self) -> None:
        for field in FIELD_SITES:
            assert STATE_BLOCK <= field.field < STOCK_CLASS_SIZE
            raw = bytes.fromhex(field.original)
            assert struct.unpack_from("<i", raw, field.disp_at)[0] == field.field

    def test_the_two_one_based_sites_are_the_loop_bounds(self) -> None:
        """Exactly two sites compare against ``count + 1``, and they are the pair that counts
        slots from one - the draw ceiling and the cleanup back edge. Getting a bias backwards
        loses a slot at one end or runs one past the array at the other."""
        biased = {site.va for site in COUNT_SITES if site.bias}
        assert biased == {0x0092D3E5, 0x0092D8B6}

    def test_the_edits_touch_thirty_eight_distinct_sites(self) -> None:
        edits = HeroBarSlotsPatch(_N)._edits(hero_bar_slots_image())
        assert len(edits) == len(COUNT_SITES) + 1 + len(FIELD_SITES) == 38
        assert len({off for off, *_ in edits}) == len(edits)


class TestValidation:
    @pytest.mark.parametrize("count", [0, 1, STOCK_SLOTS, MAX_COUNT + 1, 127, 1000])
    def test_a_width_outside_the_range_is_refused(self, count: int) -> None:
        with pytest.raises(ValueError):
            HeroBarSlotsPatch(count)

    def test_the_stock_width_is_refused_as_a_no_op(self) -> None:
        """16 is not "apply nothing", it is a patch whose verification a stock binary would
        pass - which would make `detect` claim every unpatched `game.dat` carries this."""
        with pytest.raises(ValueError, match="raises the ceiling"):
            HeroBarSlotsPatch(STOCK_SLOTS)

    @pytest.mark.parametrize("count", [MIN_COUNT, _N, MAX_COUNT])
    def test_a_width_inside_the_range_is_accepted(self, count: int) -> None:
        assert HeroBarSlotsPatch(count).count == count


class TestApply:
    def test_apply_then_verify(self) -> None:
        image = hero_bar_slots_image()
        HeroBarSlotsPatch(_N).apply(image)
        assert HeroBarSlotsPatch(_N).verify(image) == []

    def test_apply_writes_the_new_class_size(self) -> None:
        image = hero_bar_slots_image()
        HeroBarSlotsPatch(_N).apply(image)
        got = struct.unpack_from("<I", at(image, CLASS_SIZE_SITE, 5), 1)[0]
        assert got == class_size(_N) == 0x258

    def test_apply_is_not_idempotent(self) -> None:
        """The second run must fail rather than write again: every site asserts its *stock* bytes,
        so a double-apply is caught instead of silently re-basing the state block twice."""
        image = hero_bar_slots_image()
        HeroBarSlotsPatch(_N).apply(image)
        with pytest.raises(ValueError):
            HeroBarSlotsPatch(_N).apply(image)

    def test_apply_refuses_an_image_that_is_not_this_build(self) -> None:
        image = hero_bar_slots_image()
        off = va_to_offset(image, COUNT_SITES[0].va)
        assert off is not None
        image[off + 2] = 0x7F  # a bound that is not the stock 16
        with pytest.raises(ValueError):
            HeroBarSlotsPatch(_N).apply(image)

    @pytest.mark.parametrize("count", [MIN_COUNT, _N, MAX_COUNT])
    def test_every_width_applies_and_verifies(self, count: int) -> None:
        image = hero_bar_slots_image()
        HeroBarSlotsPatch(count).apply(image)
        assert HeroBarSlotsPatch(count).verify(image) == []


class TestVerify:
    def test_stock_is_not_reported_as_patched(self) -> None:
        image = hero_bar_slots_image()
        assert HeroBarSlotsPatch(_N).verify(image)
        assert HeroBarSlotsPatch.detect(image) is None

    def test_verify_rejects_a_different_width(self) -> None:
        image = hero_bar_slots_image()
        HeroBarSlotsPatch(_N).apply(image)
        assert HeroBarSlotsPatch(_N + 1).verify(image)

    def test_detect_recovers_the_width(self) -> None:
        for count in (MIN_COUNT, _N, MAX_COUNT):
            image = hero_bar_slots_image()
            HeroBarSlotsPatch(count).apply(image)
            found = HeroBarSlotsPatch.detect(image)
            assert found is not None
            assert found.count == count

    def test_detect_ignores_a_class_size_that_is_not_a_whole_number_of_slots(self) -> None:
        """The size alone is not proof: a `push` of something that is not
        ``0x48 + N*0x18 + 0x18`` is some other build's, and answering "patched at N" from it
        would then check 37 sites against a width nothing chose."""
        image = hero_bar_slots_image()
        HeroBarSlotsPatch(_N).apply(image)
        off = va_to_offset(image, CLASS_SIZE_SITE)
        assert off is not None
        struct.pack_into("<I", image, off + 1, class_size(_N) + 4)
        assert HeroBarSlotsPatch.detect(image) is None


class TestRegistry:
    def test_it_is_registered_and_attributed(self) -> None:
        assert PATCHES["hero-bar-slots"] is HeroBarSlotsPatch
        assert HeroBarSlotsPatch.author

    def test_apply_patches_writes_a_verifiable_file(self, tmp_path: Path) -> None:
        src = tmp_path / "in.dat"
        src.write_bytes(bytes(hero_bar_slots_image()))
        out = tmp_path / "out.dat"
        apply_patches(src, [HeroBarSlotsPatch(_N)], output=out)
        assert HeroBarSlotsPatch(_N).verify(out.read_bytes()) == []
        assert src.read_bytes() != out.read_bytes()


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="needs an installed game.dat")
class TestInstalledBinary:
    """The addresses, against the real thing. Everything above is self-consistent by
    construction; only this says the sites are where the patch claims."""

    def test_every_site_holds_its_stock_bytes(self, image: bytes) -> None:
        for site in COUNT_SITES:
            expected = site.encode(STOCK_SLOTS)
            assert at(image, site.va, len(expected)) == expected, f"{site.va:#010x} {site.note}"
        for field in FIELD_SITES:
            expected = bytes.fromhex(field.original)
            assert at(image, field.va, len(expected)) == expected, f"{field.va:#010x}"

    def test_the_ctor_allocates_the_stock_class_size(self, image: bytes) -> None:
        raw = at(image, CLASS_SIZE_SITE, 5)
        assert raw[:1] == b"\x68"
        assert struct.unpack_from("<I", raw, 1)[0] == STOCK_CLASS_SIZE

    def test_the_installed_binary_is_not_already_patched(self, image: bytes) -> None:
        assert HeroBarSlotsPatch.detect(image) is None

    def test_apply_against_the_real_binary_verifies(self, image: bytes) -> None:
        data = bytearray(image)
        HeroBarSlotsPatch(_N).apply(data)
        assert HeroBarSlotsPatch(_N).verify(data) == []
        found = HeroBarSlotsPatch.detect(data)
        assert found is not None and found.count == _N

    def test_the_patch_changes_only_the_hero_bar_cluster(self, image: bytes) -> None:
        """66 bytes, all inside the one translation unit the bar lives in. A site that had
        drifted into another function would show up here as an out-of-range offset."""
        data = bytearray(image)
        HeroBarSlotsPatch(_N).apply(data)
        changed = [i for i, (a, b) in enumerate(zip(image, data, strict=True)) if a != b]
        lo = va_to_offset(image, 0x0092B000)
        hi = va_to_offset(image, 0x0092E400)
        assert lo is not None and hi is not None
        assert changed and lo <= min(changed) and max(changed) < hi
