# Finding a value in a stripped `game.dat` — the Ghidra + Cheat Engine workflow

Distilled from *"Ghidra Demo"* by CammyFries (34 min screencast,
<https://www.youtube.com/watch?v=YsMlgmsJPPM>). Timestamps below cite the video.

**Scope, up front:** the video is recon only. It locates an end-of-game statistic in the binary,
recovers the struct offsets that hold it, and finds the in-game code that increments it. It never
writes a byte to `game.dat` and never opens an `.apt`. So it covers stage 1 of the
"patch the engine to produce a stat, surface it in the HUD" pipeline — the stage that decides
whether the other three are even possible.

| stage | what it needs | covered here |
|---|---|---|
| 1. locate | find the value, its struct offset, and the code that writes it | **yes — this is the whole video** |
| 2. patch | write new bytes that compute/store your stat | no — see [`../README.md`](../README.md), [`../engine/README.md`](../engine/README.md) |
| 3. plumb | get the number from engine memory to the UI layer | no |
| 4. surface | draw it — APT movie + ActionScript edits | no — see [`sage_apt`](../../sage_apt/README.md) |

## The method in one paragraph

A stripped binary has no function names, no variable names, and no type information. Three sources
of truth replace them, and the whole workflow is a loop between them: **Ghidra** gives you a static
map (which code exists, what it references); **Cheat Engine** gives you runtime ground truth (what
value is actually at that address right now, and which instruction just wrote it); the **running
game** is the oracle (do a thing, watch what changes). Static analysis produces candidate
locations, runtime confirms or kills them, and each confirmed fact narrows the next static search.
Nothing here is proved by reading alone.

## 1. Static: strings are the entry point

Symbols are gone; string literals are not. Any feature with user-visible text, an INI keyword, or
an error message has an anchor you can grep for.

- `Window ▸ Defined Strings`, search for the label — `STAT:RTS_UNITS_CREATED` sits at `0x00C8F364`
  (04:28; he reads it aloud as "stat ITS units created"). A string is just bytes; Ghidra is
  *interpreting* those bytes as text.
- The string has **one xref**, so exactly one function uses it. Double-click → you are in the
  builder that assembles the end-of-game scoreboard, which runs the same routine per stat (05:16).
  Here that is `0x9f18cd`, called once per stat with a `0x18`-byte-strided descriptor array — 72
  stats across the `RTS:` / `STRATEGIC:` / `PERSIST:` groups.
- Functions are named `FUN_009F19DC` because the only identity a function has is the address it
  starts at (06:06). Follow *its* xrefs to walk one level up the call graph (06:33), and repeat.

Analysis of a `game.dat` takes 20–30 minutes (01:43). Do it once, save the project, reopen it.

## 2. Static: read the decompiler as a hypothesis, not as source

- Editing the decompiled C changes nothing. The hex pane is the artifact; the C is a rendering
  (02:56). Renaming `iVar5` only helps *you* read it (04:08).
- Types are guesses. `iVar1` is declared `int` and is in fact a pointer (09:21).
- **Switch/case tables are the highest-value structure to find.** The scoreboard caller is a
  `switch` with cases `0..0x17` (07:09), sitting next to an ordered list of stat strings — that
  correspondence gives you `index → meaning` for the whole enum. Two traps, both hit live:
  - **Off-by-one.** Cases are 0-based, human counting is 1-based; the "sixth" string is `case 5`,
    not `case 6` (14:36). He corrected this mid-demo after already picking an offset.
  - **Dead entries.** Some strings exist in the binary but no longer appear in the shipped UI
    (`times each hero was purchased`, 07:36), so the two lists are *not* 1:1. Align against an
    anchor you can confirm at runtime, never by position alone.
- **`base + constant` is the struct-offset idiom.** `*(int *)(iVar1 + 0x450)` inside a function
  that runs once per player says: `iVar1` is a `Player *`, `0x450` is that stat's field offset
  (08:20 → 13:25). Recovering a struct with no symbols is exactly this — collect every constant
  applied to one base pointer and label each by what the surrounding code does with it.
- **Frame-relative names are your parameter list.** On 32-bit `cdecl`/`stdcall`, `EBP+8` is arg 1,
  `EBP+0xC` is arg 2, and so on (09:21). Ghidra won't print a signature; to learn what a parameter
  *is*, xref the function and read what the call sites push.

## 3. Runtime: pointer chains turn offsets into a live value

The static offsets become a Cheat Engine pointer entry — *Add Address Manually ▸ Pointer*, base +
chain (15:06):

```
[static base]  +0x10   ->  local player          (14:14)
               +0x44C  ->  units created  (case 5)
               +0x450  ->  units lost     (case 6)   ; adjacent 4-byte counters
```

If the displayed number ticks when you build a unit, the offset chain is right. That is the entire
verification step, and it is cheap — which is why you guess aggressively and test immediately.

## 4. Runtime: "find out what writes to this address"

The single highest-leverage move in the video (16:35). It converts *where is this value stored*
into *which code path produces it*, and it jumps you from the **read** site (the end-of-game
scoreboard builder you found statically) to the **write** site (the in-game increment) — which is
the site you would hook to compute a *new* stat.

Then, on the reported instruction:

- `Ctrl+G` to it in Memory View, `F5` to set a breakpoint (18:12–18:29). Build a unit; the game
  freezes exactly on the increment (19:05).
- **Registers are the live operands.** `mov [esi+0x70], edx` tells you nothing until you can read
  `esi` and `edx` at the moment it fires.
- **The saved return addresses are the call stack.** When a function has ten static callers, xrefs
  cannot tell you which one ran *this time*; the first return address on the stack can (20:09).
  Pop one frame at a time to walk arbitrarily far up the real call path (22:02).
- **Translate addresses between tools.** Cheat Engine reports `game.dat+0x294145`; Ghidra shows the
  VA `0x694145`, because the image base is `0x400000` (21:01). Add or subtract the base every
  single time — this is a constant, boring source of wrong answers.

## 5. Runtime: close the chain on something you can *recognise*

The proof technique worth stealing (23:52–30:38). He guesses that `EDI` holds the object just
created, then dereferences until he reaches a human-legible string:

```
EDI              ->  the object instance just created
[EDI+0x04]       ->  its template (the object *type*)
[EDI+0x04]+0x64  ->  AsciiString: name  ->  "Murloc with Soulcatcher"
```

Reading back the name of the unit he had just built is what proves *every* link in the chain at
once. Generic rule: **always terminate an offset chain at a value you can independently identify** —
a name, a known cost, a number you can change on demand. In Cheat Engine, `[EDI+4]` in square
brackets means "follow the pointer" versus `EDI+4` meaning "the address itself" (27:47), which is
the same distinction as `*(x + 4)` versus `x + 4` and just as easy to get backwards.

### Offsets reported in the video — checked against this repo's `game.dat`

Every claim below was re-derived statically from the repo's own binary (`pefile` + `capstone`,
ImageBase `0x400000`). **They all hold.** The video is working on the same build: its
`0x00C8F364` is `STAT:RTS_UNITS_CREATED` here byte-for-byte, and its `FUN_009F19DC` is a real
function boundary.

| from | offset | meaning | evidence in this `game.dat` |
|---|---|---|---|
| `PlayerList` | `+0x10` | local/current player | consistent with [`max-player-count.md`](max-player-count.md); `getNthPlayer` @`0x6a844e` is byte-identical, so it is the same `PlayerList` layout |
| `Player` | `+0x94` | **current spendable resources** | live diff, 2026-07-29: falls by exactly the amount spent (1500, confirmed against the cumulative counter). Engine-managed sides hold the default `1000`; the neutral slot holds `0`. See [`engine-globals.md`](engine-globals.md) |
| `Player` | `+0x38` / `+0x4C` / `+0x58` | display name (UTF-16) / internal name / **Side** | same offset in every populated slot; `+0x58` is the faction token (`Men`, `Civilian`, `Observer`) |
| `Player` | `+0x3DC` | base of the per-player stats block | `mov edi,[ebp+0xc]` @`0x9cded4` then `add edi, 0x3dc` @`0x9cdf0c` |
| `Player` | `+0x3E0` | cumulative resources collected (= stats `+0x04`) | live diff: rises with income, never falls. **Not** the spendable pool - that is `+0x94`, outside the stats block |
| `Player` | `+0x44C` | units created | switch `case 5` → `edi+0x70` |
| `Player` | `+0x450` | units lost | switch `case 6` → `edi+0x74` |
| object | `+0x04` | pointer to its `ThingTemplate` | 45 `mov rX,[rY+4]` → `[rX+0x64]` sites in `.text` |
| template | `+0x2C` | `DisplayName` (INI-side key) | `ThingTemplate` field table @`0xda3db8`, entry 7 |
| template | `+0x30` | resolved display name | parse fn `0x73d3e0` stores at the field offset, then `lea edi,[esi+4]` and assigns again |
| template | `+0x64` | template's own name | the one unclaimed slot in the `AsciiString` run (`0x60` `Hotkey`, `0x68` `EditorName`) — set from the block header, not an INI field |
| template | `+0x6C` | `Side` | field table entry 35 |
| template | `+0x70` | `CommandSet` | field table entry 58 |

`Player+0x3DC` is the piece that ties the two halves of the video together: the static switch reads
`edi+0x70` where `edi = Player+0x3DC`, and the runtime write site he breakpoints is
`mov [esi+0x70], edx` — the same field through the same sub-struct base, reached from opposite
directions.

**The string header.** Chars start at `+8`, not the `+4` that stock Generals-lineage
`AsciiString` uses:

```
0x00448472  8b4704   mov eax, [edi+4]      ; obj -> ThingTemplate
0x00448475  8b4064   mov eax, [eax+0x64]   ; -> AsciiStringData*
0x00448478  3bc3     cmp eax, ebx          ; NULL?
0x0044847f  83c008   add eax, 8            ; <-- characters begin here
0x00448484  b83f0cbd00  mov eax, 0xbd0c3f  ; else the "" literal
```

`inc dword ptr [eax]` in the assign helper (`0x436aed`) shows the refcount is a **dword** at `+0`,
so this build's header is `{ int m_refCount; int m_numCharsAllocated; }` = 8 bytes. That is exactly
the `02` / `14` he read off the hex dump at `+0` and `+4` (29:23).

**Dead stats are dead in the jump table, not just in the UI.** `STAT:RTS_TIMES_EACH_HERO_WAS_PURCHASED`
(`0xc8f14c`) is still registered as descriptor 21, but `case 21` and `case 17` both dispatch to
`0x9ce461` — the same address as the `ja` out-of-range branch, i.e. the default no-op. His "they got
rid of it" (07:36) is visible in the control flow.

### Other `Player` stat offsets, free from the same switch

| offset | switch case | stat |
|---|---|---|
| `+0x3E8` | 13 | money received from allies |
| `+0x3EC` | 12 | money given to allies |
| `+0x3F0` | 15 | resources spent on units |
| `+0x3F4` | 14 | resources spent on structures |
| `+0x3F8` | 16 | resources spent on heroes |
| `+0x44C` | 5 | units created |
| `+0x450` | 6 | units lost |
| `+0x4A4` | 1 | structures created |
| `+0x4A8` | 2 | structures lost |
| `+0x704` | 4 | fortresses built — ⚠ **suspect**: reads `182078920` live (a heap pointer, not a counter) while every other offset in this table reads plausibly. Either the switch case was misread or the field moved in 2.01; re-derive before use |

Reproduce with the scripts in [`../scripts/`](../scripts/) (`pe.py` needs its `PATH` pointed at your
own copy) — the switch table is at `0x9ce47f`, 24 entries, dispatched from `0x9cdf23`.

## 6. Working practices

- **Guess, then test cheaply.** Several key steps are explicitly half-remembered hunches
  (`EDI+4`, 24:19; `+0x64`, 29:01 "through a lot of trial and error"). That is fine *because* the
  runtime check costs thirty seconds. The skill is keeping the test cheaper than the reasoning.
- **Leave black boxes black.** He abandons several branch conditions outright — "what exactly is it
  checking here? I don't know, and I probably never will" (23:12). Knowing which unknowns are
  load-bearing and which can stay opaque is most of the job.
- **On AI assistance** (31:44–34:00, his own framing): useful as a sounding board for "what is this
  doing"; unreliable enough that you should expect roughly one useful answer in twenty on hard
  questions; and **it degrades as the conversation grows**. His fix is the right one — harvest the
  confirmed facts, open a fresh chat, hand it a distilled brief, and continue from there. That maps
  cleanly onto how this repo already works: a finding is only real once it is written into a doc
  like this one, not once a chat agreed with it.

## What stages 2–4 would still need

Not in the video, listed so nobody mistakes recon for a plan:

- **Writing bytes.** The existing framework applies an ordered list of `Patch` objects to a copy of
  the binary, each verifying its expected original bytes before writing, plus a disassembler-free
  `verify` pass — see [`../README.md`](../README.md). Finding a stat's write site tells you *where*
  to hook; it does not give you free space to put new code, which is its own problem (the
  CommandSet patch solved it by adding a `.cmdext` PE section).
- **Surfacing it.** The HUD is APT — a Flash-derived movie plus ActionScript bytecode, tooled in
  [`sage_apt`](../../sage_apt/README.md). Note the constraint already documented in
  [`../engine/README.md`](../engine/README.md): the ControlBar's UI arrays are fixed-size, so
  engine-side data limits and UI-side display limits are separate problems that must be lifted
  separately.
