# `TheMessageStream` — the order-injection path, and the authoritative `MSG_*` enum

Static recovery from RotWK 2.01 `game.dat` (ImageBase `0x400000`), 2026-07-29. No runtime
needed: everything below was re-derived from the shipped binary with `pefile` + `capstone`
via [`../scripts/pe.py`](../scripts/pe.py).

**Verdict up front.** Both halves of unknown 4 in [`live-api.md`](../../docs/live-api.md) §9 are
solved. The message-stream append path is a **one-line hook** — a virtual call through a single
global — and the complete `GameMessage::Type` enum is recovered with **147 network message
names**, which closes OPEN 10 in [`order_space_map.md`](../../sage_replay/order_space_map.md).

The enum was the stated entry point; the append API is the thing that actually unblocks M2.

## 1. The append API — the hook target

Every order the engine issues goes through this idiom. Taken verbatim from the `MSG_LOGIC_CRC`
emitter at `0x62E7FD`, which is the per-100-frame heartbeat the replay header calls
`REPLAY_CRC_INTERVAL`:

```asm
0062e7fd  mov  ecx, dword ptr [0x00de6398]   ; TheMessageStream
0062e803  mov  eax, dword ptr [ecx]          ; its vtable
0062e805  push 0x44a                         ; GameMessage::Type = MSG_LOGIC_CRC
0062e80a  call dword ptr [eax + 0x48]        ; appendMessage(type) -> GameMessage* in eax
0062e80d  mov  ebx, eax
0062e80f  push edi                           ; then one call per argument, in order
0062e810  mov  ecx, ebx
0062e812  call 0x7111e5                      ;   appendIntegerArgument
0062e817  push dword ptr [esi + 0x38]
0062e81a  mov  ecx, ebx
0062e81c  call 0x7111b5                      ;   appendTimestampArgument
```

| fact | value | evidence |
|---|---|---|
| **`TheMessageStream` global** | `0x00DE6398` | `mov ecx,[0xde6398]` appears **282×** in `.text` |
| **`appendMessage`** | **vtable slot `+0x48`** (index 18) | **232** of those 282 sites call `[eax+0x48]` immediately after |
| return | `GameMessage *` in `eax` | every site moves `eax` to a callee-saved register, then appends arguments through it |

That 232/282 concentration is the whole proof: one global, one vtable slot, used by nearly every
site that touches the stream. The remaining 50 are other `MessageStream` methods.

**Consequence for `sage_live` M2.** The bridge does not need to find or reimplement anything — it
resolves `[0x00DE6398]`, reads the vtable, and calls slot `+0x48` exactly as the engine does, then
appends arguments with the helpers in §2. Orders entering this way are network-ordered and
check-summed like any human input, which is the rule [`ml-agent.md`](../../docs/ml-agent.md) §4
sets for staying desync-safe.

## 2. `GameMessage::append*Argument` — one helper per argument type

Each helper calls the allocator at `0x7110B3`, stores the value at `+0x08`, and writes its type
tag to `+0x18`. **The tags are exactly `sage_replay.OrderArgumentType`** — independent
confirmation of an enum that was until now inherited from Generals rather than verified here.

| address | tag | `OrderArgumentType` | calls | store idiom |
|---|---|---|---|---|
| `0x7110EA` | 1 | `Float` | 11 | `movss [eax+8], xmm0` |
| `0x711104` | 2 | `Boolean` | 52 | `mov byte ptr [eax+8], cl` |
| `0x71111A` | 3 | `ObjectId` | 95 | `mov dword ptr [eax+8], ecx` |
| `0x711130` | 4 | `DrawableId` | 5 | `mov dword ptr [eax+8], ecx` |
| `0x711146` | 5 | `TeamId` | 4 | `mov dword ptr [eax+8], ecx` |
| `0x71115C` | 6 | `Position` | 37 | `movsd` ×4 (16 bytes) |
| `0x711179` | 7 | `ScreenPosition` | 25 | `mov dword ptr [eax+8], edx` |
| `0x711197` | 8 | `ScreenRectangle` | 6 | `movsd` ×4 (16 bytes) |
| `0x7111B5` | 9 | `Timestamp` | 10 | `mov dword ptr [eax+8], ecx` |
| `0x7111CB` | 10 | `WideChar` | 6 | `mov word ptr [eax+8], cx` |
| `0x7111E5` | 0 | `Integer` | 236 | `mov dword ptr [eax+8], ecx` |

The read shapes match `OrderArgumentType`'s docstring precisely — Boolean one byte, WideChar two,
Position and ScreenRectangle a run of four 4-byte words, everything else four bytes.

**Argument node layout**, from the allocator at `0x7110B3`:

```
size 0x1C (28 bytes), vtable 0x00C1FD00
  +0x00  vtable
  +0x04  next          ; singly-linked, appended at the tail
  +0x08  value         ; 1/2/4/16 bytes by tag
  +0x18  type tag      ; OrderArgumentType
```

And on the `GameMessage` itself: `+0x1C` is the argument-list **head**, `+0x20` the **tail** —
the allocator writes both when the list is empty and only the tail's `next` otherwise.

## 3. The complete `GameMessage::Type` enum

Recovered from `getCommandTypeAsAsciiString` at `~0x711200`. It is a three-way dispatch:

```asm
00711244  mov  eax, 0x3e9
00711249  cmp  edi, eax
0071124b  jg   0x7117c4          ; > 1001  -> table 2
00711251  je   0x7117ba          ; == 1001 -> standalone case
00711257  lea  eax, [edi - 0x24] ; 36..170 -> table 1
0071125a  cmp  eax, 0x86
0071125f  ja   0x711d32          ; default
00711265  jmp  dword ptr [eax*4 + 0x7123ef]
...
007117c4  lea  eax, [edi - 0x3ea] ; 1002..1147 -> table 2
007117ca  cmp  eax, 0x91
007117d5  jmp  dword ptr [eax*4 + 0x71260b]
```

- table 1 @ `0x7123EF`, 135 entries → enum **36..170** (keyboard/UI metas), 135/135 resolved
- standalone case @ `0x7117BA` → enum **1001**
- table 2 @ `0x71260B`, 146 entries → enum **1002..1147**, all resolved

**404** `MSG_*` string literals exist in `.rdata` (`0xC1FDE8`–`0xCA7D80`), pooled in reverse enum
order; **381** are referenced exactly once each, by a `push` in its own case body.

**The enum value *is* the replay order id, with no offset.** `0x3E9` →
`MSG_CREATE_SELECTED_GROUP` is the anchor, and the three ten-element team runs
(`CREATE_TEAM0..9` at `0x3EE`, `SELECT_TEAM0..9` at `0x3F8`, `ADD_TEAM0..9` at `0x402`) land on
exact decade boundaries — an off-by-anything would break all three at once.

### Network message range (1001–1147)

| id | name | id | name |
|---|---|---|---|
| `0x3E9` | `MSG_CREATE_SELECTED_GROUP` | `0x435` | `MSG_DO_STOP` |
| `0x3EA` | `MSG_CREATE_SELECTED_GROUP_NO_SOUND` | `0x436` | `MSG_DO_SCATTER` |
| `0x3EB` | `MSG_CREATE_SELECTED_GROUP_IDLE_WORKER_VOICE` | `0x437` | `MSG_OPEN_GATE` |
| `0x3EC` | `MSG_DESTROY_SELECTED_GROUP` | `0x438` | `MSG_DO_CHEER` |
| `0x3ED` | `MSG_REMOVE_FROM_SELECTED_GROUP` | `0x439` | `MSG_CLOSE_GATE` |
| `0x3EE`–`0x3F7` | `MSG_CREATE_TEAM0..9` | `0x43A` | `MSG_SWITCH_WEAPONS` |
| `0x3F8`–`0x401` | `MSG_SELECT_TEAM0..9` | `0x43B` | `MSG_CONVERT_TO_CARBOMB` |
| `0x402`–`0x40B` | `MSG_ADD_TEAM0..9` | `0x43C` | `MSG_CAPTUREBUILDING` |
| `0x40C` | `MSG_DO_ATTACKSQUAD` | `0x43D` | `MSG_CASTLE_UNPACK` |
| `0x40D` | `MSG_DO_WEAPON` | `0x43E` | `MSG_CASTLE_PACK` |
| `0x40E` | `MSG_DO_WEAPON_AT_LOCATION` | `0x43F` | `MSG_CASTLE_UNPACK_EXPLICIT_OBJECT` |
| `0x40F` | `MSG_DO_WEAPON_AT_OBJECT` | `0x440` | `MSG_SNIPE_VEHICLE` |
| `0x410` | `MSG_DO_SPECIAL_POWER` | `0x441` | `MSG_DO_SPECIAL_POWER_OVERRIDE_DESTINATION` |
| `0x411` | `MSG_DO_SPECIAL_POWER_AT_LOCATION` | `0x442` | `MSG_DO_SALVAGE` |
| `0x412` | `MSG_DO_SPECIAL_POWER_AT_OBJECT` | `0x443` | `MSG_CLEAR_INGAME_POPUP_MESSAGE` |
| `0x413` | `MSG_SET_RALLY_POINT` | `0x444` | `MSG_PLACE_BEACON` |
| `0x414` | `MSG_PURCHASE_SCIENCE` | `0x445` | `MSG_REMOVE_BEACON` |
| `0x415` | `MSG_QUEUE_UPGRADE` | `0x446` | `MSG_SET_BEACON_TEXT` |
| `0x416` | `MSG_CANCEL_UPGRADE` | `0x447` | `MSG_SET_REPLAY_CAMERA` |
| `0x417` | `MSG_QUEUE_UNIT_CREATE` | `0x448` | `MSG_SELF_DESTRUCT` |
| `0x418` | `MSG_CANCEL_UNIT_CREATE` | `0x449` | `MSG_CREATE_FORMATION` |
| `0x419` | `MSG_FOUNDATION_CONSTRUCT` | `0x44A` | `MSG_LOGIC_CRC` |
| `0x41A` | `MSG_DOZER_CONSTRUCT` | `0x44B` | `MSG_SET_MINE_CLEARING_DETAIL` |
| `0x41B` | `MSG_DOZER_CANCEL_CONSTRUCT` | `0x44C`–`0x44F` | `MSG_DO_USER1..4` |
| `0x41C` | `MSG_SELL` | `0x450` | `MSG_MOVE_ARMY_TO_POSITION` |
| `0x41D` | `MSG_EXIT` | `0x451` | `MSG_AUTO_SAVE` |
| `0x41E` | `MSG_EVACUATE` | `0x452` | `MSG_CHANGE_CAMERA_ARRIVED_AT_WAYPOINTID` |
| `0x41F` | `MSG_EVACUATE_CONTESTERS` | `0x453` | `MSG_HORDE_TOGGLE_FORMATION` |
| `0x420` | `MSG_SACRIFICE` | `0x454` | `MSG_ONE_RING` |
| `0x421` | `MSG_COMBATDROP_AT_LOCATION` | `0x455` | `MSG_CREW_EVACUATE` |
| `0x422` | `MSG_COMBATDROP_AT_OBJECT` | `0x456` | `MSG_DO_SPELLBOOK_SPECIAL_POWER` |
| `0x423` | `MSG_COMBINE_HORDES_WITH_OBJECT` | `0x457` | `MSG_WEAPONSET_TOGGLE` |
| `0x424` | `MSG_AREA_SELECTION` | `0x458` | `MSG_DO_AUTO_ABILITY` |
| `0x425` | `MSG_DO_ATTACK_OBJECT` | `0x459` | `MSG_DO_AUTO_ABILITY_WEAPON` |
| `0x426` | `MSG_DO_FORCE_ATTACK_OBJECT` | `0x45A` | `MSG_REVIVE` |
| `0x427` | `MSG_DO_FORCE_ATTACK_GROUND` | `0x45B` | `MSG_TOGGLE_NO_AUTO_ACQUIRE` |
| `0x428` | `MSG_GET_REPAIRED` | `0x45C` | `MSG_WAKE_AUTO_PICKUP` |
| `0x429` | `MSG_GET_HEALED` | `0x45D` | `MSG_START_SELF_REPAIR` |
| `0x42A` | `MSG_DO_REPAIR` | `0x45E` | `MSG_SUMMON_REINFORCEMENTS` |
| `0x42B` | `MSG_RESUME_CONSTRUCTION` | `0x45F` | `MSG_CALL_IN_REINFORCEMENTS` |
| `0x42C` | `MSG_ENTER` | `0x460` | `MSG_HORDE_SET_FORMATION` |
| `0x42D` | `MSG_DOCK` | `0x461` | `MSG_CREATE_SELECT_ALL_GROUP` |
| `0x42E` | `MSG_HARVEST` | `0x462` | `MSG_ENABLE_RETALIATION_MODE` |
| `0x42F` | `MSG_DO_MOVETO` | `0x463` | `MSG_WALL_HUB_CONSTRUCT_SPAN` |
| `0x430` | `MSG_DO_ATTACKMOVETO` | `0x464` | `MSG_DO_MOVETO_FORMATION` |
| `0x431` | `MSG_DO_FORCEMOVETO` | `0x465` | `MSG_DO_MOVE_AND_ORIENTATE_OBJECTTO` |
| `0x432` | `MSG_ADD_WAYPOINT` | `0x466` | `MSG_GIVE_MONEY` |
| `0x433` | `MSG_DO_GUARD_POSITION` | `0x467` | `MSG_DO_ROTATE_FIRINGARC` |
| `0x434` | `MSG_DO_GUARD_OBJECT` | `0x468` | `MSG_CHANGE_STANCE` |
| `0x469` | `MSG_CHANGE_ORDERMODE` | `0x46E` | `MSG_START_NEIGHBORHOOD_REPAIR` |
| `0x46A` | `MSG_ACTIONQUEUE_EXECUTE_PLANNED` | `0x46F` | `MSG_CANCEL_NEIGHBORHOOD` |
| `0x46B` | `MSG_ACTIONQUEUE_CLEAR_ALL` | `0x470` | `MSG_ORDER_SYNCHRONIZE` |
| `0x46C` | `MSG_ACTIONQUEUE_CLEAR_PLANNED` | `0x471` | `MSG_ADD_ALL_FACTION_UPGRADE` |
| `0x46D` | `MSG_ACTIONQUEUE_CLEAR_LAST` | `0x472`–`0x47B` | `MSG_ADD_TO_TEAM0..9` |

## 4. Cross-check against `order_space_map.md`

**Confirmed, no change needed.** `0x3E9` select, `0x3EC` deselect, `0x410`/`0x411`/`0x412` the
three cast shapes, `0x413` rally, `0x414` spellbook purchase (`MSG_PURCHASE_SCIENCE`), `0x415`
research (`MSG_QUEUE_UPGRADE`), `0x417` recruit (`MSG_QUEUE_UNIT_CREATE`), `0x41B` cancel build,
`0x41C` sell, `0x41D` exit, `0x41E` evacuate, `0x424` band-box, `0x42F` move, `0x448` leave game,
`0x44A` CRC heartbeat, `0x457` weapon-set toggle, `0x463` wall span, `0x468` stance.

Two provisional 🟡 entries are now confirmed outright: **`0x416`** `MSG_CANCEL_UPGRADE` and
**`0x418`** `MSG_CANCEL_UNIT_CREATE`.

**Vindicated inference.** `0x43F` is `MSG_CASTLE_UNPACK_EXPLICIT_OBJECT` — the map derived
"unpack / build at a selected plot" purely from replay evidence and ground-truth watching, and
guessed the raw id was "Generals `MSG_DO_SALVAGE` repurposed". The behaviour reading was exactly
right; the id is a genuine BFME2 addition, and `MSG_DO_SALVAGE` lives separately at `0x442`.

**Three corrections.**

| id | map says | binary says | note |
|---|---|---|---|
| `0x419` | "Generals `MSG_DOZER_CONSTRUCT` signature" | **`MSG_FOUNDATION_CONSTRUCT`** | the *meaning* (placement-UI build) is right; only the Generals name attribution was off. `MSG_DOZER_CONSTRUCT` is `0x41A`, which the map already reads correctly as the mobile-builder case |
| `0x444` | "camera jump (Generals `MSG_SET_REPLAY_CAMERA` raw id + signature)" 🟡 | **`MSG_PLACE_BEACON`** | `MSG_SET_REPLAY_CAMERA` is `0x447`. A beacon also carries a Position, so the observed `(Position)` signature stays consistent. That message is telemetry *out* rather than a way to drive the camera — see [`camera-control.md`](camera-control.md), which does it with one call on `TheTacticalView` instead |
| `0x473`/`0x474`/`0x475` | "all-client echoes … prime **fortress-destroyed / defeat-event** candidate" 🟡 | **`MSG_ADD_TO_TEAM1/2/3`** | the fortress-destroyed hypothesis is **refuted**. The names are ground truth; the observed behaviour (every client emitting the same ObjectId within 1–2 frames, only in the final minutes) is *not* explained by a control-group add and needs revisiting |

**Two ❓ entries newly named**, both fitting their observed behaviour well:

- **`0x453`** → `MSG_HORDE_TOGGLE_FORMATION`. The map records "exactly 17 per player at decided
  ends" — a formation toggle is a plausible end-of-game sweep but this is not yet explained.
- **`0x469`** → `MSG_CHANGE_ORDERMODE`. The map's "modal-state bracket, only `(1,0)` enter and
  `(0,1)` exit ever occur" is precisely an order-mode enter/exit. This one is effectively solved.

Also newly visible and relevant to existing work: **`0x45A` `MSG_REVIVE`** exists as its own
message, distinct from the `0x417` flag=True command-slot path the map documents for hero
recruits; and **`0x454` `MSG_ONE_RING`**.

## 4a. The injection hook site — M2 needs a patch, not a DLL

Injecting an order needs somewhere to call `appendMessage` **from**: a per-frame callback on
the logic thread. That site is now identified, and it means M2 can be a pure `sage_patch`
byte patch with no DLL, no injector and no proxy library.

**`GameLogic::update` is at `0x0062E4E8`**, and it carries the logic tick:

```asm
0062e4e8  mov  eax, 0xB841DA     ; <-- the entry, and the hook site
0062e4fa  mov  esi, ecx          ; esi = the GameLogic `this`
...
0062e571  je   0x62e57a          ; not advancing -> skip
0062e575  jne  0x62e57e          ; paused -> skip
0062e577  inc  dword ptr [esi+0x40]   ; <-- the frame counter, once per logic frame
```

That confirms `+0x40` is the frame counter from the write side, having been found from the
read side in [`live-object-model.md`](live-object-model.md).

**Do not hook the tick itself.** `inc dword ptr [esi+0x40]` is `FF 46 40` — three bytes, too
short for a `jmp rel32`, and the next instruction at `0x62E57A` is the target of the `je`
above it, so the five bytes cannot be taken without breaking that branch.

### ⚠ The function is virtual — do not look for it by following calls

`GameLogic::update` is dispatched through a **vtable slot at `0x00BD85C4`**. It therefore has
**no `call rel32` xrefs at all**, and the obvious derivation — "the nearest call target at or
below the frame tick" — silently returns an unrelated function **2195 bytes earlier** at
`0x0062DCE4`.

That wrong site was hooked first, and the failure mode is worth recording because it looks
exactly like success: the patch applies, `verify` passes, the five bytes are correct, the cave
is byte-perfect in memory, and the game runs normally. It simply never fires, because nothing
calls that function per frame. It was caught only by injecting an order and watching the
`ready` flag stay set while the frame counter advanced.

**Find the entry in the vtable, and assert the dispatch before hooking.**
`sage_patch.patches.live_bridge` refuses to apply unless `[0x00BD85C4] == HOOK_VA`.

Both functions happen to open with the same five-byte `mov eax, <SEH scope table>` shape,
which is why the wrong one looked so plausible — `0xB841B0` at `0x0062DCE4` versus `0xB841DA`
at the real `0x0062E4E8`. Shape is not identity.

**The hook.** `0x0062E4E8` opens with

```
b8 da 41 b8 00        mov eax, 0xB841DA
```

**exactly five bytes**, at a function entry (one inbound target by construction, so no
interior branch can land inside the `jmp`), displacing a plain constant load that re-emits
trivially in the cave:

| | |
|---|---|
| patch | `0x0062E4E8`: `B8 DA 41 B8 00` → `E9 <rel32>` |
| cave | save flags/registers, poll the order buffer, emit any pending order, restore |
| tail | `mov eax, 0xB841DA`, then `jmp 0x0062E4ED` |

Nothing in the cave depends on incoming register state: `TheMessageStream` comes from its
global, so the hook is independent of where in the function it sits.

**Getting orders in needs no IPC library.** With no ASLR, the buffer's address inside the new
section is a compile-time constant, so the Python side writes it with `WriteProcessMemory` —
the same handle machinery `sage_live.ProcessMemory` already opens, plus `PROCESS_VM_WRITE |
PROCESS_VM_OPERATION`. Write the payload, then write a `ready` dword **last**; the hook reads
`ready`, consumes, clears. One writer, one reader, and x86 store ordering makes that safe
without locking.

The infrastructure is already proven on this binary: `sage_patch.utils.allocate_section`
appends a cave past every existing section (as `.cmdext` and `.cahfac` already do) and
`apply_byte_patch` asserts the expected original bytes before writing.

**When a DLL becomes worth it:** M3, not M2. Per-frame observation means walking object lists,
resolving templates, applying fog and serialising a struct - real logic that is miserable as
hand-assembled bytes and an afternoon in C++. The step up is small once the patch exists: add
a `LoadLibraryA` stub to the same cave, and keep the byte patch's only job as loading.

**One consequence to weigh:** patching `game.dat` changes the exe CRC that replay headers
record, so replays from a patched build carry a different patch fingerprint and
`sage_replay.aggregate` will refuse to mix them with an unpatched corpus. A DLL leaves the CRC
untouched. Irrelevant for the M2 acceptance test itself, which only parses the replay the
patched game records, but it matters if those replays are later pooled with ladder data.

### 4b. What has actually run

Verified on 2026-07-29 against a running skirmish, build `2.01.2614.37001`, cave at
`0x00ED3000`. Three orders, chosen to walk the argument machinery in order of risk:

| order | arguments | what it exercises | result |
|---|---|---|---|
| `MSG_DO_STOP` `0x435` | none | the hook fires per logic frame at all | consumed within one frame |
| `MSG_CREATE_SELECTED_GROUP` `0x3E9` | `Boolean`, `ObjectId` | `call [table + eax*4]`, by-**value** | consumed, no crash |
| `MSG_DO_MOVETO` `0x42F` | `Position` | by-**pointer** marshalling | the horde walked to the commanded point |

The by-pointer case is the one worth stating explicitly, because it is the only place the cave
hands an address of its own into engine code: the three floats are laid into an argument
record's value slots and the slot address is passed instead of a value. A wrong layout is a
wild read inside `appendMessage`, not a subtly wrong order. A horde ordered from `(785, 3185)`
to `(985, 3185)` formed up around the target, closest member 22 units out after ~240 units of
travel — so the floats are read in the right order, at the right stride, through the pointer.

**Do not read a mid-path position as a failure.** The first sample was taken 2 s after the
order and showed the horde 86 units *off-axis*, which reads like a misdecoded `Position`. It
was pathing around a castle that had spawned over its route. Sample after the units are
stationary.

Not yet exercised: the remaining by-pointer types (`ScreenPosition`, `ScreenRectangle`,
`WideChar`), and any order carrying more than three arguments.

### 4c. The acceptance test — injected orders are recorded as real input

The claim the patch rests on is that injection goes through the engine's *own* input path, so
orders are network-ordered and check-summed rather than poked into logic. That is testable:
if it is true, the engine writes injected orders into the replay it records.

**Skirmish mode does not record replays.** The test needs a one-player *online* game. Run on
2026-07-29 as Lothlorien; the artifact is `API Test.BfME2Replay`.

Four orders were injected — a bare `MSG_DO_STOP` as an opening marker, the `select`/`move`
pair under test, a closing `MSG_DO_STOP` — spaced so each landed on its own logic frame. All
four appear in the replay, at the frames the hook consumed them on:

| injected | consumed on frame | replay timecode | arguments recorded |
|---|---|---|---|
| `0x435` | 161 | 162 | — |
| `0x3E9` | 164 | 165 | `(Boolean, True)`, `(ObjectId, 400)` |
| `0x42F` | 167 | 168 | `(Position, (1202.25, 867.5, 120.0))` |
| `0x435` | 169 | 170 | — |

The `Position` round-tripped **exactly**, not within tolerance: Python float → cave slots →
pointer read by `appendMessage` → network order → replay file → parser, with no drift.

**`ObjectId 400` was read from the live object table**, which is what settles the live half of
OPEN 8 — see [`live-object-model.md`](live-object-model.md) section 1.

**The player index is not transmitted, and the two spaces disagree.** `encode_order` sends
`order_type`, `arg_count` and the arguments — nothing else. The engine attributes the order to
the local player itself, so the `player` argument on every `sage_live.api.orders` constructor is
**inert for injection** and matters only when round-tripping through `serialize_replay`. In
this game the in-memory `PlayerList` index was **3** and the replay recorded **player 2**. One
data point: it may be a constant −1, or the replay may simply not number a leading slot. Do
not assume one index works in both spaces until a game with a different slot says which.

## 5. What this unblocks

- **OPEN 10 is closed.** Every order type in the corpus now has an authoritative engine name.
- **`live-api.md` unknown 4 is solved** — M2 (order injection) is no longer gated on RE.
- **`sage_replay.OrderArgumentType` is verified against the engine**, not inherited.
- `Bfme2OrderType` currently carries 40 members (deliberately only the ✅ grades). All 147
  network names are now available to extend it — a separate, mechanical change.

Still open and unchanged: unknowns 1–3 (object list head, object body offsets, player
resources). Those are the observation half and remain the gate on M1.

## 6. Reproduction

Scripts used `pefile` 2024.8.26 + `capstone` 5.0.7 against
`C:\Program Files (x86)\Games\bfme\rotwk\game.dat` (11,346,944 bytes), through
[`../scripts/pe.py`](../scripts/pe.py) — point its `PATH` at your own copy.

Method, in the order it worked:

1. Regex `MSG_[A-Z0-9_]+\0` over the whole image → 404 literals, all in `.rdata`.
2. `find_imm_refs` on each → 381 single references, all in `.text`, one tight cluster at
   `0x711270`–`0x7123BB`. A pointer-array layout was ruled out first (zero contiguous runs).
3. Disassemble backwards from the cluster → the three-way dispatch and both jump tables.
4. Walk each table, decode the first `push imm32` in each case body, map back to the string.
5. For the append path: anchor on the `68` (`push imm32`) byte pattern for each network id —
   a linear sweep of `.text` desyncs badly and is useless here — then decode forward to the
   first `call`. Studying `MSG_LOGIC_CRC`'s two sites gave the idiom directly.
6. Confirm by counting: `mov ecx,[0xde6398]` ×282, of which ×232 call `[eax+0x48]`.
