# sage_cah

A lossless reader and writer for `.cah`, the BFME2/RotWK Create-a-Hero file: one custom hero's
identity, class, colours, ten purchasable powers, twelve "bling" customization and attribute
entries, a GUID, and a CRC-32 checksum the game validates before loading.

The field layout, enums and checksum come from withmorten's reversed `cah_file` (MIT-licensed C++,
`cah_file.h`/`cah_file.cpp`), and were checked byte-exact (parse, round trip, checksum) against all
15 example heroes shipped in both games' `Data1.big`.

## Binary format

All integers little-endian. A `pstr` is a uint8 length followed by that many latin-1 bytes, no NUL.
The hero name is the exception: its length counts UTF-16 code units.

```
8   bytes  magic "ALAE2STR"
i32        header_unk1        # 1 in every fixture; meaning unknown
i32        header_unk2        # 0 in every fixture; meaning unknown
u8         version            # 8 in every fixture; 1-8 seen historically
i32        obj_id             # 19 / 55 / 57 in fixtures; semantics unclear
u8         name_len           # count of UTF-16 code units, not bytes
2*name_len bytes  name, UTF-16LE, no terminator
i32        class_index        # see the display names below
i32        sub_class_index
i32        reserved1          # 0 in fixtures
i32        reserved2          # 0 in fixtures
u32 x3     color1, color2, color3   # primary / secondary / tertiary palette indices

15 x power slot (slots 0-9 are the buyable powers; 10-14 are always empty):
    pstr       command_button     # the ini CommandButton this slot triggers
    i32        exp_level          # in-game level minus 1
    i32        button_index       # 1-5, or 8 for the "no power" dummy

i32        bling_count        # 12 in every fixture
bling_count x:
    pstr       group_name         # e.g. "CreateAHero_Weapon", "CreateAHero_ArmorAttribute"
    i32        bling_index        # in-game value minus 1, for the 5 *Attribute groups

pstr       guid_str           # see GUID format below
u8         is_system_hero     # 1 on every shipped hero
u32        checksum           # CRC-32, coverage below
```

Nothing follows the checksum.

## Checksum

A standard zlib CRC-32, chained from 0 over, in order: `obj_id`; the name encoded as **UTF-8**;
`class_index`, `sub_class_index`, `reserved1`, `reserved2`; the three colours; for each of the
**15** power slots, its command-button bytes, `exp_level` and `button_index`; `bling_count`; for
each bling, its group-name bytes and `bling_index`; and the `is_system_hero` byte. The magic, the
header ints, `version`, the length prefixes and the GUID are not covered.

`write_cah` keeps the stored checksum by default, for a byte-exact round trip; pass
`refresh_checksum=True` to write `compute_checksum(hero)`, as the game itself does.

## GUID format

A Windows `GUID` written as seven concatenated, unpadded uppercase hex fields: `Data1`, `Data2`,
`Data3`, then the first four bytes of `Data4` - hence the varying lengths of shipped file names
(`myhero_<hex>.cah`). `new_guid()` makes one from a fresh UUID.

## Class and sub-class display names

From `cah_file.h` (RotWK). These are UI labels, not part of the format: the same hero has different
indices in BFME2 and RotWK, and mods rename and reorder freely. An unknown index prints as a number.

| index | class | sub-classes (index: name) |
| --- | --- | --- |
| 0 | Men of the West | 0: Captain of Gondor, 1: Shield Maiden |
| 1 | Archer | 0: Male Elven Archer, 1: Female Elven Archer |
| 2 | Wizard | 0: Wanderer, 1: Avatar, 2: Hermit |
| 3 | Dwarf | 0: Taskmaster, 1: Sage |
| 4 | Servant of Sauron | 0: Orc Raider, 1: Uruk |
| 5 | Corrupted Man | 0: Easterling, 1: Haradrim |
| 6 | Olog-hai | 0: Great Troll, 1: Snow Troll, 2: Hill Troll |

## Model and example

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

`CustomHero` also offers `active_powers`, `bling(group_name)` (case-insensitive) and
`checksum_valid`.

```python
from sage_cah import new_guid, parse_cah_from_path, write_cah_to_path

hero = parse_cah_from_path("myhero_47c6206b5c124324a54a2da3.cah")
print(hero.name, hero.class_index, [p.command_button for p in hero.active_powers])

hero.guid = new_guid()
write_cah_to_path(hero, "myhero_edited.cah", refresh_checksum=True)
```

## Command-line tool

```
sage-cah info <cah>                        # identity / class / powers / bling / checksum
sage-cah json <cah> [--out] [--compact]    # the parsed structure as JSON
sage-cah check <path>                      # file or directory: round trip + checksum
sage-cah fix <cah> -o OUT [--new-guid]     # rewrite with a refreshed checksum
```

## Desktop editor

```sh
pip install "pysage-tools[cah-ui]"   # from a checkout: pip install -e ".[cah-ui]"
sage-cah-ui                          # or: python -m sage_cah.ui
```

Edits one `.cah`: name, class, object id, colours, GUID (**New GUID** for a copied hero), powers and
bling. Saving writes a fresh checksum; fields the editor does not show are written back unchanged,
so an untouched hero saves byte for byte. Loading a game (the **GAME DATA** card, or **Find
installed game**) adds completion from the game's own data: class names in the file's index order,
the powers each class can buy with their unlock levels, and what each bling index picks.

## Reading a game's Create-a-Hero data

`sage_cah.gamedata` is the Qt-free half of that:

```python
from sage_cah.gamedata import scan_ini_root

data = scan_ini_root("C:/Games/rotwk")           # a folder holding data/ini, or an ini root
data.classes[3].name                             # "Diener der Dunkelheit"
[p.command_button for p in data.powers_for(3)]   # what class 3 may buy
data.bling_choices("CreateAHero_Helmet", 3, 0)   # what a helmet index counts into
```

`load_cah_game_data([("big", ".../ini.big"), ...])` does the same over ordered folders and `.big`
archives. Only files declaring a `CommandButton` or `CreateAHeroSystem` are parsed, so a full Edain
install scans in seconds. `bling_choices` applies the two indexing rules: an attribute group's index
counts into that group's options (the same for every class), and an appearance group's counts into
the sub-class's `BlingUpgrades` for that group.
