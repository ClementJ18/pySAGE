# Letting an observer page the command bar — reverse-engineering notes

The RE behind [`patches/observer_command_range.py`](../patches/observer_command_range.py), which
lets an observer click `PUSH_VISIBLE_COMMAND_RANGE` and `POP_VISIBLE_COMMAND_RANGE` buttons so the
pages behind them can be read while watching. ROTWK `game.dat` build `2.01.2614.37001`, ImageBase
`0x400000`, recovered statically from `sage_mods/edain/patching/engine/game.dat.backup` on
2026-08-21. Every site named below is byte-identical in the installed `game.dat`.

## The gap

Observing a seat — a replay, or a live game after being defeated — the palantir populates for the
observed player: portraits, production, upgrade states, the lot. Selecting a structure that pages
its command set (a `PUSH_VISIBLE_COMMAND_RANGE` button, the mechanism
[`push-visible-command-range.md`](push-visible-command-range.md) documents) shows the paging
button, drawn enabled — and clicking it does nothing. Whatever is being bought or researched on
page 2 is unreadable for the whole match.

## TL;DR

- One predicate eats the click, and it eats **every** command-bar click an observer makes:
  `0x00941BD2` in `ControlBar::processCommandUI`, calling
  `PlayerList::localPlayerIsNotActive` (`0x006A87F5`) and bailing with 0 when it answers true.
  That is `m_isObserver || m_isDefeated` on `ThePlayerList->m_local`, so it is true for the
  whole of any observed game.
- Nothing else is in the way. The two commands' executors (`0x00941A7D` / `0x00941A9C`) push and
  pop an 8-byte range record on `ControlBar+0x2B0` and re-run `switchToContext`. **No
  `GameMessage`, nothing enters the simulation** — client-side UI, exactly like
  [`observer-switch`](observer-switch.md).
- The bar is *already* right for an observer. `PlayerList::getLocalPlayer` (`0x006A8839`)
  silently redirects to `ControlBar+0x218`, the observed player, whenever `m_local` is inactive —
  so `getCommandAvailability` evaluates every button against the player being watched, and the
  page it would reveal is the observed player's real state.
- Both command types land in `getCommandAvailability`'s **default** case, verdict **1 =
  ENABLED**, and the per-frame status update deliberately leaves an observer's verdicts alone.
  That is why the button looks live and is not.
- The patch is one `call` retargeted at `0x00941BD2` plus a ~20-byte cave that lets command types
  **55** and **56** past the predicate and tail-calls it for everything else.

## 1. The command type numbers

`CommandButton+0x14` holds the type, parsed by index into the name table at `0x00DA4D10`
(`0` = `NONE`). Dumping it gives 60 named types; the two that matter are

| value | name |
|-------|------|
| **55** (`0x37`) | `PUSH_VISIBLE_COMMAND_RANGE` |
| **56** (`0x38`) | `POP_VISIBLE_COMMAND_RANGE` |

Cross-checked against a live use of the field: `0x00940682` reads `cmp dword [esi+0x14], 0x35`
against the same table's `DOZER_CONSTRUCT` (53).

## 2. The click path, end to end

The palantir's chrome is APT, but the 33-slot command grid is still `GameWindow` gadgets. The
window system callback is bound by name in the table at `0x00DA1AF8`:

```
0x00DA1AF8  "ControlBarSystem"          -> 0x0080406B
0x00DA1B04  "ControlBarObserverSystem"  -> 0x00914945
```

`ControlBarObserverSystem` is the observer *seat-picker* bar — the eight player buttons and the
"back to free camera" button that write `ControlBar+0x218`. It has nothing to do with command
buttons.

`ControlBarSystem` funnels the gadget messages `0x4009` and `0x400B` (the left/right click pair
that becomes the executor's two bool arguments) to a thunk, twice:

```asm
0080436f  push eax                      ; the gadget message
00804370  push [ebp+0x10]               ; the GameWindow
00804373  call 0x0071c4ea               ; -> jmp 0x00941b9f
```

and `0x0071C4EA` is a bare `jmp 0x00941B9F` — `ControlBar::processCommandUI(GameWindow *,
GadgetGameMessage)`, thiscall on `TheControlBar`, `ret 8`.

## 3. Where the click dies

```asm
00941b9f  push ebx / push edi
00941ba1  mov  edi, [esp+0xc]           ; the GameWindow
00941ba5  test edi, edi ; je <ret 0>
00941bb1  call 0x0072979c               ; window -> CommandButton
00941bb7  mov  esi, eax                 ; esi = the button, live to the end
00941bbd  call [eax+0x20]               ; a virtual on the window; false -> discard
00941bc2  test al, al ; je <ret 0>
00941bc8  test esi, esi ; je <ret 0>
00941bcc  mov  ecx, [0x00de4928]        ; ThePlayerList
00941bd2  call 0x006a87f5               ; <-- THE FIVE BYTES
00941bd7  test al, al
00941bd9  jne  0x00941bc4               ; <-- the click is discarded here
00941bdb  cmp  [esp+0x14], 0x400b       ; -> the executor's two bools
00941bfc  call 0x00940435               ; ControlBar's click executor
```

`0x006A87F5` is the predicate [`observer-switch.md`](observer-switch.md) §2 already names:

```asm
006a87f5  mov  ecx, [ecx+0x10]          ; PlayerList::m_local  <- note: no redirect
006a87f8  call 0x006aac52               ; Player::isPlayerActive
006a87fd  neg al / sbb eax, eax / inc eax   ; return !active
```

`isPlayerActive` is `!m_isObserver && !m_isDefeated` (`Player+0x35A` / `Player+0x754`). It reads
`m_local` **directly**, which is the whole asymmetry: everything else on the bar goes through
`getLocalPlayer` and gets the observed player, this one does not and gets the `ReplayObserver`.

It has **12 callers** — the observer bar's own visibility gate at `0x006D7822` among them — so it
must not be widened in place. The edit belongs at this call site.

## 4. What the two commands actually do

Both reach the executor's type switch at `0x009408C9` (`edx = type - 1`, bounds `0x3B`, byte
index table at `0x00941B63`, jump table at `0x00941AC3`):

```asm
00941a7d  add  esi, 0x22c               ; PUSH: &button->m_range (start, count)
00941a83  push esi
00941a84  mov  esi, [ebp-0x14]          ; esi = the ControlBar
00941a87  lea  ecx, [esi+0x2b0]         ;   +0x2B0, the range stack
00941a8d  call 0x0097d718               ; append the record (8 bytes)
00941a92  push [esi+0x6c] / push [esi+0x70]
00941a97  call 0x0071d8be               ; switchToContext(current, current) -> repopulate

00941a9c  lea  eax, [ecx+0x2b0]         ; POP: the same stack
00941aa5  cmp  [eax], [eax+4] ; je <no-op on empty>
00941aac  add  dword [eax+4], -8        ; drop one 8-byte record
00941ab0  push [ecx+0x6c] / push [ecx+0x70]
00941ab6  call 0x0071d8be
```

That is the entire effect: a vector on the ControlBar and a repopulate. No message is posted, no
object is touched, nothing is sent. `switchToContext` clears that vector whenever the context or
the selected drawable changes (`0x0071D8E0`), so a page resets on re-selection — for an observer
exactly as for a player.

## 5. Why the rest of the bar already works for an observer

Three engine facts, none of which need patching:

### 5.1 `getLocalPlayer` already means "the observed player"

```asm
006a8839  mov  esi, [ecx+0x10]          ; m_local
006a883d  test esi, esi ; je <return NULL>
006a8847  call 0x006aac52               ; isPlayerActive(m_local)
006a884e  jne  <return m_local>
006a8850  mov  eax, [0x00de7744]        ; TheControlBar
006a8859  mov  eax, [eax+0x218]         ; the observed player
006a8861  jne  <return that>
```

`ControlBar::getCommandAvailability` (`0x00942733`) takes its player from this at `0x0094275D`,
so every science, upgrade and affordability test on the bar is asked of the seat being watched.
The page a `PUSH` would reveal is therefore already computed correctly — it is just unreachable.

### 5.2 The observer gets the full command context

`ControlBar`'s context evaluator ends with

```asm
0071eed2  mov  eax, [0x00de4928] / mov ecx, [eax+0x10]
0071eee0  call 0x006adbeb               ; Player::getRelationship(obj->team)
0071eee9  call 0x0068b749               ; Object::isLocallyControlled
0071eeee  cmp  al, 1 ; je <context 2>
0071eef2  cmp  edi, 1 ; jne <bail>      ; 1 = NEUTRAL
0071eefe  push 2                        ; switchToContext(CB_CONTEXT_UNIT_SELECTED)
```

`getRelationship` returns **1 (NEUTRAL)** by default when neither the team map nor the
player-to-player map holds an entry (`0x006ADC3A`, `0x006ACEED`), which is what an observer seat
with no declared relationships gets against every real team — so an observer takes the same branch
a neutral capturable structure takes, and gets the full command set populated. (`ENEMIES=0,
NEUTRAL=1, ALLIES=2`, from the name list at `0x00D9F5F8`.) This is the step the observed behaviour
confirms: the bar populates, which is what makes the dead paging button visible in the first
place.

### 5.3 The verdict for these two types is ENABLED, and the observer keeps it

`getCommandAvailability`'s type switch (`0x00942A70`) routes both 55 and 56 to its **default**
case at `0x00942FF1`:

```asm
00942ff1  xor eax, eax / inc eax        ; 1 = ENABLED
```

and the per-frame status update at `0x0094397F` explicitly does *not* override that for an
observer:

```asm
00943a89  call 0x0068b749               ; isLocallyControlled(obj) -> [ebp-0xd]
00943ae2  cmp  [ebp-0xd], bl ; jne <normal>
00943af9  call 0x006aac52               ; isPlayerActive(m_local)
00943b00  je   0x00943b20               ; observer: [ebp-0xe] = 1, verdict untouched
00943b06  ...                           ; active player on a foreign object: verdict forced to 0
```

Verdict 1 reaches `0x00943C7C` → `winEnable(TRUE)`. So the button an observer sees is enabled,
hit-tested, and delivered to `processCommandUI` — where §3 throws it away.

## 6. The patch — [`patches/observer_command_range.py`](../patches/observer_command_range.py)

**One `call` retargeted, plus a cave.**

At `0x00941BD2`, the `call` points at a cave instead of `0x006A87F5`:

```
e8 1e 6c d6 ff   ->   e8 <rel32 to the cave>
```

The cave, 28 bytes, as it disassembles out of a patched binary (here at the `.obscmd` base a
clean image gives it):

```asm
00ed3000  837e1437       cmp  dword [esi+0x14], 0x37   ; PUSH_VISIBLE_COMMAND_RANGE
00ed3004  0f840f000000   je   0x00ed3019
00ed300a  837e1438       cmp  dword [esi+0x14], 0x38   ; POP_VISIBLE_COMMAND_RANGE
00ed300e  0f8405000000   je   0x00ed3019
00ed3014  e9dc577dff     jmp  0x006a87f5               ; ecx already = ThePlayerList
00ed3019  32c0           xor  al, al                   ; "the local player is active": proceed
00ed301b  c3             ret
```

Four things make it safe:

- **`esi` is the button and is live.** Loaded at `0x00941BB7`, null-checked at `0x00941BC8` four
  instructions above the call, and still used at `0x00941BF0` and `0x00941BFB` below it. The
  cave only reads it.
- **The contract is preserved exactly.** Callee-saved registers are untouched; the cave clobbers
  `eax` and flags, which the stock predicate clobbers anyway; `ecx` is already loaded for the
  tail `jmp`, which keeps the thiscall shape and the `ret` count identical.
- **One call site, not the predicate.** `0x006A87F5` has 12 callers, including the observer
  bar's own visibility gate — widening it in place would leak into all of them. Retargeting the
  call changes only this one question.
- **Nothing enters the simulation.** §4. Like `observer-switch` and `replay-outcome`, and unlike
  `production-condition`, this does not have to be on every peer, and a replay stays faithful.

The whitelist has to sit at *this* gate rather than anywhere downstream, because this gate is the
only thing standing between an observer and **every** command button. Removing it wholesale would
let an observer issue real orders — `UNIT_BUILD` and friends post `GameMessage`s — so the two
types are named explicitly.

### Why not in place

`0x00941BCC..0x00941BD9` is 13 bytes: `mov ecx, imm32` (6) + `call` (5) + `test`/`jne` (2+2).
Keeping the stock predicate for other buttons and adding a two-value type test needs ~21, so
there is no inline form. Adding the cave via `allocate_section` (patcher rule 1) keeps it
composable with the other section-adding patches.

## 7. Spillovers and limits

- **Defeated players get it too.** The predicate is `m_isObserver || m_isDefeated`, so a player
  who has lost a live game can also page the bar. Nothing is issued either way — it is the same
  read-only affordance, and the alternative (splitting the two cases) would need the observer bit
  read separately for no behavioural gain.
- **It does not add a UI.** The paging buttons revealed are the ones the mod's `CommandSet`
  already defines; a set with no `PUSH_VISIBLE_COMMAND_RANGE` button gains nothing.
- **The page ceiling still applies.** `CommandRangeStart + CommandRangeCount ≤ N` — an INI-side
  overrun reads off the end of `m_command` and crashes, observer or not. See
  [`push-visible-command-range.md`](push-visible-command-range.md).
- **A page does not survive re-selection.** `switchToContext` clears `ControlBar+0x2B0` on any
  context or drawable change, which is stock behaviour.
- **The executor's other two callers are untouched.** They are the spellbook APT handler
  `OnAptInGameSpellBookButtonPressed` (`0x00930DE5`) and the deferred button-queue flush at
  `0x00823413` — neither consults this predicate, and neither is on the command-bar click path.

## 8. What `apply` and `verify` anchor

Both run the same checks, so a binary someone else patched is held to what this one writes.

- **The gate, either side of the `call` and never across it** — `0x00941BC8` (`test esi,esi` and
  the `ThePlayerList` load) and `0x00941BD7` (`test al,al` / `jne`, and the `cmp [esp+0x14],
  0x400b` that follows). Split that way, both halves stay valid once the call is retargeted.
- **`0x00941BB1`**, the `call` that puts the `CommandButton` in `esi` and the `mov esi, eax` that
  keeps it. Nothing else would catch a build that sourced `esi` differently: the cave would read
  `[esi+0x14]` off whatever was there.
- **The first bytes of `0x006A87F5`** (`8b 49 10 e8 …`), so the tail `jmp` is proved to land on
  the predicate.
- **The dispatch and its two tables.** `0x009408B3`'s 29 bytes pin the switch and both table
  addresses, and then `index_table[T-1] → jump_table[…]` is *walked* for T = 55 and 56 and
  required to reach `0x00941A7D` / `0x00941A9C`, whose own first bytes are checked too. So the
  two command numbers are read out of the shipped dispatch rather than trusted from the name
  table they were originally derived from — which is the check that matters, because a build that
  renumbered them would have the cave waving through whatever command landed on 55.
- **The cave**, located with `find_section` and compared against `build_code(section_va)` rather
  than looked for at a fixed RVA.

## Address index

The click path: `"ControlBarSystem"` `0xC189C0` → `0x0080406B` · `"ControlBarObserverSystem"`
`0xC189A4` → `0x00914945` (the seat picker; writes `ControlBar+0x218`) · the name→callback table
`0x00DA1AF8` · thunk `0x0071C4EA` → **`ControlBar::processCommandUI` `0x00941B9F`** · window →
button `0x0072979C` · **the gate `0x00941BD2` / `0x00941BD9`** · the click executor `0x00940435`
(thiscall on `TheControlBar`, `ret 0xC`) · its type switch `0x009408C9`, jump table `0x00941AC3`,
byte index table `0x00941B63` · **`PUSH` `0x00941A7D`** · **`POP` `0x00941A9C`** ·
`ControlBar::switchToContext` `0x0071D8BE` (clears the range stack at `0x0071D8E0`) · the range
stack `ControlBar+0x2B0`, `CommandButton+0x22C` the range record.

The predicates: `PlayerList::localPlayerIsNotActive` `0x006A87F5` (12 callers) ·
`Player::isPlayerActive` `0x006AAC52` · **`PlayerList::getLocalPlayer` `0x006A8839`** (redirects
to `ControlBar+0x218` when `m_local` is inactive) · `Object::isLocallyControlled` `0x0068B749` ·
`Object::getControllingPlayer` `0x0068B678` · `Player::getRelationship` `0x006ADBEB` (default
`1` = NEUTRAL at `0x006ACEED`).

The bar: `ControlBar::getCommandAvailability` `0x00942733` (player from `0x0094275D`, type switch
`0x00942A70`, default → `0x00942FF1` = verdict 1) · the per-frame status update `0x0094397F`
(observer branch `0x00943B20`, enable path `0x00943C7C`) · the context evaluator's ownership test
`0x0071EED2`..`0x0071EEFE` · `GameWindow::winEnable` `0x007154B3`.

Tables: the `CommandButton` type names `0x00DA4D10` (`PUSH` = 55, `POP` = 56) · the
`Relationship` names `0x00D9F5F8`.

Globals: `ThePlayerList` `0x00DE4928` (`m_local` `+0x10`) · `TheControlBar` `0x00DE7744`
(`m_currentDrawable` `+0x6C`, `m_currentContext` `+0x70`, observed player `+0x218`, range stack
`+0x2B0`) · `TheInGameUI` `0x00DE4830` · `TheGameLogic` `0x00DE412C`.
