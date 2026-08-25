# Spell-store upgrade selection

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`). Implemented by
[`patches/experimental/spell_store_upgrade.py`](../patches/experimental/spell_store_upgrade.py).

## INI surface

Add one or more mappings to any `PlayerTemplate` block:

```ini
PlayerTemplate FactionGondor
    PurchaseScienceCommandSetUpgrade = Upgrade_SubFactionA GondorSpellStore_SubFactionA
    PurchaseScienceCommandSetUpgrade = Upgrade_SubFactionB GondorSpellStore_SubFactionB
End
```

Each value is exactly two names: `Upgrade CommandSet`. The field may repeat. Mappings are global
because upgrade names are global; placing them on `PlayerTemplate` makes them live beside the two
stock purchase-science fields without relying on the template pointer seen during parsing.

Selection is deterministic:

1. mappings are tested in declaration order;
2. the first mapping whose upgrade is complete and whose CommandSet exists wins;
3. declaring the same upgrade again replaces its CommandSet without changing its priority;
4. no match, an unknown upgrade, an out-of-range index, or an unknown CommandSet falls through to
   stock `PurchaseScienceCommandSet` / `PurchaseScienceCommandSetMP` selection.

The table holds 128 distinct upgrades. A line beyond that limit is consumed and ignored. The
SpellStore must be closed and opened to re-run `initializeSpellSlots`; no observer or cached player
state is installed.

## Hook scope

The patch redirects one call only:

```asm
00822ACF  E8 5F CE EF FF  call 0071F933
```

It becomes `call selector` in the appended `.ssupgr` section. The shared function at `0x0071F933`
is not changed and is the selector's tail-call fallback, so every non-SpellStore caller keeps stock
behaviour. The other engine edit is data plumbing: the one `push imm32` that names the
`PlayerTemplate` field table is repointed at a rebuilt table containing the new field.

The call receiver is preserved byte-for-byte into both paths. Existing pySAGE work identifies
`0x0071EFA2` as `CommandSetStore::findCommandSet(const AsciiString *)`; earlier ControlBar-focused
notes named both routines as ControlBar helpers. The class name is less important than the tested
ABI: thiscall receiver in `ecx`, one callee-cleaned argument, `CommandSet *` in `eax`.

## Runtime path

The parser stores two ref-counted `AsciiString`s per row. It does not resolve the upgrade while INI
files are loading, because the upgrade definition may not have loaded yet. At SpellStore open:

```text
mapping.upgrade name
    -> TheUpgradeCenter::findUpgrade (0x0066F5E5)
    -> UpgradeTemplate::upgradeIndex (+0x38)
    -> reject index >= 36 * 32
    -> Player.completedUpgradeMask[index >> 5] (+0x14C)
       test bit (index & 31)
    -> CommandSetStore::findCommandSet (0x0071EFA2)
```

Before the walk, `Player+0x34` is required to contain a `PlayerTemplate *`. The selector does not
read `PlayerTemplate+0x138/+0x13C` itself: the untouched `0x0071F933` fallback owns the SP/MP choice
and therefore remains the single source of stock behaviour.

## Evidence status

| Fact | Status | Evidence |
|---|---|---|
| `AptSpellStore::initializeSpellSlots` `0x00822A98` | **CONFIRMED** | traced call path; reopening reinitializes slots |
| SpellStore-only callsite `0x00822ACF` and stock bytes | **CONFIRMED** | `E8 5F CE EF FF` targets `0x0071F933`; patch asserts all five bytes |
| `Player::playerTemplate +0x34` | **CONFIRMED** | existing pySAGE layout and prior live work |
| completed upgrade mask `Player+0x14C`, 36 DWORDs | **CONFIRMED** | prior mask tracing and successful index-149 prototype |
| `UpgradeTemplate::upgradeIndex +0x38` | **CONFIRMED** | prior index-149 prototype |
| `PlayerTemplate` purchase fields `+0x138/+0x13C` | **CONFIRMED** | verified from the live `PlayerTemplate` field table before patching |
| `0x0071F933` purchase-science selector ABI | **HIGH** | original call plus successful prototype/fallback convention |
| `0x0071EFA2` CommandSet lookup ABI | **HIGH** | reused by existing pySAGE patches and the successful prototype |
| generic repeated-field parser and 128-row table | **HIGH** | apply/verify and synthetic disassembly tests; not yet played |
| upgrade classification (`PLAYER_UPGRADE` vs `OBJECT_UPGRADE`) | **OPEN** | no type offset is known; an object-only upgrade simply has no completed bit in this player mask |

The hardcoded index-149 prototype has been observed switching the SpellStore in play. The generic
name-based parser and multi-mapping implementation have not, so this patch remains experimental.

## Static safety and composition

- The patch refuses a build whose callsite is not the exact stock `call 0x0071F933`.
- It fingerprints both purchase-science fields by name and offset in the live field table.
- Its PE section is allocated after every existing section and found by name during verification.
- The live `PlayerTemplate` field table is copied rather than the stock address assumed, so field
  extensions such as `command-point-upkeep` compose in either order.
- Invalid data cannot make the mask read run past 36 DWORDs: the resolved index is bounded before
  the word and bit are computed.
- The selector preserves `ebx`, `esi`, `edi`, `ebp`, the original receiver, and the stock `ret 4`
  stack contract.
