"""Jump To Game's patches on the install's game.dat: backed up, applied, and put back."""

import os
import re

import pytest

from sage_ini.engine import AppliedPatch, Engine
from sage_patch.patches.experimental.command_line_skirmish import CommandLineSkirmishPatch
from sage_patch.patches.mod_load_order import ModLoadOrderPatch
from sage_patch.patches.multi_mod import MultiModPatch
from sage_worldbuilder import launch_patch
from sage_worldbuilder.launch_patch import (
    LAUNCH_PATCHES,
    LaunchPatchError,
    backup_path,
    missing_patches,
    patch_for_launch,
    restore_after_launch,
    restore_pending,
    sagepatch_patches,
)

ORIGINAL = b"MZ stock game"


def fake_patch(patch_name, mark):
    """Appends a mark; detected by it. The real patches need the real binary."""

    class FakePatch:
        name = patch_name

        def apply(self, data):
            if not data.startswith(b"MZ"):
                raise ValueError("the hook sites are not mapped - not the expected build")
            data += mark

        def verify(self, data):
            return [] if mark in data else ["not patched"]

        def options(self):
            return {}

        @classmethod
        def detect(cls, data):
            return cls() if mark in data else None

    return FakePatch


class LimitPatch:
    """A patch with a parameter, which its mark records, as a `.sagepatch` would list it."""

    name = "commandset-limit"

    def __init__(self, count=64):
        self.count = count

    def options(self):
        return {"count": self.count}

    def apply(self, data):
        data += b"+limit%d" % self.count

    def verify(self, data):
        return [] if b"+limit%d" % self.count in data else ["not patched"]

    @classmethod
    def detect(cls, data):
        found = re.search(rb"\+limit(\d+)", bytes(data))
        return cls(int(found.group(1))) if found else None


SKIRMISH = fake_patch("command-line-skirmish", b"+skirmish")
MODS = fake_patch("multi-mod", b"+mods")
BOTH = ORIGINAL + b"+skirmish+mods"


@pytest.fixture
def game_dat(tmp_path, monkeypatch):
    monkeypatch.setattr(launch_patch, "LAUNCH_PATCHES", (SKIRMISH, MODS))
    path = tmp_path / "game.dat"
    path.write_bytes(ORIGINAL)
    return path


def test_jump_to_game_patches_skirmish_mod_order_and_multi_mod():
    assert LAUNCH_PATCHES == (CommandLineSkirmishPatch, ModLoadOrderPatch, MultiModPatch)


def test_patches_with_a_backup_and_puts_the_original_back(game_dat):
    os.utime(game_dat, (1_000_000, 1_000_000))

    assert patch_for_launch(game_dat) is True
    assert game_dat.read_bytes() == BOTH
    assert backup_path(game_dat).read_bytes() == ORIGINAL
    assert restore_pending(game_dat)

    assert restore_after_launch(game_dat) is None
    assert game_dat.read_bytes() == ORIGINAL
    assert game_dat.stat().st_mtime == 1_000_000
    assert not restore_pending(game_dat)
    assert sorted(path.name for path in game_dat.parent.iterdir()) == ["game.dat"]


def test_only_the_missing_patches_are_applied(game_dat):
    game_dat.write_bytes(ORIGINAL + b"+mods")

    assert missing_patches(game_dat.read_bytes()) == [SKIRMISH]
    assert patch_for_launch(game_dat) is True
    assert game_dat.read_bytes() == ORIGINAL + b"+mods+skirmish"
    assert restore_after_launch(game_dat) is None
    assert game_dat.read_bytes() == ORIGINAL + b"+mods"


def test_a_game_carrying_every_patch_is_left_alone(game_dat):
    game_dat.write_bytes(BOTH)

    assert patch_for_launch(game_dat) is False
    assert not backup_path(game_dat).exists() and not restore_pending(game_dat)
    assert restore_after_launch(game_dat) is None
    assert game_dat.read_bytes() == BOTH


def test_patching_again_before_restoring_keeps_the_first_backup(game_dat, monkeypatch):
    monkeypatch.setattr(launch_patch, "LAUNCH_PATCHES", (SKIRMISH,))
    patch_for_launch(game_dat)
    monkeypatch.setattr(launch_patch, "LAUNCH_PATCHES", (SKIRMISH, MODS))

    assert patch_for_launch(game_dat) is True
    assert backup_path(game_dat).read_bytes() == ORIGINAL
    assert restore_after_launch(game_dat) is None
    assert game_dat.read_bytes() == ORIGINAL


def test_a_binary_the_patches_do_not_fit_is_refused_untouched(game_dat):
    game_dat.write_bytes(b"not a game")

    with pytest.raises(LaunchPatchError, match="not the expected build") as raised:
        patch_for_launch(game_dat)
    assert "command-line-skirmish, multi-mod" in str(raised.value)
    assert game_dat.read_bytes() == b"not a game"
    assert sorted(path.name for path in game_dat.parent.iterdir()) == ["game.dat"]
    with pytest.raises(LaunchPatchError, match="Could not read"):
        patch_for_launch(game_dat.with_name("missing.dat"))


def test_a_game_dat_replaced_since_is_not_overwritten(game_dat):
    patch_for_launch(game_dat)
    game_dat.write_bytes(b"MZ another build")

    problem = restore_after_launch(game_dat)

    assert problem is not None and "replaced" in problem
    assert game_dat.read_bytes() == b"MZ another build"
    assert backup_path(game_dat).read_bytes() == ORIGINAL
    assert not restore_pending(game_dat)


def test_a_held_game_dat_stays_pending_until_it_can_be_restored(game_dat, monkeypatch):
    patch_for_launch(game_dat)

    def held(source, target):
        raise PermissionError(13, "The process cannot access the file")

    with monkeypatch.context() as patch:
        patch.setattr(launch_patch.os, "replace", held)
        problem = restore_after_launch(game_dat)

    assert problem is not None and "still running" in problem
    assert restore_pending(game_dat) and game_dat.read_bytes() == BOTH
    assert restore_after_launch(game_dat) is None
    assert game_dat.read_bytes() == ORIGINAL


def test_a_sagepatch_adds_its_patches_to_the_launch_ones(game_dat):
    assert patch_for_launch(game_dat, [LimitPatch(80)]) is True
    assert game_dat.read_bytes() == BOTH + b"+limit80"
    assert restore_after_launch(game_dat) is None
    assert game_dat.read_bytes() == ORIGINAL


def test_a_sagepatch_patch_the_game_carries_is_not_applied_twice(game_dat):
    game_dat.write_bytes(ORIGINAL + b"+limit80")

    assert patch_for_launch(game_dat, [LimitPatch(80)]) is True
    assert game_dat.read_bytes() == ORIGINAL + b"+limit80+skirmish+mods"


def test_a_patch_carried_with_other_parameters_is_refused_untouched(game_dat):
    game_dat.write_bytes(BOTH + b"+limit64")

    with pytest.raises(LaunchPatchError, match="other parameters") as raised:
        patch_for_launch(game_dat, [LimitPatch(80)])
    assert "{'count': 64}" in str(raised.value) and "{'count': 80}" in str(raised.value)
    assert game_dat.read_bytes() == BOTH + b"+limit64"
    assert not backup_path(game_dat).exists()


def test_a_sagepatch_entry_takes_the_place_of_the_launch_patch_it_names(game_dat):
    assert patch_for_launch(game_dat, [SKIRMISH()]) is True
    assert game_dat.read_bytes() == ORIGINAL + b"+mods+skirmish"


def test_a_later_jump_builds_from_the_original_again(game_dat, monkeypatch):
    patch_for_launch(game_dat, [LimitPatch(80)])

    # The .sagepatch no longer lists the limit: it does not stay behind.
    assert patch_for_launch(game_dat) is True
    assert game_dat.read_bytes() == BOTH
    assert backup_path(game_dat).read_bytes() == ORIGINAL

    # Nothing asked for at all: the original is what runs.
    monkeypatch.setattr(launch_patch, "LAUNCH_PATCHES", ())
    assert patch_for_launch(game_dat) is False
    assert game_dat.read_bytes() == ORIGINAL
    assert not restore_pending(game_dat)
    assert sorted(path.name for path in game_dat.parent.iterdir()) == ["game.dat"]


def test_the_sagepatch_manifest_is_rebuilt_with_its_parameters():
    engine = Engine(patches=(AppliedPatch("multi-mod"),))
    assert [type(patch) for patch in sagepatch_patches(engine)] == [MultiModPatch]
    assert sagepatch_patches(Engine()) == []

    with pytest.raises(LaunchPatchError, match="no-such-patch"):
        sagepatch_patches(Engine(patches=(AppliedPatch("no-such-patch"),)))


def test_stopping_before_game_dat_was_written_cleans_up(game_dat):
    patch_for_launch(game_dat)
    game_dat.write_bytes(ORIGINAL)

    assert restore_after_launch(game_dat) is None
    assert sorted(path.name for path in game_dat.parent.iterdir()) == ["game.dat"]
