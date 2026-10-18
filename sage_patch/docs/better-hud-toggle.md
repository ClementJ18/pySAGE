# F9 hides the HUD in replays

The RE behind [`patches/better_hud_toggle.py`](../patches/better_hud_toggle.py). Build
`2.01.2614.37001`, ImageBase `0x400000`. Every address below was read statically, and every site
the patch asserts holds the same bytes in the repo-root `game.dat` and in the clean
`sage_mods/edain/patching/engine/game.dat.backup`.

**What it does.** During replay playback, F9 with no modifier hides the HUD, and F9 again shows it.
Whenever the HUD is hidden, by F9 or by anything else that calls the engine's hide (`HIDE_UI`,
cinematics, a `TOGGLE_CONTROL_BAR` binding), five more things stop drawing: unit occlusion (the
behind-building silhouettes), the top-left text messages, the floating "+N" over resource
buildings, veterancy pips, and the construction percentage over buildings being built. They come back whenever the engine shows the HUD.

## 1. Why stock has no way to do this

The engine already has a `CommandMap` meta command for the HUD, `TOGGLE_CONTROL_BAR`
(`MSG_META` `0x71`, from the meta-name table row at `0x00BF0930`). Its handler, in the command
translator, **refuses during playback**:

```asm
00820048  mov  ecx, [0x00DE7CD8]        ; TheRecorder
0082004e  cmp  ecx, ebx
00820050  je   0x00820060
00820052  call 0x007B0F25               ; mov eax, [ecx+0x1C]: the recorder mode
00820057  cmp  eax, 1                   ;   1 = playback
0082005a  je   0x00820680               ;   -> do nothing
...
008200b4  push 1
008200b6  call 0x00804707               ; the toggle
```

Stock RotWK also binds no key to it, and plain F9 is unbound: the shipped `CommandMap.ini` uses F9
only under Ctrl, Ctrl+Alt and Shift+Ctrl, all `DebugCommandMap`s.

The toggle (`0x00804707`) is not usable as-is either. It flips `ControlBar+0x2A4` through
`0x0071C8F9`, which appends **`MSG_DESTROY_SELECTED_GROUP`** (`0x3EC`, named by
`GameMessage::getCommandTypeAsString`'s second jump table, `0x0071260B`) to the message stream and
deselects everything. The patch calls the hide and show beneath it and leaves that state alone
(§3).

## 2. The key

`MetaEventTranslator::translateGameMessage` (`0x005DA83D`) takes raw key messages (`0x15` and
`0x16`) and builds everything a `CommandMap` match needs before it walks the map:

```asm
005da86c  cmp  dword [0x00DE789C], 2    ; German layout: swap DIK_Y and DIK_Z
005da873  mov  eax, [eax]
005da875  mov  [ebp-0x0C], eax          ; the DirectInput scan code
005da89d  mov  eax, [eax]               ; argument 1
005da8a5  mov  [ebp-0x10], eax          ; the KEY_STATE_* word
005da8a3..005da8bf                      ; [ebp-4] = the CTRL/SHIFT/ALT mask
005da8c3  mov  eax, [0x00DE7890]        ; <- hook (TheShell: picks the UseableIn mask)
```

`KEY_F9` is `0x43` in the `CommandMap` key-name table (`0x00BF0BB8`), which is the DirectInput
code. The state bits are `KEY_STATE_UP 0x01`, `DOWN 0x02`, Ctrl `0x04/0x08`, Shift `0x10/0x20`, Alt
`0x40/0x80` and autorepeat `0x100`, matching what the translator itself tests (`test al, 0xc`,
`test ax, 0x430`, `test al, 0xc0`, `test byte [ebp-0xf], 1`).

The cave fires on F9 with `DOWN` set, autorepeat clear and every modifier bit clear, while
`[TheRecorder+0x1C] == 1`. It tests the modifier keys from the state word rather than from
`[ebp-4]`, because the mask also folds in `0x400`, which `spellbook-hotkeys.md` §2 found set when
no key is held. Then it leaves through `0x005DA99B`, the edge every matched `CommandMap` takes:
the message is marked destroyed and the translator's tail runs. Any other key press rejoins the
stock code with the displaced load done.

## 3. The HUD

The hide and show are the pair the `HIDE_UI` and `SHOW_UI` script actions dispatch to. Their
templates sit at index `0x15B` and `0x15C` (name at template `+0x2C`, stride `0x80`, so
`0xADAC` and `0xAE2C` in `0x007DB935` / `0x007DB972`), and their cases in
`ScriptActions::executeAction`'s jump table are:

```asm
007ccd26  push 1 / call 0x00804576      ; HIDE_UI
007ccd2f  push ebx / call 0x008046A1    ; SHOW_UI (the argument is ignored)
```

`0x00804576` (cdecl, one argument) hides `ControlBar.wnd:ControlBarParent`, hands the tactical
view the full screen height, and tells the APT HUD to hide: `[0x00DE4A70]->0x006D527E(1)` (the
palantir, whose resource text is in `inflation-readout`), `[0x00DE3D6C]->0x00616873(1)`, and the
`InGameUI` sub-object at `+0x10`. `0x008046A1` calls it, then makes `ControlBar+0x2A4` 1 if it is
0, then calls the same three with "show". Cinematics use the same pair (`0x007BC8B7`, the letterbox
action), and so does every game start:

```asm
00628546  call 0x00484A85               ; game mode 4 or 7 (not a match)
0062854d  je   0x00628558
0062854f  push 1 / call 0x00804576      ;   -> hide
00628558  push ebx / call 0x008046A1    ; a match, replays included -> show
```

`ControlBar+0x2A4` is read only by the toggle and by show: the other `+0x2A4` loads in the image
are `Player`'s (`0x0071D274`, `0x0069C6CC`, `0x00776FE7`, `0x0087C8A6` all pick between a player's
`+0x2A0` and `+0x2A4`). So hiding without flipping it is safe, and it keeps the deselect away.

The patch keeps one flag at its section's base, and ties it to the pair itself. **Hide's first
instruction sets it** (`0x00804576`, `mov eax, <SEH frame>` ahead of the `EH_PROLOG` call), and
**show clears it** once the hide it starts with has returned (`0x008046A1`, whose first two
instructions are `push 1 / call hide`). F9 calls hide when the flag is clear and show when it is
set, so a HUD hidden some other way during a replay counts as hidden and F9 brings it back.

Hide has 15 callers. Besides the script actions, the letterbox action, the toggle, show and the game
start above, they are load and teardown paths (`0x00626222`, `0x0062836C`, `0x0062CA8B`,
`0x0063CF41`, `0x006138BF`, `0x0069CCBC`, `0x00779449`) and the living-world map
(`0x006BE0F6`, `0x006BF8D9`). Game modes 4 and 7, the non-match modes, hide at start, so the
flag is set on the shell map. That map has no HUD, and every match start shows, which clears it.

Show is not the only way the palantir comes back. `0x006D5397`, a palantir method that sets a
message (`+0x14C`) and re-shows the palantir if any of its hidden bits (`+0x60 & 7`) is set, calls
`0x006D527E(0)` on its own. Its callers are `InGameUI` vtable slots (`0x00BDDB0C`,
`0x00C13644`, through `0x0069B788`) and `0x00897987`, which passes it a non-empty wide string.
That reopens the palantir alone and leaves the flag set, so the five elements stay hidden until
something calls show. Stock `HIDE_UI` lets the palantir reopen the same way. The other show-capable
call, `0x005EAD06`, passes `edi`. It is followed by the same `InGameUI` `+0x24` call as
`0x0061239D`, which passes 1 (hide), and is not traced further.

## 4. The five other elements

Each one has a single gate, and the patch adds the flag to it.

**Text messages.** `InGameUI::postDraw` (`0x006A0BC0`) draws the message list only while
`InGameUI+0x811` is set:

```asm
006a0bd2  cmp byte [edi+0x811], 0       ; <- gate
006a0bd9  je  0x006A0D23                ;    skip the message loop
006a0bdf  ...                           ;    MessagePosition (+0x81C) / MessagePositionLW (+0x824)
```

The offsets come from the `InGameUI` field table (`0x00C12410`: `MessagePosition +0x81C`,
`MessageDelayMS +0x838`).

**Floating text.** `InGameUI::draw` (`0x006A3B59`) is four calls, the third the floating-text pass:

```asm
006a3b6a  call 0x0069DC5B               ; walk InGameUI+0x8A0, project, draw
```

The pass reads `FloatingTextMoveUpSpeed` (`+0x8A8`) and its update sibling `0x0069DB40` reads
`FloatingTextVanishRate` (`+0x8AC`). The patch replaces the call and leaves the update alone. The floating text list also carries the red "lost gold" text, which hides
with it.

**Veterancy pips.** `Drawable`'s icon pass (`0x00679A04`) is a switch on the icon kind, and case 2
is the pips:

```asm
00679a2f  mov  ecx, esi
00679a31  call 0x0067939F               ; reads GlobalData+0xEB8, VeterancyPipDrawObjectFilter
```

`0x00C00C40` is that row of the `GameData` table (`offset 0xEB8`). The patch replaces the call.

**Construction percentage.** Case 0 of the same switch ends with the "under construction" text:

```asm
00679a6b  mov  ecx, esi
00679a6d  call 0x00677CF9               ; Drawable::drawConstructPercent, thiscall, plain ret
```

`0x00677CF9` returns early unless the object has status 2 and not status `0x13`, then formats
`Object+0x288` with `CONTROLBAR:UnderConstruction` (`00677e66  push 0x00C11144`; an object whose
template name matches `0x00C11180`, `"moot"`, uses `CONTROLBAR:CouncilDesc` instead). The text is
drawn in `DrawableCaptionFont` (`InGameUI+0x7A0`, bold `+0x7A4`) into a display string kept at
`Drawable+0x340`, which the routine itself frees once the object stops being under construction.
Skipping the call while hidden leaves that string in place, and the first visible frame after
construction ends frees it as stock would. The patch replaces the call.

Health bars, and the rest of the switch, are untouched.

**Unit occlusion.** The script action `OPTIONS_SET_OCCLUSION_MODE` (template `0x12A`, case
`0x007CE207`) writes `GameLogic+0x99` through `0x007BD549`. Its two readers are in one render setup
function, each followed by a test of the byte `0x00DD1E44` that skips the occlusion setup when set:

```asm
0047074d  mov  ecx, [TheGameLogic]
00470753  cmp  byte [ecx+0x99], 0
0047075a  je   0x00470782
0047075c  cmp  byte [0x00DD1E44], 0     ; <- gate A
00470763  jne  0x00470782

004707c1  mov  eax, [TheGameLogic]
004707c6  cmp  byte [eax+0x99], 0
004707cd  je   0x004707DE
004707cf  cmp  byte [0x00DD1E44], 0     ; <- gate B
004707d6  jne  0x004707DE
```

The patch makes the flag act like `0x00DD1E44`, so a hidden HUD takes the path a disabled
occlusion already takes. It does not write `GameLogic+0x99`, so a map script that sets occlusion
during the replay keeps its setting. The getter `0x0046D812` (`mov al, [ecx+0x99]`) has no
references, so these two sites are the only readers.

## 5. What is still unknown

- `0x00DD1E44`, the byte that also suppresses occlusion, is unidentified. The patch only reads it.
- Which APT movies `[0x00DE3D6C]` and the `InGameUI` `+0x10` sub-object are. The hide treats them
  as the engine does, so the HUD looks the way it does in a cinematic.
- Show never re-shows `ControlBarParent` or restores the tactical view height that hide changed.
  Stock `SHOW_UI` behaves the same, so if a `.wnd` element stays missing after F9, it would also
  be missing after a cinematic.
- The key arrives only if no window has keyboard focus first. A focused text box would take F9.
- What drives `0x00897987`, the palantir message that can reopen a hidden palantir (§3).
