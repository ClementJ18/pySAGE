# Making the Palantir button open Objectives instead of the player list

A patch scope. Engine build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically
2026-08-12. Follows [`mission-objectives.md`](living-campaign/mission-objectives.md), which established that the
objectives system is intact and already authored in Edain's campaign data.

**Partly confirmed in game.** The tracker read and the symptom below come from a live RotWK process
on `Erebor_gold`; everything else is static analysis. Revised 2026-08-12 after that run.

## The mechanism: one button, three screens, and the chooser asked twice

The Palantir's objectives button does not show or hide. It **opens one of three movies**, and the
same predicate is consulted **twice** on the way. First in the button's own callback
(`0x006D40C9`), which picks *which handler runs*:

```asm
006d40cc  mov  ecx, [0x00DE412C]
006d40d2  call 0x00625456          ; <-- the chooser, first ask
006d40d7  test al, al
006d40d9  je   0x006D40E2
006d40db  call 0x00914EF0          ; -> "PlayerTribute.apt"   <- predicate TRUE
006d40e2  call 0x008E8843          ; -> asks again, below     <- predicate FALSE
```

The hotkey dispatch (`0x0081FFAA`) repeats that branch verbatim at `0x0081FFD8`. `0x00914EF0`
pushes `PlayerTribute.apt` and asks nothing further — **that is the screen a skirmish or War of the
Ring battle actually gets**, and `0x008E8843` is never entered.

Inside `0x008E8843`, if it is reached, the chooser is asked a second time:

```asm
008e8952  mov  ecx, [0x00DE412C]
008e8958  call 0x00625456          ; <-- the chooser, second ask
008e895f  xor  esi, esi
008e8961  test al, al
008e8968  je   0x008E8972
008e896a  inc  esi
008e896b  push 0x00C18C2C          ; "PlayerStatus.apt"   <- predicate TRUE
008e8970  jmp  0x008E8977
008e8972  push 0x00C18C5C          ; "Objectives.apt"     <- predicate FALSE
```

`PlayerStatus.apt` is the player/enemy list; `PlayerTribute.apt` is the resource-transfer screen.
The two handlers carry the *same* guard chain (`0x008E8865`–`0x008E88EA` and `0x00914F00`–
`0x00914F81` are instruction-for-instruction the same tests), differing only in the already-open
check each makes on its own screen — so anything that reaches one would reach the other.

The chooser, `0x00625456`, returns 1 — meaning *not a campaign screen* — if **any** of:

```asm
00625459  call 0x00441B7C            ; game type in {1, 5}   (reads [obj+0x110])
00625462  cmp  [esi + 0x110], 2      ; game type == 2
0062546b  [0x00DE7CD8] exists && 0x007B0F25() == 1
00625484  && [0x00DE7CD8 + 0xED4] in {1, 2, 5}
```

All three terms are **game-type checks**. Nothing in the chain consults the map, the campaign, or
whether objectives exist — which is why a WotR battle lands on the tribute screen no matter how the
map is authored.

## Corrections to earlier revisions of this document

**Revision 1** named `0x006D7873` as the gate and proposed a five-byte patch there. That was wrong:
that call site sits in a block whose show/hide helper (`0x0080043E`) targets the APT function
**`FlashObjectivesButton`** (`0x00C4E4D0`) — it controls whether the button *flashes*, not which
screen it opens. Both gates are real and independent: `0x00441E4A` ("living world active")
suppresses the flash, `0x00625456` (game type) picks the screen. Only the second matters here.

**Revision 2** found `0x00625456` and patched the call at `0x008E8958` — the right predicate, but
only its *second* ask. Applied and verified against the install, tested on `Erebor_gold` (a map with
three `MissionObjectiveTag`s, confirmed present in the live tracker at `0x00DE8C94`), the button
still opened the tribute screen, because in a skirmish-mode battle the *first* ask at `0x006D40D2`
already routes the click to `0x00914EF0` and `0x008E8843` never runs.

Both mistakes have the same shape: taking the first site that matched as *the* site, without
walking outward to ask who reaches it. Enumerating the predicate's 31 callers and reading the two
that sit in the Palantir's own code would have caught the second one before the live test —
`0x006D40D2` and `0x0081FFD8` are in that list, adjacent to the branch they gate.

## The patch — implemented as `objectives-screen`

The map's own data is the opt-in: **if a map declares objectives, the button opens them**. No new
INI field, and nothing to clear between maps.

```sh
sage-patch apply objectives-screen --in game.dat --out game.dat
sage-patch verify objectives-screen game.dat
```

**Three** calls are redirected into one cave that asks a different question first:

```
at 0x006D40D2   e8 7f 13 f5 ff     call 0x00625456   <- the button's ask: tribute, or 0x008E8843?
at 0x0081FFD8   e8 79 54 e0 ff     call 0x00625456   <- the hotkey's, same branch
at 0x008E8958   e8 f9 ca d3 ff     call 0x00625456   <- inside 0x008E8843: player list, or objectives?
become          e8 <rel>           call <cave>
```

All three, or none: the outer two decide whether `0x008E8843` runs at all, so redirecting only the
inner one leaves every skirmish and WotR click on `PlayerTribute.apt` — which is exactly what
revision 2 shipped.

and the cave, as it assembles:

```asm
00ed4000  push ecx                          ; the stock predicate's `this`
00ed4001  mov  eax, [0x00DE8C94]            ; TheMissionObjectiveTracker
00ed4006  test eax, eax        ; je fallback
00ed400e  mov  eax, [eax + 0x10]            ; the objective list
00ed4011  test eax, eax        ; je fallback
00ed4019  mov  edx, [eax + 8]               ; end
00ed401c  sub  edx, [eax + 4]               ; - begin
00ed401f  cmp  edx, 8          ; jb fallback  (entries are 8 bytes; one is enough)
00ed4028  pop  ecx
00ed4029  xor  eax, eax                     ; false -> Objectives.apt
00ed402b  ret
00ed402c  pop  ecx                          ; fallback:
00ed402d  jmp  0x00625456                   ; tail call, `this` intact, its ret is ours
```

The list is read exactly the way the HUD reads it (`0x006D789C`, `0x0079DEA8`), so "declares
objectives" means the same thing to the patch as to the engine.

**A map with no `MissionObjectiveList` is indistinguishable from stock**, because the fallback edge
runs the original predicate unchanged — skirmish and multiplayer keep the tribute screen. The
predicate itself is never modified; it has 31 callers and decides much more than this button, so
only these three call sites are redirected.

The trade is that a campaign map cannot have both: on a map that declares objectives, the button no
longer reaches the tribute or player-list screens. Given no skirmish map declares a
`MissionObjectiveList` and every campaign map does, that lands where it should.

**Verification.** The patch refuses to apply unless the screen pushes (`0x008E896B`, `0x008E8972`),
both handler calls on each outer branch (`0x006D40DB`/`0x006D40E2`, `0x0081FFE1`/`0x0081FFEB`) and
the stock predicate's first bytes are exactly as expected, so a build whose branches moved or
swapped fails loudly rather than having an unrelated call redirected. Thirteen tests cover the cave
by disassembling it back — `ecx` balanced on every edge, all three guards landing on the same
fallback, the objectives edge returning zero, and the fallback tail-calling rather than calling —
plus one asserting a file with any single site left stock does not verify.

### If you want objectives everywhere regardless

```
at 0x006D40D9   74 07      je  0x006D40E2      ; the button's route
become          eb 07      jmp 0x006D40E2
at 0x0081FFDF   74 0a      je  0x0081FFEB      ; the hotkey's
become          eb 0a      jmp 0x0081FFEB
at 0x008E8968   74 08      je  0x008E8972      ; the screen choice
become          eb 08      jmp 0x008E8972
```

Three bytes, always `Objectives.apt`. Not bundled: it also removes the tribute and player-list
screens from ordinary skirmish and multiplayer, where those are correct. Note that all three
branches have to flip — the first alone only trades the tribute screen for the player list.

### If you later want an explicit `EnableObjectiveUI`

The `MissionObjectiveList` field table at `0x00C537E8` holds two rows and a terminator, with string
data immediately after, so it cannot grow in place — but it has exactly one reference
(`0x00835DF2`), making relocation a one-dword repoint. The cost is the rest: the list object is only
`0x10` bytes (`push 0x10` at `0x008364B4`) with no free member, so the field would set a global, and
a global needs clearing per map — which means also hooking the block parser at `0x00836497`. Three
hooks and a lifetime problem, against the shipped version's one hook and none.

## Unknowns

| | question | why it matters |
|---|---|---|
| 1 | What are game types 1, 2 and 5 exactly? | Determines whether a WotR battle is caught by the first, second or third term — and whether a narrower patch could target only the living-world case |
| 2 | Is `tracker->[0x10]` reset between maps? | The install at `0x008364D5` happens **only if currently null**, and the already-set path discards the new list. No reset was found at any of the 16 references to `0x00DE8C94` nor in the vtable (`0x00C537A0`). Since objectives work across successive linear-campaign missions, one must exist — most likely the tracker is rebuilt per map. **Partly answered:** in a live skirmish on `Erebor_gold` the tracker held that map's three entries and nothing else, so whatever the mechanism, the list is the current map's |
| 3 | Does `Objectives.apt` render correctly when opened from a living-world battle? | It is opened as a normal screen push, so probably yes, but it has never been opened in that context — and until revision 3 it had never been opened at all outside the linear campaign |

Unknown 2 matters for option three specifically, since that variant reads the list to make its
decision.

## Method

The outer route was found by reading the *callers* of the two handlers rather than the screen
strings — `PlayerTribute.apt` has its own push site (`0x00914FC3`) that no string search from
`Objectives.apt` reaches. That the live tracker held `Erebor_gold`'s three entries while the button
still opened the tribute screen is what proved the patched call was never executed.

Chooser located by finding the `PlayerStatus.apt` / `Objectives.apt` string references and reading
the branch between them; predicate decomposed by following each term. Field and block tables dumped
as 16-byte rows. APT helper identities resolved by reading the verb and target strings each helper
pushes (`_show`/`_hide` plus a named APT function) — the step whose omission produced the error
corrected above.
