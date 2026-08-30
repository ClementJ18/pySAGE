# Recovering BFME1's Battle School

Recovered against RotWK 2.01 `game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, 2026-08-29.
Static analysis of both binaries (RotWK `game.dat` and BFME1 `lotrbfme.exe`, the latter read with
`explore.py --game`), plus `sage_apt` decompiles of BFME1's, stock RotWK's and Edain's
`MainMenu.apt`. The feature has since been **built and run**: it opens in the game, the videos
play, and the artwork does not draw. §8 separates what has been seen working from what has not, and
both halves are built —
[`patches/experimental/battle_school.py`](../patches/experimental/battle_school.py) and
[`tools/build_battle_school.py`](../../tools/build_battle_school.py).

**The finding in one sentence.** The Battle School is a **movie feature**, not an engine feature —
RotWK still carries the whole engine side (the `AptMainMenu::BattleSchool` FSCommand, the
`BlinkBattleSchoolOff` extern, the `FlashTutorial` preference and its 5-launch blink timer, the
`MainMenuToBattleSchool` window transition in stock ini, the `BinkMovie` gadget and the book
sounds), and the only thing EA deleted from the engine is the mirror command that *leaves* the
screen, which does not need re-registering because the surviving command has a free parameter to
carry the direction.

## 1. What Battle School is

BFME1's main menu bar carries a `BATTLE SCHOOL` button that opens a parchment book of six tutorial
topics — World Map, Moves & Attacks, Bases & Units, Heroes, Veterancy, Special Powers — each of
which plays a full-screen narrated `.vp6` video with page-flip animations between spreads. The
button blinks until the player has either opened it once or launched the game six times.

The engine's entire contribution is: fade the shell-map audio out so the video's own audio is clean,
remember that the player has seen it, and fade back in afterwards. Everything else — the book, the
topic list, the page flipping, the video container — lives in `MainMenu.apt`.

## 2. What survives in RotWK

Everything below is present in a stock RotWK install.

| piece | where | state |
|---|---|---|
| `AptMainMenu::BattleSchool` FSCommand | string `0x00C7D0A8`, registered `0x0091D052`, handler `0x0091B540` | **complete**, semantically identical to BFME1's |
| `BlinkBattleSchoolOff` extern | string `0x00C7CFF4`, registered `0x0091D2AA` as index 3 of the getter `0x0091BB6B` | **complete** |
| `FlashTutorial` preference | key `0x00C7CE18`, read `0x0091D446`, cleared `0x0091D485` | **complete** |
| the 5-launch blink timer | `TimesInGame` (`0x00C7CFB0`) read/incremented `0x0091D3EB`, compared `0x0091D477` | **complete** |
| `WindowTransition MainMenuToBattleSchool` | stock `ini.big`, `data/ini/windowtransitions.ini` | **complete**, byte-identical to BFME1's, comment included |
| `SOUNDFADE` / `LeaveSilent` | field table `0x00C2CAB0`, `LeaveSilent` is row 3 at offset `0x1C` | **complete** |
| `BinkMovie` APT gadget | `BinkGameWindow::Create` / `BinkMovieInit` in `game.dat`; `GameWindowGadgets.apt` exports it as character 30 | **complete** — RotWK's own `MainMenu.apt` already imports it as character 91 |
| `Gui_BookOpen` / `Gui_BookClose` / `Gui_BookPageTurn` | stock `data/ini/soundeffects.ini` | **entries survive, wave assets do not** (§5) |
| `Video Tutorial*` blocks | Edain's `data/ini/video.ini` | all ten still declared; stock RotWK's `video.ini` dropped them |

### 2.1 The surviving handler, whole

```asm
0091b540  <SEH prologue>
0091b54d  mov  eax, [0x00de7890]          ; the shell
0091b555  cmp  eax, ebx ; je 0091b560
0091b55c  mov  byte ptr [eax + 0x5d], 1   ; "a full-screen movie owns the screen"
0091b567  push 0x00c7ce28                 ; "MainMenuToBattleSchool"
0091b56c  call 0x004374e0                 ; AsciiString(name)
0091b571  mov  ecx, [0x00de3654]          ; TheWindowTransitionsHandler
0091b577  call 0x005db9a6                 ;   ->  setGroup(name)
0091b57c  mov  ecx, [0x00de7890]
0091b586  call 0x0075d9b1                 ; TheAudio vtable+0x8c (2, 1, 0) - stop shell audio
0091b58e  call 0x006e56f3                 ; OptionPreferences()
0091b593  push 0x00c7ce18                 ; "FlashTutorial"
0091b5af  call 0x007b2679                 ;   ->  set(key, 0)
0091b5c2  call 0x007b274c                 ; write user preferences
0091b5ce  mov  byte ptr [esi + 0x281], bl ; the blink flag, now off
0091b5e6  ret  4
```

BFME1's is `0x0091DD10` and does exactly the same, with the shell flag at `+0x59` and the blink
flag at `+0x25D`. Nothing was stubbed out; the code simply has no caller because no shipped RotWK
movie sends the command.

`ret 4` — the handler **takes a `params` argument and never reads it**. That is the hook §6 uses.

### 2.2 The blink extern

`BlinkBattleSchoolOff` is index 3 of the shared `this+0x228` getter:

```asm
0091bb91  test dl, dl ; jne <write path>
0091bb99  cmp  byte ptr [ecx + 0x281], dl  ; the blink flag
0091bb9f  mov  eax, 0xbd5d8c               ; "0"
0091bba4  jne  0091bc10
0091bba6  mov  eax, 0xbd5d90               ; "1"
```

So `_root.getExtern("BlinkBattleSchoolOff")` returns `"1"` once the flag is clear — the movie
blinks the button while it reads `"0"`.

The flag is seeded from the preference in the `AptMainMenu` constructor, and self-clears:

```asm
0091d446  push 0x00c7ce18 ; "FlashTutorial"
0091d453  push 1                            ; default: blink
0091d460  call 0x007b2917                   ; getBool(key, default)
0091d468  mov  byte ptr [ebx + 0x281], al
0091d477  cmp  edi, 5                       ; edi = TimesInGame, already incremented
0091d47a  jle  0091d4b6
0091d47c  cmp  byte ptr [ebx + 0x281], 0
0091d483  je   0091d4b6
0091d48d  mov  byte ptr [ebx + 0x281], 0    ; six launches is enough
0091d4a5  call 0x007b2679                   ; FlashTutorial = 0, persisted
```

## 3. The one thing EA deleted

BFME1 registers a second command, `AptMainMenu::TutorialExit` (string `0x01106514`, registration
`0x0091FCFD`, handler `0x0091DE00`). RotWK's registry has no such entry. It is the exact mirror:

```asm
0091de01  mov  eax, [0x012f4b58]           ; the shell
0091de0d  mov  byte ptr [eax + 0x59], 0    ; release the screen
0091de11  mov  ecx, [0x012ed668]
0091de19  push 8 ; call [eax + 0x28]       ; stop the tutorial video
0091de25  push 0x0110633c                  ; "MainMenuToBattleSchool"  <- the same group
0091de2f  mov  ecx, [0x012f3330]           ; TheWindowTransitionsHandler
0091de35  call 0x0041422c                  ;   ->  reverse(name)
0091de44  call 0x0042359c                  ; restart shell music
0091de49  mov  dword ptr [esi + 0x264], 0
```

RotWK has every ingredient. Its `AptMainMenu::CreditsExit` (`0x0091B6FD`) is the same function for
a different screen, and its tail is a drop-in template:

```asm
0091b733  mov  ecx, [0x00de7890]           ; the shell
0091b73d  call 0x0075d9ca                  ;   ->  isShellMusicPlaying()
0091b742  test al, al ; jne 0091b764       ; still playing -> leave the audio alone
0091b746  mov  ecx, [0x00de42fc]           ; TheAudio
0091b753  call [eax + 0x8c]                ;   ->  stop (2, 1, 0)
0091b759  mov  ecx, [0x00de7890]
0091b75f  call 0x0075df26                  ;   ->  playShellMusic()

0091b764  push 0x00c7ce40                  ; "MainMenuToCreditsScreen"
0091b770  call 0x004374e0                  ; AsciiString(name)
0091b775  mov  ecx, [0x00de3654]           ; TheWindowTransitionsHandler
0091b77b  call 0x005dba99                  ;   ->  reverse(name)   (setGroup's sibling)
0091b780  lea  ecx, [esi + 0x2a4]
0091b786  mov  dword ptr [esi + 0x288], ebx
0091b78c  call 0x00435d50                  ; AsciiString::~AsciiString
0091b791  mov  eax, [0x00de7890]
0091b796  mov  byte ptr [eax + 0x5d], bl   ; release the screen
0091b799  mov  edx, [0x00de4364]           ; TheWritableGlobalData
0091b79f  mov  ecx, [0x00de4324]           ; TheGameEngine
0091b7a5  push dword ptr [edx + 0x28]      ; GlobalData FramesPerSecondLimit
0091b7aa  call dword ptr [eax + 0x48]      ; setFramesPerSecondLimit - the movie raised the cap
0091b7b0  ret  4
```

Swap `0x00C7CE40` for `0x00C7CE28` and that *is* `TutorialExit`.

Two of those lines the patch does **not** copy, on the principle that the exit arm should undo what
the enter arm did and nothing else: `0x0091B786`'s phase reset (entering Battle School never sets
the phase) and `0x0091B780`'s destruct of the `GetExtern` scratch string (entering never touches
it). Both are harmless either way - `AsciiString::~AsciiString` nulls what it releases, so it is
idempotent - but the symmetry is the rule that decides.

### Why the absence is survivable

The FSCommand dispatcher misses silently. `0x00623BF1` looks the name up, `0x00623C00` retries on
a NULL result, and `0x00623C2E` jumps straight to the epilogue at `0x00623C40` when the second
lookup also fails. **An unregistered command is a no-op, not a crash** — so a movie can ship
`GameCode("TutorialExit")` against a stock engine and the only symptom is that the shell stays
silent, because `MainMenuToBattleSchool` sets `LeaveSilent = Yes`.

## 4. What is missing on the movie side

Stock RotWK's `MainMenu.apt` and Edain's override contain **no trace** of Battle School — no
button, no book, no `ShowBattleSchoolVideo`. Both decompile and recompile byte-exact under
`sage_apt check`, as does BFME1's, so all three are editable.

BFME1's implementation, for scale:

| | BFME1 `MainMenu.apt` | stock RotWK | Edain |
|---|---|---|---|
| characters | 310 | 94 | 94 |
| imports | 25 | 20 | 20 |
| textures | 32 `.tga` | 1 atlas page | (inherits stock) |

The Battle School subtree is **81 characters** — 76 defined plus 5 imports — reached transitively
from sprite 304:

```
sprite   32  2 31 62 68 75 85 238 241 244 245 250 255 259 260 263 269 270 273
             279 280 283 291 292 293 294 295 297 299 301 302 303 304
shape    25  22 30 61 67 74 84 240 247 249 251 254 256 258 266 267 268 276 277
             278 284 285 286 287 289 290
edittext 14  243 252 253 261 262 264 265 271 272 274 275 281 282 288
button    3  296 298 300
font      2  55 242
import    5  1 Pattern_shell · 12 buttonGlow · 33 buttonCloud · 34 buttonSuperGlow
             (MenuExport) · 237 BinkMovie (GameWindowGadgets)
```

Its 25 shapes reference 17 image characters, hence 17 textures:
`apt_MainMenu_{29,51,52,53,60,63,64,66,71,73,81,82,83,239,246,248,257}.tga`.

The glue in BFME1's root movieclip is small — three functions and one frame:

- `ShowBattleSchoolVideo` (37 bytes): hides `DebugMenu`, `_root.GameCode("BattleSchool")`,
  `FadeAnimation("out","Image","fast")`, `ExitMenu.gotoAndPlay("_show")`, `gotoframe 1`.
- `HideBattleSchoolVideo` (5 bytes): `movieContainer.Close()`.
- `AfterBattleSchoolVideoOut` (40 bytes): shows `DebugMenu`, fades in, `ExitMenu` hides,
  `MainMenu.gotoAndPlay("_show")`, **`_root.GameCode("TutorialExit")`**, `gotoframe 0`.
- root frame 2, labelled `BattleSchool`, places sprite 304 at depth 3 as `movieContainer`.

The nav entry is one `<placeobject>` carrying `buttonName = "$BattleSchool"` and
`gameCode = "BattleSchool"`, next to a frame action that sets `BattleSchool.blinkVar` from
`_root.getExtern("BlinkBattleSchoolOff")`. RotWK's `_root.CodePrefix` is already `AptMainMenu`, so
`GameCode` reaches the surviving handler with no change.

Frame 3 (`_show_credits`, sprite 309) is the same pattern in 8 characters, and RotWK kept it — so
the container/`GameCode` convention the book plugs into is live in the target movie.

## 5. What is missing on the asset side

All of it, and all of it exists in the BFME1 install.

| asset | count | BFME1 location | RotWK |
|---|---|---|---|
| tutorial videos | 6 | `data/movies/tutorial{worldmap,movesandattacks,basesandunits,heroes,veterancy,specialpowers}.vp6` | absent |
| book animations | 4 | `data/movies/{bookopen,bookclose,bookflipforward,bookflipback}.vp6` | absent |
| narration | 6 | `Tutorial{1..6}.mp3` + `DialogEvent Tutorial*` in `speech.ini` | absent |
| book sounds | 4 | `audio.big` → `data/audio/sounds/ubook{open,close,page,pageb}.wav` | **`AudioEvent`s survive, waves do not** |
| textures | 17 | `apt/mainmenu.big` → `art/Textures/apt_MainMenu_*.tga` | absent |
| geometry | 25 | `apt/mainmenu.big` → `MainMenu_geometry/*.ru` | absent |
| `APT:` strings | 16 | `lang/english/lotr.csf` | absent from `data/lotr.str` |

The strings, verbatim from BFME1's CSF:

```
APT:BattleSchool          "BATTLE SCHOOL"      APT:BattleSchoolTitle     "Battle School"
APT:WorldMapTutorial      "WORLD MAP"          APT:WorldMapTitle         "World Map"
APT:Moves&AttacksTutorial "MOVES & ATTACKS"    APT:Moves&AttacksTitle    "Moves & Attacks"
APT:Bases&UnitsTutorial   "BASES & UNITS"      APT:Bases&UnitsTitle      "Bases & Units"
APT:HeroesTutorial        "HEROES"             APT:HeroesTitle           "Heroes"
APT:VeterancyTutorial     "VETERANCY"          APT:VeterancyTitle        "Veterancy"
APT:SpecialPowersTutorial "SPECIAL POWERS"     APT:SpecialPowersTitle    "Special Powers"
APT:Tutorial              "TUTORIAL"           APT:ExitTutorial          "EXIT TUTORIAL"
```

(BFME1 also ships `APT:ArmiesTutorial`, `APT:CastlesTutorial` and a misspelt
`APT:VeterencyTutorial` that the shipped movie never asks for.)

The six tutorial videos are BFME1 gameplay footage and will look wrong beside RotWK/Edain. The
plumbing is the same either way — recording replacements is an asset decision, not an engineering
one.

### The `.dat` image map

BFME1's `MainMenu.dat` uses the crop-rectangle grammar (`119=0 0 154 39`, one `.tga` per image);
RotWK's uses the atlas-page grammar (`46->1`, everything on `apt_MainMenu_1.tga`). **RotWK parses
both** — `apt/gadgettimer.big` ships a pure rect map and `apt/ingamenotificationbox.big` mixes the
two in one file. `sage_apt.imagemap` reads both as well, so BFME1's textures can be carried over
unrepacked.

## 6. The patch

Built: [`patches/experimental/battle_school.py`](../patches/experimental/battle_school.py),
`sage-patch apply battle-school`. **One five-byte `jmp` at `0x0091B540` plus a 172-byte cave. No
new FSCommand registration.**

The registration blocks in the `AptMainMenu` constructor are ~85 bytes of straight-line code with
no slack, and adding a map entry means constructing an `AsciiString`, wrapping a functor and
calling `map::insert` (`0x0092B062`) from a cave — the expensive route
[`campaign-select.md`](campaign-select.md) §7 describes and declines. It is not needed here, because §2.1's handler already accepts a `params`
string it throws away. Give it a direction:

```asm
          mov  eax, [esp+4]                  ; params
          test eax, eax   ; je enter         ; no params -> stock behaviour
          mov  dl, [eax] ; or dl, 0x20       ; ASCII-fold, and 0 stays non-'l'
          cmp  dl, 'l'   ; jne enter
                                             ; ---- exit ----
          <CreditsExit's tail, 0x0091B733..0x0091B7B0, with 0x00C7CE28>
          ret  4
enter:    mov  eax, 0xba9a56                 ; the five displaced bytes
          jmp  0x0091b545                    ; back to the call __SEH_prolog
```

`GameCode("BattleSchool", "enter")` keeps stock behaviour and so does a stock-shaped
`GameCode("BattleSchool")` with no params at all; `GameCode("BattleSchool", "leave")` leaves. The
movie's `AfterBattleSchoolVideoOut` sends the second form instead of `GameCode("TutorialExit")`.

The two words have to differ in their **first character** — `"enter"`/`"exit"` do not, which is
the one bug in this that a disassembly listing would never show, and what
`tests/sage_patch/test_battle_school.py::TestDirection` runs the emitted bytes to prove.

Decisions worth knowing:

- The exit arm is a **copy of `0x0091B733`–`0x0091B7B0`**, not a call into it — `CreditsExit` also
  tears down the credits movie player at `0x00DEBF50`, which Battle School never allocates.
- Two of the template's lines are left out: the phase reset and the `GetExtern` scratch destruct
  (§3). Entering never touches either.
- The five stock bytes at `0x0091B540` are `mov eax, 0xba9a56` (the SEH prologue's cookie load).
  Because that instruction is position-independent, the cave re-emits it and jumps to
  `0x0091B545`, so the stock path is not merely equivalent to before — it *is* before, with the
  same stack and the same `__SEH_prolog` return address. `_check_handler` refuses a build where
  the opcode is not `mov eax, imm32`.
- The one new failure mode: the stock handler never dereferences `params`, and this one reads its
  first byte. NULL is guarded, and `campaign-select` — runtime-verified — establishes that a real
  string arrives when the movie supplies one.

### The zero-patch fallback

`MainMenuToBattleSchool` is an ordinary INI block, so a mod can redefine it. Drop
`LeaveSilent = Yes` (or shorten the fade to nothing) and no exit command is needed at all — the
missing `TutorialExit` stops mattering and the engine work drops to zero. The cost is that the
shell music no longer ducks under the tutorial's narration. Worth shipping first: it makes the
feature playable while the patch is still being written, and it is the control that tells you
whether the patch is doing anything.

## 7. The `.apt` work

Built two ways round. The scoping question was whether to give the book its own movie — which
would have hung on whether a *new* movie name resolves as an import target, something no shipped
file demonstrates — or to merge it into `MainMenu` itself, which is what BFME1 does and therefore
cannot fail for a reason nobody has seen. Merging won, and the tool it needed is
[`sage_apt.merge`](../../sage_apt/merge.py) (`sage-apt import-character`).

Merging is renumbering. Characters are an array and everything names one by index; a `shape`
additionally names a `<Movie>_geometry/<id>.ru` mesh, and **that mesh's `s tc:` fills name `image`
characters back in the array** — an edge that is not in the XML at all. Counting it takes the
book's closure from 81 characters to 98, and a merge that missed it would carry 25 shapes that
sample textures the destination does not have. `merge_character` walks the closure through the
meshes, appends the subtree, and renumbers characters, geometry ids and texture ids together;
imports are matched against the destination's own by (movie, name), which is why merging BFME1's
book into Edain's `MainMenu` adds **no** imports — both already import `Pattern_shell`,
`buttonGlow`, `buttonCloud`, `buttonSuperGlow` and `BinkMovie`.

`tools/build_battle_school.py` drives the whole thing: merge, wire, and write a packable tree.
Against Edain's `MainMenu.apt` it produces

| | |
|---|---|
| characters | 94 → 187 (the book lands at 186) |
| geometry | 25 meshes, renumbered 90–114, their fills repointed |
| textures | 17, renumbered to match their new image characters |
| root frame | 17, labelled `BattleSchool`, placing the book at depth 3 as `movieContainer` |
| root functions | `ShowBattleSchoolVideo`, `HideBattleSchoolVideo`, `AfterBattleSchoolVideoOut` |
| copied callbacks | `TutortialOpenBookDone`, `TutorialCloseBookDone`, `TutorialPageFlipDone`, `TurtorialMovieDone` (EA's spelling; the book calls them by those names) |
| constant pool | 182 → 201 entries, under the 256 a one-byte operand can address |

The three `*BattleSchoolVideo` functions are written **fresh** rather than copied: BFME1's drive
four root objects (`DebugMenu`, `Image`, `ExitMenu`, `MainMenu`) that no RotWK shell has, and
ActionScript performs a call into nothing silently. The four `Tutorial*Done` callbacks are copied
verbatim, because they touch only `movieContainer` and `_root.CurrentTutorial`, which the book
creates itself.

Depth 3 is not arbitrary: it is the slot RotWK's own `MainMenu` reserves for a full-screen movie
(its credits frame places `ShowCreditsMovie` there, and its `_reshow` frame removes it), so
`AfterBattleSchoolVideoOut` returns through `_reshow` and the shell tidies up on its own.

**What is deliberately not built is the button.** Nothing calls `ShowBattleSchoolVideo()` yet.
Where that call comes from is the mod's own menu layout, and a tool guessing at it is the one part
of this that could quietly wreck a shell. Its caption is `$BattleSchool`, and the frame that places
it can read `_root.getExtern("BlinkBattleSchoolOff")` for BFME1's blink-until-seen behaviour — the
engine still answers that (§2.2).

## 8. Status: in the game, and half working

**No longer static.** The patch is applied to the Edain mod's `tools/game.dat` (42 patches in that
binary) and the merged movie is installed in the Edain tree and packed into `__edain_apt.big`. The
Battle School opens in the running game. What follows separates what has been *seen working* from
what has not, because the two were repeatedly conflated while chasing this.

### 8.1 Confirmed in the running game

| part | state |
|---|---|
| the `BattleSchool` FSCommand, both directions | works — one command, direction taken from the first character of its parameter (`enter` / `leave`) |
| the book open animation, page flips, close | plays |
| the six topic buttons and the back button | present, laid out, clickable |
| the tutorial videos, with audio and subtitles | play, through the engine's `BinkMovie` gadget |
| leaving the screen and returning to the menu | works; no report of the permanent silence §3 predicted |

The temporary hook is **still live**: the Create-a-Hero button calls the Battle School. That is a
test harness, not a design decision, and needs replacing with a real entry point.

### 8.2 The unsolved problem: merged *shape* characters never draw

Everything the Battle School is missing visually — the parchment page behind the videos, and the
seven button plates — is one problem. A shape character copied in from BFME1 does not render, while
every other kind of copied character does.

Bisected, and each of these was actually built and looked at:

- merged **sprites**, **edittexts** and engine gadgets (`BinkMovie`, `RenderImage`) sitting on
  merged characters all render correctly — so the merge itself, the character table and the
  frame/depth machinery are sound
- the copied meshes **are loaded**: ids 207–224 were found in the live process's memory
- varying the geometry id, the mesh contents, the character ordinal, which archive it shipped in,
  and the path separator inside the mesh changed nothing
- the separator theory was wrong on its own evidence: `FactionFrame` draws 23 shapes from
  backslash-only meshes

The one experiment that moved: **Edain's own shape 89**, repointed at our mesh 207 and placed on
the book, **did draw** — a grey rectangle of the right size. So an *Edain-owned* shape renders a
*merged* mesh. That narrows the fault to the shape character itself, not the geometry.

It drew grey, i.e. with no texture resolved. The obvious next suspect was that merged **image**
characters are second-class the same way shapes are, so the mesh was pointed at Edain's own image
42 — still grey. **That test was ambiguous and should not be trusted**: the fill's UV matrix was
authored for the 1024×1024 parchment, so against a different atlas it could equally well have
sampled an empty region. It distinguishes nothing.

What *is* settled: **the textures are not missing.** All 17 (`apt_MainMenu_96` … `_139`, including
the parchment `_128`, 4,194,322 bytes) are present as loose sources in both `_mod` texture folders
and packed into `__edain_textures1.big` / `_2.big`, in the mod's `final_files` and in the live
`C:/RotWK` install — which hold byte-identical archives. Every one is referenced by a live mesh,
checked by following the `shape → geometry → s tc:…:<image>:` edge rather than the placeobject
graph, which does not reach images at all and makes all 17 look like orphans.

Verify that claim with a **control** in the same scan (assert a file you know is there, such as
`apt_MainMenu_1.tga`, and hash the bytes you found). Repeated `InDiskArchive` opens in one process
returned a short file list for an archive that demonstrably contains the entries, which produced a
confident and wrong "the live install has none of them" mid-session.

### 8.3 Two other open bugs

- **The book closes itself** a few seconds after reaching the topic list. Frame 52 already carries a
  `stop`, and only frame 53 (`_closeBook`) removes the page depth, so something is actively calling
  the close path rather than the clip running on. Not traced.
- **A topic video plays only once**; that button is then unresponsive. Two fixes are installed and
  **neither is yet tested**. The first copies BFME1's toggle release sequence (a guard,
  `if (_root.CurrentTutorial != undefined) CurrentTutorial.Hide()`, plus a `nav.gotoAndPlay(...)`
  call) — it did not help, which is itself informative.

  The movie side is provably not at fault. The topic clip's own state machine is complete: `Show()`
  jumps to frame 1 when parked and to frame 40 with `restartMovie = true` when mid-play; frame 53
  reads that flag and loops back to frame 1; `_CallOnLastFrame = "TurtorialMovieDone"` on the
  `BinkMovie` gadget is wired to `_root.CurrentTutorial.Hide()`, and RotWK still dispatches that key
  (stored at gadget `+0x26C` by `0x00975358`, read and invoked by the thunk at `0x00975181`).
  Two runtime observations close it off: the video **clears itself** when it ends, so the callback
  really does fire and the clip really does reach frame 51 (which removes the Bink window) and park
  at frame 0; and an **unclicked button still works** afterwards, so nothing is covering the layer.
  From frame 0 a second click takes the plain `gotoframe 1; play` path, which cannot fail.

  So the fault is the button, not the movie. The seven buttons are `MenuExport::GenericButton_Short`
  clips (import slot 81) driven by the engine's `buttonName` gadget — the identical construction to
  Edain's own `QuitMainMenu` and `BattleSchool` (slot 2, `GenericButton_Med`). The difference is
  lifecycle: Edain's buttons are cycled through `_hidden` / `_reveal` on every menu transition
  (`RevealAllButtons` does `gotoAndPlay("_reveal")` on them), while these are placed once at root
  frame 17 and never cycled, so whatever state a click leaves a button in is permanent. That
  predicts exactly the observed shape — one-shot, per-button, others unaffected.

  The second fix follows from that: `TurtorialMovieDone` now also cycles all six topic buttons
  through `_reveal`. The reset has to live there rather than in the button handler, because a stuck
  button cannot reset itself on a click it never receives.

### 8.4 Where to resume

1. **Run the split-mesh diagnostic.** It is the cheapest decisive test and it was built but never
   looked at — the answer arrived as "put the background back" first. Give one mesh two fills: a
   **solid** colour on the left half, the **textured** parchment on the right, and put it on a shape
   that is known to draw (Edain's 89). Solid-only means textures are the remaining problem; both
   means it is solved; neither means the donor is not drawing that mesh at all.
2. **If solid draws and textured does not**, the parchment needs an Edain-owned image id rather than
   a merged one — or take the proven route and play a one-frame `.vp6` through the `BinkMovie`
   gadget, which already works on this screen.
3. **`SetBackground` cannot help.** `0x00815507` accepts only `fadein`, `fadeout`, `off` and `on` —
   there is no image-name form, so the parchment can never come from that call.
4. Then the self-close (§8.3), then confirm the replay fix, then replace the Create-a-Hero hook.

### 8.5 The state the tree was left in

The background experiments are **reverted**: Edain's shape 89 is back on its own mesh 89 (the
pristine tree confirms the identity mapping `shape N → mesh N` for every Edain shape), its test
placement on book frame 22 is gone — that depth belongs to the topic clip anyway — and the
`SetBackground("fadeout")` / `("fadein")` calls are removed from `ShowBattleSchoolVideo` and
`AfterBattleSchoolVideoOut`, so the mod's own main-menu background shows behind the book again.
`207.ru` is back to its authored single parchment fill. All 13 movies round-trip clean.

Assets in the Edain tree, for a future cleanup or repack:

| what | where | note |
|---|---|---|
| the movie | `_mod/apt/MainMenu.{apt,const,dat,xml}` | the `.xml` is the same `<aptdata>` format and is kept in sync |
| the meshes | `_mod/apt/MainMenu_geometry/200–224.ru` | `200.ru` is a transparent zero-area stub whose shape (95) is placed by nothing; it is kept only because geometry looks eagerly loaded and a dangling reference is not worth the risk |
| the textures | `_mod/art/Textures/` and `_mod/art/compiledtextures/ap/` | 17 files, `apt_MainMenu_96` … `_139`. Every apt texture lives in **both** folders byte-identically — `art/Textures` is a strict subset of `compiledtextures/ap` — and they pack into `__edain_textures1.big` and `_2.big` respectively |
| the videos and audio | `data/movies/*.vp6`, `_english/data/audio/{sounds,speech}` | |
| the strings | `data/ini/speech.ini` (6 `DialogEvent`s), `Lotr.csv` (16 rows) | |

## Address index

### RotWK `game.dat` 2.01.2614.37001

| symbol | address |
|---|---|
| `"AptMainMenu::BattleSchool"` | `0x00C7D0A8` |
| its registration block | `0x0091D052` |
| `BATTLE_SCHOOL_HANDLER` | `0x0091B540` |
| `"BlinkBattleSchoolOff"` / its registration (index 3) | `0x00C7CFF4` / `0x0091D2AA` |
| the shared GetExtern getter / its case 3 | `0x0091BB6B` / `0x0091BB91` |
| `"MainMenuToBattleSchool"` | `0x00C7CE28` |
| `"FlashTutorial"` / `"TimesInGame"` | `0x00C7CE18` / `0x00C7CFB0` |
| ctor: seed the blink flag / clear it after 5 launches | `0x0091D446` / `0x0091D477` |
| `AptMainMenu::CreditsExit` — the exit template | `0x0091B6FD` |
| its audio + transition tail, which the cave copies | `0x0091B733`–`0x0091B7B0` |
| `"MainMenuToCreditsScreen"` | `0x00C7CE40` |
| `TheWindowTransitionsHandler` | `0x00DE3654` |
| its `setGroup` / `reverse` (one by-value `AsciiString`, `ret 4`, callee destroys it) | `0x005DB9A6` / `0x005DBA99` |
| the shell object (`+0x5D` = movie owns the screen, `+0x68` = its music handle) | `0x00DE7890` |
| `Shell::isShellMusicPlaying` / `Shell::playShellMusic` | `0x0075D9CA` / `0x0075DF26` |
| `TheAudio` / its stop-channels vtable slot | `0x00DE42FC` / `+0x8C` |
| stop-audio thunk the enter handler uses | `0x0075D9B1` |
| `TheGameEngine` / `setFramesPerSecondLimit` vtable slot | `0x00DE4324` / `+0x48` |
| `SOUNDFADE` field table (`LeaveSilent` row 3, offset `0x1C`) | `0x00C2CAB0` |
| FSCommand lookup / its miss path | `0x00623BF1` / `0x00623C2E` → `0x00623C40` |
| `AptMainMenu` callback map / GetExtern map / `map::insert` | `this+0x21C` / `this+0x228` / `0x0092B062` |
| the blink flag member | `this+0x281` |
| `OptionPreferences` ctor / get / set / write | `0x006E56F3` / `0x007B2917` / `0x007B2679` / `0x007B274C` |

### BFME1 `lotrbfme.exe`, for the comparison

| symbol | address |
|---|---|
| `"AptMainMenu::BattleSchool"` / registration / handler | `0x01106534` / `0x0091FC94` / `0x0091DD10` |
| `"AptMainMenu::TutorialExit"` / registration / handler | `0x01106514` / `0x0091FCFD` / `0x0091DE00` |
| `"MainMenuToBattleSchool"` / `"FlashTutorial"` | `0x0110633C` / `0x0110632C` |
| the shell object (`+0x59`) | `0x012F4B58` |
| `TheWindowTransitionsHandler` / `setGroup` / `reverse` | `0x012F3330` / `0x00445C28` / `0x0041422C` |
| the blink flag member | `this+0x25D` |
