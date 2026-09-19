# The CAH faction enum — which sides may build a Create-A-Hero

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), verified against the
clean `engine/game.dat.backup`.

**Verdict up front:** the restriction is a nine-name enum plus a 32-bit mask on each CAH subclass.
Three options, in increasing order of usefulness:

- **A — force the gate open.** Three 3-byte writes. Every subclass is offered to every side.
- **B — extend the enum wholesale.** Twenty dword repoints. Costly and buys little on its own.
- **C — a `--sides` list plus an `All` token.** A new section, twenty-nine dword repoints and one
  byte. Mods declare their own sides in `UsableFactions`, and `All` means *every* side, present or
  future. **Built** — see [`patches/cah_factions.py`](../patches/cah_factions.py).

The enum has 23 free bits, so up to 22 mod sides plus `All` fit with no structure growth. The
ceiling is 32 and it is hard: the side index is used as a bit position in two independent 32-bit
masks.

## The enum

Nine names, NULL-terminated, in **two identical copies**:

| VA | file offset | used by |
|---|---|---|
| `0x00da3ac0` | `0x009a3ac0` | code — 19 sites index or scan it |
| `0x00d9edd0` | `0x0099edd0` | INI — `userData` of the `DefaultFaction` field |

```
0 Men   1 Elves   2 Dwarves   3 Isengard   4 Mordor
5 Wild  6 Angmar  7 Arnor     8 Neutral    (NULL)
```

The repo already carries the second copy: it is name table `0x00d9edd0` in
[`ini-types.json`](ini-types.json), recovered by [`module_defaults.py`](../scripts/module_defaults.py).

Neither array has slack. `0x00da3ac0` runs to its terminator at `0x00da3ae4` and the next pointer
table (`NONE`/`HOLD`/`KILL`/`SPAWN`) starts at `0x00da3ae8`; `0x00d9edd0` terminates at `0x00d9edf4`
with one spare dword before the `CreateAHeroSystem` string pointer. Growing either in place
overwrites a neighbour — but see [Option C](#option-c), which grows a *copy* and repoints.

## The INI surface

The fields live on the `SubClass` block nested in `CreateAHeroClass`, field-parse table
`0x00d9f088`, same `{const char* name, parseFn, userData, offset}` 16-byte stride as everywhere else:

```
table@0x00d9f158  DefaultFaction   offset=0x64  parse 0x0042e956 (Enum)  userData=0x00d9edd0
table@0x00d9f168  UsableFactions   offset=0x68  parse 0x0061c0a5
table@0x00d9f178  ViewInfo         offset=0x6c  parse 0x00619141
```

`DefaultFaction` is a plain index; the ctor at `0x0061e550` defaults it to `8` (Neutral).

`UsableFactions` is a **bitmask, one bit per enum index**, parsed token by token at `0x0061a85a`:
`None` clears it, `+Name` sets a bit, `-Name` clears one, a bare `Name` resets on first token then
sets. Each token is resolved by `INI::scanIndexList` (`0x0042b914`) against `0x00da3ac0`, which
aborts INI load on an unknown token — so an unlisted side cannot be named in `UsableFactions` at all.

The mask is **exactly 4 bytes**: it occupies `+0x68..+0x6c`, its ctor at `0x007fc3b8` is
`memset(this, 0, 4)` and its copy at `0x007b3ce0` is `memcpy(…, 4)`. Nine of 32 bits are in use.

## The three gates

The mask is tested in three places. Only the first is a function; the other two are the same test
inlined, and **any patch that opens the gate must address all three**.

| # | site | shape |
|---|---|---|
| 1 | `0x00619477` | `isFactionUsable(side) -> Bool`, a 32-byte leaf |
| 2 | `0x00842e96` | inlined, `test [eax+ecx*4], edx ; jne` |
| 3 | `0x00843c0f` | inlined, `and edx, [eax+ecx*4] ; neg ; sbb dl,dl` |

```
00619477  8b542404   mov  edx, [esp+4]              ; side index
0061947b  33c0       xor  eax, eax
0061947d  56         push esi
0061947e  8bf1       mov  esi, ecx                  ; this = SubClass
00619480  40         inc  eax
00619481  8bca       mov  ecx, edx
00619483  83e11f     and  ecx, 0x1f
00619486  d3e0       shl  eax, cl                   ; 1 << (side & 31)
00619488  c1ea05     shr  edx, 5
0061948b  23449668   and  eax, [esi + edx*4 + 0x68] ; UsableFactions
0061948f  5e         pop  esi
00619490  f7d8       neg  eax
00619492  1bc0       sbb  eax, eax
00619494  f7d8       neg  eax                       ; -> 0 / 1
00619496  c20400     ret  4
```

Site 1 has one caller, `0x0061d2ef`, in `CreateAHeroSystem::collectSubClassesForFaction` at
`0x0061d295`, which fills the shell's class list box (its own only caller is `0x0084f02f`). Sites 2
and 3 sit in two further shell paths, both reached from `PlayerTemplate::getSideIndex`, both fetching
the subclass by the same `(class, subclass)` pair via `0x00619ce6`. All three short-circuit on a
side index of `-1`, which means "unrestricted".

Nothing in game logic, the spawn path, or the `.cah` file format (which stores class/subclass
indices and no faction — see [`sage_cah`](../../sage_cah/README.md)) re-checks the mask.

## How a side reaches the gates

```
0084f006  mov  ecx, [0xde3b10]        ; ThePlayerTemplateStore
0084f00f  call 0x5fcad9               ; getPlayerTemplate(slot's template index)
0084f01a  call 0x5fc95b               ; PlayerTemplate::getSideIndex()  -> 0x73bda3
0084f021  or   eax, -1                ; no template -> -1 (unrestricted)
```

`0x0073bda3` maps the PlayerTemplate's `Side` string to an index:

```
0073bda3  mov  ecx, [esp+4]
0073bda7  push 0xc25224               ; "Goblins"
0073bdac  call 0x406585
0073bdb3  jne  0x73bdb9
0073bdb5  push 5 ; pop eax ; ret      ; "Goblins" is an alias for Wild (5)
0073bdbc  push [esi*4 + 0xda3ac0]     ; linear scan
0073bdd1  cmp  esi, 9                 ; <-- hard-coded count
0073bdd6  push 9 ; pop eax            ; not found -> 9, one past the end
```

**This is the whole failure mode.** A mod side whose name is not one of the nine resolves to `9`.
The gates test bit 9 of the mask — a bit no INI can ever set, because the parser rejects any token
outside the same nine names. Result: every CAH subclass is filtered out and the side gets an empty
class list. No overflow, no crash; bit 9 is inside the 32-bit mask.

## The 32-entry ceiling

The side index is used as a bit position in two independent 32-bit masks — `UsableFactions` at
`SubClass+0x68`, and a stack-local mask at `0x00932745` (`test [ebp + eax*4 - 4], edx`). Both are one
dword. An index of 32 would make `shr …, 5` yield 1 and read the dword *after* the mask — `ViewInfo`
in the first case. So the enum, including any not-found sentinel, must stay within 0..31.

<a name="option-a"></a>
## Option A — force the gates open

Make each test unconditionally succeed. In all three the "wanted bit" register is already non-zero
(`1 << side`), so testing it against itself is the equal-length rewrite:

| site | before | after | effect |
|---|---|---|---|
| `0x00619483` (file `0x00219483`) | `83 e1 1f` … `23 44 96 68` | `b8 01 00 00 00 c2 04 00` at `0x00619477` | `mov eax,1 ; ret 4` |
| `0x00842e96` (file `0x00442e96`) | `85 14 88` `test [eax+ecx*4], edx` | `85 d2 90` `test edx,edx ; nop` | always non-zero |
| `0x00843c0f` (file `0x00443c0f`) | `23 14 88` `and edx, [eax+ecx*4]` | `23 d2 90` `and edx,edx ; nop` | edx survives → true |

Small, but crude: every subclass is offered to every side with no way to say otherwise, and
`UsableFactions` becomes dead data. Prefer Option C, which reaches the same place via an opt-in
token.

<a name="option-b"></a>
## Option B — extend the enum wholesale

Cheaper than it first looks, because the arrays do not need to be *relocated with their bounds* —
they need to be **repointed to a superset**. Build a new table `[the 9 originals…, new names…, NULL]`
in a fresh section and rewrite every reference to it. Consumers that scan to NULL see the longer
list; consumers with a hard-coded count keep their present behaviour, unchanged, as long as the first
nine entries stay in order.

All 19 code references are a bare `imm32` or `disp32` — every one is a 4-byte in-place write, no
instruction changes length:

| shape | sites |
|---|---|
| `push 0xda3ac0` | `0x0061a8b5`, `0x0061a8f5`, `0x0061a960` (the `UsableFactions` parser) |
| `mov reg, 0xda3ac0` | `0x0073bd9d`, `0x007be046`, `0x0093c58f`, `0x0093dcfe`, `0x0093debb`, `0x0093df77`, `0x0093e030`, `0x0093e114`, `0x009f02fe` |
| `[reg*4 + 0xda3ac0]` | `0x0073bdbc`, `0x0096063f`, `0x009a9abc`, `0x009d0f28`, `0x009d1040`, `0x009d1a5d`, `0x009e571c` |

Plus one data write — the `DefaultFaction` `userData` at `0x00d9f160` — so `DefaultFaction` accepts
the new names too.

Eight further sites bound a loop by the array's **end address** (`&table[8]`) rather than a count,
and must move with it to keep iterating exactly the first eight entries:

```
0093c5ae  81 fe e0 3a da 00       cmp esi, 0xda3ae0          ->  cmp esi, NEWBASE+0x20
0093dd1d  81 fe e0 3a da 00       cmp esi, 0xda3ae0          ->  ...
0093defe  81 fe e0 3a da 00       cmp esi, 0xda3ae0
0093dfba  81 fe e0 3a da 00       cmp esi, 0xda3ae0
0093e08c  81 fe e0 3a da 00       cmp esi, 0xda3ae0
0093e098  81 7d f0 e0 3a da 00    cmp [ebp-0x10], 0xda3ae0
0093e170  81 fe e0 3a da 00       cmp esi, 0xda3ae0
0093e17c  81 7d f0 e0 3a da 00    cmp [ebp-0x10], 0xda3ae0
```

`0x009f0467` (`cmp edi, 8`) is a count, not an address — leave it, and the stats screens keep listing
their eight sides.

Finally the resolver's scan bound, one byte:

```
0073bdd1  83 fe 09    cmp esi, 9   ->  cmp esi, <entry count>
```

On its own this is not worth doing. `0x0073bda3` binds by exact string, so a new entry only helps a
mod that renames its side to match, and the mod must still enumerate every side in every subclass.

<a name="option-c"></a>
## Option C — a `--sides` list plus an `All` token

Option B, plus one idea that makes it worth the trouble: **let `All` expand to every bit at parse
time.** Then no gate needs patching at all — sites 1, 2 and 3 test a mask that is already
`0xFFFFFFFF`, and so would any gate added by a future engine build.

### Layout

```
index   0..8   the nine originals, in order        (never moved)
index   9      "All"                                (the reserved catch-all)
index  10..N   the sides passed to --sides
index  N+1     NULL
```

`All` goes at index 9 deliberately. Index 9 is *already* the engine's "unknown side" answer, and
`0x0062d4bd` independently uses the literal `9` for "this slot has no player template". Making 9 mean
`All` keeps those paths benign and gives the resolver's not-found return exactly the semantics you
want, for free:

> An unrecognised side gets the subclasses that opted into `All`, and nothing else.

So `push 9` at `0x0073bdd6` is **left alone**; only the scan bound `cmp esi, 9` moves to the new
entry count. With `All` occupying index 9 and the sentinel folded into it, the highest usable index
is 31, so `--sides` accepts up to **22** names before the 32-bit ceiling bites.

### The parser wrapper

`0x0061c0a5` is the `UsableFactions` field parser, a five-instruction cdecl thunk
`(ini, instance, store, userData)` that uses only `ini` and `store`. Wrap it in the new section and
repoint the field table's parser pointer at `0x00d9f16c`:

```asm
usable_factions_wrapper:            ; cdecl(ini, instance, store, userData)
    push dword [esp+0x10]           ; ff 74 24 10   userData
    push dword [esp+0x10]           ; ff 74 24 10   store
    push dword [esp+0x10]           ; ff 74 24 10   instance
    push dword [esp+0x10]           ; ff 74 24 10   ini
    call 0x0061c0a5                 ; e8 <rel32>    the stock parser, unmodified
    add  esp, 0x10                  ; 83 c4 10
    mov  eax, [esp+0x0c]            ; 8b 44 24 0c   store = &mask
    test dword [eax], 0x200         ; f7 00 00 02 00 00   bit 9 = All
    jz   .done                      ; 74 06
    mov  dword [eax], 0xffffffff    ; c7 00 ff ff ff ff
.done:
    ret                             ; c3
```

43 bytes. The stock parser still validates every token, so a typo in `UsableFactions` still fails
INI load loudly rather than silently doing nothing.

### The full recipe

| # | write | what |
|---|---|---|
| 1 | new section | extended pointer table + the name strings + the 43-byte wrapper |
| 2 | 19 × dword | repoint the code references listed in Option B |
| 3 | 8 × dword | the end-address loop bounds → `NEWBASE+0x20` |
| 4 | 1 × dword @ `0x00d9f160` | `DefaultFaction` userData → new table |
| 5 | 1 × dword @ `0x00d9f16c` | `UsableFactions` parser → wrapper |
| 6 | 1 × byte @ `0x0073bdd1` | `cmp esi, 9` → `cmp esi, <entry count>` |

No relocated engine code, no structure growth, every write either in the new section or a
same-length immediate. `append_section` and `apply_byte_patch` in [`utils.py`](../utils.py) already
do the mechanical parts, and the whole thing derives from `--sides`, so `verify` can re-derive and
check every site the way `CommandSetLimitPatch` does.

### What a mod then writes

```ini
CreateAHeroClass MyClass
  SubClass Whatever
    UsableFactions = All             ; every side, including ones the engine has never heard of
    UsableFactions = Men Rohan       ; a stock side and a mod side
    DefaultFaction = Rohan
  End
End
```

`Rohan` here is the mod's `PlayerTemplate` `Side` string; it must match a `--sides` name exactly,
since `0x0073bda3` compares by string.

### Known rough edges

- `All` is not subtractive. Once a line sets it the mask is all-ones, so a later `-Men` clears only
  the `Men` bit and leaves the other 31 set. Document `All` as a whole-field value.
- Adding a side does **not** make the WOL/stats screens list it. Those loops are bounded by a count
  or an end address and are deliberately left at eight; widening them is a separate job with its own
  string requirements.
- `Goblins` remains hard-coded at `0x0073bda7` as an alias for `Wild` (5) and is checked before the
  table scan, so `Goblins` cannot be reused as a `--sides` name.
- Adding a side does not extend the **editor's** table on its own — see
  [the Worldbuilder half](#the-worldbuilder-half) below, which is a separate patch and has to be
  applied with the same `--sides` list in the same order.

<a name="the-worldbuilder-half"></a>
## The Worldbuilder half

`Worldbuilder.exe` parses `CreateAHeroClass` the way the game does, out of its **own** two copies
of the same nine-name table — the same code / INI-`userData` pair `game.dat` has at
`0x00da3ac0` / `0x00d9edd0`:

| VA | used by |
|---|---|
| `0x02231fec` | code — 20 sites index or scan it |
| `0x0222f470` | INI — `userData` at `0x0222f7f0`, row 13 of the `SubClass` field table `0x0222f718` |

```
table@0x0222f7e8  DefaultFaction   offset=0x64  parse 0x006d3b30  userData=0x0222f470
table@0x0222f7f8  UsableFactions   offset=0x68  parse 0x00b884c0
table@0x0222f808  ViewInfo         offset=0x6c  parse 0x00b82ae0
```

The editor names the enum itself in its assert strings — `BitFlags<9,enum FactionType>`,
`Source\Common/BitFlags.h` — and that `9` is baked into **ten** `cmp`s as well as into the table:

```
00b8a6d7  call 0x006cd120           ; INI::scanIndexListFromString -> index
00b8a6e2  cmp  dword [ebp-8], 9     ; BitFlags<9,FactionType>::SetBit's `bit < NUMBITS`
00b8a6e6  jb   0x00b8a743           ; >= 9 falls into the assert path
```

| # | site | which method |
|---|---|---|
| 1 | `0x00b8a6e2` | `SetBit`, the `+Name` branch |
| 2 | `0x00b8a7ca` | `ClearBit`, the `-Name` branch |
| 3 | `0x00b8a8bb` | `SetBit`, the bare-name branch |
| 4 | `0x00b8aa1b` | `testNameArray`'s walk |
| 5 | `0x00bf30a5` | `getSideIndex`'s scan bound — the twin of `0x0073bdd1` |
| 6-10 | `0x00b820e9`, `0x00d10c37`, `0x01356eab`, `0x014cae69`, `0x014ce9eb` | `test`, the mask's readers |

Two things make the editor's failure different from the game's. First it is **quiet**:
`INI::scanIndexListFromString` (`0x006cd120`) reports through `TheDebug` and then answers **0**, so
`UsableFactions = Rohan` reads as `Men` and the load continues. Second, `testNameArray`
(`0x00b8aa00`) asserts the list holds exactly nine non-NULL names followed by a NULL — and it
reads that terminator through a **baked absolute address**, `cmp dword [0x02232010], 0` at
`0x00b8aa9c`, so the address has to move with the table.

The recipe is otherwise the `game.dat` one with the wrapper dropped — the editor has no gate that
reads the mask, so an `All` bit needs no expansion there:

| # | write | what |
|---|---|---|
| 1 | new section | the superset pointer table + the new name strings, and no code |
| 2 | 20 × dword | every reference to `0x02231fec` |
| 3 | 1 × dword @ `0x0222f7f0` | `DefaultFaction` `userData` → the same new table |
| 4 | 10 × byte | the bit counts above, `9` → `<entry count>` (an `imm8` at every one) |
| 5 | 1 × dword @ `0x00b8aa9e` | `testNameArray`'s terminator → `NEWBASE + count*4` |

Six of the twenty references are stats loops bounded by a hard-coded **8** and go on listing the
same eight sides; the rest read `table[i]` for a caller-supplied `i`. All of them see the same
first nine entries after the move, which is why only the parse path needs step 4. `getSideIndex`'s
not-found answer (`mov eax, 9` at `0x00bf30f0`) is left alone for the same reason the game's
`push 9` is.

Built as `cah-factions-wb`, in the same module — see
[`patches/cah_factions.py`](../patches/cah_factions.py):

```sh
sage-patch apply cah-factions-wb --sides Rohan,Lothlorien \
    --in worldbuilder.exe.backup --out worldbuilder.exe
```

It applies cleanly to a shipped `Worldbuilder.exe`: all 32 sites match their expected original
bytes, the rebuilt table reads back as the stock nine plus `All` plus the caller's sides, the
`DefaultFaction` descriptor points at it, every bit count becomes the entry count and the
terminator check lands on the new NULL. **Static only — the patched editor has not been run.**

## Status

Option C is implemented as [`CahFactionsPatch`](../patches/cah_factions.py), registered as
`cah-factions`:

```sh
sage-patch apply cah-factions --sides Rohan,Lothlorien \
    --in game.dat.backup --out game.dat
sage-patch verify cah-factions --sides Rohan,Lothlorien game.dat
```

It applies cleanly to a real build-`2.01.2614.37001` `game.dat`: all 30 sites match their expected
original bytes, the rebuilt table reads back as the stock nine plus `All` plus the caller's sides,
the emitted wrapper disassembles as intended with its `call` resolving to `0x0061c0a5`, the resolver
becomes `cmp esi, <count>` with `push 9` intact, and the PE stays RVA-ordered with `SizeOfImage`
covering the new section. It composes with `commandset-limit` in either order — see the
composition contract in [the package README](../README.md#composing-patches).

Everything above is verified statically against the binary, and the patched engine has been run.
What stays outside this analysis is the in-game *behaviour* of a CAH offered to a side it was never
designed for: that is a data question for the mod, not one the binary answers.
