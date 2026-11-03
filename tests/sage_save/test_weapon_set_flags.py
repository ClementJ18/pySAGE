"""`object_weapon_set_flags`: the saved weapon-set flag count against the names that follow it.

A count above the names is the save that does not load: `production-condition`'s appended flag
was counted by `WeaponSetFlags::xfer` but never named (good campaign 07, 2026-10-31). Data-free:
each body is the tail of an `Object::xfer` prefix built by hand.
"""

from __future__ import annotations

import struct

from sage_save import object_weapon_set_flags
from sage_save.chunks import SaveObject

TEMPLATE = "DwarvenKaserne"


def _name(text: str) -> bytes:
    return bytes([len(text)]) + text.encode("ascii")


def _object(count: int, names: tuple[str, ...]) -> SaveObject:
    flags = b"\x01" + struct.pack("<I", count) + b"".join(_name(n) for n in names)
    weapon_set = b"\x01" + _name(TEMPLATE) + b"\x01" + bytes(16)
    # Something before the flags that holds a stray 1, as a real prefix does.
    body = b"\x1a" + _name(TEMPLATE) + b"\x01\x00\x00\x00" + flags + b"\xff" * 6 + weapon_set
    return SaveObject(1, 247, TEMPLATE, body, 0)


def test_a_consistent_list_is_read_back():
    found = object_weapon_set_flags(_object(1, ("PLAYER_UPGRADE",)))
    assert found is not None
    assert (found.count, found.names, found.consistent) == (1, ("PLAYER_UPGRADE",), True)


def test_a_count_above_its_names_is_reported():
    """The save 24 barracks: two flags counted, one named."""
    found = object_weapon_set_flags(_object(2, ("PLAYER_UPGRADE",)))
    assert found is not None
    assert (found.count, found.names, found.consistent) == (2, ("PLAYER_UPGRADE",), False)


def test_no_flags_at_all():
    found = object_weapon_set_flags(_object(0, ()))
    assert found is not None and found.consistent and found.names == ()


def test_an_object_without_the_layout_is_none():
    assert object_weapon_set_flags(SaveObject(1, 2, TEMPLATE, b"\x1a" + bytes(40), 0)) is None
