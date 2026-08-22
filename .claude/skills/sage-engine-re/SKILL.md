---
name: sage-engine-re
description: >-
  Explore the ROTWK SAGE engine binary (`game.dat`) - find where a value, keyword, table, global
  or behaviour lives, read the code around it, and check what this repo already knows about that
  address. Use when asked how the engine does something, where a field / function / struct offset
  lives, to reverse-engineer or hunt an address, before writing or debugging a `sage_patch` patch,
  or when interpreting a running game read through `sage_live`. Backed by `sage_patch` (78 RE
  write-ups, 400+ named addresses) and this skill's `explore.py`.
---

# Exploring the ROTWK engine

The target is one build: **RotWK `game.dat` 2.01.2614.37001**, ImageBase `0x400000`, no ASLR - so
a virtual address here is also where the byte sits in a running process, and every address in the
docs is directly usable at runtime. Addresses are VAs everywhere; `explore.py known` prints the
file offset when a byte edit needs one.

**The repo's `game.dat` is not stock.** It carries `cah-factions` (its `.cahfac` section).
Everything below reads fine against it, but never quote it as evidence of *stock* bytes at a site a
patch rewrote - check with `python -m sage_patch.cli sagepatch game.dat`, and read a clean
`game.dat.backup` from an install with `--game` when the distinction matters.

## 1. Ask the repo before you ask the binary

Re-deriving something already written down is the most common way to burn a session. Four places,
in the order to try them:

| where | what it holds | how to ask |
|---|---|---|
| `sage_patch/addresses.py` | 400+ named addresses of this build - globals, hooked functions, the labels inside them | `explore.py known 0x9cdf23` (by VA) or `explore.py known PRODUCTION` (by name) |
| `sage_patch/docs/*.md` | 78 write-ups, each one a finding with its evidence | `grep -rin '9cdf23\|CommandSet' sage_patch/docs` |
| `sage_patch/patches/*.py` | the patches themselves - every hook site, with the stock bytes asserted in code | `grep -rn '0x5ef716' sage_patch/patches` |
| `sage_patch/docs/*.json` | the engine's own INI surface, already recovered: name tables, enums, block/module field tables with offsets and defaults | `explore.py enum KindOf`, `explore.py block AutoDepositUpdate` |

Start reading with [`sage_patch/README.md`](../../../sage_patch/README.md) (what each patch does and
the framework), [`docs/engine-globals.md`](../../../sage_patch/docs/engine-globals.md) (88 named
subsystem singletons), [`docs/live-object-model.md`](../../../sage_patch/docs/live-object-model.md)
(the object table and `Object` layout) and
[`docs/runtime-re-workflow.md`](../../../sage_patch/docs/runtime-re-workflow.md) (the Ghidra +
Cheat Engine loop, and recovered `Player` / `ThingTemplate` offsets).

## 2. The tool

Run from the repo root; it needs `capstone` (`pip install -e ".[patch]"`).

```sh
python .claude/skills/sage-engine-re/explore.py <command> [--game path/to/game.dat]
```

| command | answers |
|---|---|
| `known <VA \| NAME>` | do we already know this address? (always the first move) |
| `str <regex> [--section .rdata]` | where is this literal - the entry point into a stripped image |
| `xref <VA>` | who points at it: dword references (decoded with the instruction that carries them) and direct `call`/`jmp`/`jcc` |
| `dis <VA> [--count N]` | disassemble, annotating each branch target |
| `fn <VA>` | disassemble a whole function (stops at the `ret` no internal branch jumps past) |
| `ptrs <VA> [--count N]` | a run of dwords, each described - vtables, switch tables, descriptor arrays |
| `table <VA>` | a NULL-terminated INI field-parse table: `{name, parseFn, userData, offset}` |
| `enum <Name>` | an engine name table with each member's **mask byte and bit** |
| `block <Name>` | an INI block or module: parse fn, field offsets, types, defaults |
| `hex <VA>`, `sections` | bytes, and the section map |

VAs parse as `0x9cdf23`, `9cdf23`, or Cheat Engine's `game.dat+0x5cdf23`.

## 3. The idioms that actually find things

**Strings are the way in.** Symbols are gone; literals are not. Any feature with a keyword, a
label or an error message has an anchor. `str` it, `xref` it, `fn` the function you land in, then
`xref` *that* to walk up the call graph.

**Subsystem globals come from the registration table.** `GameEngine::init` pushes each singleton's
name then the address of the global that will hold it. Worked example, reproducible right now:

```
$ explore.py str ThePlayerList --section .rdata     ->  00bfeca8
$ explore.py xref 0x00bfeca8                        ->  0063c0f7: push 0xbfeca8
$ explore.py dis 0x0063c0f7 --count 5               ->  0063c105: push 0xde4928   ; &ThePlayerList
```

All 88 are already tabulated in `docs/engine-globals.md` - the example is how to check one, or to
recover the same thing on another build.

**An INI keyword is a row in a field-parse table.** A block type is a NULL-terminated array of
`{const char *name, ParseFn parse, void *userData, UnsignedInt offset}`, walked with `stricmp`. So
a keyword tells you a **struct offset** and a **parse function**, and the parse function tells you
the type (the constant a real is scaled by, the range it complains about, the name table a token is
resolved against). `block <Name>` reads the recovered answer; `table <VA>` reads a table live out of
the image, which is what to use once a patch has relocated one.

**A flag is an index into a name table.** `enum KindOf` prints `[9] bit 0x02 of byte +0x1 CAVALRY`,
which is how a bare mask test like `test byte [tmpl+0x109], 5` becomes `INFANTRY | MONSTER`.

**Switch and vtable dispatch are dword tables.** `jmp dword ptr [eax*4 + 0x9ce47f]` → `ptrs
0x9ce47f` gives `index → handler` for the whole enum. Watch for the two traps
`runtime-re-workflow.md` records: cases are 0-based while humans count from 1, and dead entries
dispatch to the default arm, so the string list and the case list are **not** 1:1. Anchor on
something you can confirm, never on position alone.

**`xref` scans a superset, deliberately.** It decodes a branch at *every* byte offset in `.text`
rather than sweeping linearly, because a linear sweep desyncs on inlined data and silently drops
call sites - a false negative you cannot see. This yields the occasional false positive instead,
which is visible. A window with no hits is definitively unreachable by a direct branch.

Heavier artillery, when the above stalls: `sage_patch/ghidra_scripts/` (Windows, headless Ghidra)
and the one-off scans in `sage_patch/scripts/` - those hardcode a Windows path and are excluded
from ruff; read them for method, don't expect them to run here.

## 4. The runtime oracle

Static analysis proposes; the running game disposes. On the Windows box, in an **elevated** shell:

```sh
python -m sage_live processes          # is a game running, and can this shell read it
python -m sage_live info               # frame, players, economy, object census
python -m sage_live watch --frames 60  # one line per logic frame
```

`sage_live` reads memory only (`ReadProcessMemory`, no injection), so it is the cheap way to
confirm an offset: if the number moves when you do the thing, the chain is right. Cheat Engine is
the other half - "find out what writes to this address" converts *where is this stored* into *which
code produces it*, and the saved return addresses on the stack tell you which of ten static callers
actually ran. Translate every address: Cheat Engine's `game.dat+0x294145` is VA `0x694145`.

**Terminate an offset chain at something you can recognise** - a name, a cost, a number you can
change on demand. `[obj+4] -> template`, `[template+0x64] -> AsciiString` (chars at `+8`, not `+4`)
reads back the unit's own name and proves every link at once.

## 5. Rules of the road

- **Guess, then test cheaply.** The skill is keeping the test cheaper than the reasoning.
- **Leave black boxes black.** Knowing which unknowns are load-bearing is most of the job; a branch
  condition nobody needs can stay unexplained.
- **Static-verified is not runtime-verified.** A patch is a reading of the machine code and its
  tests are written from the same reading, so a wrong reading passes both. Only the running game
  disagrees. Say which of the two a claim has had - the docs and the README's experimental section
  are careful about this and so should you be.
- **A finding is real once it is written down**, not once a chat agreed with it. Harvest confirmed
  facts into a doc; don't carry them in conversation.
- **VA vs file offset**, and ImageBase, are a constant source of wrong answers. Convert every time.

## 6. Writing a finding down

The house shape for a new piece of RE, in order:

1. **A doc**, `sage_patch/docs/<topic>.md`: what the engine does today, the addresses, the
   disassembly that proves it, and what is still unknown. Every claim carries its evidence - a
   site, an instruction, a live diff - because the next reader cannot re-derive prose.
2. **The addresses**, into `sage_patch/addresses.py` with the docstring saying where they came from.
   That module is the single home for facts about this build; `sage_live` and the patches both read
   it.
3. **Only if it becomes a patch**: a `Patch` subclass in `sage_patch/patches/`, registered in
   `registry.py`, a README row, and tests that assert the **stock bytes** at every site plus an
   apply/verify/detect round-trip. Read the README's "The patch framework" and "Composing patches"
   first - allocate caves with `allocate_section`, never a fixed RVA; never edit or read bytes
   another patch rewrites.

Follow [`CONVENTIONS.md`](../../../CONVENTIONS.md) for the code, and describe the current state
rather than the history of how it was found.
