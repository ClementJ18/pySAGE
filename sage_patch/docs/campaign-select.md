# Starting a campaign by name — reverse-engineering notes

The RE behind [`patches/campaign_select.py`](../patches/campaign_select.py). ROTWK `game.dat`
build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-08-10.

## The gap

A ROTWK shell can start exactly the campaigns EA compiled into it, and the shipped
`LinearCampaignExpansion1.ini` says so in a comment:

> Note that campaign names are basically hard-coded into the game engine. It would be
> nice to pull them from the flash file or something but... we don't. They must be
> named ANGMAR_CAMPAIGN

The main menu's Solo Play flyout offers two campaign entries — `Expansion1Campaign` and
`BonusCampaign` — and each is bound to one string literal in the binary. A mod shipping a third
campaign has nowhere to put it.

## TL;DR

- The `.apt` reaches the engine through `_root.GameCode(func, params)`, which is
  `geturl2("FSCommand:AptMainMenu::" + func, params)`. `AptMainMenu` builds a **string-keyed
  callback map** at `this+0x21C` in its constructor (`0x0091CA80` onwards), one ~85-byte
  registration block per command.
- `AptMainMenu::Expansion1Campaign`'s callback is 35 bytes at `0x0091AF8C`. It writes a phase, a
  screen id, and **the first byte of the params string** as the difficulty — and throws the rest
  of the string away. That discarded tail is the channel this patch uses.
- The screen id indexes a **14-entry jump table** at `0x0091C70B`. Case 13 (`Expansion1Campaign`)
  and case 14 (`BonusCampaign`) each defer a thunk that builds an `AsciiString` holding one
  literal and calls `startLinearCampaign` (`0x0091B1D2`).
- `startLinearCampaign` takes an `AsciiString *` and resolves it through `TheCampaignManager`
  (`0x005EB010`, returns `-1` for an unknown name). **Only the name is hardcoded** — everything
  under it is already generic.
- Case 13's thunk holds its `AsciiString` in a **function-local static behind an MSVC magic-static
  guard** (`0x00DEA35C` / `0x00DEA360`). Fill the static and set the guard bit before the thunk
  runs and the literal is never reached.
- So the patch is **one five-byte `jmp`** plus a 129-byte cave: no jump-table relocation, no new
  FSCommand registration, no functor construction. The `.apt` sends
  `"Hard:DWARVEN_CAMPAIGN"` instead of `"Hard"`.

## 1. How the movie reaches the engine

`MainMenu.apt`'s `SoloPlayNav` sprite (character 25) places five `menu1_sub01` clips on its
`_show` frame, named `Skirmish`, `WarOfTheRing`, `Expansion1Campaign`, `BonusCampaign` and
`LoadGame`. Dispatch is by placeobject **name**: the clip's button calls
`_root.OnButtonClick(parent, this)`, which invokes `_root[this._name + "Button"]()`.

`Expansion1CampaignButton` opens the difficulty sprite, and that sprite's frame 41 does the actual
call:

```
_root.GameCode(this.side, this.level)      ; side = "Expansion1Campaign", level = "Hard"
```

`GameCode(func, params)` is:

```
geturl2("FSCommand:" + _root.CodePrefix + "::" + func, params)   ; CodePrefix = "AptMainMenu"
```

So the engine receives the command name in the URL and **`params` as the target** — a plain
string the movie chooses freely. Today it is only ever `"Easy"`, `"Medium"` or `"Hard"`.

## 2. The callback registry

`AptMainMenu`'s constructor fills two string-keyed maps, in ~85-byte blocks that differ only in
the name and the member function:

```asm
0091cb02  push 0x00c7d254               ; "AptMainMenu::Expansion1Campaign"
0091cb07  lea  ecx, [ebp+8]
0091cb0a  mov  esi, 0x0091af8c          ; <-- the callback
0091cb0f  xor  edi, edi
0091cb11  call 0x004374e0               ; AsciiString(name)
          ...                           ; wrap (esi, edi, ebx) into a functor
0091cb40  lea  ecx, [ebx+0x21c]
0091cb46  call 0x0092b062               ; map::insert
```

Those 13 bytes — `push <name>` / `lea ecx, [ebp+8]` / `mov esi, <callback>` — are what tie the
string to the code, and the patch fingerprints them. Without that link, `0x0091AF8C` is
indistinguishable from the `BonusCampaign` callback 35 bytes later, which is byte-identical apart
from one immediate.

The sibling map at `this+0x228` (`0x0092B0C7`, name + getter + index) is the `GetExtern` side —
`MainMenuLevel`, `MainMenuContinueCampaign`, `MainMenuUnlockBonusCampaign`, `BlinkBattleSchoolOff`,
all served by one getter at `0x0091BB6B` switching on the index. Not used by this patch, but it is
the route a future "tell the movie which campaigns exist" change would take.

## 3. The callback, whole

```asm
0091af8c  mov  eax, [esp+4]             ; params
0091af90  mov  [ecx+0x288], 9           ; phase: leaving the menu
0091af9a  mov  [ecx+0x28c], 0Dh         ; screen id 13
0091afa4  mov  al, [eax]                ; <-- ONE BYTE
0091afa6  mov  [ecx+0x2a8], al          ; 'E' / 'M' / 'H'
0091afac  ret  4
```

`BonusCampaign` at `0x0091AFAF` is the same with `0Eh`.

Two things follow, and they are the whole patch:

1. `params` is a `const char *` the engine already holds and already dereferences — not an
   `AsciiString` (`[eax]` would then be the low byte of a heap pointer, which could not be a
   difficulty letter). Confirming: the between-missions path at `0x009C5060` pushes `0x45` — `'E'`
   — into the same field directly.
2. Everything after `params[0]` is discarded. Nothing downstream can see it, so nothing downstream
   can be broken by putting something there.

## 4. From screen id to campaign name

```asm
0091c349  mov  eax, [ebx+0x28c]
0091c34f  dec  eax
0091c350  cmp  eax, 0Dh
0091c353  ja   <default>
0091c359  jmp  dword ptr [eax*4 + 0x0091c70b]     ; 14 entries
```

| case | body | thunk | campaign |
|---|---|---|---|
| 11 | `0x0091C3A3` | `0x0091BE05` | `GOOD_CAMPAIGN` |
| 12 | `0x0091C3B4` | `0x0091BDB0` | `EVIL_CAMPAIGN` |
| 13 | `0x0091C3C2` | `0x0091BE64` | `ANGMAR_CAMPAIGN` / `ANGMAR_CAMPAIGN_DEMO` |
| 14 | `0x0091C3D0` | `0x0091BEFA` | `ANGMAR_BONUS_CAMPAIGN` |

The table ends at `0x0091C743`, where a function starts — so it cannot grow in place, and adding a
fifteenth case would mean relocating it. It does not have to.

Each case does `mov al, [ebx+0x2a8]` / `push eax` / `call <wrapper>`; the wrapper wraps the thunk
into a functor and hands it to `0x0091C108`, which runs it after the screen fade.

## 5. Where the name is actually said

Case 13's thunk:

```asm
0091be64  <SEH prologue>
0091be6f  and  dword ptr [ebp-0x10], 0             ; a throwaway local AsciiString
0091be73  mov  eax, [0x00de4324]
0091be7c  cmp  byte ptr [eax+0x60], 0              ; the demo build flag
0091be83  je   0091be8c
0091be85  push 0x00c7ced4                          ; "ANGMAR_CAMPAIGN_DEMO"
0091be8a  jmp  0091be91
0091be8c  push 0x00c7cec4                          ; "ANGMAR_CAMPAIGN"
0091be91  call 0x004050e6                          ; -> the local

0091be96  test byte ptr [0x00dea360], 1            ; the magic-static guard
0091be9d  push esi
0091be9e  mov  esi, 0x00dea35c                     ; the static - loaded either way
0091bea3  jne  0091beca                            ; already initialised -> skip
0091bea5  or   dword ptr [0x00dea360], 1
0091beb6  call 0x00435f30                          ; static = local  (copy-ctor)
0091bec0  call 0x00a3cf72                          ; atexit(dtor)

0091beca  push [ebp+0xc]
0091becd  fld  dword ptr [ebp+8] ; push ecx ; fstp dword ptr [esp]
0091bed4  push esi                                 ; <-- the static, always
0091bed5  call 0x0091b1d2                          ; startLinearCampaign
```

The local built from the literal is **thrown away**; what reaches `startLinearCampaign` is always
the static at `0x00DEA35C`. And the static is written exactly once per process, guarded by
`0x00DEA360 & 1`.

So: set the static, set the guard bit, and the literal path never runs again. The thunk is
unmodified, the jump table is unmodified, the registry is unmodified.

### Why `startLinearCampaign` accepts anything

```asm
0091b236  push dword ptr [esp+0x10]                ; the AsciiString*
0091b23a  mov  ecx, [0x00de36cc]                   ; TheCampaignManager
0091b240  call 0x005eb010                          ; -> index, or -1
0091b245  mov  esi, eax
0091b247  cmp  esi, -1
0091b24a  je   <give up>
```

A name lookup against the campaign manager's list, which is built from the `LinearCampaign` blocks
in INI. Any block name in the mod's INI is therefore already startable — the shell just had no way
to say it. An unknown name is a no-op, not a crash.

## 6. The patch

Five bytes at `0x0091AF8C` become `jmp <cave>`; the remaining 30 are left as unreachable stock
code, which is what `verify` re-reads as a fingerprint. The cave reproduces the stock callback
exactly and then parses the tail of `params`:

```asm
          mov  eax, [esp+4]                        ; ---- the stock callback ----
          mov  [ecx+0x288], 9
          mov  [ecx+0x28c], 0Dh
          mov  dl, [eax]
          mov  [ecx+0x2a8], dl
          test dl, dl ; je done                     ; empty params: nothing to parse

          mov  edx, eax                            ; ---- find the separator ----
scan:     mov  cl, [edx] ; inc edx
          test cl, cl ; je done                     ; no ':' -> stock behaviour
          cmp  cl, ':' ; jne scan
          cmp  byte ptr [edx], 0 ; je done          ; "Hard:" names nothing

          mov  eax, <buffer>                       ; ---- copy, bounded by the buffer ----
copy:     mov  cl, [edx] ; mov [eax], cl
          test cl, cl ; je installed
          inc  edx ; inc eax
          cmp  eax, <buffer+63> ; jb copy
          mov  byte ptr [eax], 0                    ; truncate, still terminated

installed:mov  ecx, 0x00dea35c                     ; ---- install ----
          push <buffer>
          call 0x004050e6                          ; AsciiString::set  (`ret 4`)
          or   dword ptr [0x00dea360], 1           ; the guard
done:     ret  4
```

Only `eax`, `ecx` and `edx` are touched — the three the stock callback already clobbers — so there
is no prologue and no frame.

`AsciiString::set` (`0x004050E6`) `strlen`s its argument and hands both to the buffer assign at
`0x004360C0`, which releases or reuses whatever the string held. Calling it on the
never-constructed static is safe: the assign tests `m_data` against NULL first, and the static
lives in zero-initialised data.

### The movie's half

```
_root.GameCode("Expansion1Campaign", "Hard:DWARVEN_CAMPAIGN")
```

Byte 0 is still the difficulty. `sage_patch.patches.campaign_select.params()` builds the string and
`campaign_of()` states the parse rule in Python; the test suite runs the emitted bytes through a
20-opcode interpreter and asserts the two agree for every shape of input, including truncation at
63 characters.

## 7. What this does not do

- **It does not touch `BonusCampaign`.** Case 14 and its `ANGMAR_BONUS_CAMPAIGN` literal are
  untouched, so that button keeps working exactly as it did. One generic channel is enough; the
  movie routes every campaign entry through `Expansion1Campaign`.
- **It does not make the campaign list data-driven.** The movie still has to know the names. Doing
  that in the engine means new entries in the `this+0x228` getter map (§2) so the `.apt` can ask
  what campaigns exist — a separate, larger change.
- **It does not add a menu.** The Solo Play flyout is still five fixed entries; the second-level
  campaign menu is `.apt` work.
- **A stock params string is left completely alone** — no copy, no static write, no guard. A movie
  that never uses the separator gets stock behaviour, `_DEMO` variant included.

### One consequence

Once a name has been installed the guard stays set for the life of the process. The
between-missions screen's own route into case 13 (`0x009C506F`, `push 0x45` / `call 0x0091C262`)
therefore continues whichever campaign was started, rather than reverting to `ANGMAR_CAMPAIGN` —
which is what you want, and why the movie should send a name on **every** campaign button rather
than mixing the two forms.

### One leak

Filling the static ourselves skips the `atexit` registration at `0x0091BEC0`, so the last campaign
name allocated is never freed. One `AsciiString` buffer, reclaimed by the OS at process exit.

## Status

Applies and verifies against the real `game.dat`; the emitted cave is executed by the test suite's
interpreter, and the addresses are checked against the installed binary by `TestInstalledBinary`.

**Runtime-verified in game**, 2026-08-10. No shipped movie sends a separator, so the test needed a
throwaway `.apt` edit: two instructions in `MainMenu.apt`'s `LevelOfDifficulty` sprite (character
82, frame 41), turning the params argument into `this.level + ":ANGMAR_BONUS_CAMPAIGN"` —

```xml
<pushthis/><getnamedmember val="4"/>          <!-- this.level -->
<pushstring str=":ANGMAR_BONUS_CAMPAIGN"/>    <!-- inserted -->
<newadd/>                                     <!-- inserted -->
<pushthis/><getnamedmember val="5"/>          <!-- this.side  -->
```

— so that **Solo Play → "An Unexpected Party"** (the `Expansion1Campaign` button, whose callback is
the one this patch detours) asks for a campaign it cannot reach on a stock engine. Stock, that
button can only ever load `ANGMAR_CAMPAIGN`, whose first mission is the map **Hobbiton**;
`ANGMAR_BONUS_CAMPAIGN`'s is **laketown**.

**Laketown loaded.** The engine took the campaign name from the movie.

Two things the run establishes beyond the patch itself:

- `startLinearCampaign` really does accept an arbitrary name through the static — the substitution
  survives the deferred, post-fade call path, not just the callback.
- A `sage_apt` round-trip of a **shell** movie loads in the real game. Only `Palantir.apt` had been
  validated before (`sage_apt/TODO.md`, M1), and `MainMenu.apt` is the file carrying the corpus's
  one unresolvable branch — which is in `SoloPlayNav`, not the block edited here, and came through
  untouched. Recompiling changed three lines of decompiled XML: the two inserted instructions and
  the `branchiftrue` displacement the compiler recomputed (24 → 32), still resolving onto the same
  `anchor="L1"`.

The `.apt` edit is **not** part of the patch and was applied only to the installed
`__edain_apt.big`, never to the mod's authoring tree.

## Address index

| symbol | address |
|---|---|
| `MAIN_MENU_CAMPAIGN_COMMAND` — `"AptMainMenu::Expansion1Campaign"` | `0x00C7D254` |
| `MAIN_MENU_CAMPAIGN_REGISTRATION` — the block binding it | `0x0091CB02` |
| `MAIN_MENU_CAMPAIGN_HANDLER` — the callback (35 bytes) | `0x0091AF8C` |
| `BonusCampaign`'s callback, for contrast | `0x0091AFAF` |
| screen-id jump table (14 entries) | `0x0091C70B` |
| the bound check on it (`cmp eax, 0Dh`) | `0x0091C350` |
| case 13 body / wrapper / thunk | `0x0091C3C2` / `0x0091C262` / `0x0091BE64` |
| `CAMPAIGN_NAME_BIND` — the guard test the patch relies on | `0x0091BE96` |
| `CAMPAIGN_NAME_STATIC` / `CAMPAIGN_NAME_STATIC_GUARD` | `0x00DEA35C` / `0x00DEA360` |
| `startLinearCampaign(AsciiString*, float, int)` | `0x0091B1D2` |
| `TheCampaignManager` / its name lookup | `0x00DE36CC` / `0x005EB010` |
| `ASCII_STRING_SET` — `AsciiString::set(const char*)` | `0x004050E6` |
| its buffer assign | `0x004360C0` |
| `"ANGMAR_CAMPAIGN"` / `"_DEMO"` / `"ANGMAR_BONUS_CAMPAIGN"` | `0x00C7CEC4` / `0x00C7CED4` / `0x00C7CEEC` |
