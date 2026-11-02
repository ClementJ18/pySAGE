# PillageModule upgrade gates and independent StealAmount

`pillage-module-extension` extends the existing `PillageModule` in RotWK
`2.01.2614.37001`. It adds four upgrade conditions and an optional unsigned
`StealAmount`. Omission preserves the original transfer; an explicit value,
including zero, selects an all-or-nothing deduction with independent payout.
`StealPercentage` is not implemented. The earlier percentage research document
is historical and is superseded by this specification.

Status: implemented, applied and verified against the supported binary; native
event, money, mask and lifecycle paths executed in Unicorn with engine service
doubles. No in-game, multiplayer or replay/CRC test has been performed.

## INI syntax and behavior

Original syntax remains valid and takes the original transfer path:

```ini
Behavior = PillageModule ModuleTag_Pillage
    PillageAmount = 10
    NumDamageEventsPerPillage = 1
    PillageFilter = ANY
End
```

Extended example:

```ini
Behavior = PillageModule ModuleTag_Pillage
    PillageAmount = 10
    NumDamageEventsPerPillage = 2
    PillageFilter = ANY
    TriggeredBy = Upgrade_Pillage
    ConflictsWith = Upgrade_NoPillage
    RequiresAllTriggers = Yes
    RequiresAllConflictingTriggers = No
    StealAmount = 4
End
```

| Field | Type | Default / meaning |
| --- | --- | --- |
| `TriggeredBy` | Upgrade list | Empty: no activation requirement; otherwise any listed upgrade must be held |
| `ConflictsWith` | Upgrade list | Empty: no conflict; otherwise any held listed upgrade blocks the event |
| `RequiresAllTriggers` | Bool | No; Yes requires all entries in TriggeredBy |
| `RequiresAllConflictingTriggers` | Bool | No; Yes requires all conflicts before blocking |
| `StealAmount` | Unsigned dword | Omitted: native transfer; present: cost required for the independent payout |

The same native mask parser and tests used by `large-group-bonus` evaluate the
owner object's upgrades and its current controlling player's completed upgrades.
They test the two masks separately and OR their results. An ALL requirement split
between object and player therefore does not satisfy either individual test.
Conflicts take precedence over satisfied triggers. Upgrade names must already
be resolvable when parsed, as with the existing native mask parser.

The INI surface uses the supported grammar spellings `Ref[]:upgrades`, `Bool`, and
`Int`. The last describes an integer field to pySAGE; the actual engine parser is
unsigned and accepts the engine's `#` constants. There is no `UInt32` spelling in
the current `parse_type()` grammar. Its surface default is `None`, recording
omission rather than pretending that omitted and explicit zero are equivalent.

The event order is:

1. Run the stock PillageFilter against the victim with NULL player context.
2. Evaluate the new upgrade gates. Failure preserves the current partial counter.
3. Increment the native counter, compare against NumDamageEventsPerPillage, and
   return below the threshold. Threshold 0 or 1 attempts every accepted event.
4. Reset the counter before attempting the transaction.
5. Execute either the native transfer or the explicitly requested transaction.

There is no per-frame polling or activation latch. Grants, removals, conflicts and
owner changes are observed at the next event. Losing a requirement does not reset
partial progress. No dependency on `upgrade-module-removal` is necessary.

The fields implement reversible eligibility, not an actual UpgradeMux interface.
They do not add `Permanent`, upgrade animation/texture effects, or upgrade-removal
side effects.

## Money semantics

With StealAmount omitted, the original RotWK instructions still execute:

```text
amount = min(PillageAmount, victimResources)
withdrawn = nativeWithdraw(victim, amount)
if withdrawn != 0:
    nativeDeposit(attacker, withdrawn)
    originalPopup(withdrawn)
```

With StealAmount present:

```text
if victimResources < StealAmount:
    return
nativeWithdraw(victim, StealAmount)
if PillageAmount != 0:
    nativeDeposit(attacker, PillageAmount)
    originalPopup(PillageAmount)
```

The affordability comparison is unsigned. It happens before any withdrawal, so a
failed transaction performs neither money call. No partial withdrawal or payout
occurs. Native withdrawal is called with zero when the explicit cost is zero;
it returns without side effects, and its zero result no longer blocks payout.
For payout zero, withdrawal remains effective, and the deposit/+0 popup is skipped.
All arithmetic is integer arithmetic; there is no rounding or fractional state.

For `PillageAmount = 10`:

| Victim resources | StealAmount | Victim loses | Attacker gains |
| --- | --- | --- | --- |
| 100 | 10 | 10 | 10 |
| 3 | 4 | 0 | 0 |
| 3 | 3 | 3 | 10 |
| 3 | 2 | 2 | 10 |
| 3 | 0 | 0 | 10 |
| 0 | 0 | 0 | 10 |

`PillageAmount = 0, StealAmount = 10` deducts 10 with no payout when affordable.
`PillageAmount = 4, StealAmount = 10` deducts 10 and pays 4. Omitted StealAmount
with an empty victim account still pays nothing, while explicit zero can pay 10.

The counter is consumed on an unaffordable attempt. With threshold 3, cost 10 and
victim balance 5, successive counters are 1, 2, 0, 1 with no money transfer.

## Evidence and address map

All addresses below are VAs, ImageBase `0x00400000`, in the supplied original
the RotWK reference executable (11,346,944 bytes). Its SHA-256 is
`5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`.
PE section mapping is used rather than assuming VA minus ImageBase is a file offset.

The Pillage tables, factories, constructor, event handler, Xfer and money bodies
were independently inspected in this binary. The registration-internal helpers
listed separately below are supplied RE facts; this patch does not modify them
or depend on their internal algorithms.

### Fields, data and parsing

| VA | Meaning |
| --- | --- |
| `0x00C0687C` | `PillageFilter` string |
| `0x00C0688C` | `NumDamageEventsPerPillage` string |
| `0x00C068A8` | `PillageAmount` string |
| `0x00C068B8` | Pillage-specific field table; PillageAmount row |
| `0x00C068C8` | NumDamageEventsPerPillage row |
| `0x00C068D8` | PillageFilter row |
| `0x00C068E8` | Zero terminator |
| `0x0042ECB2` | Unsigned integer field parser; cdecl, four arguments |
| `0x0042EA42` | Native unsigned scan, including # constants |
| `0x0042DC9F` | Native token handling used by the unsigned parser |
| `0x0076392F` | ObjectFilter INI parser |
| `0x00653593` | PillageModuleData constructor |
| `0x006535A6` | LEA ECX,[ESI+0x10] for filter initialization |
| `0x006535AC` | Store data vtable 0x00C06800 |
| `0x006535B2` | Default PillageAmount to zero |
| `0x006535B5` | Default NumDamageEventsPerPillage to zero |
| `0x006535B8` | Call filter constructor |
| `0x0076406F` | ObjectFilter handle constructor |
| `0x006535CC` | Field registration callback |
| `0x006535D2` | PUSH shared field table 0x00C84858 |
| `0x006535D7` | Call field builder |
| `0x006535E2` | PUSH Pillage field table; operand at 0x006535E3 |
| `0x006535E7` | Call field builder |
| `0x0042B8D7` | FieldParseBuilder::add, thiscall, two stack arguments |
| `0x006535ED` | ModuleData factory |
| `0x006535F9` | PUSH 0x14 allocation size |
| `0x006535FB` | Call GameAlloc / OPERATOR_NEW |
| `0x0065360E` | Sole direct call to the data constructor |
| `0x00653624` | PUSH field-registration callback |
| `0x0065362A` | Call INI multi-procedure initializer at 0x0042DBBD |
| `0x00C06800` | Data vtable |
| `0x00654D4E` | Scalar deleting data destructor |
| `0x00654D6A` | Data destructor, releases the filter at +0x10 |
| `0x007629B0` | Filter handle destructor |

The field record is `{name, parseFn, userData, offset}`, four dwords, 16 bytes.
The third dword is the parser's fourth argument, not a field size. For the unsigned
parser, nonzero userData is an upper bound; all Pillage rows use zero. The retained
rows are exactly:

| Field | Parser | userData | Offset |
| --- | --- | --- | --- |
| PillageAmount | 0x0042ECB2 | 0 | +0x08 |
| NumDamageEventsPerPillage | 0x0042ECB2 | 0 | +0x0C |
| PillageFilter | 0x0076392F | 0 | +0x10 |

PillageFilter is a four-byte ObjectFilter handle, not an inline KindOf bitset.
The common table at 0x00C84858 remains untouched.

### Registration and runtime

| VA / value | Meaning |
| --- | --- |
| `0x006579C9` | Factory registration function containing the supplied Pillage block |
| `0x0065AAF7` | Start of Pillage registration, PUSH its name |
| `0x00C0AC64` | `PillageModule` literal |
| `0x0065AAFF` | AsciiString constructor call |
| `0x0065AB04` | PUSH registration metadata 0x2000 |
| `0x0065AB0C` | PUSH ModuleData factory; operand at 0x0065AB0D |
| `0x0065AB11` | PUSH runtime factory; operand at 0x0065AB12 |
| `0x0065AB1F` | Call registration helper |
| `0x006570FE` | Store factory pointers and registration metadata |
| `0x00655A0C` | Supplied RE: construct the prefixed NameKey representation |
| `0x00656F4A` | Supplied RE: find or insert registry entry |
| `0x0064C492` | Runtime factory |
| `0x0064C49D` | PUSH 0x1C runtime allocation size |
| `0x0064C49F` | Call GameAlloc / OPERATOR_NEW |
| `0x0064C4B9` | Call Pillage runtime constructor |
| `0x00888199` | Runtime constructor, thiscall, RET 8 |
| `0x009910C0` | First base constructor |
| `0x006530B4` | Behavior base constructor |
| `0x00708270` | ObjectModule base constructor |
| `0x008881A9` | Zero the counter at runtime +0x18 |
| `0x008881AD` | Store primary vtable 0x00C60DCC |
| `0x008881B3` | Store secondary vtable 0x00C60D10 |
| `0x008881BA` | Store Pillage interface vtable 0x00C60D04 |
| `0x00C60D04` | Event-interface slots: 0x0088826E, 0x00993440 |
| `0x00888247` | Pillage Xfer: version, base Xfer, uint counter |
| `0x00991117` | Base Xfer, including runtime +0x14 ObjectID |

### Event, money and GUI

| VA | Meaning |
| --- | --- |
| `0x0088826E` | Event entry; original signature retained, RET 8 |
| `0x0088827D` | EDI = interface this |
| `0x0088827F` | EBX = [EDI-0x0C], ModuleData |
| `0x0088828E` | ESI = [EDI-8], owner object |
| `0x00888299..0x008882A8` | Original filter argument setup, call and rejection branch |
| `0x007640C1` | Filter evaluation, two stack arguments, RET 8 |
| `0x008882AE` | Counter INC; new gate hook |
| `0x008882B1` | Load counter |
| `0x008882B4` | Compare counter with ModuleData+0x0C |
| `0x008882B7` | Below-threshold branch to exit |
| `0x008882BD` | Load victim object from [EBP+0x0C] |
| `0x008882C0` | Reset counter |
| `0x008882C4` | Resolve victim player |
| `0x008882C9` | Load owner object for player lookup |
| `0x008882CD` | Resolve attacker player |
| `0x0068B678` | Object::getControllingPlayer, thiscall, no arguments |
| `0x008882D2` | Load data; new transfer hook |
| `0x008882D5` | Load PillageAmount |
| `0x008882DA` | Load victim resources from Player+0x94 |
| `0x008882E0..0x008882E2` | Unsigned min(PillageAmount, victim balance) |
| `0x008882F5` | Native withdrawal call |
| `0x008882FA..0x008882FE` | Retain withdrawn amount in EDI; exit on zero |
| `0x00888304` | Original deposit argument setup, shared by positive extended payouts |
| `0x00888314` | Native deposit call |
| `0x007B17EF` | Money::withdraw, thiscall, RET 0x0C; EAX = actual withdrawal |
| `0x007B1801..0x007B180B` | Requested amount and unsigned clamp to available balance |
| `0x007B1871` | Native balance subtraction |
| `0x007B18A6` | Return actual amount |
| `0x007B18B8` | Money::deposit, thiscall, RET 0x0C |
| `0x007B18CA..0x007B18D1` | Load amount and return for zero |
| `0x007B192F` | Native balance addition |
| `0x0088831E` | Read GameText from global 0x00DE4B04 |
| `0x00888328` | PUSH GUI:AddCash string 0x00C13EE0 |
| `0x00888330` | GameText virtual slot +0x44 |
| `0x00888338` | UnicodeString format, amount comes from EDI |
| `0x0088838E` | Floating-text dispatch through InGameUI slot +0x1A0 |
| `0x0088839B` | UnicodeString destruction |
| `0x008883A0` | Exit with POP ESI and the original EH epilogue |
| `0x008883AE` | RET 8 |

Both money methods receive `(amount, &Player::scoreKeeper, true)` on their stack,
with ECX = Player+0x90. ScoreKeeper is +0x3DC; the balance is Money+4 = Player+0x94.
Withdrawal clamps defensively and updates native bookkeeping/statistics/audio;
deposit uses the supplied amount and also updates native bookkeeping/statistics/audio.
No global money-function hook or direct balance write is installed.

The exact original name and meaning of the callback's first argument remain
unknown. The victim argument at [EBP+0x0C], interface adjustment, filter call and
RET 8 are confirmed. The patch preserves the caller's event-selection behavior
and adds no relationship, damage-size or horde-specific conditions.

## Layout and lifecycle audit

Original ModuleData, size 0x14:

| Offset | Contents |
| --- | --- |
| +0x00 | Vtable 0x00C06800 |
| +0x04 | Base field; meaning unconfirmed, untouched |
| +0x08 | Unsigned PillageAmount, default 0 |
| +0x0C | Unsigned NumDamageEventsPerPillage, default 0 |
| +0x10 | ObjectFilter handle |

Runtime, unchanged size 0x1C:

| Offset | Contents |
| --- | --- |
| +0x00 | Primary vtable 0x00C60DCC |
| +0x04 | ModuleData pointer |
| +0x08 | Owner object pointer |
| +0x0C | Secondary vtable 0x00C60D10 |
| +0x10 | Pillage event vtable 0x00C60D04 |
| +0x14 | Base-initialized zero; base Xfer transfers it as an ObjectID |
| +0x18 | Damage-event counter |

The interface this pointer is runtime+0x10. Data is [this-0x0C], owner is [this-8],
and counter is [this+8]. The callback's native frame caches data at [EBP-0x10].

Patch-owned ModuleData tail, total size 0x13C:

| Offset | Contents |
| --- | --- |
| +0x14 | StealAmount, unsigned dword |
| +0x18..+0xA7 | TriggeredBy, 36 dwords |
| +0xA8..+0x137 | ConflictsWith, 36 dwords |
| +0x138 | RequiresAllTriggers byte |
| +0x139 | RequiresAllConflictingTriggers byte |
| +0x13A | StealAmount presence byte |
| +0x13B | Alignment padding |

All added bytes start at zero. The presence byte is set only after the native
unsigned parser returns successfully; no sentinel consumes a valid input value.

The data constructor has one direct call, from the data factory. Its factory
pointer is registered once under PillageModule, and its field-registration
callback is referenced by that factory. Code-reference scanning plus inspection
found no Pillage-specific copy constructor or size-bearing virtual clone path.
The data vtable contains the deleting destructor, no-op/common Snapshot methods
and query methods; none supplies a Pillage field copy/allocation implementation.
The virtual method at +0x38 constructs a default AsciiString output, not a clone.
The factory constructs the data and then parses it through the existing INI
initializer; the patch does not replace that exception-managed lifecycle.

The data destructor releases only the original filter handle at +0x10 and restores
the Snapshot vtable. Its deleting wrapper invokes unsized operator delete, so it
does not need the old 0x14 size. Added masks/integers have no dynamic ownership.
The unknown +0x04 field is never cleared or repurposed by the allocation stub.

Runtime Xfer still saves the original version, base state and uint counter at
+0x18. No new per-instance latch or persistent state is added, and no Xfer version
change is necessary for this design. The native counter/base-ID path is exercised
with modeled Xfer storage/load; actual game save/load remains an in-game check.

## Hook strategy and binary validation

Implementation: `../patches/pillage_module_extension.py`.
Facts/fingerprints: `../addresses/objects.py`, exported through the central
`addresses` namespace. Shared unsigned parser and all-of mask test constants are
added to `addresses/runtime.py` and `addresses/player.py` respectively. Existing
Money, allocator, player/owner lookup, masks and field-table helpers are reused.

New shared definitions are `INI_PARSE_UNSIGNED_INT` and `UPGRADE_MASK_TEST_ALL`.
The Pillage-specific `PILLAGE_*` facts and full fingerprints are grouped in
`addresses/objects.py`. Reused constants include `OPERATOR_NEW`, `MONEY_WITHDRAW`,
`MONEY_DEPOSIT`, `MONEY_AMOUNT`, `PLAYER_MONEY`, `PLAYER_SCORE_KEEPER`,
`OBJECT_GET_CONTROLLING_PLAYER`, `OBJECT_UPGRADE_MASK`,
`PLAYER_COMPLETED_UPGRADE_MASK`, `PLAYER_COMPLETED_UPGRADE_MASK_WORDS`,
`INI_PARSE_BOOL`, `INI_PARSE_UPGRADE_MASK`, `UPGRADE_MASK_ANY`,
`UPGRADE_MASK_TEST_ANY`, and the existing
`LEVEL_GRANT_SPECIAL_POWER_ACCEPTANCE_FILTER_PARSER` for the unchanged filter.

| Site | Original bytes | Replacement |
| --- | --- | --- |
| 0x006535F9 | `6A 14 E8 E0 C0 DD FF` | JMP allocate + 2 NOPs |
| 0x006535E2 | `68 B8 68 C0 00` | PUSH relocated Pillage field table |
| 0x008882AE | `FF 47 08 8B 47 08` | JMP gate + NOP |
| 0x008882D2 | `8B 4D F0 8B 49 08` | JMP transfer + NOP |

Allocation pushes 0x13C, invokes the existing allocator, preserves its result and
EDI, and zeroes only the new tail. It rejoins at 0x00653600, where the native POP
ECX still cleans the size argument. Constructor, INI initialization, allocation
failure handling and exception cleanup remain native.

The gate preserves all registers with PUSHAD/POPAD, uses native mask helpers, and
either replays the displaced INC/load or enters the original exit. No flags are
live across this window: the resumed native CMP supplies the threshold branch.

The transfer stub distinguishes omission before modifying the transfer state.
The omitted path replays the displaced data/amount loads and resumes at
0x008882D8. The extended path retains the current attacker in EBX, checks the
victim balance, and calls native withdrawal. It then loads payout into EDI and
rejoins the native deposit/popup path at 0x00888304 for positive payouts; otherwise
it exits. Native UnicodeString construction, EH state transitions and destruction
are preserved. The stub does not add an extra call frame around Money or GUI.

Neither factory registration operand is redirected. Registration metadata 0x2000,
the public Behavior name, runtime factory/size and all vtables remain unchanged.
The factory strategy is a local allocation detour, not a replacement factory.

`.pillage` is a dynamically allocated, read/execute PE section containing five
keyword strings, eight field rows plus terminator, and the helper code. The
unsigned presence parser forwards all four native parser arguments and returns
with the same cdecl convention. Its table userData is zero.

Before any mutation, complete native Pillage bodies, original table/strings,
registration, lifecycle code and reused money/mask/parser fingerprints are checked.
The shared ModuleData table is retained. A foreign table relocation or overlapping
hook is rejected instead of silently discarding another extension. Repeat
application is rejected. `verify` checks the entire generated section, all edits
and all retained anchors; `detect` recognizes only a completely verified installation.
Composition with `large-group-bonus` and `upgrade-module-removal` is tested in both
orders on the real binary.

## Applying and validation

```sh
python -m sage_patch apply pillage-module-extension --in game.dat.backup --out game.dat
python -m sage_patch verify pillage-module-extension game.dat
```

Tests in `tests/sage_patch/test_pillage_module_extension.py` cover field surface,
binary rejection/detection, allocation boundaries/defaults, retained runtime
interfaces, unsized data deletion, counter Xfer, native stock equivalence,
all-or-nothing transactions, zero values, UINT32_MAX, upgrade ANY/ALL/conflicts,
grant/remove/regrant, owner changes and the last mask word. Emulator events assert
stack cleanup, callee-saved registers, exception-chain restoration and x87 balance.
Money/statistics instructions actually execute; audio/INI/render/filter/player
lookup and Xfer storage are modeled engine services, not an in-game execution.

Validation on October 14, 2026, with Python 3.13.15:

- Focused suite (Pillage, LargeGroupBonus, manifest and public exports), including
  real-binary checks: 1,787 passed, 2 skipped.
- Documentation links, layering and packaging: 151 passed. A temporary Git index
  containing the new files was used for the tracked-file inventory check; the
  checkout's real index and object store were not changed.
- Ruff lint and formatting passed for all changed Python files. Mypy passed for
  688 source files. The package-wide formatting check also reports an existing
  unrelated formatting issue in `docs/slaved-update-idle.md`, which was left intact.
- Complete core run: 14,995 passed, 576 skipped, 751 full tests deselected;
  initially 16 failures and 8 setup errors. Fifteen failures were caused by
  inaccessible sandbox TEMP directories and passed on a targeted rerun with
  workspace TEMP/TMP. The remaining failure was the new document's untracked
  status, covered by the successful temporary-index check above. The eight APT
  HTTP fixture setup errors are sandbox loopback socket denials (WinError 10013).
- The emulator runs used `-p no:faulthandler` to avoid dumps from Unicorn's handled
  Windows guard exceptions; no emulator assertions or tests were disabled.
- CLI apply, verify, manifest generation and manifest consistency check passed
  against a separate copy. The original binary was retained.

Generated local outputs are `pillage-module-game.dat` and
`pillage-module.sagepatch`. The patched binary is 11,347,968 bytes; the
unmodified source is 11,346,944 bytes. Its only installed patch is
`pillage-module-extension`.

## Multiplayer and remaining validation

The patch changes synchronized simulation state. It uses completed upgrade masks,
unsigned integer affordability, native counter order and native money methods.
No clocks, randomness, rendering decisions or pointer ordering control a transfer.
The local popup follows a completed transaction and cannot decide affordability.
All peers must use matching patched binaries and INI definitions.

Native account addition retains the engine's original dword overflow behavior;
this patch introduces no new account cap. The victim cannot underflow because the
unsigned cost is checked before withdrawal, and withdrawal also clamps natively.
Money's pre-subtraction notification path is audio bookkeeping, not a synchronized
logic callback that spends the victim's balance between the check and subtraction.

The caller's guarantees of valid owner/victim players remain native assumptions;
the original money path also dereferences them. The patch does not broaden which
damage events are supplied by the engine. Exact first-argument meaning, some base
field semantics and relationship selection remain unverified internal details.

Required in-game follow-up: test the examples with controlled funds; grant/remove
object and player upgrades; save/load a partial counter; test owner changes and
horde/contained attackers; compare replay/CRC or multiplayer behavior across
identical peers. No live match, save file or network session was used for this work.

WorldBuilder is unchanged and may reject the new fields when it parses them.
Supporting its separate binary requires a separately addressed parser/allocation
patch; the game addresses cannot be transferred to it.
