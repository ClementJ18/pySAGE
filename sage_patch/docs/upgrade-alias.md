# Upgrade aliases — giving a reused upgrade a name per use

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), read out of the repo's
`game.dat`.

**What this adds:** an upgrade *reference* may carry a descriptive suffix after an interior `@`,
and the engine resolves only the part before it. `Upgrade_TestBuilding@SmithyLevel2` and
`Upgrade_TestBuilding@GateOpen` are one upgrade to the engine and two intents to a reader.

**Why it is wanted:** the upgrade bit space is fixed at 1152 and the allocator does not check it
(see [`upgrade-mask-limit.md`](upgrade-mask-limit.md)). A mod near the ceiling reuses generic
upgrades as object-local flags, so one name means unrelated things on unrelated objects. Two uses
of one bit on a *single* object then drive each other, and nothing in the text says so. The alias
is what makes that collision nameable, and therefore lintable.

## One hook covers every name source

`UpgradeCenter::findUpgrade` at `0x0066F5E5` is the only place a name becomes an
`UpgradeTemplate`. It is a ten-byte thunk:

```
0066f5e5  56                push   esi
0066f5e6  ff742408          push   dword ptr [esp+8]          ; the const AsciiString *
0066f5ea  8bf1              mov    esi, ecx                   ; this = UpgradeCenter
0066f5ec  8b0de490dd00      mov    ecx, [0x00dd90e4]          ; TheNameKeyGenerator
0066f5f2  e87dfee2ff        call   0x0049f474                 ; nameToKey(const AsciiString *)
0066f5f7  50                push   eax
0066f5f8  8bce              mov    ecx, esi
0066f5fa  e831fcffff        call   0x0066f230                 ; findUpgradeByKey(NameKeyType)
0066f5ff  5e                pop    esi
0066f600  c20400            ret    4
```

It has **84 direct callers**, and they are not only the INI parsers:

| caller | what reaches it |
|---|---|
| `0x0066F690` | `parseUpgradeMask` — `TriggeredBy`, `ConflictsWith`, `RequiredUpgrades`, … |
| `0x0066FC75` | `newUpgrade`, i.e. the `Upgrade <name>` block header |
| `0x00736E6C` | the Lua grant/remove helper behind `ObjectGrantUpgrade` and `ObjectHasUpgrade` |
| `0x0073AFBE`, `0x0073B04B` | map-script arguments naming an upgrade |

Hooking the lookup rather than the INI parser is what makes Lua and map scripts work without
per-parser effort. The Lua chain is worth pinning because it is the non-obvious one: the
registration loop at `0x00739FB0` pushes handler `0x00736FB1` and binds it to the name
`"ObjectGrantUpgrade"` at `0x00C24BB4`; that handler tail-calls the shared helper `0x00736DF5`,
which reads the Lua string argument, builds an `AsciiString`, and calls `findUpgrade` at
`0x00736E6C`. `ObjectHasUpgrade` (name at `0x00C24BC8`) binds to the same helper.

## The separator has to be interior

`@` is **not** an unused character. Create-a-hero bling lists mark their default option with a
leading one:

```
BlingUpgrades = @Upgrade_NoHelmet Upgrade_CorruptedMan_1_CHH01 Upgrade_CorruptedMan_1_CHH02
```

31 tokens across the `createaherosystem*.inc` files are spelled that way. Every other `@` in the
base game data sits inside a comment, where no parser sees it. So the rule is: a separator splits
only when a name precedes it. Truncating `@Upgrade_NoHelmet` at position zero would hash the empty
string and break every create-a-hero default — the carve-out is load-bearing, not tidiness.

`@` is also not one of the lexer's comment markers (`;`, `//`, `--`), so an interior one survives
into the value intact.

## What the cave does

`.upgali`, 102 bytes, entered by a five-byte `jmp` over `push esi` / `push [esp+8]`. The hook is
exactly those five bytes, so nothing is left over and the resume point is the next byte,
`0x0066F5EA`.

The scan reads the `AsciiString`'s buffer pointer, takes the chars at `+8`, and walks from the
*second* character looking for `0x40`. No interior separator means the cave reproduces the two
overwritten instructions and jumps to `0x0066F5EA`, so the stock body runs unchanged — which is
what the base game's 5368 upgrade reference tokens all do, for the cost of a string scan.

With a separator, the cave does what the stock body does but keyed off raw chars:

```
push   ebx
push   esi
mov    esi, ecx                   ; the UpgradeCenter
mov    ebx, edx                   ; where the separator sits
mov    byte [ebx], 0              ; truncate in place
push   eax                        ; the truncated chars
mov    ecx, [0x00dd90e4]          ; TheNameKeyGenerator
call   0x005487ec                 ; nameToKey(const char *)   ; ret 4
mov    byte [ebx], 0x40           ; put the name back
push   eax                        ; the key
mov    ecx, esi
call   0x0066f230                 ; findUpgradeByKey          ; ret 4
pop    esi
pop    ebx
ret    4
```

`0x005487EC` is the C-string overload the `AsciiString` one calls through to — `0x0049F483`
substitutes a pointer to a lone NUL for an empty string, so the key is taken off a NUL-terminated
buffer and never a stored length, which is what makes a transient NUL a valid truncation.

## Why writing into the caller's string is safe

Three things, and the third is the one worth checking rather than assuming:

- **The buffer is writable.** It is the `AsciiString`'s heap allocation. The only non-heap string
  in this path is the empty-string literal at `0x00BD0C3F`, which `nameToKey` substitutes
  internally when the buffer pointer is NULL — and the cave sends a NULL buffer down the stock
  path without writing anything.
- **Nothing observes the gap.** `nameToKey` neither yields nor calls back into game code, and the
  byte is restored before the cave returns.
- **The intern path copies.** When the key is new, `nameToKey` allocates an entry and stores the
  name through `ASCII_STRING_SET` at `0x00548888` rather than keeping the pointer, so restoring
  the separator afterwards cannot corrupt what was interned. The compare path uses `STRICMP` at
  `0x00548846`, a read, and case-insensitively — matching the engine's own name matching.

This is the opposite choice from [`upgrade-grant-lists`](upgrade-grant-lists.md), which copies each
token into its cave's frame instead of NUL-ing a separator in the field's shared buffer. That patch
splits a list and calls `findUpgrade` repeatedly against a long-lived module-data field; this one
does a single lookup and has the byte back before it returns.

## Determinism and cost

The truncation is a pure function of the name applied before any logic reads the result, so an
aliased reference is network- and replay-safe. Mask indices are assigned in INI load order and are
untouched: **an alias creates no upgrade and consumes no bit**, which is the whole point — it is a
naming convention, not a capacity increase. For the capacity question see
[`upgrade-mask-limit.md`](upgrade-mask-limit.md), whose conclusion is unchanged.

## On a stock binary

An aliased name is simply an unknown upgrade, and the two failure modes differ:

| source | unknown name |
|---|---|
| INI | fatal load error, `"An upgrade mask references %s, which is not an Upgrade"` (`0x00C10C90`) |
| Lua, map script | the handler returns zero and silently does nothing |

The silent one is the dangerous one, so a mod that adopts aliases in scripts ships this patch or
does not run.

## Composition

Order-independent. The cave is allocated past every existing section and `verify` finds it by
name. The only engine bytes edited are the five at `0x0066F5E5`, which no bundled patch touches:
`spell-store-upgrade` (`0x0066F5E5` at its line 100) and `upgrade-grant-lists` (line 127) both
*call* that address from their own caves and edit neither it nor anything it reads, so both inherit
alias resolution rather than conflicting with it. Applying with `commandset-limit` in either order
verifies clean.

## The linter half

`sage_ini.model.aliases` is the single definition of the split and applies it unconditionally, so
`sage_lint` agrees with a patched engine without being told which binary the data targets. Four
rules make the annotation load-bearing: an alias on a *definition* header is an error (the engine
resolves a header through this same lookup, so it would silently override the upgrade it aliases),
a malformed alias is an error, two intents on one upgrade within one object is an error, and an
upgrade annotated in some places but not others is a warning. `sage_map` strips the alias before
its own `Game.lookup`, so map-script upgrade arguments and `objectUpgradesList` properties resolve
the same way.

## Verification notes

Verified directly against the binary: the ten-byte body of `findUpgrade` and its two callees'
conventions (`__thiscall`, `ret 4` each), the C-string overload at `0x005487EC` and its NUL
termination, the intern path copying through `ASCII_STRING_SET`, the Lua registration chain from
`"ObjectGrantUpgrade"` to `0x00736E6C`, the two map-script call sites, and the leading-`@` bling
syntax in the base data.

Verified by emulation (`tests/sage_patch/test_upgrade_alias.py`): the cave runs under Unicorn with
both callees stubbed, and is asserted to hash only the part before the separator, to pass the right
`this` to each helper, to restore the separator byte, to take the stock path for a bare name, a
leading `@`, a lone `@`, an empty name and a NULL buffer, to balance the stack as `ret 4` on both
paths, and to give back `ebx`, `esi` and `edi`.

**Not established:** no running-game test. The cave is static- and emulation-verified, not
runtime-verified, and the fixtures are written at the offsets believed correct, so a wrong belief
and a wrong fixture would cancel out. The cheapest real check is a mod that renames one reference
to an alias and confirms the upgrade still fires.
