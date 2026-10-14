# Command-button flyouts using the stance submenu

Research date: 2026-10-12. Scope: design and read-only reverse engineering; no patch implemented.

## Recommendation

A flyout containing complete CommandButtons looks feasible. Start with **one popup of at most three children**, opened from an ordinary Palantir command slot. Reuse the stance submenu's APT container, animation and frame lifecycle, but supply normal command-button presenters and normal command dispatch. Use `CommandRangeStart` and `CommandRangeCount` to select children from the currently effective CommandSet without pushing the normal visible-range stack.

This is a medium-to-large UI/engine patch, not a change to a single command enum or INI field. The visual container is already close to the desired feature; correctly binding command state, ownership, targeting and destruction is the substantial work. Supporting every command category, arbitrary lengths and the side bar should be separate milestones.

| Requested feature | Assessment |
| --- | --- |
| Existing stance opening/closing presentation | Strong reuse candidate; native code invokes APT `Show` and `FadeOut` |
| Up to three complete child buttons | Plausible via a new child factory/presenter; not supported merely by filling `Stances` |
| Another of the six Palantir slots | Strong evidence for slot-independent attachment; exact artwork/position still needs testing |
| Popup extending sideways from a Palantir slot | Plausible APT/layout change; inspect clipping, coordinates and hit testing |
| Popup attached to the separate side command bar | Additional bridge work; six-slot Palantir support does not prove side-bar support |
| More than three children | Requires container storage/lifecycle changes as well as APT layout |
| Pure INI implementation | No evidence that stock commands can express this behavior |

## Evidence and address conventions

OpenBfme2 was inspected at commit `842bf8da5e2b26546f5d2389507c30e8db26b5f3`. Its `reverse/functions.csv` marks the cited recovered functions as matched. That ledger status was inspected, not independently rebuilt in this task. Some original class names remain WorldBuilder-derived leads; address-named views should not be mistaken for a complete SDK.

**OpenBfme2 addresses below are RVAs from its ledger. RotWK addresses below are VAs**, with image base `0x00400000`. Do not paste BFME2 RVAs into RotWK or assume a constant inter-game delta.

Direct RotWK inspection used `tools/BFME-FILES/game.dat.backup`:

- SHA-256: `5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`
- PE image base: `0x00400000`.
- Existing pySAGE patch documentation targets build `2.01.2614.37001`; the hash above identifies the actual file inspected here. Verify the intended deployment file independently, including already installed patches.

Three evidence levels are distinguished below: recovered BFME2 source, newly inspected RotWK instructions, and proposed design. No in-game validation or APT asset inspection was performed in this task.

## What the stance button actually does

The recovered `InGameToggleStanceCommandButton::Impl::OnLeftClicked` at BFME2 RVA `0x00568021`:

1. Obtains a submenu through the owner's factory virtual slot `+0x10`.
2. Performs an object/player relationship guard.
3. If closed, walks the CommandButton's stance vector at `+0x234`.
4. Adds entries while the submenu count is **less than three**.
5. Passes each entry a two-word payload containing the parent implementation and a stance integer.
6. Shows the submenu, or requests closure if it is already active.

The add wrapper at `0x00567B6D` creates a reference-counted factory-like object; the container does not simply receive a CommandButton pointer. This indirection is a useful potential extension seam: the container later invokes a virtual creation method after a frame becomes available.

The child `StanceButton::DoUpdate` at `0x005679A4` selects an image through the parent's stance list and writes a fixed presentation value `6`; it also has an optional countdown path. This is **not proof of normal cooldown, cost, queue, upgrade, or readiness support**.

The selection path at `0x00567A6E` sets the parent's selected image index, creates message `0x468` with the stance integer, requests menu closure and plays stance voice feedback. Forwarding arbitrary commands through this path would still execute stance semantics. Full buttons must enter their own existing command pathways.

Hotkeys are special too: `0x00567DA6` registers actions per stance, and the constructor removes the parent button's ordinary hotkey before registering stance-specific actions. Copying this behavior unchanged would produce the wrong scope and potentially consume unrelated hotkeys.

## The three-entry limit is structural

BFME2's submenu implementation allocates `0x48` bytes and contains:

| Offset | Observed role |
| --- | --- |
| `+0x00` | owner |
| `+0x04`, `+0x08` | APT level and movie path representation |
| `+0x0C` | callback-map registration storage |
| `+0x18` | active flag |
| `+0x1C` | entry count |
| `+0x20` | three records, each 12 bytes |
| `+0x44`, `+0x45` | close/lifecycle flags |

The recovered constructor and destructor both handle **three** records. The unload callback independently validates `0 <= index < 3`. `Add` advances the count and stores into the next record without a local bounds check. Raising only the stance-loop limit would overwrite adjacent fields.

The records hold the source factory/reference, an owned frame wrapper, and the resulting live child presenter. Update waits for the frame, constructs the child through the factory's virtual method, releases the source reference and updates the live child. The frame-loaded callback parses `index` and `name`. This asynchronous lifecycle matters: a click cannot safely assume that all APT frames already exist.

Closing is deferred: a flag requests `FadeOut`, then `_OnClosed` releases the children and notifies the owner. Do not free child objects immediately after starting the animation, or leave callbacks referring to a destroyed owner.

**Direct RotWK corroboration:** constructor `0x009D353B` allocates `0x48` bytes and calls `0x009D3380`. At `0x009D33C9` the implementation constructor pushes `3`, then at `0x009D33CB` pushes `0x0C`, and constructs the array at `this+0x20`. It also initializes the flags at `+0x18`, `+0x44`, `+0x45`. Thus the three-record constraint is verified in the inspected RotWK binary, not merely imported from BFME2.

## Placement: why slot 1 is probably not special

BFME2 `OnSubMenuLoaded` at RVA `0x005297DD` parses the slot and movie path and installs a submenu into that slot's record. Records start at `+0x64`, have stride `0x14`, and hold the submenu at record offset `+4`. The recovered owner has six records.

The corresponding RotWK function is **VA `0x0093023D`**, found from the registered string `PalantirCommandUI::OnSubMenuLoaded`:

- Registration at `0x00930B6A` pushes string VA `0x00C7F31C`.
- At `0x00930B77`, callback address `0x0093023D` is loaded.
- Slot parser `0x00930088` explicitly accepts `0 <= slot < 6` (`cmp eax,6` at `0x009300D1`).
- Callback instructions at `0x00930285` calculate `(slot + 5) * 0x14`, equivalent to `0x64 + slot*0x14`, then select the submenu member at `+4`.
- It creates an eight-byte wrapper and calls constructor `0x009D353B`.

This demonstrates a per-slot native attachment mechanism. It does **not** prove that every slot's current movie exports an identical submenu, that every controller factory returns it, or that all opening directions fit on screen.

For a lateral flyout, retain the source slot's anchor and alter child placement in APT. Trace local/global coordinate conversion, container scaling, masks, depth and mouse hit regions. Treat moving the same popup sideways and attaching it to `InGameSideCommandBar` as different tasks: the latter has its own frame callbacks and ownership path.

Existing [command-set research](commandset-button-limit.md) reports `CommandButtonSubMenu` and `CommandButtonBacks` imported from `libInGameUI` into a decompiled Edain `Palantir.apt`. Those particular character numbers and assets are **mod-specific observations**, not universal RotWK constants. APT renders the visual shell, while native gadget/window objects can still carry input and command state; do not discard those native bindings as obsolete merely because the HUD is APT-driven.

## Recommended command and data model

Proposed semantics, not currently supported syntax:

```ini
CommandButton Command_OpenAbilityFlyout
    Command = OPEN_COMMAND_RANGE_FLYOUT ; proposed new token
    CommandRangeStart = 6
    CommandRangeCount = 3
    ; ordinary icon/text fields omitted
End
```

Here `6` selects INI CommandSet slots `7..9`: range starts are zero-based, while INI slot names are one-based. Resolve the **effective** CommandSet, including upgrades/overrides, rather than only the template's original set.

Use PUSH's range fields and lookup semantics, but keep popup state separate from the ordinary range stack. Executing a real PUSH before opening the popup would repopulate the underlying command bar and can destroy/rebind the opener. That would defeat the desired temporary overlay.

For the first prototype, close the existing popup before opening another; do not introduce nesting. Reject or disable recursive openers and PUSH/POP children initially. Later define whether those commands operate on the base bar or a nested flyout explicitly.

Alternatives:

| Child source | Benefit | Additional work |
| --- | --- | --- |
| Range of current CommandSet | Reuses existing fields and fits requested behavior | Bounds, effective-set resolution and multi-selection semantics |
| Named CommandSet | Reusable menus independent of host layout | New parser/reference field, resolution lifetime and owner-context rules |
| List of CommandButton names | Flexible noncontiguous selection | New list storage/parser, resolution, duplicate handling and ownership rules |

Prefer the range first. If possible, carry new popup metadata externally keyed by the existing button rather than enlarging the shared CommandButton object; this is a design option requiring investigation, not an established hook. Adding a command token requires checking its name table, dispatch switches, enum assumptions and WorldBuilder acceptance. Do not insert a token in the middle of an enum and silently shift existing values.

## Making the entries complete CommandButtons

Investigate the normal APT command-button adapter before inventing rendering and click behavior. OpenBfme2's `Rva005C33DDWindowNotification.cpp` and `Rva005C3549Dtor.cpp` expose a useful family with a WorldBuilder lead named `ParasiticInGameCommandButton`.

The recovered adapter forwards through an associated `GameWindow`, its instance owner and ID; nearby paths send messages `0x4008` and `0x4009`. Its right-click handling checks button state/flags and selects normal enabled/disabled sounds. These are better leads for ordinary command semantics than `SetStance`, but the exact factory required for popup embedding remains unresolved.

A successful child binding needs all of the following:

- Correct CommandButton and controlled object/selection context.
- Normal validity/readiness/upgrade/resource checks and disabled presentation.
- Normal tooltip generation, images, cooldown/progress and queue information where applicable.
- Left click, right click, autocast/toggle behavior and targeting mode transitions.
- Correct dispatch to the existing game-message path; opening/closing alone remains local UI state.
- Destruction on deselection, death, ownership change, CommandSet replacement, page change and UI unload.
- A clear rule for hotkey collisions and registration only while appropriate.

Do not merely borrow a hidden ordinary slot's window without tracing its lifetime: base-bar repopulation may overwrite its button/context. Also distinguish closing the popup from cancelling a targeting operation. An ability can close the popup after entering targeting mode and still need its command/context to remain valid.

## Practical search plan for RotWK game.dat

### 1. Establish identity and reproduce the known anchor

Record file hash, PE image base, version and installed patches. In Ghidra or IDA, search `PalantirCommandUI::OnSubMenuLoaded`, follow its pointer use into callback registration, and recover the installed function pointer. On the inspected file the result is `0x0093023D`.

This route is robust across layout changes because it uses a descriptive string and a delegate-construction pattern. Raw four-byte pointer matches are leads; classify each as data or a decoded instruction before accepting it as an xref.

### 2. Recover the submenu contract

Follow the load callback to wrapper/implementation construction. Label the three records and their lifecycle flags. Follow registration of `_OnButtonFrameLoaded`, `_OnButtonFrameUnloaded` and `_OnClosed`. Trace callers of the add/show methods back to the stance controller. Follow child-factory vtables forward to construction, update, help and click handling.

RotWK update function `0x009D2F92` has the same distinctive close/update pattern as BFME2 RVA `0x005C3B3E`: checks `+0x45`, `+0x18`, `+0x44`, calls the APT wrapper with `FadeOut`, and processes records from `+0x20`. This is a directly inspected structural correspondence; other functions also use `FadeOut`, so that string alone is insufficient.

### 3. Find command parsing and dispatch

Newly located RotWK anchors:

| Item | VA in inspected file | Evidence/next use |
| --- | --- | --- |
| `PUSH_VISIBLE_COMMAND_RANGE` string | `0x00C2C24C` | Pointer at `0x00DA4DEC` |
| `POP_VISIBLE_COMMAND_RANGE` string | `0x00C2C230` | Pointer at `0x00DA4DF0` |
| `TOGGLE_STANCE` string | `0x00C2C220` | Pointer at `0x00DA4DF4` |
| `Stances` field string | `0x00C2BEE0` | Field-table entry at `0x00C2BDD8` |
| Stances field parser | `0x0075D4D0` | Field-table callback, offset `+0x234` |

Determine the command-name table's actual start and parser convention before calculating enum values. Adjacent string pointers do not by themselves prove numerical command IDs. Trace the parsed value into the command UI factory and the click dispatcher; an extra token without a presenter/dispatch case is not a working command.

A raw executable-section scan also found `push 0x468` at `0x0096F576` and three sites around `0x008201FC..0x0082023D`. The former is a **candidate** for the stance-message path, not a recovered function entry. Establish instruction boundaries and surrounding image-update, argument-append and voice calls before naming it. Do not start disassembly at an arbitrary nearby byte and trust the output.

Existing project research supplies these additional **previously documented, not independently revalidated here** RotWK anchors:

| Operation | VA / offset |
| --- | --- |
| PUSH / POP handlers | `0x00941A7D` / `0x00941A9C` |
| Single-object ControlBar population | `0x00943D6F` |
| Visible-range getter | `0x0071CF0A` |
| Range stack | `ControlBar+0x2B0` |
| Range fields | `CommandButton+0x22C` / `+0x230` |
| CommandSet button lookup | `0x0080C837`, array at `+0x14` |

See [visible command ranges](push-visible-command-range.md) for the known bounds problem: 33 ordinary widgets and multiple population passes, not all locally capped. Validate popup ranges independently against actual CommandSet capacity and popup capacity. Never assume the installed command-set expansion patch or its clamp exists.

### 4. Inspect the actual mod's APT assets

Use pySAGE's existing tooling, for example:

```text
python -m sage_apt to-xml Palantir.apt --game <game-or-mod-directory>
python -m sage_apt to-xml libInGameUI.apt --game <game-or-mod-directory>
```

Locate the exact assets first and supply their real paths. Inspect `CommandButtonSubMenu`, `Show`, `FadeOut`, frame-loaded/unloaded callbacks, `index`, `name`, placement transforms and child creation. Also inspect the side-bar movie for a lateral-bar version. Check widescreen and standard variants separately. `sage_apt` reports incomplete/partly untested format coverage; verify round trips before shipping asset edits.

### 5. Validate assumptions in a running game before patch design is finalized

Break on submenu load, entry creation, stance opening and normal button activation. Log source slot, movie path, owner, effective CommandSet, button pointer and child index. Compare the original stance button in different Palantir slots, then inspect the side-bar route separately. Debugger breaks are for a controlled local test session.

Use staged acceptance gates for a later implementation:

1. Original stance popup in a non-first slot: confirms anchor/factory/layout assumptions.
2. One ordinary immediate command in a three-entry container: confirms dispatch and context.
3. Targeted special power, unavailable upgrade/resource state and cooldown: confirms a real presenter rather than icon-only reuse.
4. Production/revive and right-click behaviors: confirms command-category coverage.
5. Rapid open/close, selection changes, object death, CommandSet upgrades and targeting cancellation: confirms lifecycle.
6. Multiplayer/replay tests: popup state stays local, emitted commands remain equivalent to ordinary clicks.
7. Only then expand capacity or attach to the separate side bar.

## Reference navigation

Paths below are relative to the OpenBfme2 root (`F:/Modding/OpenBfme2` in this workspace). Search these paths and the exact function names/RVAs in `reverse/functions.csv` to recover provenance without loading the entire ledger.

- `Code/GameEngine/Source/Common/VslotSmallBodiesAJ.cpp`: `OnLeftClicked`, destructor and stance observer cleanup.
- `Code/GameEngine/Source/GameClient/GUI/InGame/Tactical/InGameToggleStanceCommandButton.cpp`: stance child update, help and message dispatch.
- Same directory, `InGameToggleStanceCommandButtonCtor.cpp` and `InGameToggleStanceCommandButtonHotKeys.cpp`: ownership/selection and specialized hotkeys.
- Same directory, `PalantirCommandInterface.cpp`: per-slot submenu registration and attachment.
- `Code/GameEngine/Source/Common/Rva00567B6DAdd.cpp`: stance-specific factory payload.
- `Code/GameEngine/Source/Common/Rva005C3A37ElemDtor.cpp`: submenu storage, construction, update and deferred close.
- `Code/GameEngine/Source/Common/Rva005C3C0BMethod.cpp` and `Rva005C3D5FRva005C3D5F.cpp`: frame callbacks and index checks.
- `Code/GameEngine/Source/Common/Rva005C3EA5Show.cpp`: `Show` with the entry count.
- `Code/GameEngine/Source/GameClient/GUI/Rva005C33DDWindowNotification.cpp` and `Code/GameEngine/Source/Common/Rva005C3549Dtor.cpp`: ordinary button adapter leads.

The highest-value next investigation is whether that ordinary button adapter can be instantiated through the existing submenu child factory with a correctly owned command window. If it can, the desired feature can reuse substantial engine behavior. If it assumes a fixed base-bar slot, use a dedicated child presenter that forwards to the established command/state routines; do not force stance widgets to impersonate complete commands.
