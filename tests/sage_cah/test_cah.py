"""Data-free tests for `sage_cah.cah`. Every hero here is built in code - nothing reads a real
.cah fixture - so these check the reader/writer against a known-correct model rather than
against real game data (see test_full_cahs.py for that corpus gate)."""

import struct
import zlib

import pytest

from sage_cah.cah import (
    POWER_SLOT_COUNT,
    CahBling,
    CahError,
    CahPower,
    CustomHero,
    compute_checksum,
    new_guid,
    parse_cah,
    write_cah,
)


def _build_hero(name: str = "Test Hero", guid: str = "ABCDEF0123456789ABCD") -> CustomHero:
    """A full synthetic hero: 10 real power slots + 5 always-empty ones, 12 blings."""
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
        class_index=0,
        sub_class_index=1,
        reserved1=0,
        reserved2=0,
        color1=0x11223344,
        color2=0x55667788,
        color3=0x99AABBCC,
        powers=real_powers + empty_powers,
        blings=blings,
        guid=guid,
        is_system_hero=1,
        checksum=0,
    )


def test_write_parse_round_trips_by_equality_and_is_stable():
    hero = _build_hero()
    hero.checksum = compute_checksum(hero)

    data = write_cah(hero)
    parsed = parse_cah(data)

    assert parsed == hero
    assert write_cah(parsed) == data


def test_compute_checksum_matches_hand_derived_value():
    """Hand-chain the CRC-32 independently of `compute_checksum` (rather than calling it) so a
    regression that reorders or drops a field from the checksum coverage is caught here even
    though it would also break `checksum_valid` on real fixtures."""
    hero = _build_hero(name="A")

    crc = 0
    crc = zlib.crc32(struct.pack("<i", hero.obj_id), crc)
    crc = zlib.crc32(hero.name.encode("utf-8"), crc)
    crc = zlib.crc32(
        struct.pack(
            "<iiii", hero.class_index, hero.sub_class_index, hero.reserved1, hero.reserved2
        ),
        crc,
    )
    crc = zlib.crc32(struct.pack("<III", hero.color1, hero.color2, hero.color3), crc)
    for power in hero.powers:
        crc = zlib.crc32(power.command_button.encode("latin-1"), crc)
        crc = zlib.crc32(struct.pack("<ii", power.exp_level, power.button_index), crc)
    crc = zlib.crc32(struct.pack("<i", len(hero.blings)), crc)
    for bling in hero.blings:
        crc = zlib.crc32(bling.group_name.encode("latin-1"), crc)
        crc = zlib.crc32(struct.pack("<i", bling.bling_index), crc)
    crc = zlib.crc32(bytes([hero.is_system_hero]), crc)

    assert compute_checksum(hero) == crc


def test_refresh_checksum_true_fixes_a_mutated_hero_default_keeps_it_stale():
    hero = _build_hero()
    hero.checksum = compute_checksum(hero)
    assert hero.checksum_valid

    hero.color1 ^= 0xFF  # mutate a checksum-covered field
    assert not hero.checksum_valid

    stale_data = write_cah(hero)  # default: writes hero.checksum verbatim, now stale
    reparsed_stale = parse_cah(stale_data)
    assert reparsed_stale.checksum == hero.checksum
    assert not reparsed_stale.checksum_valid

    fresh_data = write_cah(hero, refresh_checksum=True)
    reparsed_fresh = parse_cah(fresh_data)
    assert reparsed_fresh.checksum_valid
    assert reparsed_fresh.checksum == compute_checksum(hero)


def test_non_ascii_name_round_trips_and_checksums_via_utf8():
    name = "Éowyn 龍"
    hero = _build_hero(name=name)

    data = write_cah(hero, refresh_checksum=True)
    parsed = parse_cah(data)

    assert parsed.name == name
    assert parsed.checksum_valid

    # Independently confirm the name is chained into the CRC as UTF-8 (not the on-disk
    # UTF-16LE) - the one field whose file encoding and checksum encoding differ.
    crc = 0
    crc = zlib.crc32(struct.pack("<i", hero.obj_id), crc)
    crc = zlib.crc32(name.encode("utf-8"), crc)
    crc = zlib.crc32(
        struct.pack(
            "<iiii", hero.class_index, hero.sub_class_index, hero.reserved1, hero.reserved2
        ),
        crc,
    )
    crc = zlib.crc32(struct.pack("<III", hero.color1, hero.color2, hero.color3), crc)
    for power in hero.powers:
        crc = zlib.crc32(power.command_button.encode("latin-1"), crc)
        crc = zlib.crc32(struct.pack("<ii", power.exp_level, power.button_index), crc)
    crc = zlib.crc32(struct.pack("<i", len(hero.blings)), crc)
    for bling in hero.blings:
        crc = zlib.crc32(bling.group_name.encode("latin-1"), crc)
        crc = zlib.crc32(struct.pack("<i", bling.bling_index), crc)
    crc = zlib.crc32(bytes([hero.is_system_hero]), crc)

    assert parsed.checksum == crc


def test_bad_magic_raises():
    with pytest.raises(CahError, match="bad magic"):
        parse_cah(b"NOTMAGIC" + b"\x00" * 20)


def test_truncated_header_raises():
    with pytest.raises(CahError, match="truncated header"):
        parse_cah(b"ALAE2STR" + struct.pack("<i", 1))  # header_unk2/version/obj_id missing


def test_truncated_name_raises():
    header = struct.pack("<iiBi", 1, 0, 8, 19)
    # name_len claims 5 UTF-16 code units (10 bytes) but only 4 bytes follow.
    data = b"ALAE2STR" + header + struct.pack("<B", 5) + b"shrt"

    with pytest.raises(CahError, match="truncated name"):
        parse_cah(data)


@pytest.mark.parametrize("cutoff_fraction", [0.05, 0.25, 0.5, 0.75, 0.95])
def test_truncation_at_various_offsets_always_raises_cah_error(cutoff_fraction):
    hero = _build_hero()
    hero.checksum = compute_checksum(hero)
    data = write_cah(hero)
    cutoff = int(len(data) * cutoff_fraction)

    # Never a bare struct.error escaping - every truncation is wrapped into a CahError.
    with pytest.raises(CahError):
        parse_cah(data[:cutoff])


def test_trailing_bytes_raises():
    hero = _build_hero()
    hero.checksum = compute_checksum(hero)
    data = write_cah(hero) + b"\x00"

    with pytest.raises(CahError, match="trailing bytes"):
        parse_cah(data)


def test_negative_bling_count_raises():
    hero = _build_hero()
    data = write_cah(hero)
    # The count is the 4 bytes right before the first bling's pstr (length byte + name).
    first_bling = bytes([len(hero.blings[0].group_name)]) + hero.blings[0].group_name.encode()
    count_offset = data.index(first_bling) - 4
    corrupted = data[:count_offset] + struct.pack("<i", -1) + data[count_offset + 4 :]

    with pytest.raises(CahError, match="negative bling count"):
        parse_cah(corrupted)


def test_write_wrong_power_slot_count_raises():
    too_few = _build_hero()
    too_few.powers = too_few.powers[: POWER_SLOT_COUNT - 1]
    with pytest.raises(CahError, match="15 power slots"):
        write_cah(too_few)

    too_many = _build_hero()
    too_many.powers = too_many.powers + [CahPower(command_button="", exp_level=-1, button_index=0)]
    with pytest.raises(CahError, match="15 power slots"):
        write_cah(too_many)


def test_write_over_255_byte_pascal_string_raises():
    hero = _build_hero()
    hero.powers[0] = CahPower(command_button="x" * 256, exp_level=0, button_index=1)

    with pytest.raises(CahError, match="255-byte"):
        write_cah(hero)


def test_write_over_255_code_unit_name_raises():
    hero = _build_hero(name="x" * 256)

    with pytest.raises(CahError, match="255-unit"):
        write_cah(hero)


def test_bling_lookup_is_case_insensitive():
    hero = _build_hero()

    found = hero.bling("createahero_group3")
    assert found is not None
    assert found.group_name == "CreateAHero_Group3"
    assert hero.bling("nope") is None


def test_active_powers_filters_empty_slots():
    hero = _build_hero()

    assert len(hero.active_powers) == 10
    assert all(not p.is_empty for p in hero.active_powers)


def test_power_level_and_bling_value_are_one_based():
    power = CahPower(command_button="X", exp_level=3, button_index=1)
    assert power.level == 4

    bling = CahBling(group_name="G", bling_index=6)
    assert bling.value == 7


def test_new_guid_shape():
    guid = new_guid()

    assert len(guid) > 0
    assert guid == guid.upper()
    assert all(c in "0123456789ABCDEF" for c in guid)
