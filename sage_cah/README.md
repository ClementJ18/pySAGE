# sage_cah

A lossless reader/writer for `.cah`, the BFME2/RotWK Create-a-Hero file - one custom hero's
identity, class, colors, the ten purchasable powers, the twelve "bling" customization/attribute
entries, a GUID, and a CRC-32 checksum the game validates before loading.

Credit for the field layout, enums, and checksum goes to withmorten's reversed `cah_file`
(MIT-licensed C++, `cah_file.h`/`cah_file.cpp`) - the tables below were checked byte-exact
(parse, round-trip, and CRC-32 recomputation) against all 15 shipped example heroes from both
games' `Data1.big` (7 BFME2, 8 RotWK).

## Binary format

All integers little-endian. A `pstr` is a uint8 length prefix followed by that many latin-1
bytes - no NUL terminator; this lets arbitrary bytes round-trip even though every known fixture
is plain ASCII. The hero name is the one field that isn't a `pstr`: its length prefix counts
UTF-16 code units, not bytes.

```
8   bytes  magic "ALAE2STR"
i32        header_unk1        # 1 in every fixture; meaning unknown
i32        header_unk2        # 0 in every fixture; meaning unknown
u8         version             # 8 in every fixture; 1-8 seen historically
i32        obj_id              # 19 / 55 / 57 in fixtures; semantics unclear
u8         name_len            # count of UTF-16 code units, not bytes
2*name_len bytes  name, UTF-16LE, no terminator
i32        class_index         # see display maps below
i32        sub_class_index
i32        reserved1           # 0 in fixtures
i32        reserved2           # 0 in fixtures
u32 x3     color1, color2, color3   # primary / secondary / tertiary palette indices

15 x power slot (slots 0-9 are the real, buyable powers; 10-14 are always empty):
    pstr       command_button      # the ini CommandButton name this slot triggers
    i32        exp_level           # in-game level minus 1
    i32        button_index        # 1-5, or 8 for the "no power" dummy

i32        bling_count         # 12 in every fixture
bling_count x:
    pstr       group_name          # e.g. "CreateAHero_Weapon", "CreateAHero_ArmorAttribute"
    i32        bling_index         # in-game value minus 1, for the 5 *Attribute stat groups

pstr       guid_str            # see GUID format below
u8         is_system_hero      # 1 on every shipped hero
u32        checksum            # CRC-32, coverage below
```

No fixture has trailing bytes after the checksum - a `.cah` is exactly this one fixed-size
(modulo strings) struct, with no chunk-skip story the way `sage_w3d` needs for unknown chunks.

## Checksum

A standard CRC-32 (the reference's table is the stock zlib polynomial table), chained with
`zlib.crc32(chunk, crc)` starting from 0, over exactly, in order:

1. `obj_id` (4 bytes)
2. the name, encoded **UTF-8** (not the on-disk UTF-16), no terminator
3. `class_index`, `sub_class_index`, `reserved1`, `reserved2` (4 bytes each)
4. `color1`, `color2`, `color3` (4 bytes each)
5. for each of the **15** power slots: the command-button bytes, then `exp_level`, then
   `button_index`
6. `bling_count`
7. for each bling: the group-name bytes, then `bling_index`
8. the single `is_system_hero` byte

Not covered: the magic, the two header ints, `version`, every length prefix, and `guid_str`.
`write_cah` preserves the stored checksum verbatim by default (a byte-exact round trip even for
a hand-edited file whose checksum has gone stale); pass `refresh_checksum=True` to write
`compute_checksum(hero)` instead, matching what the game's own `write()` always does.

## GUID format

`update_guid()` in the C++ reference formats a Windows `GUID` (`Data1` u32, `Data2` u16, `Data3`
u16, `Data4` byte[8]) as 7 concatenated **unpadded** uppercase `%X` fields: `Data1`, `Data2`,
`Data3`, then the first 4 bytes of `Data4` - which is why the shipped filenames
(`myhero_<hex>.cah`) have varying hex lengths. `new_guid()` reproduces this from a fresh v4
UUID.

## Class / sub-class display names

From `cah_file.h` (RotWK-era). The same hero carries a *different* index in BFME2 vs RotWK
(Thrugg is class 4 / sub-class 2 in bfme2, 4 / 1 in rotwk) - these maps are display labels for
a UI, not an invariant of the format, and an index outside a map should just print the bare
number rather than raising.

| index | class | sub-classes (index: name) |
| --- | --- | --- |
| 0 | Men of the West | 0: Captain of Gondor, 1: Shield Maiden |
| 1 | Archer | 0: Male Elven Archer, 1: Female Elven Archer |
| 2 | Wizard | 0: Wanderer, 1: Avatar, 2: Hermit |
| 3 | Dwarf | 0: Taskmaster, 1: Sage |
| 4 | Servant of Sauron | 0: Orc Raider, 1: Uruk |
| 5 | Corrupted Man | 0: Easterling, 1: Haradrim |
| 6 | Olog-hai | 0: Great Troll, 1: Snow Troll, 2: Hill Troll |

## Model

```python
from sage_cah import CahBling, CahPower, CustomHero

CahPower(command_button: str, exp_level: int, button_index: int)     # .level, .is_empty
CahBling(group_name: str, bling_index: int)                          # .value
CustomHero(
    header_unk1: int, header_unk2: int, version: int, obj_id: int, name: str,
    class_index: int, sub_class_index: int, reserved1: int, reserved2: int,
    color1: int, color2: int, color3: int,
    powers: list[CahPower], blings: list[CahBling],
    guid: str, is_system_hero: int, checksum: int,
)
```

`CustomHero` adds a few read-only conveniences: `active_powers` (the non-empty power slots),
`bling(group_name)` (case-insensitive lookup), and `checksum_valid` (compares `checksum` against
`compute_checksum(self)`).

## Example

```python
from sage_cah import compute_checksum, new_guid, parse_cah_from_path, write_cah_to_path

hero = parse_cah_from_path("myhero_47c6206b5c124324a54a2da3.cah")
print(hero.name, hero.class_index, hero.sub_class_index)
print([p.command_button for p in hero.active_powers])
print(hero.checksum_valid)

hero.guid = new_guid()
write_cah_to_path(hero, "myhero_edited.cah", refresh_checksum=True)
```

## Command-line tool

```
sage-cah info <cah>                        # identity / class / powers / bling / checksum
sage-cah json <cah> [--out] [--compact]    # the parsed structure as JSON
sage-cah check <path>                      # file or directory: round-trip + checksum check
sage-cah fix <cah> -o OUT [--new-guid]     # rewrite with a refreshed checksum
```
