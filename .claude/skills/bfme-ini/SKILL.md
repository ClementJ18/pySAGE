---
name: bfme-ini
description: >-
  Read, understand, or edit Battle for Middle-earth / SAGE-engine `.ini` game data
  (Object, CommandButton, CommandSet, Weapon, Upgrade, Armor, Locomotor, behaviors, draws,
  nuggets, ...). Use when working in a `.ini` under a BFME/SAGE mod tree, when a field's
  meaning or valid values are unclear, or when a value references another definition (a
  button, command set, weapon, upgrade, macro, include) and you need to know where it is
  defined. Backed by the typed `sage_ini` model via the `sage-ini` CLI.
---

# BFME / SAGE ini assistant

The `sage-ini` CLI exposes a fully typed model of the game's ini schema. It is the source of
truth - read field types and reference targets from it, never guess. Every cross-reference
field reports an `R:<table>` code naming the Game table its value resolves into; that is how
you know *where to look* for a referenced button, command set, weapon, upgrade, and so on.

## Quick start: brief one file

`sage-ini brief <mod-ini-dir> <file> [name]` is the one-shot view of a file: what it defines,
the resolved references each definition makes (with the target's `file:line`), what it
includes, and the macros it uses (with their origin). For a large catalog file (e.g.
`commandbutton.ini`) it prints a per-table reference summary and caps the detail - pass a
definition `name` to focus on a single entry. Start here; drop to the steps below when you need
field-level schema detail or to chase a specific name further.

## Changelog between two versions

`sage-ini diff <old> <new>` reports what game data changed between two assembled mods as a
human-readable changelog, not a text diff: definitions are matched by table and name, fields by
key, and sub-modules (behaviors, draws, nuggets, nested states) recursively - so a buried
`MaxHealth` edit surfaces as `ActiveBody ModuleTag_01 > MaxHealth: 300 -> 350`, not a line hunk.

- `<old>`/`<new>` are two ini folders, **or** two git refs with `--repo <repo>` (each ref is
  checked out into a throwaway worktree; `--path <subdir>` points at the ini folder inside it).
- Output groups by table, then by definition: `+ Name` added, `- Name` removed, `~ Name` changed
  with its field/module edits indented beneath. `#define` macro changes are reported too; pass
  `--strings` to also include `.str`/`.csv` display-string changes.

Use it to answer "what changed between these two commits" - read the changelog, then drop to
`brief`/`xref`/`resolve` to explain any one entry in depth.

For a real mod whose files `#include` the base game, prefer **`sage-lint diff <oldRef> <newRef>
[repo]`** instead: it reads the mod's `.sagelint`/`.sagelint.local` (root + base archives), so
each ref assembles with the base game merged in and base `#include`s resolve. The base-game
definitions are identical on both sides and cancel, leaving only the mod's real changes - without
the base, unresolved includes do not corrupt the diff (base content is simply absent on both
sides), but `sage-lint diff` is the faithful, config-aware path.

## Workflow for insight into a single file

1. **Load the maps (lean, ~3K tokens).** Run `sage-ini primer`. It prints:
   - a **LEGEND** of the compact type codes,
   - **TABLES**: every reference table `key -> Kind` (an `R:<key>` resolves here),
   - **MODULES**: the `Behavior=` / `Draw=` / nugget sub-blocks an `Object` may contain.
2. **Read the target file** and note the block kinds it defines (`Object Foo`, `CommandButton
   Command_Bar`, ...) and the sub-blocks inside them.
3. **Pull field detail on demand**, only for the kinds actually present:
   - `sage-ini primer expand <Kind>` - that kind's full field schema (with its enums).
   - `sage-ini primer enum <Name>` - an enumeration's valid members.
   Read the codes with the LEGEND: `R:cursors` is a reference into the cursors table,
   `L[R:mappedimages]` a list of image references, `?R:objects` a nullable object reference,
   `E:SlotTypes` an enum, `<1..N>: R:commandbuttons` the numbered slots of a CommandSet.
4. **Resolve a specific reference.** When the file names something defined elsewhere (a
   command button, a command set, an upgrade, a macro):
   - `sage-ini resolve <mod-ini-dir> <Name>` - where it is defined, as `file:line` (works for
     both definitions and `#define` macros, case-insensitive).
   - `sage-ini xref <mod-ini-dir> <Name>` - what it references and what references it.
   - `sage-ini includes <mod-ini-dir> <file>` - a file's `#include` edges both directions, i.e.
     its resolution scope (what a macro/definition used here could be coming from).
5. **Check the file.** `sage-ini lint <file>` reports parse/conversion problems for one file;
   `sage-lint lint <mod-ini-dir>` assembles the whole game and adds judgment rules (dangling
   references, undefined macros, out-of-range values, duplicate definitions).

## Where the things the file points at live

- **Buttons / command sets.** A `CommandButton`'s `CommandTrigger`/`ToggleButtonName` and a
  `CommandSet`'s numbered slots are `R:commandbuttons`; a unit's `CommandSet` field is
  `R:commandsets`. Resolve a name with `xref`, or read the commandset/commandbutton ini files.
- **Macros** (`#define`, `#MULTIPLY(...)`, `#ADD(...)`). Defined in the mod's gamedata/macro
  ini and expanded at load. `sage-ini resolve <dir> <MACRO>` locates a `#define`;
  `sage-lint lint <dir>` flags undefined ones. Assembling the folder (not a lone file) is what
  makes their definitions visible.
- **Includes** (`#include`). They set a file's resolution scope; `sage-ini includes <dir>
  <file>` shows them both directions. Point `resolve`/`xref`/`lint` at the folder so includes
  are assembled and cross-file references resolve.

## Rules

- Do not invent field names, enum members, or reference targets - `expand`/`enum` instead.
- A reference value that does not resolve is dangling (usually a typo or a missing include);
  `sage-lint` surfaces these.
- Resolution needs the whole mod, not one file: run `xref`/`lint` against the ini **folder**.
