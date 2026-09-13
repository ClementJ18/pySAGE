# Hiding the War of the Ring selection-details tray

Engine build `2.01.2614.37001`, ImageBase `0x400000`. **Read from the disassembly and the shipped
`.apt` files, 2026-09-13.** The patch,
[`hide-selection-details`](../../patches/experimental/hide_selection_details.py), is static only.

## What the tray is

The panel behind `STRATEGICHUD:ToggleSelectionDetailsTitle` ("Toggle Selection Details") shows the
selected territory's armies, structures and build queue. Nothing in INI controls whether it shows:
`strategichud.ini`'s `ToggleSelectionDetailsButton` holds an `Image`, a `Title` and a `Help`, and no
`Scenario` or `LivingWorldCampaign` field touches it.

It is an APT movie. `StrategicHUD.apt` (`apt/strategichud.big`) loads it in frame 0:

```
StrategicDetailsTray.swf  ->  selectionDetails      ; and _OnSelectionDetailsLoaded / Unloaded
```

`StrategicDetailsTray.apt` defines `Open` (`gotoAndPlay("_open")`), `Close` (`"_close"`) and
`SetToggleButtonState`, sends `_OnOpened` at the end of the open animation and `_OnClosed` at the
end of the close one, and in `_closed` shows nothing - frame 31 sets `tray._visible` and
`Frame._visible` false. Edain ships its own copy only in `___edain_apt_widescreen.big`; at 4:3 the
stock `apt/strategicdetailstray.big` is the one loaded.

## The engine class that drives it

`StrategicHUD`'s `_OnSelectionDetailsLoaded` handler (`0x0083A0E6`) constructs one object
(`0x00985DD6`, called only from `0x0083A141`), vtable `0x00C867C0`:

| slot | address | what |
|---|---|---|
| `+0x04` | `0x009859D6` | `setHasContent(Bool)` - stores `+0x2C` if it changed, `ret 4` |
| `+0x14` | `0x009859E5` | `isOpen` - `state == 2` |
| `+0x18` | `0x009859EF` | `isClosed` - `state == 0` |
| `+0x1C` | `0x00985CB8` | `jmp open` |
| `+0x20` | `0x00985CBD` | `jmp close` |

```asm
00985b28  push esi                        ; open()
00985b29  mov  esi, ecx
00985b2b  mov  eax, [esi+0x18]            ; the movie path
          ...  push "Open" / call 0x0092B9C8 ; the movie's Open()
00985b53  mov  dword [esi+0x28], 1        ; opening
00985b5b  ret
```

`close` (`0x00985B5C`) is the same with `"Close"` and state 3. The constructor registers the
movie's callbacks against the object: `_OnClosed` -> `0x00985CFB` (3 -> 0), `_OnOpened` ->
`0x00985D16` (1 -> 2), and `_OnToggleButtonClicked` -> `0x00985CC2`, which opens a closed tray and
closes an open one.

The HUD's per-frame refresh, `0x00985C53` (called from `0x008397E6`):

```asm
00985c56  cmp  byte [esi+0x2c], 0         ; anything to show?
00985c5a  jne  0x985c70
00985c5c  cmp  dword [esi+0x28], 2
00985c60  jne  0x985c67
00985c62  call close                      ; no: close an open tray
00985c67  push 0
00985c6b  call setToggleButtonState       ; and "_disabled"
          ...
00985c96  cmp  byte [esi+0x2c], 0         ; yes: "_enabled" unless it is animating
```

So `+0x2C` decides everything the refresh does, and `setHasContent` is its only writer.

## The scenario

`LivingWorldCampaignManager::advanceAct` (`0x007B970F`) and its neighbour at `0x007B9743` read the
current campaign as `manager->[0x14][manager->[0x10]]`, checking `0 <= index < (end - begin) / 4`.
The start-up state builder at `0x00932B95` reads that campaign's `Scenario` as `[campaign+0x1C]`,
and walks `DisableRegions` at `Scenario+0x1C` from it (see
[`living-world-region-gating.md`](living-world-region-gating.md)).

`Scenario` is `0xC4` bytes (`push 0xC4` at `0x0090288D`). Its field table (`0x00C7A578`, referenced
once, at `0x009028B2`) ends with the two `Bool`s `HistoricalScenario` (`+0xC0`) and
`UseMpRulesVictoryCondition` (`+0xC1`); the constructor writes them at `0x00901E6A`
(`mov byte [esi+0xC0], bl`, `ebx` zero from `0x00901DE5`) and `0x00901E70`
(`mov byte [esi+0xC1], 1`). `+0xC2..+0xC3` is padding.

## The patch

- `Scenario` gains `HideSelectionDetails`, a `Bool` at `+0xC2`, in a rebuilt field table.
- The constructor's store at `0x00901E6A` becomes `mov dword [esi+0xC0], ebx`, zeroing the field;
  the next instruction puts `UseMpRulesVictoryCondition` back to `Yes`.
- `setHasContent` is entered through a cave that stores 0 when the current scenario's flag is set,
  then replays the compare and resumes on the stock `je`.
- `open` is entered through a cave that returns at once when the flag is set.

With the flag set, the refresh sees nothing to show: it closes the tray if it is open and disables
the toggle button, and a click on it reaches an `open` that does nothing. Any null on the way to the
flag - no manager, no current campaign, no `Scenario` - answers `No`.

```
LivingWorldCampaign WOTRScenarioAngmar
    Scenario
        HideSelectionDetails = Yes
    End
End
```

## What is not known

- **Nothing here has run.** Every step is a reading of the disassembly.
- **The movie's own auto-open.** `StrategicDetailsTray.apt`'s frame 0 loads
  `StrategicDetailsRegion.swf` into `tray` and plays `_open` when `!_global.InGame`, without the
  engine. The engine registers `InGame` with the movie player at `0x00815EF3`, which reads as that
  branch being the movie's standalone preview; if it does run in game, the tray opens once on load
  with the engine's state still 0, and the refresh (which only closes state 2) would not close it.
- **The toggle button's image.** Neither tray movie names a `toggleButton` clip, so
  `SetToggleButtonState` has nothing to act on in these movies; where the button is drawn was not
  traced.
- **What the player loses.** The tray is the interface for a territory's structures and build
  queue; hiding it has not been checked against what else in the HUD reaches those.
