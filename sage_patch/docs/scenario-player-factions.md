# Per-player `DisabledFactions`

How a War of the Ring scenario decides which factions may be taken, why it cannot say **who** takes
which, and the four-call patch that lets it. Engine build `2.01.2614.37001`; every address is a VA
in that image.

## 1. What the INI can say today

A `LivingWorldCampaign`'s `Scenario` block is parsed through the field table at `0x00C7A578`,
21 rows. The three that matter here:

| row | keyword | parse fn | offset |
|---|---|---|---|
| 10 | `DefaultStartSpots` | `0x0042EED6` (`AsciiString` vector) | `+0x34` |
| 15 | `StartingRestriction` | `0x009A7DD4` | — |
| 18 | `DisabledFactions` | `0x0042EED6` (`AsciiString` vector) | `+0x40` |
| 19 | `HistoricalScenario` | `0x0042E558` (bool) | `+0xC0` |

`MaxPlayers` is `+0x10` and `MinPlayers` `+0x14`, both `0x0042EC5E`.

So `DisabledFactions` is a `std::vector<AsciiString>` at `Scenario+0x40 .. +0x44`, holding
`PlayerTemplate` **names** — `FactionMen`, `FactionAngmar` — not sides. That is confirmed by what
the comparison is handed; see §3.

`HistoricalScenario = Yes` adds the rule the shipped comments describe: every player must take a
*different* faction, and each faction's start region and team come from a `StartingRestriction`
rather than from the player. What no keyword can say is which player takes which faction.

## 2. `StartingRestriction` is not the missing piece

It looks like it should be. `0x009A7DD4` allocates `0x20` bytes, parses them through the table at
`0x00C88780`/`0x00C887C0`:

```
[0] 'Regions'   parse=0x0042eed6  offset=0x8    ; AsciiString vector
[1] 'Factions'  parse=0x009a7cb8  offset=0x4
[2] 'Teams'     parse=0x009015ce  offset=0x14   ; Int vector
```

`Factions` (`0x009A7CB8`) reads the line as an `AsciiString` vector and feeds each token to
`0x00703B8D` on the `0x14`-byte object hanging off `StartingRestriction+0x4` — a set of faction
names at `+0x8`, a team at `+0x4` (written by the post-parse fixup `0x009A7C3D` when `Teams` names
exactly one), and three flag bytes at `+0x0..+0x2`.

That set **is** consulted, by `0x00844548`:

```
esi = restriction + 8
if ([esi+4] == 0) return true            ; an empty set allows everything
copy the side name; if it does not start with "Faction" (0x00C1377C), prefix it
return map_find(esi, name) != end
```

and it is reached from the faction combo-box fill at `0x00844DDE`:

```
00844dd8  cmp  dword [ebp-0x20], 0     ; the restriction for this slot's start region
00844ddc  je   0x844e00                ; none: no per-region filter
00844dde  mov  ecx, [ebp-0x18]
00844de1  call 0x975942                ; isHistoricalScenario()
00844de6  test al, al
00844de8  jne  0x844e00                ; <-- historical: skip the filter entirely
00844dea  lea  eax, [esi+0x18]         ; PlayerTemplate::m_side
00844ded  push eax
00844dee  push dword [ebp-0x20]
00844df1  call 0x844548
```

The `jne` at `0x00844DE8` is the whole answer: in a `HistoricalScenario` the per-region faction
filter is skipped. Which is consistent — in a historical scenario the region is *derived from* the
faction, so filtering the faction by the region would be circular — but it also means
`StartingRestriction` cannot be repurposed to pin a player.

The restriction for a slot comes from `0x009759BB`, worth recording because it is the only place
the two game modes' per-start-position data are unified:

```
009759bb  getStartingRestrictionForSlot(slot):
    ebx = getGameInfo()                    ; 0x0083FF11 on [this+0x18]
    eax = ebx->getSlot(slot)                ; 0x00800B74
    esi = eax->[0x10]                       ; the slot's start position
    if (this->[0x1c] == 1) {                ; War of the Ring
        region = getRegionByIndex(esi)      ; 0x0060E8DB on [0x00DE4950]->[0xB0]
        scenario = this->[0x68]->[0x29c]->[0x1c]
        return scenario->findRestrictionForRegion(region)   ; 0x0090125B
        ; walks the StartingRestriction* vector at Scenario+0xB4..+0xB8, asks each one whether
        ; its `Regions` list holds this region's name (0x009A7C89), and returns the matching
        ; restriction's `+0x4` - the faction set / team object described above.
    }
    return &map->[0x54 + 0x14 * esi]        ; skirmish: the map's per-start-spot record
}
```

`this` here is the game-setup screen's WOTR sub-object at `screen+0x60`, whose other accessors are
`0x009758E3` (`getMaxPlayers`: `scenario->[0x10]` in WOTR, the map's player count otherwise),
`0x00975828` (`getScenarioIndex`) and `0x00975942` (`isHistoricalScenario`: `scenario->[0xC0]`).

## 3. The function with no player in it

```
0090182d  Scenario::isFactionEnabled(AsciiString side)     ; __thiscall, ret 4
    edi = [esi+0x40]                       ; DisabledFactions.begin
loop:
    if (edi == [esi+0x44]) { bl = 1; goto out }
    if (compare(&arg, edi) == 0) { bl = 0; goto out }   ; 0x004065AA
    edi += 4
    goto loop
out:
    lea ecx, [ebp+8]
    call 0x00435D50                        ; ~AsciiString - the callee owns the argument
    return bl
```

Two facts about it drive everything below.

**It takes no player.** The signature is the whole limitation. `DisabledFactions` is a property of
the scenario because the only function that reads it is a property of the scenario.

**The comparison is case-sensitive.** `0x004065AA` → `0x00406307` → `0x004052F9` →
`0x00A3D01A`, which is `jmp dword [0x00BD0698]` = **`memcmp`** in `msvcr71.dll`. The image also
imports `_memicmp` (through `0x00A3D020`), and this path does not use it. Any replacement that
folded case would start disabling factions in scenarios that load correctly today.

The companion `Scenario::hasDisabledFactions` at `0x009012D7` is just `(end - begin) != 0`.

`AsciiString` is one pointer to a buffer laid out `{ UnsignedInt refCount; UInt16 length; UInt16
allocated; char data[] }`, so the characters begin at `+8` and `str()` on a null handle is the
image's empty string at `0x00BD0C3F`. Both are used verbatim by the replacement.

## 4. Every reader of the list

`xref 0x0090182D` finds **four** direct calls and no dword references — no vtable, no table of
function pointers. All four are in the multiplayer game-setup screen, and each one already holds
the lobby slot it is asking about:

| call | in | what it decides | slot at the call |
|---|---|---|---|
| `0x0084348B` | the start-game gate | raises `GUI:DisabledFaction` and refuses to start | `[ebp-0x24]` |
| `0x00844735` | `0x008445F2`, the historical fixup | rejects a slot's duplicate or disabled pick | `[ebp-0x18]` |
| `0x008448E1` | `0x008445F2`, second pass | picks a faction for a slot left on Random | `[ebp-0x18]` |
| `0x00844E51` | `0x00844BD4`, the combo-box fill | greys and disables the entries it refuses | `[ebp+0x8]` |

Each local is established by an instruction that can be asserted, which is what makes the claim
"this is a slot index" checkable rather than asserted:

* `0x008432E2` `mov [ebp-0x24], ebx` with `ebx` zero, incremented at `0x008434A1` and bounded at 8;
  the same loop pushes `[ebp-0x24]` into `GameInfo::getSlot` at `0x008432E5`.
* `0x00844685` and `0x008447C8`, both `and dword [ebp-0x18], 0`, each opening a loop that hands
  `[ebp-0x18]` to `GameInfo::getSlot` (`0x00800B55`) and increments it at `0x00844758` /
  `0x00844941`.
* `0x00844BFB` `mov edi, [ebp+8]` / `push edi` into `getSlot`, followed at `0x00844C0F` by
  `mov edi, [esi + edi*4 + 0x334]` — the screen's array of per-slot faction windows. An argument
  that indexes both the slot list and the per-slot window array is a slot index.

Nothing else in `.text` reaches the function: the byte-wise sweep in
`TestInstalledBinary::test_those_four_are_every_caller_in_the_image` decodes an `e8` at every
offset of `.text` and finds exactly those four.

The combo-box fill is worth one more note, because it is the only site a player *sees*. It walks
`ThePlayerTemplateStore`'s list (`[0x00DE3B10]+0x18`), skips templates that are not playable
(`+0x151`) or are observers (`+0x150`), and adds each survivor to the list box with
`0x007243A6`. A faction the scenario refuses is added in the disabled colour `[0x00DADF20]` instead
of the normal one and then passed to `0x00724160(box, item, 1)`, which is what makes it
unselectable rather than merely grey. Per-slot refusal therefore needs no new UI: the entry it
produces already exists.

## 5. What the patch does

The INI surface is the `:N` qualifier on an existing entry:

```
DisabledFactions = FactionArnor FactionElves FactionMen:1 FactionAngmar:2
```

Unqualified entries keep their scenario-wide meaning. `Faction<X>:N` disables `Faction<X>` for
lobby slot `N` — counted from 1, as `Teams` and everything else in the file counts players — and is
invisible to every other slot. The form is the one `commandset-button-upgrade` already uses to pin
a button to a slot.

Choosing the value syntax over a new keyword is what keeps the patch small: the qualifier rides in
the vector the stock parser already fills, so there is no field-table relocation, no side table
keyed by `Scenario *`, and no scenario written before the patch that changes meaning. `sage_ini`
types `DisabledFactions` as `Opaque`, so nothing on the linting side needs teaching either.

Each of the four `call` instructions is replaced with a `call` into its own two-instruction
trampoline in the `.plyfac` cave:

```
site0:  mov edx, [ebp-0x24]      ; the caller's own slot local - ebp is still the caller's
        jmp match
```

A trampoline is entered by `call`, so at its first byte `ebp` is the caller's frame pointer and the
by-value argument is at `[esp+4]`. It writes only `edx`, which is volatile across a call in
`__thiscall`, and tail-jumps into the shared replacement — so nothing on the stack moves and the
replacement's `ret 4` returns to the caller exactly as the stock function's did.

The replacement walks the same vector and, for an entry whose name part matches the side name,
either answers "disabled" (no qualifier) or parses the qualifier and answers "disabled" only when
it equals `slot + 1`. It ends by destroying the argument through `0x00435D50`, because the callee
owns it; the answer waits in `bl` across that call, since the destructor clobbers `eax`.

Malformed qualifiers apply to nobody rather than falling back to everybody: a bare trailing `:`
(no digit after it), a non-numeric qualifier, and `:0` all take the next-entry edge. An INI typo
that silently disabled a faction for every player would be worse than one that disables it for
none.

No SEH frame: the replacement makes exactly one call, to the destructor, and nothing on the path to
it can throw.

## 6. What is not covered

**Nothing here has been run against the game.** The reading is static: the addresses check out, the
cave disassembles to what it was meant to say, and apply/verify round-trip — which is exactly the
`experimental` promise and no more.

Specific things a play session would settle:

1. **Whether the slot index a player sees as "player 1" is slot 0.** The four sites are all
   0-based (`getSlot(0)` is the first), and the patch adds 1 for the INI. What has not been
   observed is how the WOTR lobby *orders* slots on screen, so `:1` is claimed to mean "the first
   slot", not "the host" — those are usually the same and may not always be.
2. **The Random resolution pass.** `0x008448E1`'s loop picks the first unused, non-disabled
   template for a slot on Random. With per-slot entries it should now pick one the slot may have;
   if a slot's entries exclude everything, the pass leaves the slot unresolved and the start gate
   refuses, which is the same failure mode as a scenario that disables every faction today.
3. **What the AI slots do.** The gate at `0x00843422` runs over all eight slots without asking
   whether a slot is human, so a per-slot entry constrains an AI slot too. That is probably what a
   scripted scenario wants and has not been confirmed to be harmless.

## 7. Addresses

All of these are in [`../addresses.py`](../addresses.py).

| name | VA |
|---|---|
| `SCENARIO_IS_FACTION_ENABLED` | `0x0090182D` |
| `SCENARIO_HAS_DISABLED_FACTIONS` | `0x009012D7` |
| `SCENARIO_DISABLED_FACTIONS_BEGIN` / `_END` | `+0x40` / `+0x44` |
| `SCENARIO_FACTION_CALL_SITES` | `0x0084348B`, `0x00844735`, `0x008448E1`, `0x00844E51` |
| `MP_SETUP_START_GATE_LOOP_INIT` | `0x008432E2` |
| `MP_SETUP_DISABLED_FACTION_PUSH` | `0x008435D9` |
| `MP_SETUP_HISTORICAL_FIXUP` | `0x008445F2` |
| `MP_SETUP_VALIDATE_LOOP_INIT` | `0x00844685` |
| `MP_SETUP_RANDOM_LOOP_INIT` | `0x008447C8` |
| `MP_SETUP_FACTION_COMBO` | `0x00844BD4` |
| `MP_SETUP_FACTION_COMBO_SLOT_ARG` | `0x00844BFB` |
| `MP_SETUP_FACTION_COMBO_SLOT_WINDOW` | `0x00844C0F` |

Named here and not in `addresses.py`, because only this document uses them:

| what | VA |
|---|---|
| the `Scenario` field-parse table | `0x00C7A578` |
| `StartingRestriction`'s parse fn / field table | `0x009A7DD4` / `0x00C887C0` |
| `StartingRestriction::isFactionAllowed` | `0x00844548` |
| `Scenario::findRestrictionForRegion` | `0x0090125B` |
| `getStartingRestrictionForSlot` | `0x009759BB` |
| `isHistoricalScenario` / `getMaxPlayers` / `getScenarioIndex` | `0x00975942` / `0x009758E3` / `0x00975828` |
| `AsciiString::compare` and the `memcmp` thunk | `0x004065AA` / `0x00A3D01A` |
| `PlayerTemplate::getName` | `0x00627707` |
| the list box's add-item and disable-item | `0x007243A6` / `0x00724160` |
