# ROTWK `game.dat` patching

Reverse-engineering + binary-patch work on the ROTWK SAGE engine (build `2.01.2614.37001`). Two
patches ship, both engine-level — they apply to any ROTWK `game.dat` of that build and benefit
every mod on it (Edain among them), not one in particular:

- **`commandset-limit`** raises the `CommandSet` button limit from its stock **33** to any **N** in
  34..127, plus the INI paging rule needed to surface the extra buttons. The shipped build uses
  **N = 64**.
- **`cah-factions`** teaches the nine-name Create-A-Hero faction enum a caller-supplied list of mod
  sides plus an `All` token, so a `SubClass` can name them in `UsableFactions`.

Uses [pyBIG](..)/capstone/pefile and Ghidra headless.

## Status

- **Shipped:** [`engine/game.dat`](engine/game.dat) — the **N = 64** build, runtime-verified.
  A `CommandSet` may define up to 64 entries (no more `"Error parsing field '34'…"`), and
  multi-select is stable.
- **Data limit lifted, display limit not.** The ControlBar still draws **33 buttons at once**;
  reach the rest by paging with `PUSH_VISIBLE_COMMAND_RANGE`
  (see [`docs/push-visible-command-range.md`](docs/push-visible-command-range.md)).
- **On-screen >33 is a separate project.** Widening the drawing loops instead of paging is a dead
  end: those `getCommandButton`-caller loops populate the ControlBar's fixed 33-slot UI arrays, so
  raising their bounds overruns those arrays and crashes. True >33 on-screen display means
  enlarging the ControlBar/APT UI, not this patch.

## CLI

Bring your own `game.dat` (this repo ships the patch recipe, never the copyrighted binary):

```sh
sage-patch list                                  # the registered patches
sage-patch apply commandset-limit --count 64 \
    --in game.dat.backup --out game.dat          # --in is read, never modified
sage-patch verify commandset-limit --count 64 game.dat   # exits non-zero on any mismatch

sage-patch apply cah-factions --sides Rohan,Lothlorien \
    --in game.dat.backup --out game.dat
sage-patch verify cah-factions --sides Rohan,Lothlorien game.dat
```

`verify` re-derives the expected tables, the repointed references and every patched site from the
same parameters and checks them against the file — a structural, disassembler-free pass/fail.

## The patch framework

`apply_patches(game_dat, patches, output=None)` applies an ordered list of `Patch` subclasses to a
copy of the binary and writes the result (in-place if `output` is omitted). Each `Patch` verifies
the bytes it expects before writing, so a list either applies in full or raises without leaving a
half-patched file.

```python
from sage_patch import apply_patches, CahFactionsPatch, CommandSetLimitPatch

apply_patches(
    "game.dat.backup",
    [CommandSetLimitPatch(count=64), CahFactionsPatch(sides=["Rohan", "Lothlorien"])],
    output="game.dat",
)
```

| module | what |
|--------|------|
| [`patcher.py`](patcher.py) | the `Patch` base class (`apply` / `verify` / CLI hooks) + `apply_patches` driver |
| [`cli.py`](cli.py) | the `sage-patch` console script (`apply` / `verify` / `list`) |
| [`registry.py`](registry.py) | the name→`Patch` map the CLI dispatches over; register a patch here to expose it |
| [`utils.py`](utils.py) | PE/byte helpers (`allocate_section`/`find_section` — the pair that makes caves order-independent — plus `apply_byte_patch`, `va_to_offset`, `image_base`, …) operating on an in-memory `bytearray` |
| [`patches/commandset.py`](patches/commandset.py) | `CommandSetLimitPatch` — raise the CommandSet button limit to any N (grow the object + relocate/enlarge the field-parse table) |
| [`patches/cah_factions.py`](patches/cah_factions.py) | `CahFactionsPatch` — add mod sides + an `All` token to the CAH faction enum (superset name table + a `UsableFactions` parser wrapper) |

`CommandSetLimitPatch(count=N)`. **`count` may be 34–127**; every offset, the object size, the
field-parse table and the slot-name strings are derived from it.

`CahFactionsPatch(sides=[...])`. **At most 22 sides**, each matching a `PlayerTemplate`'s `Side`
string exactly; the table, the name strings, the parser wrapper and the resolver's scan bound are
all derived from the list. `All` is always added, and expands to every bit at parse time so no
gate needs patching. See [`docs/cah-faction-limit.md`](docs/cah-faction-limit.md).

### Composing patches

**Any subset of the bundled patches applies in any order**, and a patch is only considered done
when it holds that. `apply_patches` takes a list precisely so they can be stacked:

```sh
sage-patch apply commandset-limit --count 64 --in game.dat.backup --out game.dat
sage-patch apply cah-factions --sides Rohan,Lothlorien --in game.dat --out game.dat
```

Three rules make that work, in decreasing order of how mechanically they hold:

| rule | enforced by | if broken |
|---|---|---|
| Allocate a cave with `allocate_section` (never a fixed RVA) and find it again with `find_section` | the helper — a patch that uses it cannot get this wrong | the section table comes out unsorted when another patch's cave is already present |
| Do not edit bytes another patch edits | not prevented, but `apply_byte_patch` asserts the original bytes first | the second patch to reach the site **raises**; nothing is silently corrupted |
| Do not derive your output from bytes another patch rewrites | nothing — this is the one the framework cannot catch | both orders "succeed" and disagree; declare the dependency in the docstring instead |

Neither bundled patch touches the other's bytes (16 and 30 edit ranges, no intersection) or reads
what the other writes, and both allocate their cave the same way — so `commandset-limit` →
`cah-factions` and the reverse produce binaries that differ only in which cave landed first, both
verifying clean.

Placement being computed rather than hardcoded costs nothing: on an unpatched image
`next_section_rva` returns exactly the `0xAD3000` that `commandset-limit` used to name as a
constant, so a lone `commandset-limit` build is byte-identical to what it produced before.

> **Why 127 and not more.** Five patch sites encode the limit as a *signed 8-bit* immediate
> (`6a NN` push, `83 fa NN` / `83 fb NN` cmp). At 128 the byte `0x80` decodes as `-128`, and one
> of those pushes supplies `rep stosd`'s counter — the constructor would zero ~4 billion dwords.
> Going higher means re-encoding those five as imm32 (3 bytes longer apiece), which no longer
> fits in place and needs relocated code, not a byte patch.

Tests live in [`tests/sage_patch/test_patching.py`](../tests/sage_patch/test_patching.py),
including a byte-identity check that `count=64` still reproduces the shipped `game.dat`.

## Layout

| path | what |
|------|------|
| [`engine/`](engine/) | thin build CLI ([`patch.py`](engine/patch.py), over the framework), verifiers, the clean input `game.dat.backup`, and the shipped `game.dat`. Start at [`engine/README.md`](engine/README.md). |
| [`docs/commandset-button-limit.md`](docs/commandset-button-limit.md) | full RE writeup: how the limit is enforced, the object layout, every patch site, and how to raise it to N. |
| [`docs/push-visible-command-range.md`](docs/push-visible-command-range.md) | the paging mechanism + the `start+count ≤ N` rule (and the exact crash it prevents). |
| [`docs/max-player-count.md`](docs/max-player-count.md) | why a map caps at 20 sides (`MAX_PLAYER_COUNT`), the map census, and a costing of what raising it would take. **Assessed, not attempted.** |
| [`docs/upgrade-mask-limit.md`](docs/upgrade-mask-limit.md) | why the engine caps at 1152 upgrades, and why passing it corrupts neighbouring masks instead of crashing. **Assessed, not attempted.** |
| [`docs/cah-faction-limit.md`](docs/cah-faction-limit.md) | full RE writeup for `cah-factions`: the nine-side enum, the three gates that read its mask, every repointed site, and the two cheaper-but-cruder alternatives that were rejected. |
| [`docs/runtime-re-workflow.md`](docs/runtime-re-workflow.md) | the static+dynamic RE method (Ghidra, Cheat Engine, INI field tables) used to recover these offsets, with the verified `Player`/`ThingTemplate` layouts. |
| [`docs/module-reference.md`](docs/module-reference.md) | every engine module, its INI fields and their compiled-in defaults - 330 modules, 2658 fields, 97% of them typed. Generated by [`scripts/module_defaults.py`](scripts/module_defaults.py); `module-reference.json` is the same data machine-readable. |
| [`docs/ini-types.json`](docs/ini-types.json) | everything a field's type alone cannot say: the 200 INI block types the loader dispatches on (`Object`, `Weapon`, `Locomotor`, `GameData`, ...) with 4247 fields of their own, the members behind every enum and flag type, the lookup lists, and the keywords of every nested sub-block. Same generator. |
| [`scripts/build_wiki.py`](scripts/build_wiki.py) | renders those files into a browsable static site under `build/wiki/` - a page per module and per block type, plus the type and enum pages. Field tables take values, check them against the field's type and write them into a copyable INI block, and `check.html` validates a whole pasted block the same way. Fields the engine parses as plain strings are annotated with what `sage_ini` says they name (`&rarr; Upgrade`, `&rarr; Object`), the one thing on the site that is modelled rather than read from the binary. |
| [`ghidra_scripts/`](ghidra_scripts/) | headless Ghidra analysis scripts + `run_ghidra.bat` runner (needs JDK 21). |
| [`scripts/`](scripts/) | standalone capstone/pefile analysis helpers used during RE. |

## Module reference

```sh
python scripts/module_defaults.py game.dat \
    --json docs/module-reference.json \
    --markdown docs/module-reference.md \
    --enums docs/ini-types.json         # needs your own game.dat
python scripts/build_wiki.py            # -> build/wiki/index.html, no game.dat needed
```

A field's type is its parse function, and those are identified from what the code does:
the constant a real is scaled by (`pi/180` is degrees in, radians out), the range the
parser complains about (`expected > 0`), the name array a token is resolved against, the
field table a nested block hands to the INI reader.

Block types are found the same way. The loader dispatches a block on `{keyword, parser}`
pairs in the data sections; a candidate is kept only when its parser really does hand a
field table to the INI reader, which is what makes it a block type rather than a string
that happens to sit next to a function pointer. Where the parser also allocates and
constructs its instance, the same constant tracking recovers that block's defaults.

The site is a build artefact and is not committed; the JSON it reads is.

## Reproduce the build

```sh
cd engine
OUT=game.dat python patch.py   # clean game.dat.backup -> N=64 game.dat  (COUNT=N for another limit)
python verify.py && python finalcheck.py
```

## Key addresses (VA, ImageBase 0x400000)

field-parse table `0xc4f3d8` · `parseCommandButton` `0x80c9e1` · ctor `0x80c949` ·
alloc `0x720298` · `getCommandButton` `0x80c837` · new `.cmdext` table `0xed3000` (on a clean
image; the RVA is computed, so it moves up if another patch's cave is already there) ·
ControlBar singleton `0xde7744` (fixed 33-slot arrays at `+0xdc` / `+0x160`) ·
paging-crash site `0x75d244`.
