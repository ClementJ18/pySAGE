# A porter delivers one upgrade — the `give-upgrade-all` patch

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`), verified byte-for-byte
against the shipped `game.dat`. The reading is static plus one live-process confirmation of the
data it turns on (§2); no site here has been watched executing under a debugger. The patched
binary has been played (2026-08-30) and the delivery behaves as described below, which is what
moved this patch out of `patches/experimental/`.

**Verdict:** `GiveUpgradeUpdate` treats "the upgrade this porter carries" as a singular. Three
sites ask `UpgradeCenter::firstSetIn` for *the* upgrade, and everything downstream — whether the
cursor is valid, whom the auto-deliver walks to, what the target receives — is decided by that one
answer. A porter holding three upgrades delivers exactly one of them, and is refused by every
target that cannot take that one. This patch makes all three sites plural.

## 1. What the engine does today

`SPECIAL_GIVE_UPGRADE` (`SpecialPowerType` 51) is the porter's targeted delivery; its sibling
`SPECIAL_GIVE_UPGRADE_NEAREST` (136) is the auto-deliver, selected by `DeliverUpgrade = Yes` on the
module. Both are `GiveUpgradeUpdate` (`ModuleData` 0xEC bytes, ctor `0x0089FC55`), and both run
through the same three questions.

**Which upgrade does the porter carry?** Its own object-upgrade mask, `Object+0x28C`, the same
bitset `GrantUpgradeCreate` writes. `UpgradeCenter::firstSetIn` (`0x0066F468`) walks the
`UpgradeTemplate` list at `TheUpgradeCenter+0x0C`, following `+0x64`, and returns the **first**
template whose `+0x38` index is set in that mask:

```
0066f468  mov  eax, [ecx+0xc]           ; the registry's list head
0066f46e  mov  edx, [eax+0x38]          ; UpgradeTemplate::upgradeIndex
0066f473  mov  ecx, edx
0066f475  and  ecx, 0x1f
0066f479  shl  esi, cl
0066f482  test [ecx+edx*4], esi         ; the caller's mask
0066f485  jne  0x66f48e                 ; -> return this one
0066f487  mov  eax, [eax+0x64]          ; else next
```

The list is newest-first, so "first" means **the upgrade declared last in the ini load order**,
which is not a property any modder is thinking about while writing `GrantUpgradeCreate` rows.

**Is a target valid?** The cursor's answer comes from
`InGameUI::canSelectedObjectsDoSpecialPower` (`0x006A4260`) → `SpecialPower::canDoAtObject`
(`0x0082D925`), which dispatches on the power's `Enum` through the byte table at `0x0082DD53` and
the jump table at `0x0082DD2F`. Enum 51 lands at `0x0082DCF7`, whose gate is `0x0082D780`:
allies-only, target not `KINDOF IMMOBILE`, a `SpecialPower` **literally named**
`SpecialAbilityGiveUpgrade` present in the store (the string is hardcoded at `0x00C362A0`), the
source owns a module for enum 0x33 — and then `GiveUpgradeUpdate::canGiveTo` (`0x0089FE64`):

```c
bool GiveUpgradeUpdate::canGiveTo(Object *target)
{
    UpgradeTemplate *u = UpgradeCenter::firstSetIn(&this->owner->upgradeMask);   // 0x0089FE77
    if (!u) return false;
    if (target->m_containedBy /*+0x27C*/) {                    // a horde member
        HordeIface *h = this->producerHordeIface(target);      // 0x0089FD77
        return h && h->vt[0xAC](u);                            // any member can accept u
    }
    return target->canAcceptUpgrade(u);                        // 0x00694914
}
```

`Object::canAcceptUpgrade` is the real predicate: the player must satisfy the upgrade's
`RequiredObjectFilter` (`UpgradeTemplate+0x80`), and the object must own a module whose
upgrade-interface (`module+0xC`, `vt[0x28]`) says it would fire on the resulting mask — in ini
terms, some module `TriggeredBy` that upgrade. `HordeContain::anyMemberCanAccept` (`0x0086ECAB`)
asks the same question of every member and every pending reinforcement.

Both halves are single-upgrade. **A porter carrying `A B C` is refused by a battalion that takes
`B` and `C` but not `A`** — with the invalid cursor and no diagnostic.

**Who receives it?** `GiveUpgradeUpdate::trigger` (`0x008A01B2`) re-checks `canGiveTo`, picks the
one upgrade again at `0x008A021B`, resolves the recipient — the target's own horde interface if it
is `KINDOF HORDE` (`0x0068C866`), else its producer's (`0x0089FD77`) — and hands it over:

```
008a024c  mov  edx, [eax]           ; horde:  HordeContain::giveUpgradeToMembers(u, force=0)
008a0255  call [edx+0xb8]           ;         0x00871A90 - gates each member on canAcceptUpgrade
008a025d  push [ebp-4]              ; plain:  canAcceptUpgrade(u)
008a0262  call 0x694914             ;         and, if it passes,
008a0287  call 0x69388b             ;         Object::giveUpgrade(u) + the flash FX
```

A zero from the picker takes the `je 0x008A02BB` edge, which is the same tail an empty-handed
porter reaches: `0x0089FE01` plays `SpawnOutFX` and fades the porter out.

**Whom does the auto-deliver walk to?** `DeliverUpgrade = Yes` runs the search at `0x0089FEC7`,
which picks the one upgrade at `0x0089FF02`, captures it in a filter functor built on the stack —
`{vtable 0x00C67A88, 0, upgrade}` — and scans for the nearest object the filter accepts. The
filter's predicate is `0x00660E04`, private to this module (its vtable is constructed at exactly
two sites, both inside `GiveUpgradeUpdate`, and nothing else reaches the function):

```c
bool UpgradeFilter::operator()(Object *o)   // 0x00660E04
{
    return o->canAcceptUpgrade(this->upgrade /*+8*/)   // 0x00694914
        && !o->hasUpgrade(this->upgrade);              // 0x00691421
}
```

So the porter walks to a recipient for upgrade #1 or to nobody.

## 2. The data this turns on, read out of a live match

A `EvilmenUpgradeGranterPorter` carrying three `GrantUpgradeCreate` rows, read with `sage_live`
from a running game (object ids are that match's):

| object | `+0x28C` mask | `+0x27C` containedBy | `+0x258` contain | `KINDOF HORDE` |
|---|---|---|---|---|
| porter, id 5 | `… 000001c0 …` (bits 70, 71, 72) | 0 | 0 | no |
| `EvilmenUmbarPikeHorde`, id 7 | empty | 0 | `0x0921DEE8` | yes |
| `EvilmenUmbarPike`, id 8 | empty | `0x09784448` (id 7) | 0 | no |

Walking `TheUpgradeCenter`'s list in the same order `firstSetIn` does resolves those three bits to
`Upgrade_MordorFireArrows` (70), `Upgrade_MordorForgedBlades` (71) and `Upgrade_MordorHeavyArmor`
(72) — and returns **72 first**, because the list is newest-first. `EvilmenUmbarPike` carries
`TriggeredBy` modules for `Upgrade_AngmarDarkIronArmor` and `Upgrade_AngmarDarkIronBlades` and for
no Mordor upgrade at all, so `canAcceptUpgrade` is false for the one upgrade the engine ever
offers it, and the battalion is not a legal target. Harad and Khand units — and the single-object
`EvilmenHaradMumakil` — do use `Upgrade_MordorHeavyArmor`, which is why the same ability accepts
them. That asymmetry is what the patch removes.

## 3. What this does

Appends a `.upgall` PE section and rewrites four windows.

| VA | stock | becomes |
|---|---|---|
| `0x0089FE64` | `GiveUpgradeUpdate::canGiveTo` entry | `jmp` to `can_give_any` |
| `0x008A021B` | `call UpgradeCenter::firstSetIn` in `trigger` | `call grant_rest` |
| `0x0089FF17` | `mov [ebp-0x24], ebx` — zeroes the filter's `+4` | `mov [ebp-0x24], esi` — the owner |
| `0x00660E04` | `UpgradeFilter::operator()` entry | `jmp` to `filter_any` |

**`can_give_any`** replaces the validity predicate with the same test over every upgrade in the
mask instead of one: resolve the recipient exactly as stock does (`+0x27C` non-zero → the
producer's horde interface, else the target itself), then loop, and answer yes on the first
upgrade that recipient accepts. Every other stock outcome is preserved, including "the member's
horde is gone → no".

**`grant_rest`** stands in for the trigger's own call to the picker and returns what that call
returned — so the twenty instructions after it are untouched — except that it returns the first
**acceptable** upgrade rather than the first present one, and grants every *other* acceptable one
itself before returning. The engine then delivers the returned upgrade through its own two arms,
with its own FX. Consequences worth stating:

- the upgrade stock hands over is now always one the recipient accepts, so the horde arm can no
  longer put an unaccepted upgrade's bit on the horde container object (`0x00871AE5` grants to the
  container unconditionally, and only then gates each member);
- nothing acceptable → the cave returns 0, which is the picker's own "this porter carries nothing"
  answer and reaches a path stock already runs;
- the extra upgrades are granted with the same call the engine uses for the chosen one —
  `HordeContain::giveUpgradeToMembers(u, force=0)` for a horde, `Object::giveUpgrade` for a plain
  object — each gated by the same acceptance test first. They do not repeat the flash FX or the
  delivery sound, which fire once for the chosen upgrade.

**`filter_any`** makes the auto-deliver's search accept a candidate that can take *any* carried
upgrade. It needs the porter, and the filter functor only captured an upgrade — hence the
three-byte edit at `0x0089FF17`, which parks the owning `Object` in the functor's `+4` slot. That
slot is dead in stock: both constructions of this functor type zero it (`0x0089FAFE`, `0x0089FF17`)
and nothing reads it. `filter_any` falls back to the exact stock predicate when `+4` is null, so a
functor built by any path this patch did not edit behaves as before.

## 4. Why the cave can trust its registers

`grant_rest` replaces a `call` rather than a function entry, so it reads three of the caller's
registers. Each is pinned by an anchor the patch asserts before it writes anything:

| register | at `0x008A021B` | anchored by |
|---|---|---|
| `ebx` | the owning porter | `0x008A01D8` `mov ebx, [esi+8]`, still live at `0x008A02B5` `push ebx` |
| `edi` | the target | `0x008A022B` `mov eax, [edi+4]` / `test byte [eax+0x115], 0x20` |
| `esi` | the module | `0x008A0240` `push edi` / `mov ecx, esi` / `call 0x0089FD77` |

The cave saves and restores all four callee-saved registers, cleans the one argument the picker's
`ret 4` cleaned, and calls only functions whose stack discipline is read off their own `ret`:
`0x0068C866` (`ret`), `0x0089FD77`, `0x00694914`, `0x0069388B`, `0x00691421` and `vt[0xAC]` (all
`ret 4`), and `vt[0xB8]` (`ret 8`).

## 5. Determinism

Every edited site is logic-side and runs inside a special power's own execution, which every peer
evaluates on the same frame from the same object state. The cave reads two bitsets and a template
list — no timing, no local player, no rendering — and the extra grants go through the engine's own
`giveUpgrade` entry points, so the upgrade masks they produce are the ones a peer would produce.
Replay- and network-safe by the same argument as the stock delivery it extends.

## 6. Blast radius

`GiveUpgradeUpdate` is the only class involved. `canGiveTo` has two callers, both in this module's
own code paths (`0x0082D7E4`, the cursor gate, and `0x008A01FA`, the trigger's re-check); the
picker call this patch redirects is one of thirteen and the other twelve are untouched; the filter
predicate is unreachable except through a vtable this module builds. An object with no
`GiveUpgradeUpdate` module cannot reach any of it.

For a porter carrying exactly one upgrade — every vanilla porter, which gets its upgrade stamped on
at spawn rather than from `GrantUpgradeCreate` — the patched path computes the same answers as
stock, with one deliberate difference: an upgrade the recipient cannot accept is no longer handed
to the horde container. Stock cannot reach that state anyway, because `canGiveTo` would have
refused the target first.

## 7. Still unknown

- `Object+0x260`, which `0x0082D780` requires to be non-null, is the interface a behavior module
  returns from secondary-vtable slot `0x4C` (cached in `Object::init` at `0x0069A3EA`). Every live
  object measured in §2 had one, so it is not a gate this patch has to think about; which module
  provides it was not chased.
- The delivery sound and `GiveUpgradeEffect` FX fire once per trigger, not once per upgrade. Making
  them plural would mean moving them inside the cave's loop, which this patch does not do.
