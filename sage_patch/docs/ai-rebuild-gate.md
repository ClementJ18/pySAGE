# Stopping the AI casting its rebuild spell on a building that is still going up

The reverse-engineering behind
[`patches/ai_rebuild_gate.py`](../patches/ai_rebuild_gate.py). ROTWK
`game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, md5
`daed3668006cd90f01c34e5a7da1901f`, recovered statically 2026-09-22.

## TL;DR

- `SpecialPowerAIType` is an index into the 53-name table at **`0x00DB84F8`**.
  `AI_SPELLBOOK_REBUILD` is index **31**.
- A factory at **`0x0099272E`** switches on that index and builds one behaviour object per type.
  Case 31 allocates `0x2C` bytes and runs the constructor at **`0x009E770B`**, which stamps
  vtable **`0x00C8DEEC`**.
- Slot 7 of that vtable, **`0x009E7744`**, is the type's target picker. Nothing else in `.text`
  points at it, so it *is* `AI_SPELLBOOK_REBUILD` and nothing else.
- It walks `TheSkirmishAIManager`'s per-player **structure** list and accepts the **first** entry
  whose `Body::getHealthRatio()` is **below 0.5**. That is the whole test: no status check, no
  "is it worth a spell" check, and not even a most-damaged-first ordering.
- A structure under construction sits at **one hit point** from the moment its foundation is
  placed ([`construction-initial-health.md`](construction-initial-health.md) §"What the engine
  does today"), so its ratio is ~0 and it wins that test against every real casualty on the map.
- The fix: one 6-byte hook at **`0x009E777C`**, the `mov ecx, [ebx+0x25C]` that fetches the
  candidate's body, into a cave that asks `Object::testStatus(UNDER_CONSTRUCTION)` first and
  jumps to the loop's own next-candidate edge when the bit is set.
- **AI-only by construction** — the picker is a `SkirmishAI` vtable slot with no player-facing
  caller, so like [`ai-construction-gate`](ai-construction-gate.md) and unlike
  [`ai-revive-gate`](ai-revive-gate.md) it needs no return-address discrimination.

## 1. From the keyword to the code

### The keyword

`SpecialPowerAIType` is row 1 of the `AISpecialPowerUpdate` field table at `0x00C6DAD0`,
parse function `0x00992693`, struct offset `0xC`:

```
[ 0] 'CommandButtonName'          parse=0x0042EE5E  offset=0x8
[ 1] 'SpecialPowerAIType'         parse=0x00992693  offset=0xC
[ 2] 'SpecialPowerRadius'         parse=0x0042ED00  offset=0x10
[ 3] 'SpecialPowerRange'          parse=0x0042ED00  offset=0x14
[ 4] 'RandomizeTargetLocation'    parse=0x0042E558  offset=0x18
[ 5] 'SpellMakesAStructure'       parse=0x0042E558  offset=0x19
```

The parse function is a plain linear name search and stores the **index**, with no bias:

```asm
009926ca  push dword [esi*4 + 0xdb84f8]   ; the name table
009926d4  call ASCII_STRING_CTOR
009926dd  call 0x406585                   ; case-insensitive compare
009926f7  cmp  esi, 0x35                  ; 53 names
009926fe  mov  [ebp-0x14], esi            ; matched -> store the index
```

`0x00DB84F8` is the table base (`0x00DB84F8 + 31*4 = 0x00DB8574` holds `0x00C87A24`,
`"AI_SPELLBOOK_REBUILD"`), so the type is **31**.

### The factory

`0x0099272E` takes the index and returns a freshly-allocated behaviour:

```asm
0099272e  mov  eax, [ebp+8]
00992732  push 0x34 / pop esi
00992735  cmp  eax, esi
00992737  ja   0x992eef                   ; out of range -> NULL
0099273d  jmp  dword [eax*4 + 0x992efe]   ; 53 cases
```

Case 31 (`0x00992F7A` holds `0x00992D50`):

```asm
00992d50  push 0x2c
00992d52  call OPERATOR_NEW
00992d5f  mov  dword [ebp-4], 0x29
00992d6c  call 0x9e770b                   ; the AI_SPELLBOOK_REBUILD constructor
```

and the constructor is three instructions, one of which is the vtable:

```asm
009e770b  push esi
009e770c  mov  esi, ecx
009e770e  call 0xa01c6b                   ; base class
009e7713  mov  dword [esi], 0xc8deec      ; the vtable
```

Vtable `0x00C8DEEC` is eight slots. Slots 1–6 are shared with every other spellbook behaviour
(`0x00993019`, `0x009E93C8`, `0x00993024`, `0x00490AC4`, `0x0063F3BF`, `0x00A01C54`); slot 0 is
the scalar-deleting destructor and **slot 7, `0x009E7744`, is the only one this class owns**.
`xref 0x009E7744` finds exactly one dword reference — `0x00C8DF08`, that vtable slot — and no
direct branches. The function is reachable only as `AI_SPELLBOOK_REBUILD`'s picker.

### Who calls slot 7

The shared cast step at `0x00993055`:

```asm
00993055  push esi
00993056  fld1
00993058  push 0x71                       ; line 113 of
0099305a  push 0xc87e90                   ;   ...\SkirmishAI\AISpecialPowers\AISPecialPower.cpp
0099305f  push ecx / push ecx
00993061  fstp dword [esp+4]              ; hi = 1.0
00993067  fldz
00993069  fstp dword [esp]                ; lo = 0.0
0099306c  call 0x6d332c                   ; the logic RNG
00993071  fld  dword [0xbd869c]           ; 0.5
0099307c  fcomip st(1)
00993080  jbe  0x99309d                   ; tails -> "not this tick", return false
00993094  mov  eax, [esi]
00993096  mov  ecx, esi
00993098  call dword [eax+0x1c]           ; slot 7 - the type's picker
```

So every tick the behaviour is asked, it flips a logic-deterministic coin and only on heads does
it ask the type where to aim. That matters for the defect's rate, not its existence.

## 2. The picker, in full

```asm
009e7744  push ebx / push ebp / push esi
009e7747  mov  ebp, ecx                   ; the behaviour object
009e7749  mov  ecx, [esp+0x10]            ; arg: the caster Object
009e774e  call OBJECT_GET_CONTROLLING_PLAYER
009e7753  mov  ecx, [0xde4938]            ; TheSkirmishAIManager
009e7759  push eax
009e775a  call 0x6a9999                   ; its per-player record
009e775f  mov  ecx, [eax+8]               ; the record's structure list
009e7762  call 0x72b229                   ; -> &vector
009e7767  mov  edi, eax
009e7769  mov  esi, [edi]                 ; begin
009e776b  jmp  0x9e7796

009e776d  push dword [esi]                ; candidate ObjectID
009e776f  mov  ecx, [0xde412c]            ; TheGameLogic
009e7775  call GAME_LOGIC_FIND_OBJECT_BY_ID
009e777a  mov  ebx, eax
009e777c  mov  ecx, [ebx+0x25c]           ; Object::m_body           <- the hook site
009e7782  mov  eax, [ecx]
009e7784  call dword [eax+0x14]           ; Body::getHealthRatio
009e7787  fld  dword [0xbd869c]           ; 0.5
009e778d  fcomip st(1)
009e778f  fstp st(0)
009e7791  ja   0x9e77a4                   ; 0.5 > ratio -> take this one
009e7793  add  esi, 4
009e7796  cmp  esi, [edi+4]               ; end
009e7799  jne  0x9e776d
009e779b  xor  al, al                     ; nothing below half health
009e779d  pop edi / pop esi / pop ebp / pop ebx
009e77a1  ret  4

009e77a4  push dword [esp+0x14]
009e77a8  add  ebx, 0x38                  ; &Object::m_position
009e77ab  mov  ecx, ebp
009e77ae  call 0xa0229f                   ; set the behaviour's target position
009e77b3  jmp  0x9e779d
```

Three things are worth stating plainly about that loop.

**The test is a bare health ratio.** `Body::getHealthRatio` is vtable slot `+0x14`
(`BODY_GET_HEALTH_RATIO_SLOT`), `0x00BD869C` holds `0.5f`, and `df f1` is `fcomip st(1)` — it
compares `0.5` against the ratio and pops, so `ja` is taken when **ratio < 0.5**. Nothing else is
asked about the candidate.

**It takes the first match, not the worst.** There is no running minimum; the loop returns on the
first candidate under half health, in whatever order the AI's structure list happens to hold.

**There is no null guard.** `findObjectByID` can return NULL and `mov ecx, [ebx+0x25C]` would
fault on it. That is stock behaviour and this patch does not change it — see §5.

### What is in that list

`0x006A9999` is `TheSkirmishAIManager`'s per-player record lookup (`[player+0x54]` is the player
index, into the `std::map` at `[manager+0xA3C]`, value at `+0x14`). The record's `+8` is the
structure list, and the predicate that decides what enters it is `0x0099E8C8`:

| test | KindOf | effect |
|---|---|---|
| `test [tmpl+0x10C], 0x400000` then `[tmpl+0x120], 0x1000000` | `UNATTACKABLE`, `EXPANSION_PAD` | unattackable things only if they are expansion pads |
| `test byte [tmpl+0x118], 4` then `cl, 0x40` | `NOT_AUTOACQUIRABLE`, `REBUILD_HOLE` | not-autoacquirable things only if they are rebuild holes |
| `test byte [tmpl+0x108], 0x80` | `STRUCTURE` | **required** |
| `test byte [tmpl+0x120], 0x10` | `ECONOMY_STRUCTURE` | rejected |
| `test [tmpl+0x10C], 0x40000` | `LINKED_TO_FLAG` | rejected |
| `test [tmpl+0x114], 0x1000000` | `BASE_SITE` | rejected |

So: the player's own military structures, plus rebuild holes and expansion pads, minus economy
buildings, plot flags and base sites. Every one of them is a structure, which is why the symptom
is always a building.

## 3. Why a construction site always wins

[`construction-initial-health.md`](construction-initial-health.md) records the four sites that
drive a structure about to be built to exactly **one hit point** — `BuildAssistant`'s placement
(`0x0079541F`), the builder dropping a foundation (`0x008AD88E`), `GettingBuiltBehavior`'s
rebuild (`0x00858975`) and the `DozerAIUpdate` restart (`0x0088D59E`) — and the two ramps that
climb from there over the build. A structure is therefore below half health for the **first half
of every build**, and at ratio ~0 for the moment before a builder reaches it.

The AI's structure list carries it the whole time: `AIPlayer`'s structure-created hook files a
new object the frame it is placed (`0x008F06CE`, §"The index is built the frame the foundation
goes down" in [`ai-construction-gate.md`](ai-construction-gate.md)), and this list's own
predicate above asks only about the template.

So from the player's side the spell lands on scaffolding. Casting it there is a waste in both
directions: the construction ramp keeps adding `maxHealth / frames` per frame regardless, so the
spell buys no time on the build, and the charge is gone when the thing it exists for — a citadel
being torn down — comes up a minute later.

In Edain the affected spells are the ones whose `AISpecialPowerUpdate` names this type:
`Command_SpellBookBaumeisterGondors` and `Command_SpellBookBaumeisterArnors` (both
`SpecialPower = SpellBookRebuild`), `Command_SpellBookBeistandinderNotNormal` and
`Command_SpellBookDruedainAllies`.

## 4. The patch

One hook, one cave, one added test.

| | |
|---|---|
| hook | `0x009E777C`, the 6 bytes `8b 8b 5c 02 00 00` (`mov ecx, [ebx+0x25C]`) |
| becomes | `jmp rel32` into the cave + one `nop` |
| cave | `.airbld`, allocated past every existing section |

```asm
push 2                        ; ObjectStatus::UNDER_CONSTRUCTION
mov  ecx, ebx                 ; the candidate Object
call OBJECT_TEST_STATUS       ; 0x0044DDEC
test al, al
jne  still_going_up
mov  ecx, [ebx+0x25c]         ; the displaced instruction
jmp  0x009E7782               ; back into the stock body
still_going_up:
jmp  0x009E7793               ; the loop's own next-candidate edge
```

**Why `ebx`.** `ebx` is the object `findObjectByID` just returned, two instructions above the
hook, and is the same register the displaced instruction indexes. `esi` is the list iterator and
`edi` the vector; testing either would read a status mask off a `std::vector`.

**Why the rejection edge is `0x009E7793` and not a `ret`.** Skipping the candidate leaves the
loop free to find a genuinely damaged building further down the list. Returning false instead
would mean one construction site anywhere on the map suppressed the spell entirely.

**Register safety.** `Object::testStatus` (`0x0044DDEC`) is `__thiscall` with one stack argument
and `ret 4`. Its body pushes and pops `esi` and touches only `eax`, `ecx` and `edx` besides — so
`ebx`, `esi`, `edi` and `ebp` all survive, and `ecx` is reloaded by the displaced instruction
after the call. The x87 stack is untouched, which matters because the resume point at
`0x009E7782` is the load of the body vtable for a call that returns on `st(0)`.

**Determinism.** `Object::m_status` is logic state, xfer'd into saves and replays and covered by
the frame CRC, so the added edge is identical on every peer. The `SkirmishAI` runs on the logic
thread on every peer, so a non-deterministic gate here would desync rather than merely misbehave
— which is why the bit is tested and not the `ACTIVELY_BEING_CONSTRUCTED` model condition, which
names the same state more precisely on the client side only.

**Logic-side, so every peer needs the same binary.** No INI change: nothing here adds a keyword
or reads one.

### Anchors

The chain from the keyword to the hooked function is *derived* rather than asserted, so a build
that moved any link fails to apply instead of jumping somewhere plausible:

| anchor | asserts |
|---|---|
| `0x00C87A24` = `"AI_SPELLBOOK_REBUILD"` | the name |
| `0x00DB8574` = `0x00C87A24` | it is index 31 of the name table |
| `0x00992F7A` = `0x00992D50` | the factory's case for index 31 |
| `0x00992D6C` = `e8 9a 49 05 00` | that case calls `0x009E770B` (decoded, not written down) |
| `0x009E770B` = `56 8b f1 e8 58 a5 01 00 c7 06 ec de c8 00` | that constructor stamps vtable `0x00C8DEEC` |
| `0x00C8DF08` = `0x009E7744` | vtable slot 7 is the function being hooked |
| `0x009E7744` = `53 55 56 8b e9` | the picker's prologue |
| `0x009E7782` = `8b 01 ff 50 14 d9 05 9c 86 bd 00 df f1 dd d8 77 11` | the resume point, through the `0.5` compare and the accept branch |
| `0x009E7793` = `83 c6 04 3b 77 04 75 d2` | the next-candidate edge and the loop |
| `0x0044DDEC` = `8b 54 24 04` | `Object::testStatus` |

## 5. What this deliberately does not do

- **No null guard.** The stock loop dereferences `findObjectByID`'s result without checking it,
  and so does the cave — the added `testStatus` would fault on NULL exactly one instruction
  before the stock code does. Adding the guard would be a second, unrequested fix.
- **No change to the 0.5 threshold, the first-match ordering or the coin flip.** Those are the
  spell's tuning, and the complaint is not about tuning.
- **Rebuild holes and re-builds are skipped too.** A structure being rebuilt from a hole carries
  `UNDER_CONSTRUCTION` as well, so the gate covers it. That is the same waste for the same
  reason, but it is worth naming because "under construction" in the ticket meant a fresh
  foundation.
- **Nothing on the player's side moves.** The picker is a `SkirmishAI` vtable slot; a human
  casting the same spell never reaches it.

## 6. Status

**Runtime-verified in game**, 2026-09-22. The assembly is written against the disassembly
above, the patch applies to a clean `game.dat` and `sage-patch verify` confirms it, the cave is
executed under Unicorn in `tests/sage_patch/test_ai_rebuild_gate.py` against the engine's own
`testStatus` bytes — both edges, with the status mask planted — and it has since been played,
which is what moved it out of `patches/experimental/`.

## 7. Composition

The six bytes at `0x009E777C` are touched by no other bundled patch — nothing else in
`sage_patch` reads or writes anything in `0x009E`. The cave is allocated by name past every
existing section, so the patch is order-independent.

Worth naming, because it reads like a conflict and is not:
[`construction-initial-health`](construction-initial-health.md) raises the health a structure
starts its build at. With `--percent 10` a fresh foundation sits at ratio 0.1, still under 0.5,
so it remains a target for the stock picker — the two patches address the same symptom from
opposite ends and neither subsumes the other. They share no bytes.
