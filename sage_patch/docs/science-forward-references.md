# Forward references in `PrerequisiteSciences`

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read from the repo's
clean `game.dat`. This is the writeup for the **`science-prereqs`** patch,
[`patches/science_prereqs.py`](../patches/science_prereqs.py), with its tests in
[`tests/sage_patch/test_science_prereqs.py`](../../tests/sage_patch/test_science_prereqs.py).

```sh
sage-patch apply science-prereqs --in game.dat.backup --out game.dat   # both tiers
sage-patch apply science-prereqs --no-report-missing --in ... --out ...   # tier 1 only
sage-patch apply science-prereqs --all-keywords --in ... --out ...        # every keyword
sage-patch verify science-prereqs game.dat            # verify takes the flags apply was given
```

**Status: built and static-verified; not yet runtime-verified in a game.** Both tiers ship. The
patch applies, verifies, round-trips through `detect` — which recovers *which* flags were used —
and composes with every other `game.dat` patch in either order. This document is the derivation
behind it, kept as written apart from [§4.2](#42-when-to-run-the-check) and
[§4.3](#43-how-to-report), where the implementation settled questions the design left open, and
[§8](#8-verifying-it-in-a-game), which is still the open list.

**What it does:** makes `PrerequisiteSciences` accept the name of a science that has not been
defined *yet*, so a mutual pair

```
Science C
  PrerequisiteSciences = A or D
End

Science D
  PrerequisiteSciences = B or C
End
```

parses in one file instead of needing the second half injected from `map.ini`. The safety net is
kept by default: every name that did not resolve at parse time is recorded, and the ones that are
*still* unknown once every science INI file has been read are reported with the engine's own
error.

**Verdict up front: the permissive half is the smallest patch in the tree — one rewritten `rel32`
and a 16-byte cave.** No new INI keyword, so no field-table rebuild and no `sage_ini` surface. No
new format string. No data-structure growth, no savegame change, no runtime hook. The reason it is
this cheap is [§2](#2-why-a-forward-reference-is-already-representable): `ScienceType` **is** the
name key, so the value a forward reference stores is bit-identical to the value a backward
reference stores. The engine's parse-time check is pure validation — remove it and nothing
downstream can tell.

The deferred report is a separate, larger tier: a writable cave section, a second repointed call,
and the recorder, walker and throw sequence in [§4](#4-tier-2--reporting-what-stayed-missing).

| | edits | cave | new INI surface | risk |
|---|---|---|---|---|
| **Tier 1** — allow forward references | 1 (`rel32`) | 16 bytes, read-execute | none | very low |
| **Tier 2** — + report what stayed missing | 2 (`rel32` ×2) | 1246 bytes, read-write-execute | none | low |

Both are one patch object with two flags, because the tiers share the shim: `report_missing`
(default `True`) adds the recorder and the report, `all_keywords` (default `False`) widens tier 1
from `PrerequisiteSciences` to every science-name keyword. `all_keywords` **without**
`report_missing` raises rather than applying — see [§3.1](#31-the-one-edit-variant-and-why-not-to-ship-it-alone).

## 1. What the parse actually does

`Science`'s field-parse table is at `0x00BF8788` — six entries, 16-byte stride, NULL-terminated:

| keyword | parse fn | `ScienceInfo` offset |
|---|---|---|
| `PrerequisiteSciences` | `0x0073BCBF` | `0x1C` |
| `SciencePurchasePointCost` | `0x0042EC5E` | `0x28` |
| `SciencePurchasePointCostMP` | `0x0042EC5E` | `0x2C` |
| `IsGrantable` | `0x0042E558` | `0x30` |
| `DisplayName` | `0x0073B192` | `0x14` |
| `Description` | `0x0073B192` | `0x18` |

`0x0073BCBF` is the OR-group parser and it is used by **`PrerequisiteSciences` and nothing else** —
the flat `vector<ScienceType>` parser `0x0073B4A0` serves the other four science-name keywords
(`RequiredSciences`, `IntrinsicSciences`, `IntrinsicSciencesMP`, `SciencesGranted`, and
`CommandButton`'s `Science`). That separation is what lets Tier 1 stay surgical.

The whole of `0x0073BCBF`, in structure:

```asm
0073bcd6  call 0x73bc98              ; outer.resize(1)      -> one empty group
0073bcde  lea  esi, [eax-0xc]        ; esi = &outer.back()  (inner stride 0xc)
0073bd59  call 0x42dbf5              ; ini->getNextToken()  -> ebx, loop while non-NULL
0073bce3  push 0xbd3bf8 / stricmp    ; "None"  -> clear the group and stop
0073bcf5  push 0xc2519c / stricmp    ; "OR"    -> push a fresh empty group, esi = &back()
0073bd44  push ebx
0073bd45  call 0x73a386              ;  else   -> name -> ScienceType
0073bd52  call 0x5487bb              ;            group.push_back(key)
0073bd7b  ...                        ; drop a trailing empty group ("A or" with nothing after)
```

So `PrerequisiteSciences = A or D` builds `[[A],[D]]`: tokens within a group are ANDed, groups are
ORed. `ScienceInfo` (`0x34` bytes, allocated at three sites in `INI::parseScienceDefinition`
`0x005FF7DA`) holds that as `vector<vector<ScienceType>>` at `+0x1C..+0x24`, with the block's own
name key at `+0x10`.

`0x0073A386` is a four-instruction thunk with **four** callers — the two vector parsers, the
single-science parser `0x0073AFE3`, and `0x00740483`:

```asm
0073a386  push dword [esp+4]
0073a38a  mov  ecx, [0xde3b20]       ; TheScienceStore
0073a390  call 0x5feec7              ; ScienceStore::getScienceFromInternalName, ret 4
0073a395  ret                        ; cdecl: the caller pops (`pop ecx` at 0x73bd4a)
```

and `getScienceFromInternalName` is where the whole problem lives:

```asm
005feec7  ...
005feed3  mov  ecx, [0xdd90e4]       ; TheNameKeyGenerator
005feed9  call 0x5487ec              ; nameToKey(name)  -> esi
005feee3  call 0x5fed95              ; this->isValidScience(esi)
005feeea  jne  0x5fef10              ;   defined -> return esi
005feefa  call 0x42f3c1              ;   not     -> AsciiString::format(3 args)
005feefa                             ;              "Science name %s not known! (Did you define
005feefa                             ;               it in Science.ini?)"    [0x00bf86ac]
005fef0b  call 0xa3ce04              ;              _CxxThrowException
005fef10  mov  eax, esi              ; the return value is the key, either way
```

The return value is `esi` — the name key — computed **before** the check and unaffected by it. The
check contributes nothing to the result. That is the entire finding.

## 2. Why a forward reference is already representable

Two facts, both measured, and together they are the argument that this patch is safe rather than
merely small.

**`ScienceType` is a `NameKeyType`.** Not an index into the store, not a pointer. `ScienceInfo+0x10`
is the same key, and `ScienceStore::findScienceInfo` (`0x005FEC35`) resolves key → info by walking
the store's `vector<ScienceInfo*>` at `TheScienceStore+0x0C..+0x10` comparing `+0x10`. Nothing
anywhere stores a science as an ordinal.

**`NameKeyGenerator::nameToKey` (`0x005487EC`) interns, and mints on miss.** It hashes into a
`0xAFCF`-bucket table at `TheNameKeyGenerator+0xC`, and on a miss allocates a 16-byte node
`{vtable, next, key, AsciiString name}`, takes the next key from the counter at `+0x2BF48`, and
files the node in the key→node map at `+0x2BF4C`. So asking for `"D"` before `Science D` exists
*creates* `D`'s key; when `Science D` is later parsed, `INI::parseScienceDefinition` calls the same
`nameToKey` on the same string and gets the same integer back.

Together: **a forward reference and a backward reference store the identical dword.** Deleting the
validation does not produce a degraded value that something must later repair — it produces exactly
the value the working case produces.

And a genuinely dangling key stays benign. `ScienceStore::playerHasPrereqsForScience`
(`0x005FF323`) evaluates a group by asking whether the player holds each key; a key no science
defines is a key no player can ever hold, so the group is simply unsatisfiable. The only lookup
that could fail is `findScienceInfo` on the science *being tested*, not on its prerequisites.

## 3. Tier 1 — the patch

One `rel32` and one cave stub. Redirect the `call` at `0x0073BD45` — the only science-name call
inside `PrerequisiteSciences`' parser — at a shim that does what the thunk does minus the check:

```asm
science_key:                          ; cdecl(char *name) -> NameKeyType in eax
    mov  ecx, [0x00DD90E4]            ; TheNameKeyGenerator     8b 0d e4 90 dd 00
    push dword [esp+4]                ; the token               ff 74 24 04
    call 0x005487EC                   ; nameToKey, ret 4        e8 rel32
    ret                               ;                         c3
```

Sixteen bytes, no frame, no stack imbalance: `nameToKey` is `__thiscall` with one stack argument
and cleans it, so the shim's `ret` returns to `0x0073BD4A` with the caller's `pop ecx` still
matching its own `push ebx`. `eax` carries the key. Registers touched are `eax`/`ecx`, both already
clobbered by the call being replaced.

| site | old | new |
|---|---|---|
| `0x0073BD45` | `e8 3c e6 ff ff` (`call 0x0073A386`) | `call <cave>` |

Before writing anything, `apply` fingerprints **two** structures it does not rewrite:

- **The `Science` field-parse table** (`_check_field_table`): all six entries by name *and*
  `ScienceInfo` offset, that `PrerequisiteSciences` still names the OR-group parser `0x0073BCBF`,
  and the NULL terminator after the sixth. A far stronger build check than the `rel32` alone, and
  free — the patch has to be sure it is editing inside the parser it thinks it is.
- **The shared thunk** (`_check_thunk`), all sixteen bytes, but only when the thunk is *not* the
  thing being repointed. The shim reproduces the thunk's calling convention, and nothing else
  would catch a build where that convention differs: the patch would apply cleanly and hand the
  parser a key computed from the wrong stack slot. Under `--all-keywords` the thunk is the edit,
  and `apply_byte_patch`'s own old-bytes check covers it.

**`ini_surface()` stays `STOCK`.** No keyword is added, no name-table token, no ceiling raised.
What changes is an *ordering* constraint, which the `Engine` model has no vocabulary for today.
See [§7](#7-open-questions).

### 3.1 The one-edit variant, and why not to ship it alone

Patching the shared thunk `0x0073A386` instead — five bytes, and the shim then needs no separate
`call` site — relaxes all five science-name keywords at once. It also makes **every science-name
typo in the game silent**: `RequiredSciences = SCIENCE_Legolass` would parse, store a key nobody
grants, and disable the special power with no diagnostic at all.

That is the shipped `--all-keywords`, and it is **not** the default. Because the thunk keeps the
shim's own signature (the token still at `[esp+4]`, the caller still popping) the edit is a plain
five-byte `jmp` over the thunk's first instruction, and its remaining bytes go dead. The
constructor refuses `all_keywords=True` with `report_missing=False` outright, with an error saying
why: that combination is the one that silences every science-name typo in the game with nothing
anywhere to catch it. The deferred report is what gives those four other keywords their diagnostic
back — later, and once, but back.

## 4. Tier 2 — reporting what stayed missing

### 4.1 Recording

Extend the shim: after `nameToKey`, ask `ScienceStore::isValidScience` (`0x005FED95`, `__thiscall`
on `[0x00DE3B20]`, one stack argument, `ret 4`) and, on a miss, append the key to a fixed array in
the cave.

```asm
science_key:
    mov  ecx, [0x00DD90E4]
    push dword [esp+4]
    call 0x005487EC                   ; eax = key
    mov  ecx, [0x00DE3B20]
    test ecx, ecx
    je   .done                        ; no store yet: nothing to check against
    push eax
    push eax
    call 0x005FED95                   ; isValidScience(key)
    test al, al
    pop  eax
    jne  .done
    mov  edx, [pending_count]
    cmp  edx, PENDING_CAP
    jae  .done                        ; overflow: drop, the report says so
    mov  [pending + edx*4], eax
    inc  edx
    mov  [pending_count], edx
.done:
    ret
```

That is what shipped, verbatim: 78 bytes of shim (against 16 without the recorder) plus
`4 * PENDING_CAPACITY` of table and its count. `PENDING_CAPACITY` is 256 — 1 KB, far past what any
mod needs — and an overflow drops the key rather than growing, which the report then has to say
rather than pretending the list was complete.

The `push eax` / `pop eax` pair around the call is the whole of the register discipline: the key
has to survive `isValidScience`, and `pop` does not touch the flags, so the `test al, al` before
it still decides the `jne`. `ebx`, `esi` and `edi` are live in the parser across this call; every
callee here is `__thiscall` and preserves them, and the shim itself touches only `eax`/`ecx`/`edx`.

Only the key is stored — the token buffer is reused by the tokenizer, so the pointer would dangle,
but `NameKeyGenerator::keyToName` (`0x00548700`, `__thiscall(key)` → `AsciiString*`) recovers the
name at report time from the key→node map. Duplicates need no dedup: the validator re-checks each
entry against the store, so a name referenced five times before its definition simply passes five
times.

This makes the cave section writable — `0x20 | 0x40 | 0x20000000 | 0x40000000 | 0x80000000`, the
same characteristics `command-point-upkeep` already uses for its 128-row store. With
`--no-report-missing` there is nothing to write and the `MEM_WRITE` bit is left off, which a test
asserts both ways.

### 4.2 When to run the check

`TheScienceStore` is created and loaded by one `initSubsystem` call:

```asm
0063b1f4  call 0x6394ad              ; ScienceStore::ScienceStore  (vtable 0x00bf86ec)
0063b1fd  push ebx / push ebx / push ebx   ; path1 = path2 = dirpath = NULL
0063b20b  push 0xbff1c4              ; "TheScienceStore"
0063b219  push 0xde3b20              ; &TheScienceStore
0063b21e  call 0x63664d              ; initSubsystem  (cdecl, 7 args)
0063b223  add  esp, 0x1c
```

No INI path is passed: `SubsystemInterfaceList::initSubsystem` (`0x005B4A7C`) calls `init()` through
vtable `+4` and then the file-loading override at vtable `+8` (`0x005B4B9A`, which ScienceStore
inherits), and *that* walks the global per-subsystem INI path lists keyed by the subsystem's name.
Whatever files a mod routes to `TheScienceStore`, they are all read by the time `0x0063B21E`
returns. That instruction is the hook.

It is a cdecl call whose arguments the caller cleans, which rules out the obvious shim: a cave that
`call`s `initSubsystem` would put its own return address exactly where the first argument belongs.
Two ways round that, and **the built patch takes the second**:

- Shim the `call` at `0x0063B21E` and carry the return address in a cave dword —
  `pop edx / mov [saved_ret], edx / call 0x0063664D / … / jmp dword [saved_ret]`. Twenty-five bytes
  plus a static, and not reentrant.
- **Detour the two instructions *after* the call**, and re-emit them in the cave. Seventeen bytes,
  no static, reentrant — and its five-byte old-bytes window covers two whole instructions instead
  of one `rel32`, which is a stronger build check for free:

```asm
0063b223  83 c4 1c 6a 24    ->    jmp <after_load>

after_load:
    add  esp, 0x1c                    ; initSubsystem's seven arguments
    pushad
    call validate
    popad
    push 0x24                         ; the displaced instruction, reissued
    jmp  0x0063B228
```

`pushad` matters: the site sits mid-`GameEngine::init` with `ebx = 0` and live `esi`/`edi`. It is
also what lets `validate` use `esi` and `ebx` as its cursor and current key without saving them.

`validate` walks `pending`, re-asks `isValidScience`, and throws on the first survivor —
123 bytes with the name lookup and the throw sequence, and 17 for `after_load` itself.

**What this hook does not cover:** a `map.ini` that defines or overrides a `Science` block runs long
after startup, so a forward reference introduced there is never re-checked. That is a strict
improvement on today (where it is not checkable at all) but it should be documented, not glossed.

### 4.3 How to report

**Settled: the engine's own idiom, verbatim.** The validator builds the exception exactly as
`getScienceFromInternalName` does — the same format string, the same code, the same `throwinfo` —
so a deferred report is indistinguishable from the parse-time error it replaces:

```asm
missing:                              ; ebx = the key that is still unknown
    push ebx
    mov  ecx, [0x00DD90E4]
    call 0x00548700                   ; keyToName -> AsciiString *
    mov  eax, [eax]                   ; its buffer, NULL if never allocated
    test eax, eax
    je   no_name
    add  eax, 8                       ; -> the chars, past refcount and length
    jmp  throw
no_name:
    mov  eax, 0x00BD0C3F              ; a static "" - what an unallocated buffer means
throw:
    sub  esp, 8                       ; Exception { char *message; int code; }
    push eax                          ; the %s
    push 0x00BF86AC                   ; "Science name %s not known! (Did you define it in …)"
    push 3                            ; the code both stock INI throw sites pass
    lea  eax, [esp+0xc]               ; &exception
    push eax
    call 0x0042F3C1                   ; cdecl(Exception *out, int code, const char *fmt, …)
    add  esp, 0x10
    push 0x00D17000                   ; the parse throw's own throwinfo
    lea  eax, [esp+4]
    push eax
    call 0x00A3CE04                   ; _CxxThrowException - does not return
    int3
```

Note `0x0042F3C1` is *not* an `AsciiString` builder: it writes a two-field `Exception` the caller
supplies. Getting the stack arithmetic of those two `lea`s wrong is the failure mode that would
still assemble, apply and verify, so the tests disassemble the sequence back and check both
displacements against the pushes between them. `0x00BD0C3F` is the static empty string an
`AsciiString` with no allocated buffer stands for; a key that got into `pending` came from
`nameToKey`, so it should always have a name, and the branch costs five bytes to not depend on it.

The remaining catch is one only a running game can settle: the throw originates in
`GameEngine::init` rather than inside `INI`'s field loop. That turns out to matter less than it
looks: the four `"Error parsing field/block … in file '%s', line %i."` format strings
(`0x00BD3EBB`, `0x00BD3F00`, `0x00BD3F4C`, `0x00BD3FA5`) have **no `imm32` reference anywhere in the
image**. The release build's INI handler never adds file and line; the text the user sees is the
exception's own string. So a throw from the validator should surface through the same top-level
handler with the same wording. *Should* — [verify item 2](#8-verifying-it-in-a-game) is the one
that confirms it.

Two fallbacks if it does not: format one line per survivor into the game's debug log, or hold the
list and let `sage_lint` do the reporting from INI instead of the engine ([§7](#7-open-questions)).

**Only the first survivor is reported**, because the throw does not return. That matches the stock
behaviour — the parse-time check also aborts on the first bad name — and it is why
`PENDING_CAPACITY` overflowing is tolerable rather than merely tolerated: the list only has to
contain *a* still-missing name, not all of them.

### 4.4 The cave, as built

One appended section, `.scipre`. The pending list comes first so that the code after it can
address the table as a link-time constant:

| offset | tier 1 | both tiers |
|---|---|---|
| `+0x000` | `science_key`, 16 bytes | `count`, one dword |
| `+0x004` | — | `pending`, `4 × 256` bytes |
| `+0x404` | — | `science_key`, 78 bytes |
| `+0x452` | — | `validate` / `missing` / `throw`, 123 bytes |
| `+0x4cd` | — | `after_load`, 17 bytes |
| total | **16 bytes** | **1246 bytes** |

`verify` rebuilds the whole section from the located base VA and the flags it was given and
compares it byte-for-byte, then checks each repointed site; `detect` probes the three legal flag
combinations and returns the one whose `verify` comes back clean, so a patched binary reports
which tiers are actually in it rather than assuming the defaults.

## 5. Blast radius

- **Only `PrerequisiteSciences` changes** by default. The other four keywords keep the strict
  check, since they route through `0x0073B4A0`/`0x0073AFE3` and the untouched thunk.
  `--all-keywords` is the deliberate exception, and moves the edit to that thunk.
- **The `"duplicate science %s!"` guard is untouched** (`0x005FF8BC`, format at `0x00BF87F8`).
  Defining a science twice still fails.
- **`None` and `OR` still work**: they are compared before the name lookup, at `0x0073BCE3` and
  `0x0073BCF5`.
- **Nothing runtime changes.** No structure grows, no vtable moves, no per-frame code is touched.
  The patched build and the stock build produce identical `ScienceInfo` contents for any INI the
  stock build accepts.
- **Multiplayer/replay:** as with every patch here, the exe differs from vanilla; expect a
  version-hash mismatch against unpatched peers. But a mod that uses this feature already differs
  in its INI, so this adds no new axis of incompatibility.

## 6. Composition

Nothing shares a byte. The two edit sites (`0x0073BD45`, `0x0063B21E`) are edited by no bundled
patch, and the cave comes from `allocate_section`. The only structure read is the `Science`
field-parse table, which nothing else rewrites.

Called out in the patch docstring, because it is the near miss a future reader would otherwise
have to re-derive: `cah-factions` edits `0x0073BD9E`, `0x0073BDBF` and `0x0073BDD1` —
`getSideIndex`, the function that begins at `0x0073BDA3`, immediately after the prerequisite
parser ends at `0x0073BD9C`. Adjacent compiland, disjoint bytes.

Under `--all-keywords` the edit moves to `0x0073A386`, which is likewise untouched by anything
else, so the composition argument holds for both variants.

## 7. Open questions

- **Cycles at runtime.** A mutual prerequisite is a cycle by construction, and
  `playerHasPrereqsForScience` (`0x005FF323`) recurses through prerequisites with a
  `map<ScienceType,bool>` memo that it reads on entry but only writes **on exit**
  (`0x005FF3D9`) — so a cycle the player cannot satisfy from outside has no obvious termination in
  the static read. That said, **this patch does not change it**: the runtime graph a patched build
  builds from one file is the same graph the `map.ini` workaround already builds today, and that is
  in service. If it is genuinely stable in play, it is stable either way; if it is not, the bug is
  in the mutual prerequisite, not in the patch. Reproducing the "player has neither A nor B"
  case in a game is verify item 4 below, and it is worth doing regardless of this patch.
- **How `sage_lint` should treat this.** Its unresolved-reference rule
  (`sage_lint/rules/definitions.py`) is definition-set based, not order based, so a forward
  reference within the loaded set already does not trip it — no lint change is needed for Tier 1.
  The interesting question is the other direction: with Tier 2's report being the engine's only
  safety net and blind to `map.ini`, `sage_lint` is arguably the better place to catch a genuinely
  missing science, and it already has the whole file set. If that view wins, Tier 2 gets cheaper —
  possibly to zero.
- **Should the ordering relaxation be declarable in `ini_surface()`?** Today `Engine` describes
  fields, tokens and ceilings. "Reference ordering is not enforced for field X" is a fourth kind of
  fact. Adding it for one patch is over-building; note it and let the second instance decide.
- **Case sensitivity.** The name comparison inside `nameToKey` is a `strcmp` on the interned
  string (`0x00A3CF40` at `0x00548846`), so `SCIENCE_D` and `Science_D` are different keys — in a
  patched build a case-mismatched forward reference becomes a silently dead prerequisite where
  today it is a load error. Tier 2 catches it; Tier 1 alone does not, which is what
  `--no-report-missing`'s help text says and what verify item 3 exists to observe.
- **`PENDING_CAPACITY` overflow.** 256 is far past plausible, and because the throw stops at the
  first survivor an overflow can only lose *additional* names, never the diagnostic itself. The
  case is still unreported as such: the shim drops silently past capacity rather than recording
  that it did.

## 8. Verifying it in a game

None of this has been done yet — the patch is static-verified only. Item 8 is the part that
already passes in CI; everything above it needs the game.

1. **The motivating case loads.** The mutual `C`/`D` pair from the top of this document, defined in
   one file with no `map.ini` injection, must load with no error.
2. **A real typo still fails (Tier 2).** Rename one prerequisite to a science that exists nowhere;
   the build must abort at startup with the stock `Science name %s not known!` wording.
3. **A real typo is silent (Tier 1 alone).** The same file on a Tier-1-only build must load, and
   the science must be unpurchasable. Confirm that is what happens rather than assuming it —
   this is the cost of the cheap tier and it should be observed once.
4. **The cycle behaves.** In a skirmish, open the spellbook with neither `A` nor `B` owned and
   confirm the game does not hang or overflow the stack — see [§7](#7-open-questions). Then buy `A`
   and confirm `C` becomes available, and that `D` follows from `C`.
5. **The other keywords still validate.** A misspelled `RequiredSciences` on a special power must
   still abort the load exactly as it does today — at parse time on a default build, and at the
   deferred check on an `--all-keywords` one.
6. **Duplicate detection survives.** Two `Science D` blocks must still fail.
7. **`map.ini` still overrides.** The existing workaround must keep working on a patched build,
   since mods will have both for a while.
8. **`sage-patch verify` round-trips** and `detect` recovers the settings from a patched binary.
   This one is already covered: the tests apply all three flag combinations, verify each, reject
   each against the other two's settings, and round-trip through `apply_patches`.

## Appendix — a correction to `addresses.py`

The note above `THE_SCIENCE_STORE` (`sage_patch/addresses.py:335`) says the store's elements are
"separately allocated at *different sizes*, so no fixed offset names them and it is still
unwalked". That is not what the binary does. `INI::parseScienceDefinition` allocates `ScienceInfo`
at three sites (`0x005FF831`, `0x005FF888`, `0x005FF8E0`) and every one is `push 0x34`; the
constructor is `0x005FF6D9` and the layout is fixed:

| offset | field |
|---|---|
| `+0x00` | vtable (`0x00BF8724`) |
| `+0x04` | override chain |
| `+0x08` | "is an override" flag |
| `+0x10` | `NameKeyType` of the block name |
| `+0x14` / `+0x18` | `DisplayName` / `Description` |
| `+0x1C`..`+0x24` | `vector<vector<ScienceType>>` prerequisites, inner stride `0x0C` |
| `+0x28` / `+0x2C` | `SciencePurchasePointCost` / `…MP` |
| `+0x30` | `IsGrantable` (default `1`) |

The store is `{begin, end, capacity}` of `ScienceInfo*` at `TheScienceStore+0x0C`, exactly like
`TheSpecialPowerStore`. With `+0x10` as the key and `NameKeyGenerator::keyToName` (`0x00548700`)
resolving it, `sage_live` can name all 263 sciences from memory today. Independent of this patch,
but found by it — fix the comment either way.
