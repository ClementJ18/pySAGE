"""Tests for `infantry-lighting`, which widens the KindOf test that hands a drawable the map's
infantry light environment.

There is no hand-written assembly here, so the interesting properties are about the *shape* of the
edit and about what stops it landing on the wrong thing. Three carry most of the weight.
:meth:`TestShape.test_the_edit_touches_the_immediate_and_nothing_else` pins down what the widening
form is allowed to be - one immediate byte, same instruction, same branch - and
:meth:`TestShape.test_every_drawable_defuses_only_the_branch` the same for the `--all` form.
:meth:`TestShape.test_sites_and_fingerprint_are_disjoint` is what keeps `verify` meaningful: a
fingerprint overlapping a site would still hold its stock bytes after `apply`, so `verify` would
report a correctly patched file as broken.

Names are never hardcoded in the patch - they are resolved against the image's own kindof table -
so the stand-in carries the real table, and :class:`TestSelection` is about what that resolution
accepts and refuses. The synthetic image is built from the patch's own tables and so cannot confirm
the addresses are the right ones; :class:`TestInstalledBinary` does that against the real `game.dat`
when it is present, and ``docs/infantry-lighting.md`` records the derivation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch.patcher import apply_patches
from sage_patch.patches.infantry_lighting import (
    DEFAULT_KINDS,
    EVERY_MASK,
    FINGERPRINT,
    LANE_BITS,
    MASK_BYTE_OFFSET,
    NOP_PAIR,
    SITES,
    STOCK_MASK,
    InfantryLightingPatch,
)
from sage_patch.patches.utils import kind_of
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import INFANTRY_LIGHTING_LANE, infantry_lighting_image

_GAME_DAT = Path(r"C:\Program Files (x86)\Games\bfme\rotwk\game.dat")

#: What the default selection encodes: INFANTRY (bit 8) | CAVALRY (bit 9) | MONSTER (bit 10).
DEFAULT_MASK = 0x07


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def immediate(data: bytes | bytearray, site) -> int:
    return at(data, site.va, len(site.stock))[len(site.test_prefix)]


def tail(data: bytes | bytearray, site) -> bytes:
    return at(data, site.va, len(site.stock))[len(site.test_prefix) + 1 :]


@pytest.fixture
def image() -> bytearray:
    return infantry_lighting_image()


class TestShape:
    """What the two forms of the edit are allowed to be."""

    @pytest.mark.parametrize("site", SITES, ids=lambda s: s.note)
    def test_the_edit_touches_the_immediate_and_nothing_else(self, site):
        """The widening form rewrites one byte. Same instruction, same length, same branch and the
        same target, so the patched path is one the stock binary already takes - for more kindofs
        now."""
        stock, patched = site.stock, site.patched(DEFAULT_MASK, every_drawable=False)
        assert len(stock) == len(patched)
        differing = [i for i, (a, b) in enumerate(zip(stock, patched, strict=True)) if a != b]
        assert differing == [len(site.test_prefix)]
        assert patched[-len(site.branch) :] == site.branch

    @pytest.mark.parametrize("site", SITES, ids=lambda s: s.note)
    def test_every_drawable_defuses_only_the_branch(self, site):
        """The `--all` form leaves the test standing and replaces the skip with `nop`s, so the
        setter call becomes unconditional without moving a single byte of anything else."""
        patched = site.patched(0, every_drawable=True)
        assert len(patched) == len(site.stock)
        assert patched[: len(site.test_prefix)] == site.test_prefix
        assert patched[len(site.test_prefix)] == EVERY_MASK
        assert patched[-len(NOP_PAIR) :] == NOP_PAIR

    @pytest.mark.parametrize("site", SITES, ids=lambda s: s.note)
    def test_every_site_tests_the_same_mask_byte(self, site):
        """`test r/m8, imm8` with a disp32 one byte into the KindOf mask. The immediate is a mask
        over bits 8..15 only because that is the byte both sites read; the patch's refusal of
        anything wider is this fact."""
        assert site.test_prefix[0] == 0xF6  # test r/m8, imm8
        assert site.test_prefix[1] & 0xC0 == 0x80  # mod=10, i.e. disp32
        assert int.from_bytes(site.test_prefix[2:6], "little") == MASK_BYTE_OFFSET
        assert MASK_BYTE_OFFSET == kind_of.THING_TEMPLATE_MASK_OFFSET + 1
        assert tuple(LANE_BITS) == tuple(range(8, 16))

    @pytest.mark.parametrize("site", SITES, ids=lambda s: s.note)
    def test_the_branch_is_a_forward_short_je(self, site):
        assert site.branch[0] == 0x74, "je is the skip-the-setter arm at both sites"
        assert 0 <= site.branch[1] <= 0x7F, "a forward rel8"

    def test_sites_and_fingerprint_are_disjoint(self):
        spans = [
            (va, va + len(blob), f"fingerprint 0x{va:08x}") for va, blob in FINGERPRINT.items()
        ]
        spans += [(site.va, site.va + len(site.stock), site.note) for site in SITES]
        previous_end, previous_what = 0, "start of image"
        for start, end, what in sorted(spans):
            assert start >= previous_end, f"{what} overlaps {previous_what}"
            previous_end, previous_what = end, what

    def test_the_stock_mask_is_infantry_and_monster(self, image):
        """The bug in one assertion: the immediate the engine ships names two kindofs, and
        `CAVALRY` is not either of them."""
        table = kind_of.read(image)
        named = {
            kind_of.read_cstring(image, table.pointers[bit])
            for bit in LANE_BITS
            if STOCK_MASK & (1 << (bit - LANE_BITS.start))
        }
        assert named == {"INFANTRY", "MONSTER"}
        assert "CAVALRY" in DEFAULT_KINDS


class TestApply:
    def test_widens_both_sites(self, image):
        InfantryLightingPatch().apply(image)
        for site in SITES:
            assert immediate(image, site) == DEFAULT_MASK
            assert tail(image, site) == site.branch

    def test_every_drawable_nops_both_branches(self, image):
        InfantryLightingPatch(every=True).apply(image)
        for site in SITES:
            assert immediate(image, site) == EVERY_MASK
            assert tail(image, site) == NOP_PAIR

    def test_a_narrower_selection_is_honoured(self, image):
        """Nothing forces the stock two to stay in: a mod that wants only mounted units lit this
        way can say so, and the immediate follows."""
        InfantryLightingPatch(("CAVALRY",)).apply(image)
        for site in SITES:
            assert immediate(image, site) == 0x02

    def test_leaves_the_fingerprint_alone(self, image):
        InfantryLightingPatch().apply(image)
        for va, expected in FINGERPRINT.items():
            assert at(image, va, len(expected)) == expected

    def test_leaves_the_kindof_table_alone(self, image):
        """This patch reads that table and never rewrites it, which is what makes it compose with
        the patches that do."""
        before = kind_of.read(image)
        InfantryLightingPatch().apply(image)
        assert kind_of.read(image) == before

    def test_verify_is_clean_afterwards(self, image):
        patch = InfantryLightingPatch()
        patch.apply(image)
        assert patch.verify(image) == []

    def test_a_clean_image_does_not_verify(self, image):
        problems = InfantryLightingPatch().verify(image)
        assert len(problems) == len(SITES)
        assert all("expected" in problem for problem in problems)

    def test_verify_is_specific_to_the_selection(self, image):
        InfantryLightingPatch(("CAVALRY",)).apply(image)
        assert InfantryLightingPatch(("CAVALRY",)).verify(image) == []
        assert InfantryLightingPatch().verify(image) != []

    def test_applying_twice_raises(self, image):
        patch = InfantryLightingPatch()
        patch.apply(image)
        with pytest.raises(ValueError, match="expected"):
            patch.apply(image)

    def test_adds_no_ini_surface(self, image):
        """The patch changes which lights a model is drawn with, not the INI the engine parses:
        every name it takes is a kindof that already exists."""
        assert InfantryLightingPatch().ini_surface() is STOCK

    def test_writes_through_apply_patches(self, tmp_path, image):
        source = tmp_path / "game.dat"
        source.write_bytes(bytes(image))
        out = apply_patches(source, [InfantryLightingPatch()], tmp_path / "patched.dat")
        assert InfantryLightingPatch().verify(out.read_bytes()) == []


class TestSelection:
    """What resolving names against the image's own kindof table accepts and refuses."""

    def test_an_unknown_name_refuses(self, image):
        with pytest.raises(ValueError, match="not a KindOf"):
            InfantryLightingPatch(("CHIVALRY",)).apply(image)

    def test_a_kindof_outside_the_byte_refuses_and_names_the_alternative(self, image):
        """`HERO` is bit 90, three bytes further into the mask. The site has no room to read
        another byte, so the patch says so and points at `--all` rather than dropping it."""
        with pytest.raises(ValueError, match=r"bit 90.*--all"):
            InfantryLightingPatch(("INFANTRY", "HERO")).apply(image)

    def test_nothing_is_written_when_a_name_refuses(self, image):
        before = bytes(image)
        with pytest.raises(ValueError):
            InfantryLightingPatch(("HERO",)).apply(image)
        assert bytes(image) == before

    @pytest.mark.parametrize("bit,name", sorted(INFANTRY_LIGHTING_LANE.items()))
    def test_every_name_in_the_lane_resolves_to_its_own_bit(self, image, bit, name):
        assert InfantryLightingPatch((name,)).mask(image) == 1 << (bit - LANE_BITS.start)

    def test_duplicate_names_refuse(self):
        with pytest.raises(ValueError, match="duplicate"):
            InfantryLightingPatch(("CAVALRY", "CAVALRY"))

    def test_an_empty_selection_refuses(self):
        with pytest.raises(ValueError, match="at least one"):
            InfantryLightingPatch(())

    def test_every_with_names_refuses(self):
        with pytest.raises(ValueError, match="ambiguous"):
            InfantryLightingPatch(("CAVALRY",), every=True)


class TestDetect:
    def test_a_stock_image_is_not_carrying_it(self, image):
        """Even though `INFANTRY + MONSTER` is a selection this patch could have been asked for,
        the stock immediate with an intact branch is the engine's own answer, not a patch."""
        assert InfantryLightingPatch.detect(image) is None

    def test_recovers_the_selection(self, image):
        InfantryLightingPatch(("INFANTRY", "CAVALRY")).apply(image)
        found = InfantryLightingPatch.detect(image)
        assert found is not None
        assert found.kinds == ("INFANTRY", "CAVALRY")
        assert not found.every

    def test_recovers_every_drawable(self, image):
        InfantryLightingPatch(every=True).apply(image)
        found = InfantryLightingPatch.detect(image)
        assert found is not None
        assert found.every
        assert found.kinds == ()

    def test_recovered_names_are_in_bit_order(self, image):
        InfantryLightingPatch(("MONSTER", "CAVALRY", "INFANTRY")).apply(image)
        found = InfantryLightingPatch.detect(image)
        assert found is not None
        assert found.kinds == ("INFANTRY", "CAVALRY", "MONSTER")

    def test_a_half_written_site_is_not_detected(self, image):
        """`detect` reads the first site and `verify` then checks both, so a binary whose two
        gates disagree - a partial write, or another patch on one of them - is reported absent
        rather than as a working configuration."""
        InfantryLightingPatch().apply(image)
        off = va_to_offset(image, SITES[1].va)
        assert off is not None
        image[off : off + len(SITES[1].stock)] = SITES[1].stock
        assert InfantryLightingPatch.detect(image) is None


class TestRefusals:
    def test_a_changed_fingerprint_refuses(self, image):
        va = next(iter(FINGERPRINT))
        off = va_to_offset(image, va)
        assert off is not None
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="unexpected build"):
            InfantryLightingPatch().apply(image)

    def test_a_changed_fingerprint_fails_verify_rather_than_raising(self, image):
        InfantryLightingPatch().apply(image)
        va = next(iter(FINGERPRINT))
        off = va_to_offset(image, va)
        assert off is not None
        image[off] ^= 0xFF
        assert InfantryLightingPatch().verify(image) != []
        assert InfantryLightingPatch.detect(image) is None

    def test_an_image_without_the_sites_refuses(self):
        with pytest.raises(ValueError, match="unexpected build"):
            InfantryLightingPatch().apply(bytearray(infantry_lighting_image()[:0x400]))


class TestRegistry:
    def test_is_registered(self):
        assert PATCHES[InfantryLightingPatch.name] is InfantryLightingPatch

    def test_the_cli_round_trips_both_forms(self):
        parser = argparse.ArgumentParser()
        InfantryLightingPatch.add_cli_arguments(parser)

        widened = InfantryLightingPatch.from_cli_args(parser.parse_args([]))
        assert widened.kinds == DEFAULT_KINDS

        narrowed = InfantryLightingPatch.from_cli_args(parser.parse_args(["--kinds", "CAVALRY, "]))
        assert narrowed.kinds == ("CAVALRY",)

        everything = InfantryLightingPatch.from_cli_args(parser.parse_args(["--all"]))
        assert everything.every

    def test_all_beats_kinds(self):
        parser = argparse.ArgumentParser()
        InfantryLightingPatch.add_cli_arguments(parser)
        both = InfantryLightingPatch.from_cli_args(
            parser.parse_args(["--kinds", "MACHINE", "--all"])
        )
        assert both.every


@pytest.mark.skipif(not _GAME_DAT.exists(), reason="requires a local ROTWK install")
class TestInstalledBinary:
    """The addresses, against the real thing. Everything above is self-consistent by construction;
    only this says the sites are where the patch claims."""

    @pytest.fixture
    def installed(self) -> bytearray:
        return bytearray(_GAME_DAT.read_bytes())

    def test_the_fingerprint_is_present(self, installed):
        for va, expected in FINGERPRINT.items():
            assert at(installed, va, len(expected)) == expected, f"0x{va:08x}"

    def test_each_site_reads_stock_or_patched(self, installed):
        for site in SITES:
            got = at(installed, site.va, len(site.stock))
            widened = {site.patched(mask, False) for mask in range(0x100)}
            assert got in ({site.stock, site.patched(0, True)} | widened), f"{site.note}"

    def test_the_lane_is_the_kindofs_this_patch_claims(self, installed):
        """The eight names the help text lists, checked against the real table rather than
        restated: `CAVALRY` being bit 9 is the whole reason this patch exists."""
        table = kind_of.read(installed)
        found = {bit: kind_of.read_cstring(installed, table.pointers[bit]) for bit in LANE_BITS}
        assert found == INFANTRY_LIGHTING_LANE

    def test_apply_then_verify(self, installed):
        """Forced back to stock first, so this passes whether or not the install already carries
        the patch."""
        for site in SITES:
            off = va_to_offset(installed, site.va)
            assert off is not None
            installed[off : off + len(site.stock)] = site.stock
        patch = InfantryLightingPatch()
        assert patch.verify(installed) != []
        patch.apply(installed)
        assert patch.verify(installed) == []
