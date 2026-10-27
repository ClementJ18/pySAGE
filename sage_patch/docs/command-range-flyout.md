# CommandRange Palantir flyout prototype

Author: **Ostkannit**.

Target: RotWK `game.dat` **2.01.2614.37001**, image base `0x00400000`.
The registered experimental patch is `command-range-flyout`.

## Supported behavior

Any CommandButton with both explicitly parsed `CommandRangeStart` and `CommandRangeCount`
opts in when it uses `Command = TOGGLE_STANCE`. No specific name is required. Its existing stance flyout presents at most three
entries, while clicks resolve absolute, zero-based indices from the effective CommandSet.
Exactly one selected drawable is supported. The accepted child commands are:

| Category | Commands |
| --- | --- |
| Powers and weapons | `SPECIAL_POWER`, `SPECIAL_POWER_TOGGLE`, `FIRE_WEAPON` (with or without target selection) |
| Toggles and formations | `SWITCH_WEAPON`, `TOGGLE_WEAPON`, `TOGGLE_WEAPONSET`, `TOGGLE_NO_AUTO_ACQUIRE`, `HORDE_TOGGLE_FORMATION`, `HORDE_SET_FORMATION` |
| Gates and evacuation | `CLOSE_GATE`, `OPEN_GATE`, `TOGGLE_GATE`, `EVACUATE`, `EVACUATE_CONTESTED`, `CREW_EVACUATE` |
| Other immediate actions | `STOP`, `WAKE_AUTO_PICKUP`, `START_SELF_REPAIR`, `START_NEIGHBORHOOD_REPAIR`, `CANCEL_NEIGHBORHOOD` |

Production, upgrades, construction, spellbook/player powers, individual passenger exit,
stanced children, visible-range commands and other unlisted categories remain disabled.
Multiple selection, stale owners, missing buttons, invalid ranges and unavailable children
are disabled. Passive (`NONPRESSABLE`), script-only, autocast and cancelable configurations
are excluded. This is an experimental bounded implementation, not support for every category.

Buttons without both explicit fields retain stock stance behavior, including the default
range values 0/33. Other command types retain their original behavior.
The surface check also requires the Palantir factory and basic submenu wrapper types;
other UI factories take the original path. No radial, visible-range stack, six-slot Palantir
layout, `InitialVisible`, `PUSH_VISIBLE_COMMAND_RANGE`, APT file or container size is patched.

## Configuration

Both `CommandRangeStart` and `CommandRangeCount` **already exist** in the stock parser.
The field-table rows at `0x00C2BDB8` and `0x00C2BDC8` use integer parser `0x0042EC5E`
and write `CommandButton+0x22C` and `+0x230`. Two forwarding parsers mark the presence
of each field, then tail-call the original integer parser with all four cdecl arguments.
The numeric fields and their defaults stay unchanged. Both presence bits are required;
INI order does not matter, including whether Command is specified before or after them.
Explicit fields inherited through a CommandButton override remain present in the copy.

Presence bits use alignment byte `CommandButton+0x139`, between the `NeedDamagedTarget`
boolean at +0x138 and `AutoAbilityDisallowedOnModelCondition` at +0x13C. The constructor
store at `0x0075D6B2` and the assignment load/store at `0x007200D5` are widened to dwords
without changing instruction lengths, preserving the existing boolean and initializing/copying
its padding. Object size stays unchanged. This does not use the padding occupied by
QueueIgnoreCP (+0x10D), CommandPointCost (+0x10E), or MultiSelectGroup (+0x12E).

Parser installation validates the live CommandButton table through its existing reference
resolver and updates every exact copy of the two stock rows, including retained tables
from other field patches. Subsequent table relocations copy the forwarding parsers normally.
Verification checks the active table as well as cave code and hook instructions.

Copy an existing, working TOGGLE_STANCE definition under any desired name. Preserve
its stance/image/text lists and add:

```ini
; Inside your TOGGLE_STANCE CommandButton:
Command = TOGGLE_STANCE
CommandRangeStart = 11
CommandRangeCount = 3
```

Put that opener in an existing visible slot of a test unit's CommandSet. Put supported child
CommandButtons in **INI slots 12, 13 and 14**: these are zero-based indices **11, 12 and 13**.
Use three distinct stance values in the opener's `Stances` list. The first listed stance
maps to 11, the second to 12, and the third to 13, regardless of its numeric stance value.
For example, the order Aggressive / HoldGround / Battle (values 2 / 3 / 1) still maps to
11 / 12 / 13. Duplicate stance values are ambiguous because the stock index lookup returns
the first match; do not use duplicates in the test definition.

`Count` must be 1..3; `Start` must be nonnegative and the entire range must fit the installed
CommandSet capacity. Extra displayed stance entries beyond Count remain disabled. Lists,
images, descriptions and flash presentation still describe stances, not the resolved children.
No complete INI definition is fabricated here: copy the mod's actual artwork/text setup.
The stock stance hotkey registration is outside this patch; keyboard stance actions are not
CommandRange actions. Test this prototype by clicking the Palantir flyout.

Apply to a copy, keeping the stock image:

```text
python -m sage_patch apply command-range-flyout --in original.dat --out command-range.dat
python -m sage_patch verify command-range-flyout command-range.dat
```

## Hook and calling contracts

Five five-byte CALL instructions change, plus the parser pointers and padding initialization/
copy instructions described above. All dependencies are checked before section
allocation or mutation. `.cmdfly` is allocated by the existing PE allocator as executable,
read-only code; `verify` reconstructs the cave, all five calls, parser pointers and dependency anchors.

| Site | Stock target | Replacement contract |
| --- | --- | --- |
| `0x0096F863` | `STANCE_FLYOUT_SELECT` (`0x0096F53C`) | ECX owner, one stance stack argument; callee removes four bytes |
| `0x0096F886` | `STANCE_FLYOUT_SELECT` (`0x0096F53C`) | Direct stance-hotkey callback: owner and one stance argument |
| `0x0096F4AD` | `FLYOUT_SET_STATE` (`0x009D71E8`) | ECX embedded GUI interface, one GUI-state stack argument |
| `0x0096F5F3` | `COMMAND_BUTTON_SET_STANCE_INDEX` (`0x0075D082`) | Stance notification: ESI owner, ECX parent, one index argument |
| `0x0096FF57` | `COMMAND_BUTTON_SET_STANCE_INDEX` (`0x0075D082`) | Initial owner binding: same contract |

For a range owner, the two index-setter wrappers consume the index argument without changing
CommandButton +0xFC. The original callback still refreshes the GUI from the retained index;
external stock/direct stance changes cannot select another range entry. The initial binding
also preserves that index instead of copying the unit's current stance. The index belongs
to the CommandButton definition, as in the engine; it is not per-unit persistent storage.
After a successful child dispatch, the click wrapper finds the clicked list index, calls the
native index setter, reads its GUI value and refreshes the parent via `STANCE_GUI_VALUES_SET`.
Failed or disabled clicks never change the selected appearance. No stance order or feedback
message is emitted by that presentation update. Ordinary stance owners still invoke the
original setter at both sites.

The direct hotkey callback at `0x0096F880` calls the selector independently of GUI clicks
and observer notifications. Its call at `0x0096F886` therefore needs its own wrapper.
For range owners it emits the original `0x468` stance message with the requested stance,
but performs no index update, GUI refresh, close request, or stance-feedback event.
Thus SET_STANCE hotkeys still set the unit's real stance while leaving the range window
alone. The stock callback's registration, return value and RET 4 remain intact. This does
not turn stance hotkeys into range-command hotkeys. Ordinary owners tail-call the complete
stock selector. The prior revision only covered observer/initial-binding updates; the user
confirmed ordinary toggle behavior but reported this separate hotkey path still changed
range presentation.

The wrappers preserve integer registers with PUSHAD/POPAD. The vanilla branches restore
registers and tail-jump to the original functions with their original arguments. The range
click returns with `RET 4`, resuming **exactly at `0x0096F868`**. It never calls the stance
selector, which sends both stance message `0x468` and feedback event `0x7E3`.
The following GUI `Go` processing remains stock; its effect is not equated with closing.

`STANCE_FIND_INDEX` takes the CommandButton in **EDI**, a stance value on the stack, and
uses a plain RET: the **caller** removes four bytes. `COMMAND_SET_GET_COMMAND_BUTTON`
is thiscall, returns EAX and uses RET 4; its override lookup is preserved.

The shared resolver performs these checks on every update and again on click:

1. TOGGLE_STANCE command and both explicit-field bits, Palantir factory VTable `0x00C8D814`, and basic submenu wrapper
   VTable `0x00C8C46C`. The factory's `+0x10` points to the submenu reference. The
   Palantir frame-loaded path at `0x009301A3` supplies the slot's `+4` submenu reference;
   constructor `0x009E1A59` stores it. The same factory can serve the strategic HUD,
   whose derived submenu wrapper has a different VTable; it is excluded.
2. Valid range and stance list index. The capacity is read at runtime from the signed-byte
   operand of `CommandSet::setButton` at `0x0080C8FE`, as the existing upgrade patch does.
   Current CommandSetLimitPatch supports 34..127 (stock 33), **not 128**. No guessed 128
   storage layout is accepted. Patch application order does not freeze the capacity.
3. Non-null ControlBar, selected drawable and object; reject context 7 (multi-select).
   The native selection-list virtual method at `TheInGameUI` slot `+0x124` must contain
   exactly that drawable. Resolve the opener's object ID through GameLogic and require
   it to match the selected context. Observers/inactive local players are refused.
4. `OBJECT_GET_COMMAND_SET_STRING(context)` resolves `+0x438`, `+0x440`, `+0x43C`, then
   template `+0x70`. `COMMAND_SET_STORE_FIND_COMMAND_SET` is called on the ControlBar.
   If `OBJECT_GET_ALTERNATE_COMMAND_SET_OBJECT` returns an object, its `+0x70` name
   replaces the first lookup. No copied override logic and no cached CommandSet.
5. Walk the bounded effective set through `COMMAND_SET_GET_COMMAND_BUTTON` to ensure the
   opener is still present. Resolve Start + stance-list-index through that same function.
   This preserves its optional `0x0062FF03` override lookup and applies no visible offset.
6. Require one of the inspected command IDs. Reject option mask `0xB0080000`
   (SCRIPT_ONLY, NONPRESSABLE, AUTO_ABILITY_TRIGGERED, CANCELABLE), nonzero AutoAbility
   byte at `+0x10C`, or zero enabled byte at `+0x105`. For SPECIAL_POWER and
   SPECIAL_POWER_TOGGLE, require a non-null template at +0x44. Only FIRE_WEAPON and
   these two power types accept targeting/context mask `0x227`. Call native availability;
   no science, upgrade, recharge, player or target checks are bypassed.

The observed availability signature is:

```cpp
int __thiscall getCommandAvailability(
    ControlBar* self, CommandButton* button, GameWindow* window,
    Object* context, float* output, bool extra);
```

It returns with `RET 0x14`. The prototype supplies `window = nullptr`, the verified selected
object, stack-local output storage, and `extra = false`. This matches the dispatcher's own
calls at `0x009405B3` / `0x00940625`; a flyout child is never cast to a GameWindow.
Only availability values **1 and 2** are accepted, as in the dispatcher. They map to GUI
state 6 (`_up`); every other result maps to 1 (`_disabled`). Availability enums are not
used as GUI state indices.

On success, the click calls the existing `CONTROL_BAR_EXECUTE_COMMAND_BUTTON` as
`doCommand(button, true, false)` (RET 12). The original command switch chooses the message
and payload for immediate actions. With targeting flags, the dispatcher enters native
InGameUI target mode through virtual +0xBC with the actual persistent child CommandButton;
it does not send the final action until the user supplies a target. The engine's existing
active-command comparison/cancellation branch is retained. No GameWindow is borrowed or
fabricated, and CommandButton +0xC4 is untouched. EXIT_CONTAINER is specifically excluded
because its native case needs that window binding. The original APT Go continuation only
calls the movie function; it does not replace the InGameUI targeting pointer.

For a targeting command, dispatcher success means acceptance into targeting mode, not a
completed cast; the parent image then reflects the chosen entry even if the user later
cancels targeting. A successful dispatch uses
the original manager virtual `+0x10`, tests `FLYOUT_IS_ACTIVE`, and calls
`FLYOUT_REQUEST_CLOSE`; this sets container `+0x45` and does not destroy it.

The eight GUI states in `FLYOUT_STATE_STRING_TABLE` are 0 `_unused`, 1 `_disabled`,
2 `_extraDisabled`, 3 `_cantAfford`, 4 `_static`, 5 `_notReady`, 6 `_up`, and
7 `_visuallyEnabled`. The supplied in-game report demonstrated that state 1 grays the
stance child and blocks its click; this session did not independently repeat that test.

## Structure and address corrections

Wrapper `+4` points to a `0x48`-byte container. Container `+0x18` is the active byte,
`+0x1C` the count, `+0x20` three `0x0C` records (provider/frame/result references at
`+0/+4/+8`), and `+0x45` the deferred close-request byte. No layout changes are made.
StanceResult is `0x1C` bytes: primary VTable `+0`, refcount `+4`, GUI interface `+8`,
owner `+0x10`, stance value `+0x14`, named stance button `+0x18`. The latter remains
untouched. The opener's stance vector uses `+0x234/+0x238`.

Direct inspection found two errors in the supplied address list:

- `0x0091CF3E` is inside the LEA starting at `0x0091CF3C`, within ControlBar construction.
  It cannot be a bind function. The actual population caller at `0x00943E9E` calls
  **`0x0071CF3E`**, now `CONTROL_BAR_BIND_COMMAND_BUTTON_TO_SLOT`.
- `0x0093D22E` is inside the CALL at `0x0093D22B`. It cannot be an entry point.
  `0x00943E91` instead calls **`0x0075D22E`**, now `COMMAND_BUTTON_UPDATE_FOR_CONTEXT`.

Both rejected VAs remain explicitly named as rejected candidates in the central catalog,
so future work can find the correction. `0x0091C9A9` installs the ControlBar VTable and
performs construction; it is not a slot binder. `0x0071EFA2` was confirmed by both rel32
lookups in the effective-set path. Existing names for the dispatcher, lookup, game-message
integer append and global store are reused, rather than adding duplicate constants.

## Evidence and validation

Binary inspected: the RotWK reference executable, 11,346,944 bytes, SHA-256
`5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`.
The original two CALLs, surrounding instructions, stack cleanup, native availability
calls, name-table STOP/TOGGLE_STANCE entries, parser rows, effective-set resolution,
factory types and deferred close path were inspected directly.

The data-free tests execute the emitted x86 in Unicorn with mocked engine boundaries.
They check stack balance, nonvolatile registers, ordinary-stance fallback, non-Palantir
fallback, list order, current/alternate sets, bounds, missing children, stale ownership,
selection changes, observer rejection, disabled state, click-time revalidation, command-category
gates and success-only closure. These are ABI/control-flow tests, **not execution of
all game routines**. Separate full tests apply and verify against the stock PE and compose
with CommandSetLimitPatch at 33/64/127 in both orders. Corrupted dependencies fail before
mutation; cave tampering fails verification.

The user confirmed the initial STOP prototype works in game, but reported that external
stance changes also changed its parent image. The notification and initial-binding wrappers
address that report. This revision has not yet been validated in game; multiplayer/replay and
full targeting behavior remain unverified. `runtime_verified` intentionally remains empty.
Generated binaries are output copies; no installed game was modified.

### Initial prototype checks (2026-10-13)

- Ruff lint: passed; Ruff format: 1,452 files already formatted.
- Mypy: passed for 684 source files.
- Focused suite including stock-PE composition: **78 passed**.
- Core suite: **14,599 passed**, 576 skipped, 704 deselected on the full run; eight
  localhost APT setup errors and one Git-tracking documentation check initially remained.
  All **nine** passed on targeted reruns: APT tests needed localhost access outside the
  sandbox, and the documentation check needed the new files represented in an isolated
  review Git index. The real staging index was not changed. The first core attempt also
  exposed an unwritable sandbox temporary directory; rerunning with workspace TEMP/TMP
  resolved that setup problem. Existing pytest fixture deprecation warnings remain.
- CLI apply and CLI verify: passed for `command-range.dat`; original image
  retained. Version resource and SHA-256 were checked directly.
- `git diff --check`: passed. No game was launched.

Changed source/documentation files: `sage_patch/addresses/ui.py`,
`sage_patch/patches/experimental/command_range_flyout.py`, `sage_patch/registry.py`,
`sage_patch/README.md` (generated table), `sage_patch/docs/command-range-flyout.md`,
and `tests/sage_patch/test_command_range_flyout.py`.

### External stance isolation and general opt-in revision (2026-10-13)

- 139 focused tests passed, including emulated observer/initial binding, successful and
  failed click presentation, explicit default values, missing one/both fields, either parser
  order, padding initialization and override copy, and original-image patch composition.
- All 24 application orders with QueueIgnoreCP, CommandPointCost and MultiSelectGroup
  passed application and verification for every patch.
- A selected combination of 55 game patches applied and verified together; installation
  was unchanged.
- Repository-wide Ruff lint/format and mypy passed (684 source files).
- Core run: 14,633 passed, 576 skipped, 729 deselected. Eight localhost server tests
  passed outside the sandbox on rerun. The README table and Git-tracking documentation
  checks passed after README regeneration and use of an isolated review index. The actual
  Git staging index was not changed. All ten initial failures/errors are resolved by these
  targeted reruns; the additional focused tests also passed separately.

### SET_STANCE and additional commands revision (2026-10-13)

- 235 focused tests passed, including direct stance-hotkey routing, every accepted command,
  blocked categories/options, missing power templates, and native binary execution tests.
- Native dispatcher excerpts were executed in Unicorn for object/position/context targeting,
  existing-target-mode cancellation, and exact immediate message payloads for STOP,
  FIRE_WEAPON, both special-power types, weapon-set toggle and repair commands. External
  engine services are mocked; this does not constitute an in-game targeting test.
- The combined test build added this patch to a selection of 54 other patches.
- All 55 patches in that combined build applied and verified. Standalone CLI verification
  of the combined image also passed. Both test binaries were rebuilt; no installed game or
  mod configuration was changed.
- Ruff lint/format and mypy passed (684 source files). Core run: 14,718 passed,
  576 skipped, 748 deselected. Four Git integration tests were affected by inheriting the
  isolated documentation-review index; all four passed when rerun with their own normal
  Git environment. No test failure remains unresolved. This revision still requires in-game
  verification of hotkeys and the targeting/cancellation lifecycle.

## Manual acceptance plan and remaining gates

Run in a disposable local test mod, then record results before widening support:

| Case | Expected result |
| --- | --- |
| Ordinary TOGGLE_STANCE without both explicit Range fields | Original stance action, sound, tooltip and close behavior |
| Arbitrarily named opener, both explicit fields, list order 2/3/1, Range 11/3 | Entries resolve 11/12/13; STOP goes through ControlBar; no stance action or `0x7E3` |
| External stock/direct stance change, then reopen/reselect | Range parent retains its clicked image; stock stance button follows the unit |
| SET_STANCE hotkey while range window is open | Real stance changes; range image and open/close state do not change |
| Targeted SPECIAL_POWER/FIRE_WEAPON | Native cursor/target selection, valid-target execution, invalid-target refusal and cancellation |
| Missing target or unavailable child | `_disabled`; forced/stale click produces no command |
| Range negative, empty, >3, or beyond capacity | Disabled, no out-of-bounds lookup |
| Effective CommandSet override/disguise | Current set used; missing opener disables the old flyout |
| Death, deselection, selecting another object while open | No stale-owner dispatch; confirm stock presenter lifetime cleanup |
| Multiple selection | All test range entries disabled; ordinary stances unchanged |
| Targeted special power, build/revive, PUSH/POP child | Disabled in this prototype; no targeting mode or command emitted |
| Open/close repeatedly and click disabled entries | Original animation/callback cleanup; success requests deferred close |
| All six normal Palantir slots, paging and InitialVisible | Unchanged |
| Radial and strategic HUD, including explicit Range fields | Original behavior; type guard takes vanilla path |
| CommandSetLimitPatch at stock/64/127 | Range behavior identical; test last three valid indices |
| Stance keyboard shortcuts | Stock stance behavior; explicitly not range shortcuts |

Further categories still require their own contracts: production/cancellation, construction,
player/spellbook powers, individual passenger +0xC4 window binding, and merged selections.
The supported weapon/power target modes now use the native dispatcher, but their full
in-game targeting lifecycle still needs acceptance testing. Child artwork remains defined
by the opener's stance lists. Keep the category, option and single-selection gates.
There is no missing game.dat or INI parser blocker for the bounded prototype.

## Central address index

The definitions live in `sage_patch.addresses` (new UI symbols in `addresses/ui.py`).
This table is navigation/evidence documentation, not a second runtime address database.
All values are **VAs for RotWK 2.01.2614.37001**. Function labels not confirmed in the
paragraphs above preserve supplied RE hypotheses; names alone do not certify ABI or
semantic meaning. In particular, text-request/tooltip semantics, reference helpers and
auxiliary GUI setters still need caller-level validation before reuse.

| VA | Central symbol | Classification |
| --- | --- | --- |
| `0x0093023D` | `PALANTIR_ON_SUBMENU_LOADED` | function; supplied semantics provisional |
| `0x00930B7D` | `PALANTIR_SUBMENU_CALLBACK_REGISTRATION` | instruction/operand site, not entry point |
| `0x009D353B` | `FLYOUT_WRAPPER_CTOR` | function; supplied semantics provisional |
| `0x009D3380` | `FLYOUT_CONTAINER_CTOR` | function; supplied semantics provisional |
| `0x009D305F` | `FLYOUT_ON_FRAME_LOADED` | function; supplied semantics provisional |
| `0x009D31B3` | `FLYOUT_ON_FRAME_UNLOADED` | function; supplied semantics provisional |
| `0x009D3235` | `FLYOUT_ON_CLOSED` | function; supplied semantics provisional |
| `0x009D2EDA` | `FLYOUT_ADD_PROVIDER` | function; supplied semantics provisional |
| `0x009D3285` | `FLYOUT_WRAPPER_ADD_PROVIDER` | function; supplied semantics provisional |
| `0x009D2E16` | `FLYOUT_GET_COUNT` | function; supplied semantics provisional |
| `0x009D3334` | `FLYOUT_SHOW` | function; supplied semantics provisional |
| `0x009D2F92` | `FLYOUT_UPDATE` | function; supplied semantics provisional |
| `0x009D32D5` | `FLYOUT_WRAPPER_UPDATE` | function; supplied semantics provisional |
| `0x009D2E25` | `FLYOUT_PROCESS_PROVIDER` | function; supplied semantics provisional |
| `0x009D2E3F` | `FLYOUT_ENTRY_DTOR` | function; supplied semantics provisional |
| `0x009D2E8B` | `FLYOUT_CONTAINER_DTOR` | function; supplied semantics provisional |
| `0x009D2F21` | `FLYOUT_CLEANUP` | function; supplied semantics provisional |
| `0x009D2E0F` | `FLYOUT_IS_ACTIVE` | function; supplied semantics provisional |
| `0x009D2E1D` | `FLYOUT_REQUEST_CLOSE` | function; supplied semantics provisional |
| `0x008FAE7D` | `FLYOUT_REF_PTR_ASSIGN` | function; supplied semantics provisional |
| `0x00A110BB` | `FLYOUT_REF_PTR_RESET` | function; supplied semantics provisional |
| `0x00A0CB16` | `FLYOUT_FRAME_REF_RESET` | function; supplied semantics provisional |
| `0x0096FAC6` | `STANCE_FLYOUT_OPEN` | function; supplied semantics provisional |
| `0x0096F62F` | `STANCE_FLYOUT_ADD_PROVIDER` | function; supplied semantics provisional |
| `0x0096F2BC` | `STANCE_PROVIDER_CTOR` | function; supplied semantics provisional |
| `0x00C841B8` | `STANCE_PROVIDER_VTABLE` | VTable |
| `0x0096F9B7` | `STANCE_PROVIDER_CLONE` | function; supplied semantics provisional |
| `0x0096F9FB` | `STANCE_PROVIDER_CREATE_RESULT` | function; supplied semantics provisional |
| `0x0096F7B7` | `STANCE_RESULT_CTOR` | function; supplied semantics provisional |
| `0x00C84200` | `STANCE_RESULT_VTABLE` | VTable |
| `0x0096F83E` | `STANCE_RESULT_DTOR` | function; supplied semantics provisional |
| `0x0096F477` | `STANCE_FLYOUT_UPDATE` | function; supplied semantics provisional |
| `0x00C841E4` | `STANCE_RESULT_GUI_VTABLE` | VTable |
| `0x0096F46F` | `STANCE_RESULT_GUI_DTOR` | function; supplied semantics provisional |
| `0x0096F4FA` | `STANCE_RESULT_GUI_EVENT` | function; supplied semantics provisional |
| `0x0096F85A` | `STANCE_FLYOUT_CLICK` | function; supplied semantics provisional |
| `0x0096F863` | `STANCE_FLYOUT_CLICK_CALL` | instruction/operand site, not entry point |
| `0x0096F53C` | `STANCE_FLYOUT_SELECT` | function; supplied semantics provisional |
| `0x0096F2DA` | `STANCE_FIND_INDEX` | function; supplied semantics provisional |
| `0x0075D324` | `COMMAND_BUTTON_GET_STANCE` | function; supplied semantics provisional |
| `0x0075D082` | `COMMAND_BUTTON_SET_STANCE_INDEX` | function; supplied semantics provisional |
| `0x0075CDFC` | `COMMAND_BUTTON_STANCE_GUI_DATA` | function; supplied semantics provisional |
| `0x0075CE21` | `COMMAND_BUTTON_STANCE_INDEX_GUI_DATA` | function; supplied semantics provisional |
| `0x0096F6E7` | `STANCE_FIND_NAMED_COMMAND_BUTTON` | function; supplied semantics provisional |
| `0x009D75BC` | `FLYOUT_GUI_BINDING_INIT` | function; supplied semantics provisional |
| `0x009D72DB` | `FLYOUT_GUI_BINDING_CREATE` | function; supplied semantics provisional |
| `0x006C106C` | `STANCE_GUI_VALUES_SET` | function; supplied semantics provisional |
| `0x00715C81` | `GUI_SET_INDEXED_FIELD` | function; supplied semantics provisional |
| `0x007111E5` | `GAME_MESSAGE_APPEND_INTEGER` | function; supplied semantics provisional |
| `0x008DD5FF` | `STANCE_FEEDBACK_REQUEST_INIT` | function; supplied semantics provisional |
| `0x008DEDBB` | `STANCE_FEEDBACK_PROCESS_EVENT` | function; supplied semantics provisional |
| `0x0096F588` | `STANCE_CLOSE_MANAGER_LOAD` | instruction/operand site, not entry point |
| `0x0096F58D` | `STANCE_CLOSE_WRAPPER_CALL` | instruction/operand site, not entry point |
| `0x0096F598` | `STANCE_CLOSE_ACTIVE_CALL` | instruction/operand site, not entry point |
| `0x0096F5A3` | `STANCE_CLOSE_REQUEST_CALL` | instruction/operand site, not entry point |
| `0x0096F870` | `STANCE_CLICK_GUI_CALL` | instruction/operand site, not entry point |
| `0x0096F87A` | `STANCE_CLICK_GO_JUMP` | instruction/operand site, not entry point |
| `0x009D2DA3` | `FLYOUT_SEND_GO` | function; supplied semantics provisional |
| `0x00C86830` | `FLYOUT_GO_STRING` | string/data |
| `0x0092B9C8` | `FLYOUT_GUI_EVENT` | function; supplied semantics provisional |
| `0x0096F4A9` | `STANCE_FLYOUT_UP_PUSH` | instruction/operand site, not entry point |
| `0x0096F4AD` | `STANCE_FLYOUT_STATE_CALL` | instruction/operand site, not entry point |
| `0x009D71E8` | `FLYOUT_SET_STATE` | function; supplied semantics provisional |
| `0x009D7109` | `FLYOUT_SEND_SET_STATE` | function; supplied semantics provisional |
| `0x00C8CAF8` | `FLYOUT_STATE_STRING_TABLE` | string/data |
| `0x00C19568` | `FLYOUT_UP_STRING` | string/data |
| `0x009D71F0` | `FLYOUT_SET_STANCE_GUI_DATA` | function; supplied semantics provisional |
| `0x009D71D8` | `FLYOUT_SET_FLASH_EFFECT` | function; supplied semantics provisional |
| `0x009D6FF8` | `FLYOUT_SEND_FLASH_EFFECT` | function; supplied semantics provisional |
| `0x00914C7C` | `GUI_METHOD_BINDING` | function; supplied semantics provisional |
| `0x007154B3` | `WINDOW_ENABLE` | function; supplied semantics provisional |
| `0x0071552B` | `WINDOW_HIDE` | function; supplied semantics provisional |
| `0x00729FFD` | `GAME_WINDOW_COMMAND_PRESENTATION` | function; supplied semantics provisional |
| `0x00729F0C` | `GAME_WINDOW_COMMAND_PROGRESS` | function; supplied semantics provisional |
| `0x007296A7` | `GAME_WINDOW_COMMAND_EXTRA_STATE` | function; supplied semantics provisional |
| `0x00C841CC` | `STANCE_TEXT_REQUEST_VTABLE` | VTable |
| `0x0069BCFA` | `STANCE_TEXT_REQUEST_DTOR` | function; supplied semantics provisional |
| `0x0096FA61` | `STANCE_TEXT_REQUEST_COPY` | function; supplied semantics provisional |
| `0x0096F33E` | `STANCE_TEXT_REQUEST_BUILD` | function; supplied semantics provisional |
| `0x008EB9D8` | `STANCE_TEXT_REQUEST_COMPARE` | function; supplied semantics provisional |
| `0x0096F289` | `STANCE_TEXT_REQUEST_TYPE` | function; supplied semantics provisional |
| `0x0075CE90` | `COMMAND_BUTTON_STANCE_TEXT_FIRST` | function; supplied semantics provisional |
| `0x0075CEFC` | `COMMAND_BUTTON_STANCE_TEXT_SECOND` | function; supplied semantics provisional |
| `0x00975070` | `STANCE_TEXT_RESULT_CREATE` | function; supplied semantics provisional |
| `0x00807848` | `STANCE_TEXT_REQUEST_MANAGE` | function; supplied semantics provisional |
| `0x00940435` | `CONTROL_BAR_DO_COMMAND` | function; supplied semantics provisional |
| `0x00941B9F` | `CONTROL_BAR_PROCESS_COMMAND_UI` | function; supplied semantics provisional |
| `0x00941BFC` | `CONTROL_BAR_GUI_DISPATCH_CALL` | instruction/operand site, not entry point |
| `0x00930DE5` | `CONTROL_BAR_SUBMENU_CLICK` | function; supplied semantics provisional |
| `0x00930E21` | `CONTROL_BAR_SUBMENU_DISPATCH_CALL` | instruction/operand site, not entry point |
| `0x0072979C` | `GAME_WINDOW_GET_COMMAND_BUTTON` | function; supplied semantics provisional |
| `0x009A5E08` | `GAME_WINDOW_GET_DATA` | function; supplied semantics provisional |
| `0x0091CF3E` | `CONTROL_BAR_BIND_REJECTED_CANDIDATE` | rejected entry: inside instruction |
| `0x0091C9A9` | `CONTROL_BAR_CONSTRUCTOR` | function; supplied semantics provisional |
| `0x0093D22E` | `COMMAND_BUTTON_UPDATE_REJECTED_CANDIDATE` | rejected entry: inside instruction |
| `0x00942733` | `CONTROL_BAR_GET_COMMAND_AVAILABILITY` | function; supplied semantics provisional |
| `0x0094397F` | `CONTROL_BAR_UPDATE_SLOT_AVAILABILITY` | function; supplied semantics provisional |
| `0x00943ADB` | `CONTROL_BAR_UPDATE_AVAILABILITY_CALL` | instruction/operand site, not entry point |
| `0x00944911` | `CONTROL_BAR_OTHER_AVAILABILITY_CALL` | instruction/operand site, not entry point |
| `0x00943EAA` | `CONTROL_BAR_UPDATE_SLOT_BOUND` | instruction/operand site, not entry point |
| `0x00DE7744` | `THE_COMMAND_SET_STORE` | global pointer |
| `0x00943D6F` | `CONTROL_BAR_UPDATE_COMMAND_BUTTONS` | function; supplied semantics provisional |
| `0x0094475A` | `CONTROL_BAR_UPDATE_SELECTION` | function; supplied semantics provisional |
| `0x0094482B` | `CONTROL_BAR_SELECTED_REFERENCE_STORE` | instruction/operand site, not entry point |
| `0x00944834` | `CONTROL_BAR_UPDATE_COMMAND_BUTTONS_CALL` | instruction/operand site, not entry point |
| `0x0069156B` | `OBJECT_GET_COMMAND_SET_STRING` | function; supplied semantics provisional |
| `0x0069194E` | `OBJECT_GET_ALTERNATE_COMMAND_SET_OBJECT` | function; supplied semantics provisional |
| `0x00943D97` | `CONTROL_BAR_EFFECTIVE_SET_NAME_CALL` | instruction/operand site, not entry point |
| `0x00943DA3` | `CONTROL_BAR_FIND_COMMAND_SET_CALL` | instruction/operand site, not entry point |
| `0x00943DAE` | `CONTROL_BAR_ALTERNATE_OBJECT_CALL` | instruction/operand site, not entry point |
| `0x00943DC1` | `CONTROL_BAR_ALTERNATE_SET_LOOKUP_CALL` | instruction/operand site, not entry point |
| `0x0080C837` | `COMMAND_SET_GET_COMMAND_BUTTON` | function; supplied semantics provisional |
| `0x0062FF03` | `COMMAND_SET_BUTTON_OVERRIDE_LOOKUP` | function; supplied semantics provisional |
| `0x007808AB` | `CONTROL_BAR_ENTRIES_GET_BY_INDEX` | function; supplied semantics provisional |
| `0x0071EFA2` | `COMMAND_SET_STORE_FIND_COMMAND_SET` | function; supplied semantics provisional |
| `0x00C84208` | `STANCE_HOLD_GROUND_NAME` | string/data |
| `0x00C84224` | `STANCE_AGGRESSIVE_NAME` | string/data |
| `0x00C84240` | `STANCE_BATTLE_NAME` | string/data |
| `0x0071D6EA` | `CONTROL_BAR_FIND_COMMAND_BUTTON` | function; supplied semantics provisional |
| `0x0071D6B5` | `CONTROL_BAR_SEARCH_COMMAND_BUTTON` | function; supplied semantics provisional |
| `0x00465AF4` | `GET_FINAL_OVERRIDE` | function; supplied semantics provisional |
| `0x0071CF3E` | `CONTROL_BAR_BIND_COMMAND_BUTTON_TO_SLOT` | function; supplied semantics provisional |
| `0x0075D22E` | `COMMAND_BUTTON_UPDATE_FOR_CONTEXT` | function; supplied semantics provisional |
| `0x0080C8FE` | `COMMAND_SET_CAPACITY_IMMEDIATE` | instruction/operand site, not entry point |
| `0x0096F5DB` | `STANCE_SELECT_RETURN` | RET 4 instruction |
| `0x0096F868` | `STANCE_FLYOUT_CLICK_RESUME` | click continuation |
| `0x009D29CE` | `COMMAND_UI_GET_OBJECT_ID` | object-ID getter; thiscall |
| `0x00C8D814` | `PALANTIR_STANCE_FACTORY_VTABLE` | factory VTable; also used by strategic HUD |
| `0x00C8C46C` | `PALANTIR_FLYOUT_WRAPPER_VTABLE` | basic Palantir submenu VTable |
| `0x009E1A59` | `PALANTIR_STANCE_FACTORY_CTOR` | constructor; RET 16 |
| `0x009301A3` | `PALANTIR_STANCE_FACTORY_CREATE` | Palantir factory argument setup |
| `0x0096F5F3` | `STANCE_OWNER_NOTIFY_INDEX_CALL` | external stance notification's presentation setter |
| `0x0096FF57` | `STANCE_OWNER_INITIAL_INDEX_CALL` | initial owner binding's presentation setter |
| `0x0075D6B2` | `COMMAND_BUTTON_RANGE_FLAGS_INIT` | constructor boolean store widened into padding |
| `0x007200D5` | `COMMAND_BUTTON_RANGE_FLAGS_COPY` | override assignment's boolean load/store |
| `0x0042EC5E` | `COMMAND_BUTTON_INI_INTEGER_PARSER` | native integer parser, four cdecl arguments |
| `0x0096F886` | `STANCE_HOTKEY_SELECT_CALL` | direct hotkey selector call, independent of flyout clicks |
| `0x0094086A` | `CONTROL_BAR_COMMAND_TARGET_ROUTE` | native target-mode selection/cancellation |
| `0x00941AC3` | `CONTROL_BAR_COMMAND_DISPATCH_TABLE` | command-case jump targets |
| `0x00941B63` | `CONTROL_BAR_COMMAND_DISPATCH_INDICES` | command-ID to case mapping |
| `0x00941ABB` | `CONTROL_BAR_COMMAND_ACCEPTED` | dispatcher success tail |
