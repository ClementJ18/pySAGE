"""Binary reader/writer for the BFME2/RotWK Create-a-Hero `.cah` file: one custom hero's
identity, class, colors, the ten purchasable powers (plus five always-empty slots), the twelve
"bling" customization/attribute entries, a GUID, and a CRC-32 checksum the game validates
before loading. See README.md for the full on-disk layout and the checksum coverage.

Every integer is little-endian. Pascal strings (power command buttons, bling group names, the
GUID) are a uint8 length prefix followed by that many latin-1 bytes (no NUL terminator) - this
lets arbitrary bytes round-trip even though every known fixture is plain ASCII. The hero name
is the one exception: a uint8 length prefix counting UTF-16 code units, followed by that many
UTF-16LE code units (2 bytes each, no terminator)."""

import io
import struct
import uuid
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from sage_utils.stream import BinaryStream

__all__ = [
    "BLING_STAT_GROUPS",
    "CLASS_NAMES",
    "POWER_SLOT_COUNT",
    "SUB_CLASS_NAMES",
    "CahBling",
    "CahError",
    "CahPower",
    "CustomHero",
    "compute_checksum",
    "new_guid",
    "parse_cah",
    "parse_cah_from_path",
    "write_cah",
    "write_cah_to_path",
]

_MAGIC = b"ALAE2STR"

# Real power slots (buyable at levels 1-10); slots 10-14 exist in every fixture but are always
# the empty placeholder ("" command_button, exp_level -1, button_index 0) - the game reserves
# them but the UI/editor tooling never fills them in.
POWER_SLOT_COUNT = 15

# Display-only maps for `class_index`/`sub_class_index` (from withmorten's cah_file.h, a
# RotWK-era reversal). The same hero carries a different index in BFME2 vs RotWK (Thrugg is
# 4/2 in bfme2, 4/1 in rotwk), so these are labels for a UI, not an invariant of the format - an
# index outside the map is not an error, just print the bare number instead.
CLASS_NAMES: dict[int, str] = {
    0: "Men of the West",
    1: "Archer",
    2: "Wizard",
    3: "Dwarf",
    4: "Servant of Sauron",
    5: "Corrupted Man",
    6: "Olog-hai",
}

SUB_CLASS_NAMES: dict[int, dict[int, str]] = {
    0: {0: "Captain of Gondor", 1: "Shield Maiden"},
    1: {0: "Male Elven Archer", 1: "Female Elven Archer"},
    2: {0: "Wanderer", 1: "Avatar", 2: "Hermit"},
    3: {0: "Taskmaster", 1: "Sage"},
    4: {0: "Orc Raider", 1: "Uruk"},
    5: {0: "Easterling", 1: "Haradrim"},
    6: {0: "Great Troll", 1: "Snow Troll", 2: "Hill Troll"},
}

# The five bling groups whose bling_index is a stat level (1-based in-game, stored as -1) rather
# than a visual customization variant index.
BLING_STAT_GROUPS: frozenset[str] = frozenset(
    {
        "CreateAHero_ArmorAttribute",
        "CreateAHero_DamageMultAttribute",
        "CreateAHero_VisionAttribute",
        "CreateAHero_AutoHealAttribute",
        "CreateAHero_HealthMultAttribute",
    }
)


class CahError(Exception):
    """Raised for malformed .cah input (bad magic, truncated data) or a model that cannot be
    written back out (a string over the 255-unit pastr/name limit, other than exactly 15 power
    slots)."""


@dataclass
class CahPower:
    """One power slot. `command_button` is the ini `CommandButton` name this slot triggers, or
    `""` for one of the five always-unused slots (10-14)."""

    command_button: str
    exp_level: int
    button_index: int

    @property
    def level(self) -> int:
        """The in-game power level (`exp_level` is stored as this minus one)."""
        return self.exp_level + 1

    @property
    def is_empty(self) -> bool:
        """True for an unused power slot (no command button assigned)."""
        return self.command_button == ""


@dataclass
class CahBling:
    """One "bling" entry: a customization group (visual - weapon, armor pieces, ...) or an
    attribute group (a stat level) named by `group_name` (see `BLING_STAT_GROUPS`)."""

    group_name: str
    bling_index: int

    @property
    def value(self) -> int:
        """The in-game value shown for this bling (`bling_index` is stored as this minus one)."""
        return self.bling_index + 1


@dataclass
class CustomHero:
    """The full parsed contents of a .cah file, fields in on-disk order. `checksum` is the
    value as read (0 for a hero built fresh in code until `write_cah(..., refresh_checksum=True)`
    fills it in); `checksum_valid` compares it against `compute_checksum`."""

    header_unk1: int
    header_unk2: int
    version: int
    obj_id: int
    name: str
    class_index: int
    sub_class_index: int
    reserved1: int
    reserved2: int
    color1: int
    color2: int
    color3: int
    powers: list[CahPower] = field(default_factory=list)
    blings: list[CahBling] = field(default_factory=list)
    guid: str = ""
    is_system_hero: int = 0
    checksum: int = 0

    @property
    def active_powers(self) -> list[CahPower]:
        """The non-empty power slots, in slot order."""
        return [p for p in self.powers if not p.is_empty]

    def bling(self, group_name: str) -> CahBling | None:
        """The `CahBling` named `group_name`, matched case-insensitively, or `None`."""
        needle = group_name.lower()
        for b in self.blings:
            if b.group_name.lower() == needle:
                return b
        return None

    @property
    def checksum_valid(self) -> bool:
        """True when `checksum` matches what `compute_checksum` derives from the current
        field values."""
        return self.checksum == compute_checksum(self)


def compute_checksum(hero: CustomHero) -> int:
    """The CRC-32 the game checks before loading a hero: a `zlib.crc32` chain starting from 0
    over, in order: `obj_id`; the name as UTF-8 (not the on-disk UTF-16); `class_index`,
    `sub_class_index`, `reserved1`, `reserved2`, `color1..3`; each of the 15 power slots'
    command-button bytes + `exp_level` + `button_index`; the bling count; each bling's
    group-name bytes + `bling_index`; and finally the single `is_system_hero` byte. Not
    covered: the magic, the two header ints, `version`, any length prefix, and the GUID."""
    crc = 0
    crc = zlib.crc32(struct.pack("<i", hero.obj_id), crc)
    crc = zlib.crc32(hero.name.encode("utf-8", errors="surrogatepass"), crc)
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
    return crc


def new_guid() -> str:
    """A fresh GUID in the game's own on-disk format: a Windows `GUID` (`Data1` u32, `Data2`
    u16, `Data3` u16, `Data4` byte[8]) printed as 7 concatenated **unpadded** uppercase hex
    fields - `Data1`, `Data2`, `Data3`, then the first 4 bytes of `Data4` - matching
    `update_guid()` in the C++ reference. A standard v4 UUID's 16 bytes are laid out in the
    same big-endian field order as a Windows GUID's, so `uuid.uuid4().bytes` slices directly
    onto `Data1..Data4`."""
    raw = uuid.uuid4().bytes
    data1 = int.from_bytes(raw[0:4], "big")
    data2 = int.from_bytes(raw[4:6], "big")
    data3 = int.from_bytes(raw[6:8], "big")
    data4 = raw[8:16]
    return f"{data1:X}{data2:X}{data3:X}{data4[0]:X}{data4[1]:X}{data4[2]:X}{data4[3]:X}"


def _read_pstr(stream: BinaryStream) -> str:
    length = stream.readUChar()
    raw = stream.readBytes(length)
    if len(raw) != length:
        raise struct.error(f"pstr wants {length} bytes, got {len(raw)}")
    return raw.decode("latin-1")


def _write_pstr(stream: BinaryStream, value: str) -> None:
    raw = value.encode("latin-1")
    if len(raw) > 0xFF:
        raise CahError(f"string {value!r} is {len(raw)} bytes, over the 255-byte pstr limit")
    stream.writeUChar(len(raw))
    stream.writeBytes(raw)


def _read_name(stream: BinaryStream) -> str:
    length = stream.readUChar()
    raw = stream.readBytes(length * 2)
    if len(raw) != length * 2:
        raise struct.error(f"name wants {length * 2} bytes, got {len(raw)}")
    return raw.decode("utf-16-le", errors="surrogatepass")


def _write_name(stream: BinaryStream, value: str) -> None:
    raw = value.encode("utf-16-le", errors="surrogatepass")
    length = len(raw) // 2
    if length > 0xFF:
        raise CahError(
            f"name {value!r} is {length} UTF-16 code units, over the 255-unit name_len limit"
        )
    stream.writeUChar(length)
    stream.writeBytes(raw)


def _parse(stream: BinaryStream) -> CustomHero:
    magic = stream.readBytes(8)
    if magic != _MAGIC:
        raise CahError(f"bad magic {magic!r} at offset 0, expected {_MAGIC!r}")

    try:
        header_unk1 = stream.readInt32()
        header_unk2 = stream.readInt32()
        version = stream.readUChar()
        obj_id = stream.readInt32()
    except struct.error as exc:
        raise CahError(f"truncated header at offset {stream.tell()}: {exc}") from exc

    try:
        name = _read_name(stream)
    except struct.error as exc:
        raise CahError(f"truncated name at offset {stream.tell()}: {exc}") from exc

    try:
        class_index = stream.readInt32()
        sub_class_index = stream.readInt32()
        reserved1 = stream.readInt32()
        reserved2 = stream.readInt32()
        color1 = stream.readUInt32()
        color2 = stream.readUInt32()
        color3 = stream.readUInt32()
    except struct.error as exc:
        raise CahError(f"truncated class/color fields at offset {stream.tell()}: {exc}") from exc

    powers: list[CahPower] = []
    for i in range(POWER_SLOT_COUNT):
        offset = stream.tell()
        try:
            command_button = _read_pstr(stream)
            exp_level = stream.readInt32()
            button_index = stream.readInt32()
        except struct.error as exc:
            raise CahError(f"truncated power slot {i} at offset {offset}: {exc}") from exc
        powers.append(
            CahPower(command_button=command_button, exp_level=exp_level, button_index=button_index)
        )

    try:
        bling_count = stream.readInt32()
    except struct.error as exc:
        raise CahError(f"truncated bling count at offset {stream.tell()}: {exc}") from exc
    if bling_count < 0:
        raise CahError(f"negative bling count {bling_count}")

    blings: list[CahBling] = []
    for i in range(bling_count):
        offset = stream.tell()
        try:
            group_name = _read_pstr(stream)
            bling_index = stream.readInt32()
        except struct.error as exc:
            raise CahError(f"truncated bling {i} at offset {offset}: {exc}") from exc
        blings.append(CahBling(group_name=group_name, bling_index=bling_index))

    try:
        guid = _read_pstr(stream)
        is_system_hero = stream.readUChar()
        checksum = stream.readUInt32()
    except struct.error as exc:
        raise CahError(f"truncated footer at offset {stream.tell()}: {exc}") from exc

    return CustomHero(
        header_unk1=header_unk1,
        header_unk2=header_unk2,
        version=version,
        obj_id=obj_id,
        name=name,
        class_index=class_index,
        sub_class_index=sub_class_index,
        reserved1=reserved1,
        reserved2=reserved2,
        color1=color1,
        color2=color2,
        color3=color3,
        powers=powers,
        blings=blings,
        guid=guid,
        is_system_hero=is_system_hero,
        checksum=checksum,
    )


def parse_cah(data: bytes) -> CustomHero:
    """Parse the bytes of a .cah file into a `CustomHero`."""
    stream = BinaryStream(io.BytesIO(data))
    hero = _parse(stream)
    # This format is one fixed struct - no chunk skip/recovery story like sage_w3d's - so
    # leftover bytes mean the layout was misread, not a benign trailer to preserve.
    if stream.tell() != len(data):
        raise CahError(f"{len(data) - stream.tell()} trailing bytes after the checksum")
    return hero


def parse_cah_from_path(path: str | Path) -> CustomHero:
    """Parse the .cah file at `path` into a `CustomHero`."""
    with open(path, "rb") as f:
        return parse_cah(f.read())


def write_cah(hero: CustomHero, *, refresh_checksum: bool = False) -> bytes:
    """Serialize `hero` back to .cah bytes. By default this is the byte-exact inverse of
    `parse_cah`: the stored `hero.checksum` is written verbatim, so a hero parsed and written
    back unmodified reproduces the input exactly, stale checksum and all. Pass
    `refresh_checksum=True` (what an editing workflow wants, and what the C++ `write()` always
    does) to write `compute_checksum(hero)` instead."""
    if len(hero.powers) != POWER_SLOT_COUNT:
        raise CahError(f"expected exactly {POWER_SLOT_COUNT} power slots, got {len(hero.powers)}")

    stream = BinaryStream(io.BytesIO())
    stream.writeBytes(_MAGIC)
    stream.writeInt32(hero.header_unk1)
    stream.writeInt32(hero.header_unk2)
    stream.writeUChar(hero.version)
    stream.writeInt32(hero.obj_id)
    _write_name(stream, hero.name)
    stream.writeInt32(hero.class_index)
    stream.writeInt32(hero.sub_class_index)
    stream.writeInt32(hero.reserved1)
    stream.writeInt32(hero.reserved2)
    stream.writeUInt32(hero.color1)
    stream.writeUInt32(hero.color2)
    stream.writeUInt32(hero.color3)

    for power in hero.powers:
        _write_pstr(stream, power.command_button)
        stream.writeInt32(power.exp_level)
        stream.writeInt32(power.button_index)

    stream.writeInt32(len(hero.blings))
    for bling in hero.blings:
        _write_pstr(stream, bling.group_name)
        stream.writeInt32(bling.bling_index)

    _write_pstr(stream, hero.guid)
    stream.writeUChar(hero.is_system_hero)
    stream.writeUInt32(compute_checksum(hero) if refresh_checksum else hero.checksum)

    return stream.getvalue()


def write_cah_to_path(
    hero: CustomHero, path: str | Path, *, refresh_checksum: bool = False
) -> None:
    """Serialize `hero` and write it to `path`. See `write_cah` for `refresh_checksum`."""
    data = write_cah(hero, refresh_checksum=refresh_checksum)
    with open(path, "wb") as f:
        f.write(data)
