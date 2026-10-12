# Several contain modules on one object

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`.

**Goal.** Edain's Barrow Wight lair should take Angmar's tribute carts (a `SlaughterHordeContain`
that pays out for them) and also hide wights (a `TunnelContain`). Edain's
`AngmarBarrowWightLair_Player` declares the slaughter and its child
`AngmarBarrowWightLair_Player_Independant` removes it before adding the tunnel, because the two do
not work together.

**Verdict:** an object keeps one contain, the last one it declares, and every question about
entering it is asked of that one. A second contain is constructed and never consulted. The patch
`multi-contain` makes each place that asks about a *particular rider* pick the contain that rider
is for. A secondary contain can only be a slaughter contain, because everything that happens to a
passenger after it is inside still goes through the one stored contain.

- **Cost:** ten call-shaped hooks and a 370-byte cave (`.mltcnt`). No INI change: declaring the
  slaughter contain *before* the contain that keeps passengers is the opt-in.
- **Risk:** moderate. Ten sites in the enter path, all logic-side but one (the hint). An object
  whose stored contain accepts the rider, and every horde, behaves exactly as stock.
- **Status:** built ([`patches/multi_contain.py`](../patches/multi_contain.py)), statically
  verified against the repo's `game.dat`, and every cave routine emulated
  (`tests/sage_patch/test_multi_contain.py`). **Not runtime-verified.**

## 1. One contain per object

The `Object` constructor's module loop asks every behaviour module for its contain and stores any
non-NULL answer, with no test for one already stored:

```
0069a3ce  mov  eax, [edi]              ; edi = module + 0x0C, the BehaviorModuleInterface
0069a3d0  mov  ecx, edi
0069a3d2  call [eax+8]                 ; getContain()
0069a3d5  cmp  eax, ebx
0069a3d7  je   0x69a3df
0069a3d9  mov  [esi+0x258], eax        ; Object+0x258: the last contain declared wins
```

`.text` holds about 425 `mov` loads from a `+0x258` displacement, most of them this field. A census of the call sites that load it and then call
through the contain's vtable (a short register-tracking scan over every `mov r32, [r32+0x258]`)
puts 130 on `getHordeIface` (`+0x7C`) alone, and dozens each on the list, count and iteration
slots. Exiting, evacuating, dying with passengers inside and a passenger dying all go through it.
Making every one of those aware of a second contain is out of reach for a byte patch, so the
second contain must be one that never keeps anybody.

## 2. A slaughter contain keeps nobody

`SlaughterHordeContain` is a `HordeGarrisonContain` (constructor `0x008835AB`, `0x9EC` bytes,
contain interface at module `+0x20`, vtable `0x00C5F0D0`). Against its base
(`HordeGarrisonContain`, `0x00C5C9F0`) and `TunnelContain` (`0x00C5DCE0`), its contain interface
overrides five slots:

| slot | `HordeGarrisonContain` | `SlaughterHordeContain` | `TunnelContain` |
|---|---|---|---|
| `+0x30` "I slaughter" | `0x009188EB` `xor al, al` | `0x008BD372` `mov al, 1` | base |
| `+0x34` rally to slaughter | `0x009188EB` | `0x008BD372` | base |
| `+0x5C` | `0x0087BFA6` | `0x00883935` | `0x00880FC6` |
| `+0x98` `isValidContainerFor` | `0x0087D0E0` | `0x008838C3` | `0x0088103B` |
| `+0x9C` `addToContain` | `0x0087CFEB` | `0x008836D3` | base |

`SlaughterHordeContain::addToContain` (`0x008836D3`) only takes a rider that is not already
contained (`[rider+0x27C] == 0`), and sends a non-horde one (`KindOf` byte `+0x115` bit `0x20`
clear) to module slot `+0x78`, `0x00883B4A`. That routine pays the `CashBackPercent` (the
`MONEY_DEPOSIT` at `0x00883CB7`), shows the floating cash text, grants experience, and then:

```
00883f2f  push 0x17
00883f31  push 8
00883f33  mov  ecx, esi                ; the rider
00883f35  call 0x698ec3                ; Object::kill
00883f3a  mov  ecx, [0xde412c]
00883f40  push esi
00883f41  call 0x62bbab                ; GameLogic::destroyObject
```

The rider is never put in a list and never has its container set, so nothing later looks for it
through `Object+0x258`. That holds for the non-`HORDE_MEMBER` arm only: a horde member
(`ObjectStatus` 38) goes to `0x0087CD76`, which does put it in the contain's list. The patch
therefore leaves hordes and horde members alone.

A tribute cart (`AngmarTributkarrenCarnDum` and its two siblings) is `INFANTRY ... DOZER` with a
`DozerAIUpdate`: a single non-horde unit, the arm above.

## 3. The questions asked about one rider

`isValidContainerFor` is `__thiscall (Object *rider, Bool, Bool checkCapacity)`, `ret 0xC`. The
`OpenContain` core (`0x0086603B`) only tests status, `KindOf`, `PassengerFilter` and relationship,
and the overrides add tests in front of it, so it is safe to ask speculatively. `TunnelContain`'s
forces the second flag to 0; the patch passes 0 for both, which asks only whether this kind of
rider belongs, and leaves capacity to the caller's own question.

Every site that asks the target's contain about a specific rider, found by tracking the register
each `+0x258` load lands in to the vtable calls made through it (slots `+0x98`, `+0x9C`, `+0x158`
entry position, `+0x44`, `+0x30`):

| site | what | target | rider | loaded into |
|---|---|---|---|---|
| `0x0082CC38` | `ActionManager::canEnterObject` (`0x0082CBD5`) | `edi` | `esi` | `ebx` |
| `0x0082CF1A` | enter hint (`0x0082CEFB`) | `edi` | first of the selection in `esi` | `ebx` |
| `0x0076F540` | `AIGroup` pre-enter filter (`0x0076F518`), per member | `[[ebp+8]+0xC]` | `ebx` | - |
| `0x00751645` | `AIEnterState::onEnter` (`0x007515E1`) | `ebx` | `esi` | `ecx` |
| `0x007560AB` | `AIEnterState::update` (`0x00756067`), goal refresh | `ebp` | `ebx` | `ecx` |
| `0x0075618C` | `AIEnterState::update`, arrival and `addToContain` | `ebp` | `ebx` | `esi` |
| `0x00752B5B` | `AIEnterState::onExit` (`0x00752B0F`), release | `eax` | `ebx` | - |
| `0x007517E7` | `AIEnterAndAttackState::onEnter` (`0x00751777`) | `edi` | `esi` | `ecx` |
| `0x00756368` | `AIEnterAndAttackState::update` (`0x0075620A`), `addToContain` | `ebp` | `ebx` | `ebp` |
| `0x00752BDC` | `AIEnterAndAttackState::onExit` (`0x00752B73`), release | `eax` | `ebx` | - |

The two states are named by their vtables' slot 0, which returns the strings `"AIEnterState"`
(`0x00C29538`) and `"AIEnterAndAttackState"` (`0x00C295E8`); slots `+8`/`+0xC`/`+0x10` are
`onEnter`/`onExit`/`update`. `canEnterObject` has twelve callers, among them the client's context
walker (`0x0069D27E`, kinds 8, 9 and 15) and both enter states, so it is the gate on both the
command and the walk. `0x0082CC38` loads the contain once into `ebx`, and every contain question
the predicate asks after it - `+0x18`, `+0x20`, `+0xD8`..`+0xE4`, `+0x114`, `+0x124`, `+0x38`,
`+0x98` - is asked of that `ebx`.

The group filter matters because a player's right-click goes through it: the `MSG_ENTER` handler
reaches `0x00774EDF` -> `0x00774897`, which calls `0x0076F518` before handing out orders. Each
member the stored contain refuses is erased from the group (`0x0076EC79`), so without the hook the
carts are dropped before they are ever ordered.

The enter hint returns `0xCB` - the slaughter cursor - when the contain answers `+0x30`. Its rider
is the first selected drawable's object: `[[[esi]]+8]` is the `Drawable`, `+0xFC` its `Object`.

### The release on exit

Slot `+0x44` (`0x00867D20`, shared by every class) keeps a map at `this+0x3C` from a rider's id to
the phase of its approach. `onEnter` records phase 0 through it; `onExit` erases with phase 2,
which is a find-then-erase. By `onExit` a slaughtered cart is already destroyed, so it cannot be
matched again. The hooked `onExit` erases the rider from every contain on the target instead,
which is a no-op where it was never recorded.

## 4. The patch

`pick(target, rider)` returns, in order of preference:

1. `target+0x258` if there is none, if there is no rider, if the rider is `KindOf HORDE` or
   `HORDE_MEMBER`, or if it accepts the rider;
2. the first other contain module, in declaration order, that answers `+0x30` (slaughter) and
   accepts the rider;
3. `target+0x258` again, so a refusal reads exactly as it does today.

Each load site becomes `call stand-in` / `nop`; the stand-in saves `eax`/`ecx`/`edx` (except the
destination), calls `pick`, and puts the answer in the register the site loaded. The flags are
set by the site's own next instruction (`test` or `cmp`), as before. The hint's stand-in finds its
rider from the selection. The group site keeps its three pushes and calls a stand-in that picks
and then tail-jumps to the chosen contain's `isValidContainerFor`, whose `ret 0xC` returns to the
site. The two releases become `push ebx` / `push eax` / `call release`.

No branch lands inside any of the ten rewritten ranges (a scan of every `call`/`jmp`/`jcc` in
`.text`).

## 5. Using it

Declare the slaughter contains first and the contain that keeps passengers last:

```ini
Behavior = SlaughterHordeContain ModuleTag_SlaughterMe
    PassengerFilter = ANY +AngmarTributkarrenCarnDum +AngmarTributkarrenHillman +AngmarTributkarrenOrcs ALLIES
    ...
End

Behavior = TunnelContain ModuleTag_Contain
    PassengerFilter = NONE +BarrowWight_Summoned +BarrowWight ...
    ...
End
```

The two `PassengerFilter`s should not overlap. A rider both accept goes to the last-declared one.

`sage_lint`'s `unreachable-contain` rule checks the ordering. The patch's `ini_surface` publishes
the engine limit `contain.secondary_slaughter = 1` into the mod's `.sagepatch`, and with that limit
set the rule warns about every earlier contain that is not a slaughter contain, because no enter
order can reach it. It is silent on a stock engine. Against Edain today it reports 12 objects,
all of them unreachable on stock as well: Gandalf's four forms (hobbit `TransportContain` ahead of
the ring), five cave trolls (two `TransportContain`s) and three horde objects (two `HordeContain`s).

No current Edain object should be affected: a text scan of Edain's object INI (following
`ChildObject` inheritance and `RemoveModule`, not `#include`) finds no object with a slaughter
contain ahead of its last contain. Gandalf's
shape - a hobbit `TransportContain` ahead of the ring's `CitadelSlaughterHordeContain` - is the
reverse, and is untouched: a `TransportContain` keeps passengers, so it is never picked second.

## 6. Not covered, and what to check in game

- **Hordes** entering a secondary slaughter contain (see §2). `AIHordeEnterState` is not hooked.
- **Other rider-specific askers** the census found and the patch leaves alone: script and AI-player
  helpers at `0x005F145A`, `0x005F26ED`, `0x00747C8C`, `0x007C5E83`, `0x007C99C7`, the
  container-to-container transfer at `0x0082CAC7`, contain-internal callers in `0x0087xxxx`, and
  `0x00910C6F`. A script or skirmish-AI order that goes through one of them sees only the stored
  contain.
- **The group's walk target.** `0x00774EDF` reads the stored contain's entry position for the group
  as a whole. Each rider's `AIEnterState` then takes its own goal from the contain it is for, so at
  worst a cart sets off towards the tunnel's door and turns.

In game, on a lair carrying both:

1. Select a cart and hover over the lair: the slaughter cursor shows, and right-click sends it in.
   The cart is destroyed at the door and the cash text appears.
2. A wight still enters, is hidden, and leaves at another lair.
3. A mixed selection of carts and wights, right-clicking the lair: both kinds go to their own
   contain.
4. Destroy a lair with wights inside: they come out as they do today.
