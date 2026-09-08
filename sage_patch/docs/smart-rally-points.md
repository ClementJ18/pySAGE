# Smart rally points: rallying at an object

**Status: implemented as `smart-rally`, and registered
[experimental](../README.md)** ([`../patches/experimental/smart_rally.py`](../patches/experimental/smart_rally.py)).
Every address below was read from the clean `sage_patch/engine/game.dat.backup`
(ROTWK `2.01.2614.37001`), and every site was then asserted against the repo-root `game.dat` as well
- both hold stock bytes at all nineteen. The patch applies, verifies and round-trips through
`detect` on both binaries, and composes in either order with the other cave patches.

**Why experimental.** The default form does what it says in a real game, and so does the banner. The
`--guard` form does not (5.4), and until that is understood the honest reading is that the patch's
model of what an order does to a produced unit is incomplete - which is exactly what the flag is
for. `sage-patch list` marks it `exp` and `apply` warns before it writes.

Sections 1-4 are the reverse engineering as it was scoped. Section 5 is what was built: one edit
shorter than the scope predicted, because the client gate turned out to be unnecessary (5.5), and
one longer, because the banner needed moving too (5.6).

**The feature.** Right-click a hero or a unit with a producing structure selected and have the
structure's rally point follow *that object* instead of the patch of ground it happened to be
standing on. Units coming out of the barracks walk to where the hero is now, not to where the hero
was when the order was given.

## 1. The order already carries the target

`MSG_SET_RALLY_POINT` is `0x413` ([`message-stream.md`](message-stream.md) section 3). Its
logic-side case body is at `0x0077A26C`, reached from the dispatcher's `0x40D..0x418` jump table at
`0x0077D087` (entry 6). It reads **four** arguments through `GameMessage::getArgument`
(`0x00710C9E`):

| # | type | read at | what it is |
|---|---|---|---|
| 0 | ObjectID | `0x0077A26F` | the producing structure, resolved via `TheGameLogic->findObjectByID` (`0x00449681`) |
| 1 | Location | `0x0077A287` | the clicked world point, copied to `[ebp-0x24]` |
| 2 | Boolean | `0x0077A2AD` | the "apply to all my producers" flag |
| 3 | **ObjectID** | `0x0077A2BB` | **the object under the cursor** |

Argument 3 is resolved to an `Object*` at `0x0077A2C8` and then used for exactly one thing:

```
0077a2d5  cmp  byte [ebp+0xb], bl        ; argument 2 - "all producers"?
0077a2d8  je   0x77a2ef                  ; no  -> single-producer path
0077a2da  cmp  eax, ebx                  ; argument 3 - did the click land on an object?
0077a2dc  jne  0x77a2ef                  ; yes -> single-producer path
0077a2de  lea  eax, [ebp-0x24]
0077a2e2  push edi                       ; the producer
0077a2e3  call 0x7798d5                  ; global rally (every producer this player owns)
...
0077a2ef  push ebx                       ; 0
0077a2f0  push 1
0077a2f2  lea  eax, [ebp-0x24]           ; the clicked point
0077a2f6  push edi                       ; the producer
0077a2f7  call 0x779544                  ; single-producer rally
```

The object is tested for NULL and then dropped on the floor. It is never passed to either rally
routine.

**This is the whole reason the patch is small.** The order format does not change, the client does
not have to learn to send anything new, and a replay recorded on a patched build still parses
byte-for-byte on a stock one - only the orders the engine derives from it differ.

### Where argument 3 comes from

Two client sites build the message:

- `0x0081F58E`, inside the context-command evaluator that begins at `0x0081ED56`. It loops the
  selected drawables (`[0xDE4830]` vtable `+0x124`), and for each one appends producer id,
  location, the "all producers" boolean, and then at `0x0081F5D8`:

  ```
  0081f5d8  test edi, edi                 ; edi = the object under the cursor
  0081f5da  je   0x81f5e1
  0081f5dc  mov  eax, [edi+0x74]          ; Object::m_id
  0081f5df  jmp  0x81f5e3
  0081f5e1  xor  eax, eax
  0081f5e3  mov  ecx, [ebp+0x10]
  0081f5e6  push eax
  0081f5e7  call 0x71111a                 ; appendObjectIDArgument
  ```

  `edi` is the same pointer this function hands to the context tests for `MSG_ENTER` and the attack
  commands, so it is the hovered object and nothing else.
- `0x0083D594`, a smaller path that derives the point from a screen pixel through `TheTacticalView`
  (`[0xDE447C]` vtable `+0x168`) and always appends `0` for argument 3.

The "all producers" boolean comes from `0x0063F122`, a two-bit modifier-key test.

## 2. Where a rally point actually lives

`Object::getExitInterface` is `0x0068BB14`: it walks the module array at `Object+0x24C` asking each
module's vtable `+0x50`, and falls back to the contain module at `Object+0x258` (vtable `+0x74`).
The interface it returns is the only thing that holds a rally point.

The class that matters is **`QueueProductionExitUpdate`**. Registered at `0x00659535`, allocated
`0x44` bytes at `0x0064E65C`, constructed at `0x008A3948`:

| module offset | interface offset | what |
|---|---|---|
| `+0x04` | `-0x1C` | the module data (parsed INI) |
| `+0x08` | `-0x18` | the producing `Object*` |
| `+0x20` | `+0x00` | the `ExitInterface` vtable, `0x00C682C4` |
| `+0x28`..`+0x30` | `+0x08` | **the rally point**, a `Coord3D` |
| `+0x34` | `+0x14` | **the rally point is set** flag |
| `+0x3C` | `+0x1C` | seeded from module data `+0x28` |
| `+0x40` | `+0x20` | the `ObjectID` of the unit waiting to come out |

There is no `ObjectID` anywhere in that list. The rally point is three floats and a bool, and the
patch's central problem is that it needs a fourth thing.

The interface slots the rest of this document uses:

| slot | address | what |
|---|---|---|
| `+0x18` (6) | `0x008A3941` | `canRallyToSlaughter` - reads module data `+0x31` |
| `+0x1C` (7) | `0x008A3BCC` | set the rally point from a `Coord3D*` |
| `+0x20` (8) | `0x008A389C` | get the rally point - `return m_set ? this+8 : NULL` |
| `+0x24` (9) | `0x0088B2F0` | set the rally point, orientation-transformed against the module data's `NaturalRallyPoint`; shared with the `Default` and `SupplyCenter` exit classes |
| `+0x2C` (11) | `0x008A3BF8` | release the waiting unit |

## 3. Where a rally point is spent

`0x008A3BF8` is the routine that lets a finished unit out of the building. It resolves the waiting
unit from interface `+0x20`, clears that slot, detaches it from the contain module, and then:

```
008a3c9b  cmp  byte [esi+0x14], bl       ; is a rally point set?
008a3c9e  je   0x8a3d37                  ; no - the unit just stands there
008a3ca4  mov  eax, [esi]
008a3ca8  call dword [eax+0x20]          ; getRallyPoint()
          ...copy the Coord3D to [ebp-0x14]...
008a3cc3  mov  eax, [esi-0x18]           ; the producer
008a3cd0  call 0x8a3ab4                  ; find a "slaughter" target near the rally point
008a3cd5  cmp  eax, ebx
008a3cdc  je   0x8a3d14                  ; nothing found -> walk to the point
          ; found: set two model conditions, then
008a3d0d  call 0x770ede                  ; aiEnter(target, CMD_FROM_AI)
008a3d12  jmp  0x8a3d37
008a3d14: ...
008a3d2b  add  esi, 8                    ; the stored Coord3D
008a3d32  call 0x66c4ca                  ; aiMoveToPosition(&rally, CMD_FROM_AI)
```

Both AI calls take `this = unit->[0x260] + 0x20`. The sibling entry points with that same shape are
`aiMoveToPosition` `0x0066C4CA`, `aiEnter` `0x00770EDE`, and `aiGuardObject` `0x00771805` (reached
from the `MSG_DO_GUARD_OBJECT` handler at `0x0077ABB5` through the group walker `0x00772736`).

**The arm at `0x008A3D14` is where the patch cuts.** It is the one that runs when the rally point is
a bare position, it already holds the producer and the unit in registers, and it is three
instructions from the call that gives the unit its order. The hook itself goes on `0x008A3D23`, the
one instruction both of that arm's edges pass through.

## 4. The engine's own rally-at-object, and why it is dead

The engine is not innocent of this idea. `0x008A3AB4` scans the partition manager (`[0xDE4354]`,
`getClosestObject` `0x00A39090`) around the rally point and accepts a candidate only if **all** of
the following hold:

1. the candidate has a contain module (`Object+0x258`) whose vtable `+0x34` says yes;
2. the producer has an exit interface;
3. that interface's `canRallyToSlaughter` (slot `+0x18`, module data `+0x31`) says yes;
4. the producer/candidate relationship (`0x0068D7AB`) is `2`;
5. the candidate is within `[0xC683F0]` of the point.

The same test gates the client: the context walker `0x0069D27E`, kind `0x0E` ("can I set a rally
point here"), takes the object-target branch at `0x0069D4F7` only when the target has a contain
module and the producer answers `canRallyToSlaughter`.

`CanRallyToSlaughter` defaults to `No` and appears **zero times** in `ini.big`, `_patch201ini.big`
and `__edain_data.big`. Condition 3 therefore never holds on any shipped build, the scan at
`0x008A3AB4` always returns NULL, and the client never offers the object branch. The one existing
rally-at-object path in the engine is unreachable content.

That is good news twice over. It means the patch generalises a mechanism the engine already
believes in rather than inventing one, and it means **nothing shipped can regress**: no INI in the
tree can tell the difference between the stock behaviour of these two sites and any behaviour the
patch gives them.

The module census, for the record:

| module | `ini.big` | `_patch201ini.big` | `__edain_data.big` |
|---|---|---|---|
| `QueueProductionExitUpdate` | 121 | 9 | **352** |
| `SpawnPointProductionExitUpdate` | 4 | 0 | 26 |
| `SupplyCenterProductionExitUpdate` | 1 | 1 | 3 |
| `DefaultProductionExitUpdate` | 0 | 0 | 0 |

`QueueProductionExitUpdate` is the producer exit module in practice. Covering it alone covers the
feature.

## 5. What the patch does

Four hooks and one size, in dependency order.

### 5.1 Somewhere to keep the target

The recommendation is to **grow `QueueProductionExitUpdate` from `0x44` to `0x48`** and keep the
target `ObjectID` at module `+0x44` (interface `+0x24`). Two edits: the allocation size at
`0x0064E65C` and a zero-store in the constructor at `0x008A3948`. Both sites are unique - the
`push 0x44` at `0x0064E65C` is the class's only allocation.

Why this and not the alternatives:

- **A side table** keyed by producer `ObjectID`, living in a patch-owned PE section, needs no struct
  surgery and would cover all four exit classes at once. It also needs a size cap, an eviction rule,
  a clear on new-game, and it outlives the module it describes. The field is strictly less
  machinery.
- **Repurposing module `+0x24`** (interface `+0x04`), which the constructor zeroes, is tempting and
  should not be done without first proving nothing reads it. Interface slot `+0x30` cross-casts to
  `module+0x10` and reads offsets that do not obviously fit inside `0x44`; until that is understood,
  assume every existing field is load-bearing.

The grown field is deliberately **not** added to the module's xfer, so the save format does not
change. A save/load drops the rally target back to the stored position. That is a real limitation
and section 7 states it plainly.

Built as `ALLOC_SIZE_VA` (`0x0064E65C`, `push 0x44` -> `push 0x48`) plus the `ctor_tail` routine,
which the constructor's epilogue at `0x008A39AC` jumps into.

### 5.2 Record the target when the order arrives

At `0x0077A2EF` the handler already has the producer in `edi` and the resolved target object in
`eax`. After `0x00779544` returns - it returns its success flag in `al`, and it can legitimately
fail on "no path" - fetch the producer's exit interface (`0x0068BB14`) and store the target's `m_id`
(`Object+0x74`), or `0` if there was no target.

Storing `0` on a ground click is what clears a previous target, so this one edit is both the write
and the clear for the ordinary case.

The global arm at `0x007798D5` sets the rally point for every producer the player owns. It is only
reached when argument 3 is NULL, so on the stock control flow a smart rally can never be global.
Deciding whether to lift that is a design question, not a mechanical one - see section 9.

Built as the `record` routine, which the six bytes at `0x0077A2EF` jump into. It stashes the target
below the reproduced argument block, so the `__cdecl` call it displaced runs exactly as it did, and
it writes only when the interface's vtable is `QueueProductionExitUpdate`'s - `getExitInterface`
also answers with `SupplyCenterProductionExitUpdate`, `SpawnPointProductionExitUpdate` and contain
modules, on all of which `+0x24` is somebody else's field.

### 5.3 Clear the target everywhere else it can go stale

The scope planned to enumerate every indirect caller of interface slot `+0x1C` and zero the target
at each. The **setter itself** is the better place, and it is one hook rather than a list: the
`clear` routine takes over the position setter's epilogue at `0x008A3BF0`, so storing *any* bare
point drops whatever object it replaces. Every path that sets a plain rally point ends there,
including the global arm at `0x007798D5`, which the 5.2 hook cannot see - so a stale target cannot
outlive the point it was set with, and no enumeration is needed to be sure of it.

Ordering falls out correctly on its own: the handler's rally routine calls the setter, so the clear
happens first and 5.2's write lands on top of it.

And the enumeration the scope wanted can be settled rather than argued. A rally point is only ever
*read* when the "is set" flag at interface `+0x14` is true, and `0x008A3BF0` - the instruction this
hook displaces - is the **only** write to that flag anywhere in the exit classes' code (scanned as
`mov byte [reg+0x14], imm` across `0x008A3800`-`0x008A3E00`, `0x0088B000`-`0x0088B800` and
`0x008A9B00`-`0x008A9D00`: one hit). So no path can arm a rally point without passing through the
clear, and a stale target cannot be spent. Note in particular that the orientation-transforming
setter at slot `+0x24`, which `0x007795DE` calls first on the large-ship branch, writes the point but
*not* the flag - and is followed by the `+0x1C` call at `0x0077976E` on the same pass anyway.

Note that `0x008A3BCC` already rewrites what it is given: it runs the slaughter scan at set time and,
if that finds something, stores the *found object's* position rather than the clicked one. On a
shipped build the scan never finds anything, so today it is a plain copy.

### 5.4 Spend it

At `0x008A3D14`, before the existing `aiMoveToPosition`: read the stored id, resolve it, and if the
object is alive and the relationship test (`0x0068D7AB`) still passes, issue the order against it
instead. If anything fails, fall through unchanged - and because the stored `Coord3D` is still the
target's last known position, the fallback when a hero dies is "walk to where they fell", which is
the right answer without any extra work.

Which order to issue is the one genuinely open design choice:

| order | call | behaviour |
|---|---|---|
| move to the target's current position | `0x0066C4CA` with `target+0x38` | units walk to where the hero is at the moment they spawn, then stop. Cheapest, and cannot behave differently from a normal rally in any way the AI or the pathfinder has not already seen. **This is the form that works.** |
| guard the target | `0x00771805` | units are meant to follow and defend, as they do for `MSG_DO_GUARD_OBJECT`. **Defective - see below.** |

**The arm has two destinations, and that was the bug.** Reported from play: produced units walk to
the hero and then back to the spot where the rally point was set on him. So the object order *was*
taking - the walk to the hero is it working - and something else pulled them back afterwards.

That something is the first instruction of the arm this patch was hooking:

```
008a3d14  mov  ecx, [ebp-4]              ; the container the unit is leaving
008a3d17  mov  eax, [ecx]
008a3d19  lea  edx, [ebp-0x14]           ; the rally point copy
008a3d1c  push edx
008a3d1d  call [eax+0x244]               ; the exit path, aimed at that point
008a3d23  ...                            ; and only then the move order
```

`Object` vtable `+0x244`, handed the stored rally point. The hook used to sit at `0x008A3D23`, so
that call had already been made: the unit left the door with an exit path ending at the stored
point *and* an order naming the target, and once it reached the target the first one reasserted
itself. With the move form the two destinations are close enough to be invisible unless the target
has moved since the order was given, which is why only the guard form looked broken.

**The engine already knew not to do this.** Its own rally-at-object arm (`0x008A3CDE`, the
slaughterhouse path) never makes that call - it sets two model conditions and goes straight to
`aiEnter`. Hooking the *tail* of the walk-to-the-point arm inherited a step that belongs only to
walking to a point.

So the hook moved to `0x008A3D14`, the head of the arm, displacing the whole fifteen-byte call. A
live, allied target now suppresses it; anything else replays all fifteen bytes and re-enters the
stock arm after them, so a rejected target still costs nothing.

### The guard refusal that was not happening

Before that, the arguments were checked and one was wrong: the command source was `CMD_FROM_AI`
where the guard handler passes `CMD_FROM_PLAYER` (`push ebx` at `0x0077ABEA`). Corrected, without
changing the symptom.

Reading further suggested guard was being *refused*: `aiDoCommand` (`0x0066A7EC`, `AIUpdateInterface`
vtable slot 0) switches on the state id through the table at `0x0066B07C`, entry `0x1F` forwards to
`AIUpdate::privateGuardObject` (module vtable `+0x100`, `0x00664B19`), and that opens with three
gates - `Object::testStatus(38)`, the can-this-be-moved predicate at `0x00690E97`, and KindOf
`PROJECTILE` - each of which makes it `return -1` having touched nothing.

**That was not what was happening** - the units did reach the hero, so the order took. The check it
produced is kept anyway, because it costs four instructions and closes a real hole:
`privateGuardObject` records the guarded `ObjectID` at module `+0x64` on success (`0x00664B73`) and
the wrapper does not hand its verdict back usably (`0x0077185F` clobbers `eax` on one edge), so the
cave reads that field back, compares it against the id it asked for, and issues the move form when
they differ. A refused guard degrades to the form that works rather than to no order at all.

### 5.5 The client needs no edit, and this is why

The scope assumed `0x0069D4F7` (context kind `0x0E`) had to be relaxed, because it appears to demand
a contain module plus `canRallyToSlaughter`. Reading its failure edge settles it the other way:

```
0069d504  cmp  edi, ebx                  ; is there a target?
0069d506  je   0x69d510
0069d508  mov  esi, [edi+0x258]          ; the target's contain module
0069d50e  jmp  0x69d512
0069d510  xor  esi, esi
0069d512  call 0x68bb14                  ; producer->getExitInterface()
0069d517  cmp  esi, ebx
0069d51c  je   0x69d539                  ; no contain module -> the *ground* arm
```

A hero has no contain module, so `esi` is zero and the test goes straight to the ground arm at
`0x0069D539`, which accepts on the producer's own template flag and locally-controlled state. The
answer to "may I set a rally point here" is therefore **yes for an arbitrary hovered object**
already. And the rally branch of the context evaluator is itself a fallback - `0x0081F463` reaches
it when the higher-priority command comes back false - so right-clicking a hero with a barracks
selected already produces a `MSG_SET_RALLY_POINT` naming that hero. It has been doing so all along;
the logic simply threw the name away.

That removes the one edit that could have changed what a click means. The patch cannot take a
right-click away from something a player does today, because it does not touch the code that decides
which command a click is.

The relationship gate the scope wanted on the client is still there - it just lives on the spend
side (5.4) instead, where it is cheaper and cannot affect the UI at all. The command hint and the
cursor table (`SetRallyPoint` at `0x00BF5FC8`, referenced from `0x00D9E148`) are untouched.

### 5.6 Move the banner

The scope filed this under section 6 as cosmetic and left it out. It is not optional in practice:
with 5.1-5.4 alone the units go to the hero and the banner stays planted on the ground where the
click landed, which reads as a bug even though nothing is wrong.

The ControlBar places the banner at whatever the exit interface hands back:

```
00944397  call 0x68bb14                  ; producer->getExitInterface()
0094439c  test eax, eax
0094439e  je   0x9443af
009443a0  mov  edx, [eax]
009443a2  mov  ecx, eax
009443a4  call [edx+0x20]                ; getRallyPoint()
009443a7  push eax
009443a8  mov  ecx, ebx
009443aa  call 0x71d18f                  ; ControlBar::setRallyPointMarker
```

`0x00945099` holds the **same seven bytes** with the same registers, and follows them with the same
`push eax; mov ecx, ebx`. So one routine serves both, and it is reached by a `call` rather than a
`jmp` so its `ret` lands in whichever site asked - no per-site trampoline.

The routine reproduces the query, then answers with the target's live position instead when there
is a live, still-allied target. It asks `getRelationship` exactly as 5.4 does, so the banner cannot
promise something the units will not do. Three things it deliberately preserves:

- **a NULL answer passes straight through.** NULL is how `0x0071D18F` is told to *destroy* the
  marker, and swallowing it would leave a banner standing after the rally point was cleared.
- **the vtable is checked before `+0x24` is read**, for the same reason 5.2 checks it: this is the
  other site that reaches an interface through `getExitInterface` rather than from inside the class.
- **the pointer is safe to hand out.** `0x0071D18F` passes it to `Drawable::setPosition`
  (`0x006713E1`), which *copies*; nothing retains it. That is what makes answering with a pointer
  into a live `Object` legitimate rather than a dangling-pointer bug waiting for the hero to die.

This half is **client-side and read-only** - it moves a drawable and reads logic state without
writing any. It cannot desync anything, and a peer running it would behave identically to one that
did not.

**What it does not do.** It changes *where* the banner is drawn, not *how often* it is redrawn. Both
sites sit in the ControlBar's context refresh, not in a per-frame update, so the banner snaps to the
hero when the ControlBar re-evaluates the selected structure rather than gliding after him
continuously. Making it track frame by frame means adding a refresh the engine does not currently
have - the stock rally point never moves, so nothing ever needed one - and that is a separate
change.

## 6. Feedback the player sees

The confirmations are already wired and the patch inherits them:

| string | emitted at |
|---|---|
| `GUI:RallyPointSet` | `0x007797D2` |
| `GUI:RallyPointNoPath` | `0x007796AE` |
| `GUI:GlobalRallyPointSet` | `0x0077994C` |

plus the EVA events `RallyPointSet` and `UnableToSetRallyPoint`. The "no path" check in
`0x00779544` builds a `Locomotor` from `HumanLocomotor` or `LargeShipLocomotor` (`TheLocomotorStore`
`0xDE369C`, template lookup `0x005487EC`) and runs it through the pathfinder at `TheAI+0x10`
(`0x006F5BB0`). A unit target sits on walkable ground by definition, so this test passes for free on
the cases the patch adds.

The rally marker drawable (`RallyPointMarker`, referenced at `0x0071D1D3`) is created and moved by
`ControlBar::setRallyPointMarker` (`0x0071D18F`), which takes a `Coord3D *`, destroys the marker on
NULL, and otherwise copies the point into the drawable through `Drawable::setPosition`
(`0x006713E1`). Section 5.6 is the hook that makes it stand on the target.

## 7. What it costs

- **Multiplayer.** Every peer must run the same patched binary. The patch changes what orders the
  logic derives from a message, so a patched and a stock client diverge the first time anyone sets a
  smart rally. Same constraint as `production-condition`.
- **Replays.** The message format is untouched, so replays parse identically on both builds. A
  replay of a smart rally played back on a stock build simply shows units walking to the point
  instead of to the hero.
- **Saves.** The new field is not serialised. Load a save and every smart rally degrades to the
  position it was last stored at. No format change, no incompatibility.
- **The AI.** The skirmish AI never sends `MSG_SET_RALLY_POINT`, so it neither benefits nor breaks.
- **`sage_verify`.** Worth noting independently of this patch:
  [`sage_verify/orders.py`](../../sage_verify/orders.py) excludes rally points from its
  target-visibility evidence on the grounds that their target is "always the issuer's own property".
  Argument 3 of `0x413` is an arbitrary hovered object that the issuing client must have drawn, which
  makes it exactly the kind of evidence that module collects - on stock builds too. That is a
  separate finding and a separate change.

## 8. What was built

| | site | stock | what |
|---|---|---|---|
| size | `0x0064E65C` | `6a 44` | `QueueProductionExitUpdate` grows to `0x48` |
| `ctor_tail` | `0x008A39AC` | `8b c6 5e c2 08 00` | the constructor zeroes the new field |
| `clear` | `0x008A3BF0` | `c6 43 14 01 5b` | storing a bare point drops the target |
| `record` | `0x0077A2EF` | `53 6a 01 8d 45 dc` | the handler keeps the target it resolved |
| `spend` | `0x008A3D23` | `8b 8f 60 02 00 00` | the released unit is sent to the target |
| `marker` | `0x009443A0` | `8b 10 8b c8 ff 52 20` | the banner is drawn on the target |
| `marker` | `0x00945099` | `8b 10 8b c8 ff 52 20` | the same, from the other ControlBar site |

Thirty-nine bytes rewritten, plus a `.rally` cave holding the five routines. The four logic hooks
are `jmp`; the two marker hooks are `call`, so both reach the one routine and its `ret` sorts out
which. Every edit asserts its expected original bytes before writing, and nineteen further windows
are asserted and never written - the factory's entry, the constructor's
`mov [esi+0x20], EXIT_VTABLE`, the two vtable slots that prove the hooked routines belong to that
class, the `call findObjectByID` that proves the target is in `eax` at the record hook, what each
marker site does with the answer, both resume points, and the routines the cave calls.

`--guard` selects `aiGuardObject` over the move; `detect` recovers which form a binary carries.

The staging the scope proposed collapsed into a single change, because stage 3 turned out not to
exist (5.5) and stage 4 was cheap enough to ship beside stage 2. Stage 5 turned out not to be
optional and is 5.6 - though only its *placement* half; redrawing the banner continuously as the
target walks is still open.

## 9. Open questions

- What module `+0x24` (interface `+0x04`) is for. Not required for the recommended design, but it is
  the one field in the class this reading does not account for, and interface slot `+0x30` reaches
  offsets that do not sit comfortably inside a `0x44`-byte object.
- ~~The full set of indirect callers of interface slot `+0x1C`~~. Closed by hooking the setter
  itself rather than its callers; see 5.3.
- Whether `SpawnPointProductionExitUpdate` (26 uses in Edain, mostly spawner structures) should be
  covered. It is a separate class with its own layout, and the same five edits would have to be
  repeated for it.
- Whether the global ("all producers") arm should learn to carry a target. It needs a client change
  as well, since the stock evaluator cannot produce a message that is both global and
  object-targeted.
- Whether the banner should be redrawn every frame while a smart rally is active, so that it glides
  after a moving target rather than snapping on the ControlBar's context refresh (5.6). The engine
  has no per-frame rally-marker update to hook, because a stock rally point never moves.
- What `Object` vtable `+0x244` is, precisely. It is called on the container a unit is leaving,
  with a destination, only on the walk-to-the-point arm, and suppressing it is what fixed the two
  destinations - but it has eighteen callers across the binary and none of them was read.
- Chasing a target without `aiGuardObject` at all, if guard turns out to hold a post. `aiEnter`
  (state `0x42`) demonstrably chases a moving object - it is how a unit boards a moving transport,
  and it is what the dead slaughterhouse path uses - but what it does on arriving at something it
  cannot enter is unknown. State `0x1A` takes a lone `Object *` in the same slot and is reached
  from the `MSG_GET_REPAIRED` case body, so it is another chase-an-object candidate.
