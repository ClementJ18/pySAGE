# Why a War of the Ring save fails to complete

Engine build `2.01.2614.37001`, read with `explore.py`, and checked against the two broken Edain
Angmar saves in `tests/sage_save/fixtures/edain/`. §1–§5 are the engine as read from the
disassembly quoted beside them, and each step is matched against bytes in a real save. §6 is the
fix, as two patches whose caves were executed in Unicorn over the engine's own code; none of it
has been run in the game yet. §8 is how to confirm it there.

**The finding.** A War of the Ring player carries a `LivingWorldScoreKeeper`: whole-campaign
counts of the object types the player built, lost and destroyed, keyed by `ThingTemplate *`. At
the end of every battle the battle's own score is merged into it **by pointer**. A template that
exists only in that battle map's `map.ini` does not outlive the map, but its pointer stays in the
campaign keeper. Every later save writes each key's name through that pointer. The read faults,
or returns garbage, inside `CHUNK_LivingWorldLogic`, the first chunk of every War of the Ring
save. The engine swallows the fault and leaves the half-written file on disk:

- **`angmar 7`** is that file. It is 6.5 KB long and stops inside the score keeper's objects-lost
  map, before the map's first key.
- **`angmar 6`** completed, but its objects-lost map has two keys with **empty names**. Loading
  resolves every key by name and throws on the first one that is not a template, so the game
  reports the save corrupt.

Campaigns whose battle maps define objects in `map.ini`, as Rise of Angmar's do, hit this after
the first battle in which the player builds, loses or kills one of those objects. From then on
every save of the campaign carries the bad key.

## 1. How a save is written

`GameState::saveGame` (`0x006DE498`, `__thiscall` on `TheGameState` `0x00DE4AD4`, `ret 0x14`)
serves every save: the save menu reaches it through `0x006DEF4E` (called at `0x00817F64`), the
autosave through `0x006DE8F1`, and the message handler at `0x006297DF`. In order, it:

1. **Classifies the save** with `getSaveFileType` (`0x006DCFDF`). On the War of the Ring map
   (`LivingWorldLogic` `+0xB4` and `+0xB5` both set) it answers `4`, or `6` in a multiplayer game
   (`TheGameLogic+0x114` non-zero). `0x006DCDE9` maps the type to the extension: 3 and 4 to
   `.BfME2WotR`, 6 to `.BfME2WotRMP`, 2 to `.BfME2Skirmish`, everything else to
   `.BfME2Campaign`. A battle fails the living-world test and saves through the
   `TheGameLogic+0x114 == 0` branch as type 3. That is inferred from the extension table and
   from `ang 5` embedding its battle map (§1.3); it has not been watched live.
2. **Opens the destination file directly** (`push 0x4A` at `0x006DE5A9`, then `0x00A1420C`). There is
   no temporary file and no rename, so saving over an existing slot destroys the old save before
   the new one has been written.
3. **Writes the 16-byte header** with `XferSave::open` (`0x00A20DD0`): `ALAE`, `2STR`, `1`, and a
   flag byte from `0x00DE87BB`. `saveGame` ignores `open`'s return value.
4. **Runs `xferSaveData`** (`0x006DDF2F`) over snapshot list 0. For each registered snapshot it
   writes the name, `beginBlock`, `xferSnapshot` and `endBlock`, then `SG_EOF`:

   ```asm
   006ddf6d  lea  eax, [edi + 0xc]        ; the registered name
   006ddf81  call [eax + 0x6c]            ; xferAsciiString
   006ddf91  call [eax + 0x14]            ; beginBlock: name, "KOLB", a zero end-offset
   006ddf9b  call [eax + 0x30]            ; xferSnapshot -> the subsystem's xfer
   006ddfa2  call [eax + 0x18]            ; endBlock: seek back, write the end-offset
   006ddfa9  push dword ptr [0xda2140]    ; "SG_EOF"
   ```

   `beginBlock` (`0x00A2111A`) writes the zero placeholder; `endBlock` (`0x00A206EF`) seeks back
   and patches it. **A chunk's end offset is therefore non-zero only once its subsystem has
   serialized in full.** Both functions throw on a short write or failed seek (`0x00A21189`,
   `0x00A20780`).
5. **Closes the file**, and shows `GUI:GameSaveComplete` when the caller asked for a message.

The list-0 order, from the registrations at `0x006DF73E`, is the order every War of the Ring
save in the corpus has on disk. `LivingWorldLogic` comes first, then `Audio`, `GameState`,
`Campaign`, `Palantir`, `GameStateMap`, `TerrainLogic`, `TeamFactory`, `Players`, `GameLogic`,
`Radar`, `ScriptEngine`, and the rest down to `FireLogicSystem`.

### 1.1 Failure is silent and leaves the file

The function's exception table (`FuncInfo` at `0x00D390D4`) has two try blocks. Both are
`catch (...)`:

| try state | covers | handler |
|---|---|---|
| 6 | `XferSave::open` | `0x006DE8C6` |
| 10 | `xferSaveData` | `0x006DE7DD` |

The handler at `0x006DE7DD` builds `GUI:ErrorSavingGame` plus the file name, closes the
`XferSave` (`0x00A205AD`) and the file (`vtable+8`), and returns `3`. **It does not delete the
file.**

The image is linked with **VC++ 7.10** (PE linker version `7.10`). In that compiler `catch (...)`
also catches structured exceptions, so an **access violation** inside any subsystem's `xfer` is
handled the same way. The game neither crashes nor writes a dump; the save simply stops. The
`SetUnhandledExceptionFilter` crash handler
([`crash-dump-quality.md`](../crash-dump-quality.md)) never sees these faults, because a frame
handler claims them first.

The result is a recognisable file shape: the chunks that finished, then a chunk whose end offset
is still `0`, cut off where the fault happened. `python -m sage_save diagnose` names that chunk
(`sage_save.find_interrupted_write`).

### 1.2 What is *not* the problem

- **Long strings.** `xferAsciiString` (`0x00A1FB84`) writes a length of 255 or more as `0xFF` plus
  a `u32` (`0x00A1FBAD`), so it never throws on length. (Generals' `XferSave` did.)
- **The map file on the strategic map.** `GameStateMap::xfer` (`0x0082B8E4`) writes an empty map
  name and embeds nothing when `LivingWorldLogic` is active (`0x0082B941` → `0x0082B967`). Every
  strategic-map save in the corpus shows that empty name.
- **`map.ini` itself.** A battle save embeds the `.map` (`0x0082B612`) and a `.wak` companion,
  but never `map.ini`. On load, `map.ini` is re-read from the directory of the pristine map path
  `GameState+0x2C` (`0x006271B5`).

### 1.3 Battle and strategic-map saves share the score keeper

`ang 5` (a battle) and `angmar 6` (the strategic map) both start with `CHUNK_LivingWorldLogic`.
The battle save embeds `maps\map kampa angmar 04\map kampa angmar 04.map` in `GameStateMap`; the
strategic-map save does not. Because `LivingWorldLogic` comes first in list 0, the score keeper
below is written into both kinds of save.

## 2. Where the two Angmar saves stop

| save | what is on disk |
|---|---|
| `angmar 7` (6,516 bytes) | header, then `CHUNK_LivingWorldLogic` with end offset **0**, and 6,469 payload bytes. The last bytes are `…0f AngmarWolfRider dc000000 0d WOTRKeepAlive 06000000 01 2a 00`: one count map ends, and the next map's header (`01` version, `0x2A` = 42 entries) is followed by nothing. |
| `angmar 6` (44,529 bytes) | all 32 chunks and `SG_EOF`. The same pair of maps at the same place: the first ends with `WOTRKeepAlive`, the second (`01 2b 00`, 43 entries) begins `00 01000000`, `00 02000000`: **two entries whose names are empty**, then `AngmarBarracks`, `AngmarDen`, … |

None of the five valid War of the Ring saves in `tests/sage_save/fixtures/wotr/` has an
empty-name entry in these maps.

## 3. The map is the score keeper's objects-lost map

The byte format, version `01`, a `u16` count, then (`AsciiString`, `Int`) pairs, is
`xferObjectCountMap` (`0x009617A0`):

```asm
009617c4  call 0x404f15                ; xferVersion(1)
009617da  call [eax + 0x80]            ; xferUnsignedShort(count)
009617fc  mov  eax, [edi + 0x10]       ; the node's key: const ThingTemplate *
009617ff  add  eax, 0x64               ; key->m_name
00961806  call 0x436030                ; AsciiString copy - no check that the key is alive
00961813  call [eax + 0x6c]            ; xferAsciiString
00961824  call [eax + 0x7c]            ; xferInt(count)
```

When loading it resolves each name, and **throws when the name is not a template**:

```asm
0096186b  call 0x6d1305                ; ThingFactory::findTemplate(name)
00961870  test eax, eax
00961875  je   0x96189b                ; -> XferException(5), thrown at 0x009618B4
```

Of the ten callers, four are in one function, `0x008F3A89`. It is slot 7 of the vtable at
`0x00C79740`, which sits directly before the string `LivingWorldScoreKeeper` (`0x00C79760`). This
is `LivingWorldScoreKeeper::xfer`, version 7. After its scalar fields it writes:

```asm
008f3c61  call [eax + 0x78]            ; xferUnsignedInt(+0x74)
008f3c6c  call 0x9617a0                ; map at +0xB4
008f3c79  call 0x9617a0                ; map at +0xC0
008f3c86  call 0x9617a0                ; map at +0xCC
```

`angmar 6` has exactly that run at payload offset `0x17E9`: `28 e1 00 00`, then maps of 34, 43
and 69 entries. The broken map is the second one, **`+0xC0`**. §4 shows it is fed from the
battle score keeper's objects-lost map, which is why its named entries are the player's own
buildings and units.

## 4. How the keys get there

`Player` `0x006AA3CC` runs once per player when a battle ends (latched by `+0x35F`). It finds the
living-world player (`0x006B5DE0`) and calls
`LivingWorldScoreKeeper::mergeBattle(&player->m_scoreKeeper)` (`0x008F33A0`). The keeper sits at
living-world player `+0x348`; the battle `ScoreKeeper` is `Player+0x3DC`:

```asm
008f33b3  lea  eax, [edi + 0x1f0]      ; battle: objects built
008f33ba  lea  eax, [esi + 0xb4]       ; campaign: built
008f33c1  call 0x8f3308
008f33c6  lea  eax, [edi + 0x2ec]      ; battle: objects lost
008f33cd  lea  eax, [esi + 0xc0]       ; campaign: lost
008f33d4  call 0x8f3308
008f33e7  call 0x79e8bf                ; battle: objects destroyed, per victim (x20)
008f33ee  call 0x8f3308                ;   -> campaign: destroyed (+0xCC)
```

`ScoreKeeper::addObjectLost` (`0x0079F486`) keys the battle map by the object's template pointer
(`mov esi, [eax+4]` at `0x0079F538`, inserted at `0x0079F566`).

The per-map merge, `0x008F3308`, shows the engine already knows these pointers are
map-scoped:

```asm
008f3328  mov  edi, [esi + 0x10]       ; key: the battle's ThingTemplate *
008f3337  lea  eax, [edi + 0x64]
008f333e  call 0x436030                ; its name
008f3343  cmp  byte ptr [edi + 8], 0   ; Overridable::m_isOverride
008f3347  je   0x8f335a                ; not an override: keep the pointer as it is
008f3353  call 0x6d1305                ; an override: findTemplate(name) instead
```

`findTemplate` (`0x006D1305`) returns the factory's hash entry for the name.
`getFinalOverride` (`0x00688D3C`) walks `+0x4` from that entry. So for a `map.ini` **override**
of an object the global INI already defines, the merge stores the global template, which
survives the map. For an `Object` block that exists **only** in `map.ini`, the hash entry is that
map-only template itself. The merge stores it either way, with or without the override flag.

## 5. Why a stored key goes bad

The map's `map.ini` templates are deleted when the map ends. `ThingFactory::reset`
(`0x006D120A`) walks the factory's template list (head at `factory+0xC`, next at
`template+0x494`) and hands each template to `Overridable::deleteOverrides` (`0x005E2E2E`):

```asm
005e2e31  cmp  byte ptr [esi + 8], 0   ; m_isOverride - set on everything a map.ini pass creates
005e2e35  je   0x5e2e48                ; not one: recurse into the override chain at +4
005e2e3b  call dword ptr [eax]         ; one: the virtual destructor
005e2e3e  call 0x42f6a0                ; free it
005e2e44  xor  eax, eax                ; and answer NULL
```

`reset` erases a template answered NULL from the name hash (`0x006D12BA`), and moves the list
head past it when it is the head. A `map.ini` pass adds its templates at the head
(`0x006D115B`, `0x006D11AD`), so they are deleted from the front of the list and the list stays
whole. A template that exists **only** in `map.ini` is therefore freed when the battle map ends,
and the campaign keeper's pointer to it dangles. Every later save reads its name through freed
memory (`0x009617FF`):

- If the memory has been reused, the `AsciiString` copy faults. `catch (...)` takes it, and the
  file ends inside `CHUNK_LivingWorldLogic`, as in `angmar 7`.
- If the memory reads as a null string, the save completes with an empty name, as in `angmar 6`.
  Loading it then throws at `0x0096189B`.
- If a later `map.ini` template reuses the address, the save writes that template's name. It still
  cannot load: a save starts with `CHUNK_LivingWorldLogic`, before any battle map or its
  `map.ini` is loaded, so `findTemplate` misses and the load throws at `0x0096189B`.

This settles, for `ThingTemplate`, the open question in
[`map-transition.md`](../map-transition.md) of whether `map.ini` overrides accumulate: the
factory's `reset` removes them.

**What makes it intermittent.** A save breaks only after a battle in which a player built, lost
or destroyed an object type that exists only in that map's `map.ini`. From then on every save of
the campaign carries the key, battle saves included, because they write `LivingWorldLogic`
first too. The `+0xC0` objects-lost map is the most exposed, because it takes the map's
pre-placed units: story units and garrisons handed to the player and then killed. The player
never builds those, so they are absent from the objects-built map.

## 6. Fixes

**Content.** Define every object a player can build, lose or destroy in a War of the Ring battle in
the mod's global INI, and use a battle map's `map.ini` only to *override* existing objects. No
engine change is needed, but campaigns whose saves already carry a bad key are not repaired.

**Engine.** Two patches, independent of each other and of the content fix:

| patch | what it changes |
|---|---|
| [`score-keeper-dangling-keys`](../../patches/score_keeper_dangling_keys.py) | Skips count-map entries that fail, on every path through them. **Merge** (`0x008F335C`): a key that resolves to NULL is not merged. **Save** (`0x009617CC`, `0x009617FC`): the count and the entries written cover only keys that are live templates, found by walking the factory's list and each template's override chain and comparing pointers, so a dead key is never dereferenced. **Load** (`0x0096189B`): an entry whose name is not a template is read and dropped instead of throwing. |
| [`save-temp-file`](../../patches/save_temp_file.py) | `saveGame` opens `<path>.tmp` (`0x006DE5AC`). After the file is closed on success, `MoveFileExW(tmp, path, REPLACE_EXISTING \| WRITE_THROUGH)` replaces the real save (`0x006DE76A`). Both catch handlers delete the temporary file instead (`0x006DE856`, `0x006DE8C6`). `MoveFileExW` is resolved once through `GetModuleHandleA` and `GetProcAddress`, since the engine does not import it. |

With both applied, `angmar 7` cannot happen and `angmar 6` loads. Live entries are written and
read exactly as stock: `test_score_keeper_dangling_keys_emulated.py` runs the engine's own
`xferObjectCountMap` and merge over the real `game.dat`, stock and patched, and asserts the same
output for a map with nothing dead in it. The trade-offs:

- **Map-only objects stop counting** in the campaign statistics once their map ends. They could
  not be saved anyway.
- **The live check is a linear walk**, templates times keys, on every count map a save writes:
  a few million pointer compares for a full Edain save, small next to the save itself. It runs
  only where the stock code would write the map; an `Xfer` whose slot `+0xC` answers true leaves
  the function before either hook (`0x009617B5`).
- **A rename that fails** (another program holding the save open) leaves the complete save in
  `<path>.tmp` and the previous one in place. The game still reports success. The `.tmp` suffix
  follows the engine's extension, so the save menu does not list the file.
- **A path of 1,019 or more characters** is saved directly, as stock: the temporary path buffer
  holds 1,024 wide characters.

## 7. Reading a broken save

```sh
python -m sage_save diagnose "angmar 7.BfME2WotR"
#   FATAL   container did not parse: chunk 'CHUNK_LivingWorldLogic' at 0x10 has an out-of-range end offset 0x0
#   FATAL   [LivingWorldLogic] the save stops 6469 byte(s) into this chunk, whose end offset was never written: ...
```

A save that stops inside `CHUNK_LivingWorldLogic` points at the score keeper. One that stops
elsewhere names a different subsystem's `xfer` as the one that faulted. A completed save with an
empty name in one of these maps (the `angmar 6` shape) is not yet flagged by the tooling. Under
`save-temp-file` no partial file survives, so a failed save leaves nothing to diagnose; read the
`.tmp` with a breakpoint on `0x006DE856` instead.

## 8. Confirming it live

1. **The key before the save.** On the strategic map after the battle, read the living-world
   player's keeper at `+0x348`, then the `std::map` header at `+0xC0`. For each node, read the
   key at `+0x10`, its `[+0x8]` override byte and its `AsciiString` at `+0x64` (characters at
   `+8`). A map-only key reads as garbage, or as a name `findTemplate` does not know.
2. **The fault.** Break on `0x006DE7DD` (the save's `catch`) and save. A first-chance access
   violation just before it, with EIP inside `0x00436030` called from `0x00961806`, is the
   dangling key.
3. **A clean repro.** Write a War of the Ring battle map whose `map.ini` defines a new `Object`
   given to the player at start. Let it die, finish the battle and save on the strategic map.
   Repeat with the object moved to the global INI; the save should then complete and load.
4. **The patches.** Repeat step 3 with `score-keeper-dangling-keys` applied: the save completes,
   loads, and `sage_save` shows the objects-lost map without the map-only object. Load
   `angmar 6.BfME2WotR` with it applied. With `save-temp-file` applied, break on `0x006DE7DD`
   during a stock-binary failure and check that `<path>.tmp` is gone and the previous save is
   unchanged afterwards; on a clean save, check that no `.tmp` remains.
