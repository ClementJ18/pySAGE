# Keeping an upgrade's description after it is researched

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000` for everything cited here. Read from the repo's own `game.dat`
(11,346,944 bytes, clean).

**Verdict up front: the description is not overwritten by a design decision, it is overwritten by
one call.** The ControlBar's tooltip builder assembles the description in a single `UnicodeString`
and adds every other status line to it with `UnicodeString::concat`. The "already researched" case
is the one that calls `UnicodeString::operator=` instead — the adjacent method, one that releases
the buffer it is holding. Swapping which of those two runs is the entire feature.

- **Cost:** one 9-byte window replaced by a `jmp`, plus a 0x41-byte cave (0x29 of which is the
  shared routine; each additional site is 10 bytes of thunk).
- **Risk:** low. Client-side tooltip text, no INI keyword, no `.csf`, no `.apt`, no simulation
  state.
- **Status: built, static-verified and runtime-verified in game** (Edain, 2026-08-15) — a
  researched upgrade's tooltip keeps its `DescriptLabel` with the *"already researched"* line
  under it. See [`patches/upgrade_description.py`](../patches/upgrade_description.py).

```
sage-patch apply upgrade-description --in game.dat.backup --out game.dat
sage-patch apply upgrade-description --separator blank-line --also-blocked --in ... --out ...
sage-patch verify upgrade-description game.dat
```

## 1. The builder

`ControlBar::getTooltipForCommandButton` (the naming is inferred; it is the routine that fills the
five-part tooltip record) begins at `0x00807A81` and ends at `0x00808788`. It is entered through
the two-argument wrapper at `0x00807A00`.

It keeps six `UnicodeString`s in its own frame, and the last thing it does is hand five of them to
the record's constructor at `0x008086E5`:

| slot | what |
|---|---|
| `ebp-0x38` | the button name (`TextLabel`) |
| `ebp-0x28` | the cost line |
| `ebp-0x40` | the command-point line |
| **`ebp-0x18`** | **the description** |
| `ebp-0x48` | the trailing hint |

```
008086dd  8d 4d b8           lea  ecx, [ebp-0x48]
008086e0  51                 push ecx
008086e1  8d 4d e8           lea  ecx, [ebp-0x18]     ; the description
008086e4  51                 push ecx
008086e5  8d 4d c0           lea  ecx, [ebp-0x40]
008086e8  51                 push ecx
008086e9  8d 4d d8           lea  ecx, [ebp-0x28]
008086ec  51                 push ecx
008086ed  8d 4d c8           lea  ecx, [ebp-0x38]
008086f0  51                 push ecx
008086f3  e8 78c91600        call 0x00975070
```

`ebp-0x18` is `DESCRIPTION_TEXT_EBP_OFFSET` in [`addresses.py`](../addresses.py), and was already
recorded there by `hero-mana`, which appends its `ManaCost` line to the same slot.

### Where the description comes from

Cleared at `0x00807CB2`, then filled at `0x00807D99`, and **only if it is still empty** — the
`TOOLTIP:ScienceDisabled` case above it gets first refusal:

```
00807d88  8b 45 e8           mov  eax, [ebp-0x18]
00807d8b  3b c7              cmp  eax, edi            ; edi == 0 here
00807d8d  74 0a              je   0x00807d99
00807d8f  66 39 78 04        cmp  word ptr [eax+4], di  ; the buffer's length
00807d93  0f 85 17010000     jne  0x00807eb0          ; already has text: skip
00807d99  8b 4e 0c           mov  ecx, [esi+0xc]      ; the CommandButton
00807d9c  e8 2c51f5ff        call 0x0075cecd          ; getDescriptLabel()
...
00807dcb  ff 53 38           call dword ptr [ebx+0x38]  ; TheGameText->fetch(AsciiString)
00807dcf  8d 4d e8           lea  ecx, [ebp-0x18]
00807dd2  c6 45 fc 09        mov  byte ptr [ebp-4], 9
00807dd6  e8 b5ecc2ff        call 0x00436a90            ; operator=
```

That empty/non-empty pair is the idiom this patch reuses; see §4.

`0x0075CECD` reads `CommandButton+0x64`/`+0x68`, which is `DescriptLabel` — a **vector**, not a
scalar. Its row in the `CommandButton` field-parse table at `0x00C2BBD8` says so:

| VA | keyword | parser | offset |
|---|---|---|---|
| `0x00C2BBC8` | `TextLabel` | `0x0042EED6` | `0x58` |
| `0x00C2BBD8` | `DescriptLabel` | `0x0042EED6` | `0x64` |
| `0x00C2BBE8` | **`PurchasedLabel`** | `0x0042EE5E` | **`0x70`** |
| `0x00C2BBF8` | `ConflictingLabel` | `0x0042EE5E` | `0x74` |
| `0x00C2BC08` | `LacksPrerequisiteLabel` | `0x0042EE5E` | `0x78` |

## 2. The already-upgraded case

Reached from `0x00808178`, after the builder has established the button carries an `Upgrade`
(`CommandButton+0x24`, cached at `ebp-0x24`) and asked whether the player holds it:

```
0080814d  8b 46 0c           mov  eax, [esi+0xc]
00808150  8b 40 14           mov  eax, [eax+0x14]     ; the GUI command
00808153  ff 75 dc           push dword ptr [ebp-0x24]
00808159  83 f8 06           cmp  eax, 6
0080815c  0f 94 45 f0        sete byte ptr [ebp-0x10]
00808160  83 f8 07           cmp  eax, 7
00808163  0f 94 45 f1        sete byte ptr [ebp-0x0f]
00808167  83 f8 08           cmp  eax, 8
0080816a  0f 94 45 f2        sete byte ptr [ebp-0x0e]
0080816e  e8 3c41eaff        call 0x006ac2af          ; Player::hasUpgradeComplete
00808175  88 45 f3           mov  byte ptr [ebp-0x0d], al
00808178  0f 85 ab010000     jne  0x00808329
```

So four frame bytes carry the state: `ebp-0x10`/`-0x0f`/`-0x0e` say which of the three upgrade GUI
commands this is, and `ebp-0x0d` says the player already has it.

The case itself:

```
00808329  80 7d f0 00        cmp  byte ptr [ebp-0x10], 0
0080832d  75 0c              jne  0x0080833b
0080832f  80 7d f1 00        cmp  byte ptr [ebp-0x0f], 0
00808333  75 06              jne  0x0080833b
00808335  80 7d f2 00        cmp  byte ptr [ebp-0x0e], 0
00808339  74 4b              je   0x00808386          ; not an upgrade button: no message
0080833b  8b 76 0c           mov  esi, [esi+0xc]      ; the CommandButton
0080833e  83 c6 70           add  esi, 0x70           ; -> PurchasedLabel
00808341  8b ce              mov  ecx, esi
00808343  e8 1c9bbfff        call 0x00401e64          ; AsciiString::isEmpty()
00808348  8b 0d 044bde00     mov  ecx, [0x00de4b04]   ; TheGameText
0080834e  84 c0              test al, al
00808350  8b 01              mov  eax, [ecx]
00808352  8d 55 b4           lea  edx, [ebp-0x4c]     ; the fetch's return slot
00808355  6a 00              push 0
00808357  75 0b              jne  0x00808364          ; empty -> the default key
00808359  56                 push esi                 ; the button's own key
0080835a  52                 push edx
0080835b  ff 50 38           call dword ptr [eax+0x38]
0080835e  c6 45 fc 15        mov  byte ptr [ebp-4], 0x15
00808362  eb 0d              jmp  0x00808371
00808364  68 e4eec400        push 0x00c4eee4          ; "TOOLTIP:AlreadyUpgradedDefault"
00808369  52                 push edx
0080836a  ff 50 3c           call dword ptr [eax+0x3c]
0080836d  c6 45 fc 16        mov  byte ptr [ebp-4], 0x16
00808371  8d 4d e8           lea  ecx, [ebp-0x18]     ; <- the nine bytes this patch replaces
00808374  50                 push eax
00808375  e8 16e7c2ff        call 0x00436a90          ; operator=  <- the loss
0080837a  8d 4d b4           lea  ecx, [ebp-0x4c]     ; <- the resume point
0080837d  c6 45 fc 06        mov  byte ptr [ebp-4], 6
00808381  e8 2ae4c2ff        call 0x004367b0          ; ~UnicodeString(the temporary)
00808386  80 7d f3 00        cmp  byte ptr [ebp-0x0d], 0
0080838a  0f 85 18030000     jne  0x008086a8          ; held: nothing else to say
```

`0x00C4EEE4` is the string `TOOLTIP:AlreadyUpgradedDefault`, and it has **exactly one** reference
in the image — the `push` at `0x00808364`. That is what makes this the site.

Both fetch arms leave the fetched `UnicodeString *` in `eax` (it is the `edx` slot they were
handed), and both converge on `0x00808371`, so the replaced window can rely on `eax` unconditionally.

## 3. The two adjacent methods

| VA | what | convention |
|---|---|---|
| `0x00436A90` | `UnicodeString::operator=(const UnicodeString &)` | `__thiscall`, one stack arg, `ret 4` |
| `0x004065FE` | `UnicodeString::concat(const UnicodeString &)` | `__thiscall`, one stack arg, `ret 4` |
| `0x00405183` | `UnicodeString::concat(const WideChar *)` | `__thiscall`, one stack arg, `ret 4` |

`operator=` is the one that loses the text, and it is explicit about it:

```
00436ade  8b ce              mov  ecx, esi
00436ae0  e8 cbfcffff        call 0x004367b0          ; ~UnicodeString(this)  <- releases
00436ae5  8b 07              mov  eax, [edi]
00436ae9  89 06              mov  [esi], eax          ; then takes the source's buffer
00436aeb  74 02              je   0x00436aef
00436aed  ff 00              inc  dword ptr [eax]     ; ...and a reference on it
```

Both `concat` forms end in the same worker at `0x00436D50` with `this` still in `ecx`, which is why
they are drop-in for each other at a call site. The literal form clobbers `eax`; the
`UnicodeString` form does too. All three take the argument on the stack and clean it themselves,
so the substitution is stack-neutral.

The `operator=` call is not unusual for this builder — `TOOLTIP:ScienceDisabled` (`0x00807D65`)
and the `DescriptLabel` fetch itself (`0x00807DD6`) both use it, correctly, because both are
*establishing* the description rather than adding to it. What is unusual is using it at
`0x00808375`, where there is already text.

## 4. The separator, and why it is guarded

Two sites in the same function append a status line to a description that may or may not already
have one, and both do it the same way:

```
0080809f  ...                                          ; CONTROLBAR:Requirements
008080ae  8b 45 e8           mov  eax, [ebp-0x18]
008080b4  3b c7              cmp  eax, edi            ; edi == 0
008080b6  74 0f              je   0x008080c7
008080b8  66 39 78 04        cmp  word ptr [eax+4], di
008080bc  74 09              je   0x008080c7
008080be  56                 push esi                 ; esi == 0x00bdbc40, L"\n"
008080bf  8d 4d e8           lea  ecx, [ebp-0x18]
008080c2  e8 bcd0bfff        call 0x00405183          ; concat(const WideChar *)
008080c7  ...
```

and again at `0x008080FB`, before `TOOLTIP:BuildDisabled`. The cave reproduces that test rather
than inventing one, which is what makes a button carrying **no** `DescriptLabel` come out
byte-identical to a stock build instead of gaining a leading blank line.

Two wide literals are available and neither is owned by any one site:

| VA | content | used by |
|---|---|---|
| `0x00BDBC40` | `L"\n"` | the Requirements and BuildDisabled folds |
| `0x00C4F008` | `L"\n\n"` | `TooltipNotEnoughMoneyToBuild`, `TooltipCannotPurchaseBecauseQueueFull` |

`--separator newline` (default) uses the first, `--separator blank-line` the second. No new data
is allocated either way.

**One trap.** The two engine folds compare against `edi`, which is the function's zero — `xor edi,
edi` at `0x00807A90`. It is **not** zero on the path that reaches `0x00808329`: `0x0080817E`
reloads it with the described `Object` (`mov edi, [ebp-0x1c]`). So the cave compares with
immediates rather than copying the `cmp ..., di` encoding.

## 5. The cave

Nine bytes at `0x00808371` become `jmp <thunk>` plus four `nop`s. The thunk `call`s the shared
routine and `jmp`s to `0x0080837A`, the destructor the window was followed by:

```
push eax                       ; the message - and already the argument for the concat below
mov  eax, [ebp-0x18]           ; the description so far
test eax, eax
je   .message
cmp  word ptr [eax+4], 0
je   .message
push 0x00bdbc40                ; L"\n"
lea  ecx, [ebp-0x18]
call 0x00405183                ; concat(const WideChar *)   - ret 4 drops the literal
.message:
lea  ecx, [ebp-0x18]
call 0x004065fe                ; concat(const UnicodeString &) - ret 4 drops the message
ret
```

The opening `push eax` does both jobs: it preserves the message across the separator call, and it
*is* the stack argument the final `concat` reads. `concat`'s own `ret 4` removes it, so the routine
needs no frame and no `pop`.

The EH state byte at `ebp-4` is left exactly as the case set it (`0x15` or `0x16`, meaning "the
temporary at `ebp-0x4c` is live"), so a throw out of either `concat` unwinds through the same
handler the stock code would have used.

## 6. `--also-blocked`

`ConflictingLabel` and `LacksPrerequisiteLabel` are handled by the case immediately above, at
`0x008082C7`, in the identical shape: `esi + 0x78` instead of `esi + 0x70`, two default keys
(`TOOLTIP:HasConflictingUpgradeDefault` at `0x00C4EF04`, `TOOLTIP:LacksPrerequisiteUpgradeDefault`
at `0x00C4EF2C`) instead of one, and the same `operator=` at `0x00808310`.

Its nine-byte window starts one instruction earlier in the *emission order*:

```
0080830c  50                 push eax
0080830d  8d 4d e8           lea  ecx, [ebp-0x18]
00808310  e8 7be7c2ff        call 0x00436a90
00808315  8d 4d b4           lea  ecx, [ebp-0x4c]     ; the resume point
```

Same length, different bytes, so the two sites are fingerprinted separately and are not
interchangeable. They share the cave's routine and differ only in the `jmp` at the end of their
thunk.

Off by default: the request this patch answers is about researched upgrades, and the blocked
messages are a judgement call about a button the player cannot press anyway.

## 7. What is deliberately left alone

`0x0080838A` still jumps to the function's exit at `0x008086A8` when the upgrade is held, so a
researched upgrade's tooltip still shows **no cost line and no requirements block**. That is
correct — there is nothing left to buy — and changing it would mean re-entering a run of code that
assumes the button is purchasable.

The `ControlBar` still draws the button unavailable, and `Player::hasUpgradeComplete` still answers
the same. Nothing here is a gate; it is text.

## 8. Determinism

The whole edit is inside the tooltip builder, which runs on hover on one client. No `GameMessage`
is emitted, no logic-side state is read or written, and the strings joined are ones the engine had
already fetched. A patched and an unpatched client can play each other and replays cross — the same
rule as `replay-outcome` and `observer-switch`, and unlike `production-condition`.

## 9. Composition

The cave is allocated with `allocate_section` past every existing section and `verify` finds it by
name. The nine (or eighteen) engine bytes rewritten are touched by no other bundled patch, and the
patch reads nothing another patch rewrites.

`hero-mana` is the only other bundled patch inside this function, at `0x008085C4`
(`DESCRIPTION_RANK_APPEND`) and `0x00808675` (`DESCRIPTION_SPECIAL_POWER_CASE`). Both are past
`0x00808371` and disjoint from it, and neither reads the description slot's contents — `hero-mana`
appends to it, which composes with this patch by construction.

## 10. Site table

| what | VA | bytes |
|---|---|---|
| already-upgraded case (fingerprint) | `0x0080833B` | 75 |
| its `operator=` window | `0x00808371` | 9 |
| its resume point | `0x0080837A` | — |
| blocked case (fingerprint) | `0x008082C7` | 90 |
| its `operator=` window | `0x0080830C` | 9 |
| its resume point | `0x00808315` | — |
| `UnicodeString::operator=` | `0x00436A90` | anchor |
| `UnicodeString::concat(const UnicodeString &)` | `0x004065FE` | anchor |
| `UnicodeString::concat(const WideChar *)` | `0x00405183` | anchor |
| `L"\n"` | `0x00BDBC40` | anchor |
| `L"\n\n"` | `0x00C4F008` | anchor |
