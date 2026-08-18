# `GrantUpgrade` / `RemoveUpgrade` as lists — reverse-engineering notes

The RE behind [`patches/upgrade_grant_lists.py`](../patches/upgrade_grant_lists.py). ROTWK
`game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, no ASLR, so a file offset is
`VA - 0x400000` throughout. Read statically from the repo's own `game.dat` (11,346,944 bytes),
2026-08-18.

The sibling of [`trigger-recharge-list`](trigger-recharge-list.md), and built on the same
observation: a keyword stored as an `AsciiString` can hold a list without anything growing. That
document works the argument through for a keyword the engine compares; this one works it through
for two keywords the engine *looks up*, which is where the extra work is.

## The gap

`ObjectCreationUpgrade` fires when an object gains an upgrade. Past its spawn it does two more
things, once, at the end of the same function: it grants the upgrade named by `GrantUpgrade` and
removes the one named by `RemoveUpgrade`. Both are `AsciiString`s, both are resolved by name
through `TheUpgradeCenter` at the moment they are used, and both name exactly **one** upgrade.

One is short of what the module is normally used for. An upgrade that supersedes a tier wants the
tiers below it gone; a "the tech is now this" swap wants a set granted. Today that means a chain of
`ObjectCreationUpgrade`s, each needing its own `TriggeredBy` bookkeeping to fire, or an `Upgrade`
per combination.

## TL;DR

- Both keywords live in `ObjectCreationUpgrade`'s **own** 11-entry field-parse table at
  `0x00C6E2F8`, rows 2 and 3, both parsed by stock `INI::parseAsciiString` (`0x0042EE5E`) into
  `ModuleData+0x140` and `+0x144`. The table has exactly **one** reference in the image, the
  `push imm32` at `0x008B8205`.
- Both are used in **one place**, `0x008B870D`–`0x008B874B`: `findUpgrade(&field)` then
  `giveUpgrade` / `removeUpgrade` on the object, each guarded by its own `test eax,eax / je`
  (§1.3). Those two `findUpgrade` calls are the **only** two in the module.
- The field is an `AsciiString` - one pointer to a refcounted buffer - so the list costs no
  structure growth, no ctor shim and no destructor change. Same lever as `trigger-recharge-list`,
  and the parser is literally the same routine (`patches/utils/token_lists.py`).
- The runtime half is **not** the same, because `findUpgrade` wants an `AsciiString`, not a
  pointer into the middle of one. Each token is copied into the cave routine's own frame to be
  NUL-terminated, then `AsciiString::set` + `findUpgrade` + apply (§2.2).
- The guard is what makes the hook cheap: a cave that returns **NULL** makes the caller's existing
  `je` skip the single-upgrade call it would otherwise make. Nothing is displaced, nothing is
  jumped over, and the stock path stays in the binary unexecuted (§2.3).
- Cost: **four edits** - two `imm32`s in `.rdata`, two `call`s in `.text` - plus a `0x1F4`-byte
  cave. **Statically verified**: every site holds its stock bytes in the real binary and
  apply / verify / detect round-trip against it. **Not yet observed in game.**

## 1. Anatomy

### 1.1 The module

`ObjectCreationUpgrade`, interface mask `0x81`, `sizeof(ModuleData)` `0x174`, `ModuleData` ctor
`0x008B83E4`.

The three `AsciiString` fields are constructed together at the top of the constructor and
destroyed in reverse at the bottom, which is the cheapest confirmation that all three really are
`AsciiString`s and that nothing else shares those bytes:

```
008b8401  89 9e 40 01 00 00  mov [esi+0x140], ebx   ; RemoveUpgrade = 0
008b8407  89 9e 44 01 00 00  mov [esi+0x144], ebx   ; GrantUpgrade  = 0
008b840d  89 9e 48 01 00 00  mov [esi+0x148], ebx   ; ThingToSpawn  = 0
...
008b8782  8d 8e 48 01 00 00  lea ecx, [esi+0x148]   ; ~AsciiString, in reverse
008b8794  8d 8e 44 01 00 00  lea ecx, [esi+0x144]
008b87a3  8d 8e 40 01 00 00  lea ecx, [esi+0x140]
```

A zeroed handle is a validly constructed empty string, which is why "the field was never written"
needs no separate flag anywhere below.

### 1.2 The field-parse table

`0x00C6E2F8`, 11 rows of `{const char *name, ParseFn, void *userData, UnsignedInt offset}`,
terminator at `0x00C6E3A8`:

| # | keyword | parse fn | offset |
|---|---|---|---|
| 0 | `UpgradeObject` | `0x0073A368` | `+0x008` |
| 1 | `Delay` | `0x0073A429` | `+0x00C` |
| **2** | **`RemoveUpgrade`** | **`0x0042EE5E`** | **`+0x140`** |
| **3** | **`GrantUpgrade`** | **`0x0042EE5E`** | **`+0x144`** |
| 4 | `ThingToSpawn` | `0x0042EE5E` | `+0x148` |
| 5 | `Offset` | `0x0042F247` | `+0x14C` |
| 6 | `Angle` | `0x0042EE15` | `+0x158` |
| 7 | `DestroyWhenSold` | `0x0042E558` | `+0x15C` |
| 8 | `DeathAnimAndDuration` | `0x00851412` | `+0x160` |
| 9 | `FadeInTime` | `0x0042ECB2` | `+0x16C` |
| 10 | `UseBuildingProduction` | `0x0042E558` | `+0x170` |

Note row 4. `ThingToSpawn` is the same type with the same parser, and it is **not** in scope: it
names an object template rather than an upgrade, and the single spawn it drives is a different
feature with a different consumer. It sits in the tests as the row a patch aimed one entry wide
would hit.

The table is named exactly once, by `buildFieldParse`:

```
008b8205  68 f8 e2 c6 00     push 0xc6e2f8            ; <- the 4 bytes the patch reads
```

The patch takes the base from that instruction rather than from the constant, so a patch that had
already relocated the table into a cave would be followed rather than bypassed. That failure would
otherwise be silent: the stale copy still holds every byte the entry check asserts.

`SlaveWatcherBehavior` has keywords of the same two names in **its own** table at `0x00C609F8`
(offsets `+0x8` / `+0xC`). Different table, different module, untouched by this patch - worth
knowing because a string search for either name finds both.

### 1.3 Where the two fields are used

One block, at the end of the module's upgrade step:

```
008b870a  8b 7d f0           mov  edi, [ebp-0x10]     ; the interface found below
008b870d  8b 0d a0 45 de 00  mov  ecx, [0xde45a0]     ; TheUpgradeCenter
008b8713  8d 83 44 01 00 00  lea  eax, [ebx+0x144]    ; &GrantUpgrade
008b8719  50                 push eax
008b871a  e8 c6 6e db ff     call 0x66f5e5            ; findUpgrade  <- PATCHED
008b871f  85 c0              test eax, eax
008b8721  74 09              je   0x8b872c            ;   NULL -> nothing to grant
008b8723  8b 4f f8           mov  ecx, [edi-8]        ;   the Object
008b8726  50                 push eax
008b8727  e8 5f b1 dd ff     call 0x69388b            ;   Object::giveUpgrade
008b872c  8b 0d a0 45 de 00  mov  ecx, [0xde45a0]
008b8732  81 c3 40 01 00 00  add  ebx, 0x140          ; &RemoveUpgrade (ebx is dead after this)
008b8738  53                 push ebx
008b8739  e8 a7 6e db ff     call 0x66f5e5            ; findUpgrade  <- PATCHED
008b873e  85 c0              test eax, eax
008b8740  74 09              je   0x8b874b
008b8742  8b 4f f8           mov  ecx, [edi-8]
008b8745  50                 push eax
008b8746  e8 ed 8c dd ff     call 0x691438            ;   Object::removeUpgrade
008b874b  b8 ff ff ff 3f     mov  eax, 0x3fffffff     ; sleep forever
```

Grants happen before removals. Both `findUpgrade` results are consumed by a `test eax,eax / je`
that skips the apply - which is the whole reason this patch needs no displaced instruction: a hook
that returns NULL turns each of those two `je`s into an unconditional skip of a call that has
already been made, per name, inside the hook.

A sweep of `.text` for `lea reg, [reg+0x140]` / `[reg+0x144]` followed by an `AsciiString` or
upgrade call finds these two sites and the module's own ctor/dtor; everything else is another
class's `+0x140`. Within the module's code (`0x008B83E4`–`0x008B8800`) there are exactly **two**
calls to `findUpgrade`, the two above.

### 1.4 The engine calls

| VA | what | convention |
|---|---|---|
| `0x0066F5E5` | `UpgradeCenter::findUpgrade(const AsciiString &)` | `__thiscall`, `ret 4`, NULL when unknown |
| `0x0069388B` | `Object::giveUpgrade(UpgradeTemplate *)` | `__thiscall`, `ret 4` |
| `0x00691438` | `Object::removeUpgrade(UpgradeTemplate *)` | `__thiscall`, `ret 4` |
| `0x004050E6` | `AsciiString::set(const char *)` | `__thiscall`, `ret 4` |
| `0x00435D50` | `AsciiString::~AsciiString()` | `__thiscall`, plain `ret` |

`findUpgrade` is not a string scan: it hands the name to `TheNameKeyGenerator->nameToKey`
(`0x0049F474`) and looks the key up (`0x0066F230`), so a list of N names costs N hashes and N list
walks - the same per-name cost the stock single lookup pays.

`TheUpgradeCenter` is the global pointer at `0x00DE45A0`
([engine-globals.md](engine-globals.md)).

### 1.5 Which object gets the upgrade

The apply calls take the object from `[edi-8]`, and the cave has to reproduce that. `edi` reaches
the block by three paths, and they do not agree about *what* `edi` is - only about `[edi-8]`:

```
008b84c8  8b 4f f8           mov  ecx, [edi-8]        ; edi = this module's interface
008b84cb  6a 00              push 0
008b84cd  e8 55 3e dd ff     call 0x68c327            ; find an interface on the same object
008b84d2  85 c0              test eax, eax
008b84d4  89 45 f0           mov  [ebp-0x10], eax
008b84d7  0f 84 30 02 00 00  je   0x8b870d            ; none -> the block, edi untouched
...
008b84fd  0f 85 0a 02 00 00  jne  0x8b870d            ; likewise
...
008b870a  8b 7d f0           mov  edi, [ebp-0x10]     ; fallthrough -> edi = that interface
```

`0x0068C327` opens with `mov esi, [ecx+0x24c]` — the module array of the object it was called on —
and returns one of *that object's* module interfaces. A module interface sits at `module+0x10`
with the `Object` at `-8`, so `[edi-8]` is the same `Object` whichever of the three paths arrived.
The patch asserts all four instructions rather than the conclusion.

## 2. The patch

Four edits and one appended `.upglst` cave, `0x1F4` bytes: the shared list parser, then two
copies of the applier, one aimed at `giveUpgrade` and one at `removeUpgrade`.

### 2.1 The keywords — two `imm32`s

Rows 2 and 3 have their parse function repointed from `0x0042EE5E` at the entry's `+4`:

```
old  5e ee 42 00      ; INI::parseAsciiString - stores the first token, drops the line
new  <cave>           ; the shared list parser
```

Nothing else in either row moves, and both point at the **same** copy of the parser. The parser
itself, its contract and why a single token comes out byte-identical to stock are documented in
[`patches/utils/token_lists.py`](../patches/utils/token_lists.py) and in
[trigger-recharge-list.md §2.1](trigger-recharge-list.md).

### 2.2 The applier

`__thiscall`-shaped, standing exactly where `findUpgrade` stood: `[esp+4]` is the field, `ret 4`,
and the answer is the `UpgradeTemplate *` the caller would apply.

```
push ebp / mov ebp, esp / sub esp, 0x108      ; [ebp-4] name, [ebp-8] object, 0x100-byte buffer
push esi / push edi
and  dword [ebp-4], 0                         ; a zeroed AsciiString is a valid empty one
mov  eax, [edi-8] / mov [ebp-8], eax          ; the Object, taken before edi is reused
mov  esi, [ebp+8] / mov esi, [esi]            ; the field's buffer
test esi, esi / je .done                      ; never written -> nothing to do
add  esi, 8                                   ; its characters
.token:                                       ; skip separators
  mov al, [esi] / cmp al, ' ' / jne .copy_start
  inc esi / jmp .token
.copy_start:
  test al, al / je .done                      ; end of the list
  lea edi, [ebp-0x108] / mov ecx, 0xff        ; the buffer, and the copy bound
.copy:
  mov al, [esi] / test al, al / je .lookup
  cmp al, ' ' / je .lookup
  mov [edi], al / inc esi / inc edi
  dec ecx / jne .copy                         ; full -> take what we have
.lookup:
  mov byte [edi], 0
  lea eax, [ebp-0x108] / push eax
  lea ecx, [ebp-4] / call 004050e6            ; name.set(buffer)
  lea eax, [ebp-4] / push eax
  mov ecx, [00de45a0] / call 0066f5e5         ; findUpgrade(name)
  test eax, eax / je .advance                 ; unknown name -> skip it
  push eax / mov ecx, [ebp-8]
  call <giveUpgrade | removeUpgrade>
.advance:                                     ; run to the end of this token, take the next
  mov al, [esi] / test al, al / je .done
  cmp al, ' ' / je .token
  inc esi / jmp .advance
.done:
  lea ecx, [ebp-4] / call 00435d50            ; release the name
  xor eax, eax                                ; "no template" - see below
  pop edi / pop esi / leave / ret 4
```

Three things worth stating about it.

**Why the token is copied.** `findUpgrade` takes an `AsciiString`, and the tokens are interior
runs of one - there is no NUL after `Upgrade_A` in `"Upgrade_A Upgrade_B"`. The alternatives are
writing a NUL over the separator in the field's own (refcounted, shared) buffer and putting it
back, or building the name a character at a time with `concat(char)` and its per-character
reallocation. A frame copy is cheaper than both and touches nothing outside the routine.

**Why it is bounded.** The copy stops at `0xFF` characters and truncates, which fails the lookup
harmlessly; the longest upgrade name Edain declares is 46 characters. The bound is what keeps a
pathological line from writing past the frame, and it is the one thing in this cave that a test
can only check by running it - which
[`tests/sage_patch/test_upgrade_grant_lists.py`](../../tests/sage_patch/test_upgrade_grant_lists.py)
does, on a narrow interpreter for the forms this routine emits.

**Why `ecx` is ignored.** The caller loads `TheUpgradeCenter` into `ecx` immediately before the
call, and the cave re-reads the same global instead. Six bytes to remove a dependency on a
register the patch would otherwise be asserting about.

### 2.3 The two lookups — two `call`s

```
old  e8 <findUpgrade>
new  e8 <the matching applier>
```

The applier returns NULL, so the caller's own `test eax,eax / je` skips the single-upgrade call
that follows. Those two calls are not removed; they stop being reached. Both are asserted in
`ANCHORS` anyway - "the caller skips its own call" is only true if they are `giveUpgrade` and
`removeUpgrade` in that order, and a build with them the other way round would grant what it was
told to remove.

## 3. What changes, and what does not

- **A single name is exactly what it was.** The parser stores one token byte-for-byte as stock
  stored it, and the applier then looks that one name up and applies it to the same object through
  the same engine call. The only difference is who makes the call.
- **An empty field is exactly what it was.** The applier returns before its loop; stock's
  `findUpgrade("")` returned NULL and the `je` skipped.
- **An unknown name is exactly what it was**: nothing happens, and now it costs the names beside
  it nothing either.
- **Grants still precede removals**, which matters now that the two lists can overlap: naming the
  same upgrade in both leaves the object without it.
- **`ThingToSpawn` is unchanged**, deliberately.
- **Determinism.** Both routines are pure functions of a `ModuleData` written at INI-parse time
  and of the upgrade registry, run on the logic thread. Nothing new enters the frame or the CRC -
  but *which* upgrades an object holds is simulation state, so this is a rule change like any
  other: **every peer must run the same patched binary**, and a mod writing two names needs the
  patch or the second is dropped without a diagnostic.

## 4. Composition

Order-independent. The cave is appended past every existing section and `verify` finds it by name;
the four byte ranges rewritten are touched by no other bundled patch; and the field table is
located through the reference that names it, so a patch that relocated it first is followed rather
than bypassed. It shares the list parser with
[`trigger-recharge-list`](trigger-recharge-list.md) as *source*, not as bytes: each patch lays its
own copy in its own cave, so neither reads the other's.

## 5. Status

**Statically verified.** Every site holds its stock bytes in the real `2.01.2614.37001` binary;
both table rows are the keywords, parsed by the stock `AsciiString` parser into the offsets the
code reads; both calls still reach `findUpgrade` and they are the only two in the module; and
apply / verify / detect round-trip against the real file. The applier is executed in the test
suite - names looked up in order, unknown names skipped, the object each upgrade lands on, the
truncation bound, and the stack and registers on the way out.

**Not yet observed in game.** What that leaves open is the same as for its sibling: four engine
calling conventions read from disassembly. A wrong reading shows up as a crash or a corrupted
keyword the first time an `ObjectCreationUpgrade` fires - loudly, but only in a running game.
