# Making the AI respect a disabled `REVIVE` button — reverse-engineering notes

The RE behind [`patches/ai_revive_gate.py`](../patches/ai_revive_gate.py). ROTWK `game.dat` build
`2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-07-30.

## TL;DR

- `BuildAssistant::canMakeUnit` (`0x00794F38`, `TheBuildAssistant` vtable `+0x68`) is the **only**
  gate the AI consults before deciding a producer may make something.
- It walks the producer's `CommandSet` and splits in two. The **template** branch evaluates the
  button's `NEED_UPGRADE` / `NeededUpgrade` requirement. The **revive** branch checks only
  `Command == REVIVE` and a positional count. **It never reads `Options` or `NeededUpgrade`.**
- So a `REVIVE` button disabled by an unobtainable `NeededUpgrade` is refused to the player and
  honoured for the AI.
- The patch hooks the revive branch's 6-byte entry and routes a matched slot through the engine's
  *own* upgrade gate at `0x0079502A`, having first counted the slot. 6 bytes edited, 40 bytes of
  cave, no new engine calls.
- `canMakeUnit` has **five** call sites, and only four are AI. The fifth is `BuildAssistant`'s
  own `+0x64` gate reaching it by a **virtual self-call** — the edge the ControlBar and
  `queueCreateUnit` come in on. The cave therefore tests its own return address and takes the
  stock edge for anything that did not ask directly. See
  [Who asks `canMakeUnit`](#who-asks-canmakeunit).

## Why every building carries every hero's slot

Hero recruitment in Edain (and any mod using the same idiom) goes through the engine's revive
system: a hero sits in the player's revivable list from the start, and the button that fields it is
a `Command = REVIVE` button, not `UNIT_BUILD`. The engine even picks the wording — the tooltip
builder at `0x008083F2` chooses between `CONTROLBAR:GenericRecruitHero` and
`CONTROLBAR:GenericReviveHero` for the same button.

Heroes attach to those slots **by position**, so a building that should offer hero *n* must define
at least *n+1* `REVIVE` slots. The surplus ones are then disabled. The standard idiom, from
`data/ini/includes/commandbutton.inc`:

```ini
CommandButton Command_FakeHeroReviveSlot1
    Command       = REVIVE
    Options       = NEED_UPGRADE CANCELABLE HIDE_WHILE_DISABLED
    NeededUpgrade = Upgrade_HasDragonNestFireDrake     ; a citadel can never hold this
```

Census over one mod's merged ini tree — 95 `Command = REVIVE` buttons:

| gating | count | covered by this patch |
|---|---|---|
| `NEED_UPGRADE` + a `NeededUpgrade` list | 57 | **yes** |
| `NEED_UPGRADE` with no list | 1 | no — and the engine passes it for the player too, so parity holds |
| `DisableOnModelCondition` / `EnableOnModelCondition` only | 9 | **no** — see [Scope](#scope-what-this-deliberately-does-not-fix) |
| ungated (the slots meant to work) | 29 | n/a |

Two upgrades act as never-true sentinels (`Upgrade_HasDragonNestFireDrake`,
`Upgrade_MiniHordeLvl10`, 15 uses each), but plenty of the gates are **real** conditions
(`Upgrade_RingHero`, `Upgrade_KhazadDumFaction`, the Lothlórien wing upgrades). That is why the fix
has to *evaluate* the requirement rather than reject any button carrying the flag.

## `GUICommandType`

The command-type name table is at `0x00DA4D10`, 61 entries, recovered by finding the `"REVIVE"`
literal (`0x00C2C310`) and walking the pointer array around its single xref (`0x00DA4DC8`).
`GUICOMMAND_REVIVE = 46 = 0x2E`. `CommandButton+0x14` holds it (the `Command` INI field's offset,
from the `CommandButton` field-parse table).

Only five sites in `.text` test a command type against `0x2E`: `0x00697B19` (a ControlBar
"execute revive slot N" helper), `0x007950CE` (**`canMakeUnit`**), `0x00943F97` and `0x0094428F`
(the ControlBar's revive-slot populate), and `0x008083F2` (the tooltip builder). Nothing in the AI
region tests it — the AI reaches revives entirely through `canMakeUnit`.

## `BuildAssistant::canMakeUnit`

Found via the subsystem-registration idiom of [`engine-globals.md`](engine-globals.md):
`"TheBuildAssistant"` (`0x00BFF008`) has one xref, at `0x0063B7D6`, in the registration block that
allocates `0x28` bytes and calls the constructor at `0x007945C6`; that constructor stores vtable
`0x00C307D8`, whose slot 26 (`+0x68`) is `0x00794F38`.

Signature, from the three call sites and the body:

```c
Bool canMakeUnit(Object *producer /*[ebp+8]*/,
                 const ThingTemplate *what /*[ebp+0xC]*/,
                 Int reviveIndex /*[ebp+0x10]*/);
```

Locals: `[ebp-1]` = `isRevive` (`reviveIndex != -1`), `[ebp-8]` = the `CommandSet` slot index,
`[ebp-0xC]` = how many `REVIVE` buttons have been seen, `[ebp-0x10]` = the `CommandSet*`.

```
00794f46  if (!producer || (what == NULL && reviveIndex == -1)) return FALSE
00794f59  isRevive := reviveIndex != -1
00794f62  if (what) { for each module: if it is already producing `what` -> return TRUE }
00794fb6  cs := TheControlBar->findCommandSet(producer->getCommandSetString())
00794fce  if (!cs) return FALSE
00794fd4  slotsSeen := 0 ; i := 0
00794fdc  LOOP: btn := cs->getCommandButton(i)
00794fe9        if (!btn) goto NEXT
00794ff1        if (isRevive) goto REVIVE
          ; ---- template branch ----
00794ffb        cmd := btn->command
00794ffe        if (cmd != UNIT_BUILD(3) && cmd != DOZER_CONSTRUCT(0x35)
                    && cmd != FOUNDATION_CONSTRUCT(1)) goto NEXT
00795011        if (btn->getThingTemplate() != what) goto NEXT
          ; ---- the upgrade gate (GATE) ----
0079502a  GATE: if (!(btn->options & NEED_UPGRADE)) goto ACCEPT
00795034        n := 0 ; for each u in btn->NeededUpgrade [btn+0x28 .. btn+0x2c):
00795045            ok := (u->type == 1) ? producer->hasUpgrade(u)
                                        : producer->getControllingPlayer()->hasUpgrade(u)
00795077            if (ok) { n++ ; if (btn->NeededUpgradeAny) break }
0079508e        pass := btn->NeededUpgradeAny ? (n > 0) : (n == total)
007950ab        if (!pass) goto NEXT
007950ad  ACCEPT: player := producer->getControllingPlayer()
007950bb        if (!isRevive) return player->canBuild(btn->getThingTemplate())
          ; ---- revive branch ----
007950ce  REVIVE: if (btn->command != REVIVE(0x2e)) goto NEXT
007950d4          if (slotsSeen == reviveIndex) goto ACCEPT      ; <-- no gate, ever
007950dc  BUMP:   slotsSeen++
007950df  NEXT:   i++
007950e2          if (i < 33) goto LOOP
                  return FALSE
007950ee        return player->reviveMgr(+0x758)->canRevive(reviveIndex)
```

`Options` is `CommandButton+0x1C` and `NEED_UPGRADE` is **bit 6** (`0x40`) — index 6 of the
`Options` flag-name table at `0x00DA4C88`. `NeededUpgrade` is a vector at `+0x28`/`+0x2C`,
`NeededUpgradeAny` a bool at `+0x34`.

**The defect is one missing edge**: `007950d4`'s `je` goes straight to `ACCEPT`, skipping `GATE`.

## Who asks `canMakeUnit`

`canMakeUnit` is virtual, so its callers are `call [reg+0x68]` sites. Disassembling every one of
those in `.text` (388 candidate byte sequences, 388 real instructions) and keeping the ones that
either follow a `TheBuildAssistant` (`0x00DE8200`) load or sit inside `BuildAssistant`'s own code
leaves **exactly five**:

| site | caller | who |
|---|---|---|
| `0x008F5423` / `0x008F543B` | `0x008F5347`, the AI's "find a producer for this thing" | walks the player's object list, skips busy/disabled producers, requires a `ProductionUpdate`, then asks. Its callers build the AI's queue entries (`0x008F8A2F`) and cost estimates (`0x008F5E59`). |
| `0x009A08A5` / `0x009A0937` | `0x009A07F5`, an AI tactic | enumerates candidate templates, resolves each through `TheThingFactory`, then asks — the second loop first maps the template to its revive index, which is the hero-recruitment path. |
| **`0x00793F56`** | **`0x00793ECB`, `BuildAssistant` vtable `+0x64`** | **everyone else.** |

Both AI paths pass a revive index obtained from the player's revive manager (`Player+0x758`,
index-of-template at `0x0078131E`).

### The fifth caller, and why a scan misses it

`0x00793ECB` is `BuildAssistant`'s general "may this producer make this" gate. It reaches
`canMakeUnit` on its **own `this`**:

```asm
00793f4e  mov  eax, [esi]        ; esi = ecx = the BuildAssistant itself
00793f53  mov  ecx, esi
00793f56  call dword [eax+0x68]  ; -> canMakeUnit
00793f59  test al, al
00793f5b  jne  0x793f65          ; false -> return 1 (refused)
```

There is no `TheBuildAssistant` load anywhere near it, because it does not need one — which is
exactly why the original scan for "global load, then `call [reg+0x68]`" reported four callers and
concluded the function was AI-only. **It is not.** `+0x64` has **14** call sites, and they include
the ones that decide what a human sees and may do:

| site | what asks |
|---|---|
| `0x00940A3B`, `0x00940B84`, `0x00942EA9`, `0x00942F3F` | the **ControlBar** — whether a command button is available, which is what enables it and, under `HIDE_WHILE_DISABLED`, whether it is drawn at all |
| `0x008A1205` | `ProductionUpdate::queueCreateUnit` — the check every queued unit and hero passes before the cost is withdrawn |
| `0x0077B198`, `0x0077C605`, `0x00796806`, `0x0083E780`, `0x0088C27F`, `0x0088C2DA`, `0x008AD711`, `0x0097DCED`, `0x009EDC25` | other engine, script and AI production paths |

So an unconditional gate in the revive branch reaches the player's control bar. Symptom: heroes
whose matched slot is upgrade-gated stop being offered at all.

### Why the matched button is not the button

The stock revive branch uses the matched slot **only as a count** — reach `reviveIndex` REVIVE
buttons and the answer is `ReviveMgr::canRevive(reviveIndex)`, whichever button that happened to
be. Nothing reads the button, so nothing depends on it being the right one.

The ControlBar builds its own button→hero mapping in a separate walk (`0x00943F81`,
`mov [btn+0xC0], idx` at `0x00944340`; `+0xC0` is the attach field, `-1` when unattached, read
back by `Object::doCommandButton`'s revive case at `0x006973D3`). That walk has its own rules: it
runs over the **visible command range** rather than slots `0..32`, and it skips a button — without
advancing the index — when `ShowButton` (`CommandButton+0x106`) is false, or, in campaign and
Living-World games only (`0x005FF924`), when `Options` carries `NEED_UPGRADE`
(`test [btn+0x1c], 0x40` at `0x009442A8`).

Where those two walks disagree, the stock engine cannot tell. A gate can — it reads the matched
button, and answers for whatever slot the count landed on. That makes an unconditional gate wrong
on the player's path even where the button it *should* have evaluated is ungated.

This patch does not try to reconcile the two walks. It restricts the gate to the callers that ask
directly, which are only ever the AI's own choices, and leaves every path a human touches on the
stock edge — where the disagreement stays as harmless as it has always been.

## The patch

Hook the 6 bytes at `REVIVE` (`0x007950CE`, `83 7e 14 2e 75 0b`) with `e9 <rel32>` + `90`, into a
58-byte `.aigate` cave:

```asm
cmp dword [esi+0x14], 0x2E     ; GUICOMMAND_REVIVE
jne  -> 0x007950DF             ; NEXT
mov  eax, [ebp-0x0C]           ; slotsSeen
cmp  eax, [ebp+0x10]           ; reviveIndex
jne  -> 0x007950DC             ; BUMP
cmp dword [ebp+4], 0x00793F59  ; who asked? — see below
je   -> 0x007950AD             ; not the AI: ACCEPT, exactly as stock
inc  dword [ebp-0x0C]          ; count it now — see below
jmp  -> 0x0079502A             ; GATE
```

**Why the return address.** `canMakeUnit` opens `push ebp; mov ebp, esp`, so `[ebp+4]` is its
caller's return address for the whole body. The only non-AI caller is the `+0x64` gate's
self-call at `0x00793F56`, three bytes long, so `0x00793F59` is the one value that means "this
question came in through `+0x64`". One `cmp` separates the AI's own choices from the ControlBar,
production, scripts, and the AI's *execution* of a choice it has already made — and everything
in that second group takes the byte-for-byte stock edge. The patch cannot refuse a production or
hide a button; it can only change which producer the AI picks, which is the whole of the defect.

The constant is derived, not written down: the patch anchors the three bytes at `0x00793F56`
(`ff 50 68`) and adds their length, so a build whose layout moved fails on the anchor rather than
comparing against a stale address. It also asserts `BuildAssistant`'s vtable still names
`0x00793ECB` at `+0x64` — a `+0x64` that had moved would leave the player silently gated again.

`0x007950CE` has exactly one inbound edge (the `jne` at `0x00794FF5`), confirmed by scanning every
`jmp`/`jcc`/`call` displacement in `.text` and every immediate reference to the range — which is
what makes those 6 bytes takeable.

**Why route into `GATE` instead of re-implementing it.** `GATE` already handles
`NeededUpgradeAny`, the object-vs-player upgrade-type distinction, and the empty-list case (which
passes). Re-deriving that in the cave would be a second implementation of semantics the binary
already states, free to drift from the template branch. Register-wise the jump is safe: `GATE`
needs `esi` (the button) and `[ebp+8]` (the producer), both live; it clobbers `eax`/`ebx`/`ecx`/
`edi`, none of which is live across the revive branch.

**Why the slot is counted before `GATE` runs.** `GATE`'s failure edge is `goto NEXT`. If
`slotsSeen` had not advanced, the *next* `REVIVE` button would compare equal to the same
`reviveIndex` and be gate-tested in turn — so the AI would slide past a disabled slot onto the
following enabled one and answer for a hero the index does not name. Counting first makes a failure
final: no later slot can match, the walk runs out at `0x007950E2`, and `canMakeUnit` returns
`FALSE`. Concretely, for a citadel whose set is `GenericReviveSlot1`, `FakeHeroReviveSlot2..8`,
`GenericReviveSlot9`:

| reviveIndex | player | AI, stock | AI, counted first (this patch) | AI, not counted |
|---|---|---|---|---|
| 0 | slot 1, usable | allowed | allowed | allowed |
| 1–7 | fake slots, refused | **allowed** | refused | **allowed** (slides to slot 9) |
| 8 | slot 9, usable | allowed | allowed | allowed |

The middle column is the bug; the right-hand column is the tempting one-line fix that is subtly
wrong. `[ebp-0xC]` is dead on the accept path (nothing from `0x007950AD` onward reads it), so the
extra increment costs nothing.

## Composition with `commandset-limit`

`commandset-limit` raises the walk's bound at `0x007950E2` from 33 to N (see
[`commandset-button-limit.md`](commandset-button-limit.md#the-one-consumer-bound-that-is-raised-0x00794f38)),
so the two patches edit the same function 20 bytes apart:

```
007950ce  ai-revive-gate   6 bytes  (hook)
007950e2  commandset-limit 4 bytes  (scan bound)
```

No intersection, and the cave's four exits (`0x0079502A`, `0x007950AD`, `0x007950DC`,
`0x007950DF`) are all *below* the bound, so neither patch reads a byte the other writes. Either
order produces the same edits inside `canMakeUnit`; the two differ only in which cave takes the
lower RVA.

## Determinism

The added edge reads upgrade masks off the `Object` and its `Player` — logic state, identical on
every peer — so it is network- and replay-safe. The AI itself runs on the logic thread on all
peers, so a *non*-deterministic gate here would desync rather than merely misbehave, which rules
out the alternative below.

The return-address test is deterministic for the same reason and a stronger one: it reads the
call stack, which is a property of *how the function was entered*, not of any game state at all.
Every peer executes the same call from the same site.

## Scope: what this deliberately does not fix

**Model-condition-gated slots (9 of 95).** `DisableOnModelCondition` (`CommandButton+0x1E0`) and
`EnableOnModelCondition` (`+0x194`) are tested at `0x00942490` against a 19-dword mask at `+0x10C`.

✅ **That mask is on the `Object` (logic), not the `Drawable` (client)** — settled 2026-07-30 in
[`production-model-condition.md`](production-model-condition.md) §2. The gate's second argument
reads `+0x04` as `ThingTemplate*` and dispatches on the module at `+0x260`, which only an `Object`
carries; and `0x10C + 19*4 = 0x158`, exactly where the second `Matrix3D` copy in
[`live-object-model.md`](live-object-model.md) begins.

So **the desync objection is retired**: gating the AI on these nine is logic state, identical on
every peer, and extending the patch to them is now a question of whether it is wanted rather than
whether it is safe. The cheaper route remains converting those nine buttons to a `NeededUpgrade`
sentinel in ini, which needs no engine change at all.

**The template branch's other fields.** `RequireLevel`, `ShowButton`, `IsClickable` and the rest
are not consulted for `UNIT_BUILD` either. Making the AI honour those is a larger behaviour change
than fixing an asymmetry, and is not attempted here.

**`Command_TheodenReviveSlotHK`** carries `NEED_UPGRADE` with no `NeededUpgrade` list, which `GATE`
passes. That matches what the player's own evaluation does with it, so the patch reproduces the
player's behaviour rather than second-guessing the data.

**The two walks are still not reconciled.** The gate answers for whatever slot the positional
count landed on, which is the ControlBar's button only when the two walks agree — see
[Why the matched button is not the button](#why-the-matched-button-is-not-the-button). Restricting
the gate to the AI makes that harmless rather than correct: where they disagree the AI can refuse
a producer that could legitimately field the hero. Under-recruiting is the safe direction of a
patch whose defect is over-recruiting, so it is accepted here. Reconciling them properly means
teaching the walk the ControlBar's rules — `ShowButton`, the visible command range — and is a
larger change than this one.

## Status

**Static-verified, not yet runtime-verified.** The patch applies to a clean `game.dat`, `verify`
passes, and the installed hook and cave disassemble to the intended instructions with all four
exits landing on the intended labels. Confirming in-game that the AI stops recruiting from disabled
slots is open.

**The player's own recruit path is not yet re-tested in game.** It runs through
[the fifth caller](#the-fifth-caller-and-why-a-scan-misses-it): the ControlBar asks `+0x64`,
which asks `canMakeUnit`. A gate applied unconditionally there makes heroes unrecruitable for
the human player — Rohan's Merry and Gamling and a Create-A-Hero are the ones this shows on,
while Hama and Théoden are unaffected. The return-address test keeps the player's path
byte-for-byte stock, so it cannot happen by construction, but confirming it in a Rohan skirmish
is open.
