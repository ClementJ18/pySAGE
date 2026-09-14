# WorldBuilder's script action and condition templates

How the script editor's "New action" / "New condition" catalogue is built, and how
`tools/extract_script_templates.py` reads it out of the editor. Recovered statically from the stock
RotWK 2.01 `Worldbuilder.exe` (sha1 `5baab1c3`, ImageBase `0x400000`) with `pefile` + `capstone`,
cross-checked against `game.dat` 2.01.2614.37001 and against real maps. Nothing here has been run
in the editor; the map data is the runtime evidence.

**This targets `Worldbuilder.exe`.** Its addresses are the `WORLDBUILDER_SCRIPT_*` and
`WORLDBUILDER_ASCIISTRING_*` constants in `sage_patch/addresses.py`.

## 1. The table

One object owns every template as a fixed array of `0x80`-byte records starting at `this+0x20`.
Record `N` sits at `this + 0x20 + N*0x80`. Records 0-599 are actions (action id = `N`, matching the
600-case `ScriptActions::executeAction` switch in `game.dat`); records from 600 are conditions
(condition id = `N - 600`). A map's `content_type` is that id, in the action or condition space.

| offset | field | type |
|---|---|---|
| `+0x00` | flags | int, see §4 |
| `+0x04` | UI name: the menu path, `/`-separated, ending with the label | AsciiString |
| `+0x0C` | internal name, the name a map stores (`MOVE_NAMED_UNIT_TO`) | AsciiString |
| `+0x14` | number of sentence fragments | int |
| `+0x18` ... | sentence fragments, one AsciiString each | AsciiString[] |
| `+0x48` | number of parameters | int |
| `+0x4C` ... | parameter types, numbered as `sage_map`'s `ScriptArgumentType` | int[] |

A script line reads fragment 0, parameter 0, fragment 1, parameter 1, and so on. Most templates
have one fragment more than parameters (567), some the same number (223), two have two more.

## 2. The two builders

| function | address | fills |
|---|---|---|
| `WORLDBUILDER_SCRIPT_ACTION_TEMPLATES_INIT` | `0x00FE0AF0` - `0x00FF3376` | actions, plus conditions 115-116 |
| `WORLDBUILDER_SCRIPT_CONDITION_TEMPLATES_INIT` | `0x00FD8100` - `0x00FE0AE0` | the other conditions |

Both are unoptimised debug-build code that takes the owner in `ecx`, keeps it in a stack slot,
and loads every value from an immediate. The action builder:

```asm
00fe1fbb  mov ecx, [ebp-8]           ; this
00fe1fbe  add ecx, 0x1320            ; record 38
00fe1fc4  mov [ebp-4], ecx
00fe1fc7  push 0x1f0c4a8             ; "MOVE_NAMED_UNIT_TO"
00fe1fcc  mov ecx, [ebp-4]
00fe1fcf  add ecx, 0xc               ; internal name
00fe1fd2  call 0x405191              ; AsciiString set (const char *)
...
00fe1fea  mov dword ptr [edx+0x48], 2    ; two parameters
00fe1ff4  mov dword ptr [eax+0x4c], 0xe  ; UNIT_NAME
00fe1ffe  mov dword ptr [ecx+0x50], 7    ; WAYPOINT_NAME
```

The condition builder keeps a field pointer in a further stack slot and inlines the setter as
`strlen` (`0x016C368C`) followed by `AsciiString set (const char *, length)` (`0x00710DC0`); it
also calls the `(const char *)` thunk `0x00402513` once. Flags come either from the helper
`0x00FF3380` (`push b; push a; call` returning `a | b`) or inline (`mov eax, 2; or eax, 1`).

So the extractor evaluates each function symbolically, from its entry to its only `ret`: registers
and `ebp` slots hold either "`this` + offset" or a constant, and every write into `this` is
recorded, last write winning. Any instruction outside that model stops the extraction instead of
being skipped, so a different build fails loudly.

## 3. What the tables hold

| | count | ids |
|---|---|---|
| actions | 596 | 0-599; 227, 343, 382 and 480 are never filled |
| conditions | 196 | 0-202; 59, 60, 67, 68, 72, 73 and 122 are never filled |

The editor's own source has slips, kept in the catalogue as written:

- **Written twice.** `VICTORY` and `DEFEAT` are filled twice; the second write replaces
  `User_/ Announce win` with `Multiplayer_/ Announce victory.` and changes the sentence.
  `CAMERA_FADE_MULTIPLY` is filled twice with the same values. `SET_BASE_CONSTRUCTION_SPEED`
  writes its second fragment twice and never writes the third.
- **Declared but never filled** (recorded as `null`): parameter 0 of `CAMERA_BW_MODE_END`,
  `CAMERA_MOTION_BLUR_FOLLOW` and `SELECT_BUILDER_BUTTON_FLASH` (the last two write parameter 1
  instead); fragments in eight templates, including `DIM_WORLD_LIGHTS` and
  `BUILD_BUILDING_ON_FOUNDATION`. Maps store `SELECT_BUILDER_BUTTON_FLASH`'s first argument as
  type 0 (INTEGER).
- **One name, two ids.** Actions 552 and 553 are both `MAP_REVEAL_IN_TRIGGER`; 553's sentence says
  "shrouded". `game.dat` builds the same. Maps in the corpus use only 552. Whether the engine
  resolves a stored action by id or by name, which would decide whether 553 is reachable, is not
  established.

## 4. Open questions

- **Flags.** Only 27 records set `+0x00`. Value 3: the core scripting set (`SET_FLAG`,
  `SET_COUNTER`, `NO_OP`, `ENABLE_SCRIPT`, `CALL_SUBROUTINE`, the counter maths, the debug strings,
  and the `COUNTER`, `FLAG`, `CONDITION_TRUE`, `CONDITION_FALSE`, `COUNTER_COUNTER` conditions).
  Value 2: the six `LIVING_WORLD_*` templates. That reads as "offered in regular maps" (bit 0) and
  "offered in Living World script maps" (bit 1), with 0 meaning regular maps only, but where the
  editor tests the bits has not been traced.
- **Unlabelled parameter types.** `Parameter::getUiText` (switch at `0x00AAE408`, types 0-77)
  sends 29, 65 and 69-75 to its "Unknown parameter type." default, and prints 53 as `???`. They
  keep numbered placeholders in `sage_map`'s `ScriptArgumentType`. 29 is used only by
  `PALANTIR_EVENT`; 66 and 69-75 only by threat-finder and Living World templates, and no corpus
  map uses them. From the sentences, 69 and 70 name armies, 71 and 72 regions, 73 and 74 players
  and 75 a player template: a reading of the text, not a recovered name.

## 5. The parameter type numbers

The label `getUiText` prints for each type, together with the sentences of the templates that use
it, names every labelled type. It fixes `ScriptArgumentType` from 29 to 53: BFME2 numbers a type
at 29 that Generals does not have, so `RADAR_EVENT_TYPE` is 30, `SPECIAL_POWER_NAME` 31,
`SCIENCE_NAME` 32, `UPGRADE_NAME` 33, and so on up to `SCIENCE_AVAILABILITY_NAME` 50, then
`CAMERA_NAME` 51 (`Camera '%s'`, used by `MOVE_CAMERA_TO`) and `PERCENTAGE` 52 (`%.2f%%`). Above
that, `CAMERA_ANIMATION_NAME` 64, `THREAT_FINDER_NAME` 67 and `STANCE` 68 carry their labels.

The map data agrees: arguments stored as 32 are `SCIENCE_*` names, 31 special abilities, 33
`Upgrade_*`, 39 `Command_*`, 47 faction names and 51 named cameras.

Several enum types print a value name from a table inside `getUiText`: Comparison (6), AI mood
(20), radar event (30) and math operator (57) through a nested jump table; KindOf (27),
buildability (36), surface (37), camera shake (38), emotion (63) and stance (68) by indexing a
string array; Boolean (8) and near/far (56) by comparison.

## 6. Validation

- **Maps.** All 464 distinct `(kind, content_type)` pairs in 476 maps (the `sage_map` fixtures and
  the Edain `_mod\maps` tree) resolve to a template whose internal name matches the name the map
  stores, and every argument's stored type equals the template's parameter type wherever the
  template fills it. `tests/sage_worldbuilder/test_templates.py` re-checks the fixtures.
- **`game.dat`.** Its builder (`0x007D0000` - `0x007E8000`, optimised, with register-held
  constants) stores internal names at the same record offsets; all 766 it sets directly agree with
  the extraction. The other 26 go through register paths that scan does not follow.
- **Regeneration.** `python tools/extract_script_templates.py --check` fails when the shipped JSON
  no longer matches the exe; the `full` test runs the same comparison.
