# ROTWK `game.dat` patching — raise the `CommandSet` button limit

Reverse-engineering + binary-patch work that raises the ROTWK `CommandSet` button limit
from its stock **33** to any **N** in 34..127 (engine build `2.01.2614.37001`), plus the INI paging
rule needed to surface the extra buttons. The patch is engine-level — it applies to any ROTWK
`game.dat` of that build and benefits every mod on it (Edain among them), not one in particular.
Uses [pyBIG](..)/capstone/pefile and Ghidra headless. The shipped build uses **N = 64**.

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
```

`verify` re-derives the expected table, the repointed references and every patched site for the
given N and checks them against the file — a structural, disassembler-free pass/fail.

## The patch framework

`apply_patches(game_dat, patches, output=None)` applies an ordered list of `Patch` subclasses to a
copy of the binary and writes the result (in-place if `output` is omitted). Each `Patch` verifies
the bytes it expects before writing, so a list either applies in full or raises without leaving a
half-patched file.

```python
from sage_patch import apply_patches, CommandSetLimitPatch

apply_patches("game.dat.backup", [CommandSetLimitPatch(count=64)], output="game.dat")
```

| module | what |
|--------|------|
| [`patcher.py`](patcher.py) | the `Patch` base class (`apply` / `verify` / CLI hooks) + `apply_patches` driver |
| [`cli.py`](cli.py) | the `sage-patch` console script (`apply` / `verify` / `list`) |
| [`registry.py`](registry.py) | the name→`Patch` map the CLI dispatches over; register a patch here to expose it |
| [`utils.py`](utils.py) | PE/byte helpers (`append_section`, `apply_byte_patch`, `va_to_offset`, `image_base`, …) operating on an in-memory `bytearray` |
| [`patches/commandset.py`](patches/commandset.py) | `CommandSetLimitPatch` — raise the CommandSet button limit to any N (grow the object + relocate/enlarge the field-parse table) |

`CommandSetLimitPatch(count=N)`. **`count` may be 34–127**; every offset, the object size, the
field-parse table and the slot-name strings are derived from it.

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
| [`ghidra_scripts/`](ghidra_scripts/) | headless Ghidra analysis scripts + `run_ghidra.bat` runner (needs JDK 21). |
| [`scripts/`](scripts/) | standalone capstone/pefile analysis helpers used during RE. |

## Reproduce the build

```sh
cd engine
OUT=game.dat python patch.py   # clean game.dat.backup -> N=64 game.dat  (COUNT=N for another limit)
python verify.py && python finalcheck.py
```

## Key addresses (VA, ImageBase 0x400000)

field-parse table `0xc4f3d8` · `parseCommandButton` `0x80c9e1` · ctor `0x80c949` ·
alloc `0x720298` · `getCommandButton` `0x80c837` · new `.cmdext` table `0xed3000` ·
ControlBar singleton `0xde7744` (fixed 33-slot arrays at `+0xdc` / `+0x160`) ·
paging-crash site `0x75d244`.
