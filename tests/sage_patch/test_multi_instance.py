"""Tests for the two patches that lift the one-instance-at-a-time limit.

There is no hand-written assembly in either, so the interesting properties are about the *shape*
of the edit and about the checks that stop it landing on the wrong thing.

Two of them carry most of the weight. :meth:`TestShape.test_a_guard_edit_moves_exactly_one_byte`
pins down what these patches are allowed to be: a `jcc` becoming a `jmp`, same length, same target,
one byte different. And :meth:`TestShape.test_guards_and_fingerprints_are_disjoint` is what keeps
`verify` meaningful — a fingerprint overlapping a guard would still hold its stock bytes after
`apply`, so `verify` would report a correctly patched file as broken.

The synthetic images are built from the patches' own tables, so they cannot confirm the addresses
are the right ones; :class:`TestInstalledBinaries` does that against the real files when they are
present, and ``docs/multi-instance.md`` records the derivation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sage_ini.engine import STOCK
from sage_patch.patches.multi_instance import (
    GAME_FINGERPRINT,
    GAME_GUARDS,
    JMP_SHORT,
    LAUNCHER_FINGERPRINT,
    LAUNCHER_GUARDS,
    MultiInstanceLauncherPatch,
    MultiInstancePatch,
)
from sage_patch.registry import PATCHES
from sage_patch.utils import va_to_offset
from tests.sage_patch.synthetic import instance_guard_image

PATCH_CLASSES = (MultiInstancePatch, MultiInstanceLauncherPatch)

_INSTALL = Path(r"C:\Program Files (x86)\Games\bfme\rotwk")
_BINARIES = {
    MultiInstancePatch.name: _INSTALL / "game.dat",
    MultiInstanceLauncherPatch.name: _INSTALL / "lotrbfme2ep1.exe",
}


def at(data: bytes | bytearray, va: int, count: int) -> bytes:
    off = va_to_offset(data, va)
    assert off is not None, f"0x{va:08x} is not mapped"
    return bytes(data[off : off + count])


def spans(patch) -> list[tuple[int, int, str]]:
    """Every ``(start VA, end VA, what)`` the patch reads or writes."""
    out = [
        (va, va + len(blob), f"fingerprint 0x{va:08x}") for va, blob in patch.fingerprint.items()
    ]
    out += [(g.va, g.va + len(g.stock), g.note) for g in patch.guards]
    return sorted(out)


@pytest.fixture(params=PATCH_CLASSES, ids=lambda cls: cls.name)
def patch(request):
    return request.param()


@pytest.fixture
def image(patch) -> bytearray:
    return instance_guard_image(patch)


class TestShape:
    @pytest.mark.parametrize("guard", [*GAME_GUARDS, *LAUNCHER_GUARDS], ids=lambda g: g.note)
    def test_a_guard_edit_moves_exactly_one_byte(self, guard):
        """The whole method: rewrite the condition away, keep the jump.

        Same length means nothing downstream shifts; the same `rel8` displacement means the branch
        still lands where the compiler put it, so the patched path is a path the stock binary
        already takes — just unconditionally now."""
        stock, patched = guard.stock, guard.patched
        assert len(stock) == len(patched)
        differing = [i for i, (a, b) in enumerate(zip(stock, patched, strict=True)) if a != b]
        assert differing == [len(guard.run_up)]
        assert patched[differing[0]] == JMP_SHORT
        assert patched[-1] == stock[-1] == guard.displacement

    @pytest.mark.parametrize("guard", [*GAME_GUARDS, *LAUNCHER_GUARDS], ids=lambda g: g.note)
    def test_every_guard_is_a_short_conditional(self, guard):
        assert guard.opcode in (0x74, 0x75), "je/jne are the only forms these three gates use"
        assert 0 <= guard.displacement <= 0x7F, "a forward rel8, i.e. the skip-the-refusal arm"

    def test_guards_and_fingerprints_are_disjoint(self, patch):
        previous_end, previous_what = 0, "start of image"
        for start, end, what in spans(patch):
            assert start >= previous_end, f"{what} overlaps {previous_what}"
            previous_end, previous_what = end, what

    def test_the_two_patches_target_different_binaries(self):
        assert MultiInstancePatch.binary != MultiInstanceLauncherPatch.binary
        assert not set(GAME_FINGERPRINT) & set(LAUNCHER_FINGERPRINT)


class TestApply:
    def test_flips_every_guard(self, patch, image):
        patch.apply(image)
        for guard in patch.guards:
            assert at(image, guard.va, len(guard.patched)) == guard.patched

    def test_leaves_the_fingerprint_alone(self, patch, image):
        patch.apply(image)
        for va, expected in patch.fingerprint.items():
            assert at(image, va, len(expected)) == expected

    def test_verify_is_clean_afterwards(self, patch, image):
        patch.apply(image)
        assert patch.verify(image) == []

    def test_a_clean_image_does_not_verify(self, patch, image):
        problems = patch.verify(image)
        assert len(problems) == len(patch.guards)
        assert all("expected" in problem for problem in problems)

    def test_detect_answers_only_after_apply(self, patch, image):
        cls = type(patch)
        assert cls.detect(image) is None
        patch.apply(image)
        assert isinstance(cls.detect(image), cls)

    def test_applying_twice_raises(self, patch, image):
        patch.apply(image)
        with pytest.raises(ValueError, match="expected"):
            patch.apply(image)

    def test_adds_no_ini_surface(self, patch, image):
        """These patches change engine behaviour, not the INI the engine parses, so there is
        nothing for `sage-patch sagepatch` to write."""
        assert patch.ini_surface() is STOCK


class TestRefusals:
    def test_a_changed_fingerprint_refuses(self, patch, image):
        va = next(iter(patch.fingerprint))
        off = va_to_offset(image, va)
        image[off] ^= 0xFF
        with pytest.raises(ValueError, match="unexpected build"):
            patch.apply(image)

    def test_a_refusal_writes_nothing(self, patch, image):
        va = next(iter(patch.fingerprint))
        image[va_to_offset(image, va)] ^= 0xFF
        with pytest.raises(ValueError):
            patch.apply(image)
        for guard in patch.guards:
            assert at(image, guard.va, len(guard.stock)) == guard.stock

    def test_a_moved_guard_refuses(self, patch, image):
        """The fingerprint passes but the guard's own run-up does not — which is what a build
        where the condition is computed differently would look like."""
        guard = patch.guards[0]
        image[va_to_offset(image, guard.va)] ^= 0xFF
        with pytest.raises(ValueError, match="expected"):
            patch.apply(image)

    def test_an_all_zero_image_refuses(self, patch):
        """The degenerate wrong binary: every site reads zero rather than something plausible."""
        blank = instance_guard_image(patch)
        for va, blob in patch.fingerprint.items():
            off = va_to_offset(blank, va)
            blank[off : off + len(blob)] = bytes(len(blob))
        with pytest.raises(ValueError, match="unexpected build"):
            patch.apply(blank)

    def test_neither_patch_applies_to_the_other_binary(self):
        game, launcher = MultiInstancePatch(), MultiInstanceLauncherPatch()
        for patch, other in ((game, launcher), (launcher, game)):
            wrong = instance_guard_image(other)
            assert patch.detect(wrong) is None
            with pytest.raises(ValueError, match="unexpected build"):
                patch.apply(wrong)


class TestRegistry:
    @pytest.mark.parametrize("cls", PATCH_CLASSES, ids=lambda cls: cls.name)
    def test_is_registered(self, cls):
        assert PATCHES[cls.name] is cls

    def test_the_launcher_patch_says_which_binary_it_wants(self):
        """The CLI labels every path argument `GAME_DAT`, so a patch that wants a different file
        has to say so in the text `sage-patch list` prints."""
        assert "lotrbfme2ep1.exe" in MultiInstanceLauncherPatch.description


@pytest.mark.skipif(
    not all(path.exists() for path in _BINARIES.values()),
    reason="requires a local ROTWK install (not available in CI)",
)
class TestInstalledBinaries:
    """The addresses against the real files. This is the only thing here that can catch a patch
    aimed at bytes that are not actually the instance check."""

    @pytest.fixture
    def installed(self, patch) -> bytearray:
        return bytearray(_BINARIES[patch.name].read_bytes())

    def test_the_fingerprint_is_present(self, patch, installed):
        for va, expected in patch.fingerprint.items():
            assert at(installed, va, len(expected)) == expected, f"0x{va:08x}"

    def test_each_guard_reads_stock_or_patched(self, patch, installed):
        for guard in patch.guards:
            got = at(installed, guard.va, len(guard.stock))
            assert got in (guard.stock, guard.patched), f"{guard.note}: {got.hex()}"

    def test_apply_then_verify(self, patch, installed):
        """Forced back to stock first, so this passes whether or not the install already carries
        the patch."""
        for guard in patch.guards:
            off = va_to_offset(installed, guard.va)
            installed[off : off + len(guard.stock)] = guard.stock
        assert patch.verify(installed) != []
        patch.apply(installed)
        assert patch.verify(installed) == []
