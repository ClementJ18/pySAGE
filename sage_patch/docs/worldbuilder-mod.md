# `-mod` for Worldbuilder

Scoping for a `worldbuilder-mod` patch: teach `Worldbuilder.exe` the `-mod` switch that
`game.dat` already has, so a mod's loose files can be loaded into the editor without packing
them into a `.big`. Addresses recovered statically from the shipped `Worldbuilder.exe`
(ImageBase `0x400000`) and `game.dat` build `2.01.2614.37001` with `pefile` + `capstone`.

## 0. The premise does not survive contact with the binary

> add `-mod` to worldbuilder in the same way that there is a `-mod` for the .exe game launcher

`Worldbuilder.exe` **already carries the entire `-mod` pipeline**, not a fragment of it: the
switch is in its command-line table, its handler is a superset of `game.dat`'s, it writes the
same two `GlobalData` fields at the same offsets, and `ArchiveFileSystem::loadMods` is present
*and called* from the same place in engine init. Worldbuilder links the same
`Code/GameEngine/Source/Common/CommandLine.cpp` — its own debug strings name the file.

So this is not a port — every piece already exists. It is **linked but unreachable**: the one
function that would call it, `GameEngine::init`, never runs, because Worldbuilder never
constructs a `GameEngine` at all (§6, measured in a live process). A second, independent bug sits
in front of it: Worldbuilder is an MFC application, and MFC's document layer grabs the mod path
out of the command line and tries to open it as a map (§3) — the `Access to … was denied` dialog.
§4 works around that one for free. §7 is the patch for the real one.

## 1. How `-mod` works in `game.dat`

`-mod` lives in the *startup* parameter table — the short one parsed before the file systems
come up, not the main table.

| what | `game.dat` |
|---|---|
| startup table base | `0x00C35DA8` (`-noshellmap`, `-mod`, `-noaudio`, `-xres`, `-yres`, `-win`, …) |
| the `-mod` entry | `0x00C35DB0` → name `0x00C35ECC` `"-mod"`, handler `0x007BADB9` |
| `TheWritableGlobalData` | `0x00DE4364` |
| mod **directory** field | `GlobalData+0xD38` |
| mod **archive** field | `GlobalData+0xD3C` |

The handler is one function and it does four things:

```
007badc6  cmp dword [0x00DE4364], 0    ; no GlobalData yet -> return 1, silently ignored
007badd7  je  0x7baf3a
007badd1  cmp dword [ebp+0xc], 1       ; argc: nothing after "-mod" -> same
007bae11  push 0x3a                    ; ':' -- an absolute path?
007bae16  call 0x4353e0                ;   if not, prefix the user Mods dir
007baec5  call dword [0x00BD04B0]      ; stat(path, &buf)
007baed1  test byte [ebp-0x41], 0x40   ; S_IFDIR (0x4000) -- directory or file?
007baf0c  add ecx, 0xd38               ;   directory -> m_modDir  (a '\' is appended first)
007baf1a  add ecx, 0xd3c               ;   file      -> m_modBIG
```

Both spellings are supported: `-mod SomeMod.big` sets the archive field, `-mod SomeModFolder`
sets the directory field. **The directory form is the one that matters here** — it is what
lets loose, uncompiled files win over the shipped `.big`s.

## 2. Worldbuilder carries the identical pipeline

| what | `game.dat` | `Worldbuilder.exe` |
|---|---|---|
| startup table base | `0x00C35DA8` | `0x01EA2670` |
| `-mod` entry | `0x00C35DB0` | `0x01EA2688` |
| `-mod` handler | `0x007BADB9` | `0x00C59880` |
| `TheWritableGlobalData` | `0x00DE4364` | `0x022CA7D8` |
| mod directory field | `GlobalData+0xD38` | `GlobalData+0xD38` |
| mod archive field | `GlobalData+0xD3C` | `GlobalData+0xD3C` |
| `ArchiveFileSystem::loadMods` | present (strings stripped) | `0x00C5AC10` |

The field offsets are the same because it is the same `GlobalData` struct in both images.
Worldbuilder's handler is the *richer* of the two — it is a debug-symbol build and logs its way
through the decision, which is a gift for verification:

```
00c599a3  mov  ecx, [0x022CA7D8]        ; same GlobalData guard
00c59ac3  push 0x01EA3658               ; "E:\Builds\BFME2X\...\Common\CommandLine.cpp"
00c59ae6  push 0x01EA3768               ; "Looking for mod '%s'\n"
00c59b86  call 0x01682220               ; TheLocalFileSystem->doesFileExist()
00c59bdb  push 0x01EA3750               ; "Mod does not exist.\n"   -> bails, returns 2
00c59c57  call dword [0x022F4FD8]       ; stat()
00c59e60  push 0x01EA3724               ; "Mod dir is '%s'.\n"
00c59edd  add  ecx, 0xd38               ;   -> m_modDir
00c59f9d  push 0x01EA3710               ; "Mod file is '%s'.\n"
00c5a01a  add  ecx, 0xd3c               ;   -> m_modBIG
```

And the consumer side is wired too, not just the parser. `loadMods` at `0x00C5AC10` reads
`GlobalData+0xD3C` and carries both of its outcomes:

```
00c5ad77  push 0x01EA3888  ; "ArchiveFileSystem::loadMods - %s inserted into the archive file map.\n"
00c5ae59  push 0x01EA3844  ; "ArchiveFileSystem::loadMods - could not openArchiveFile(%s)\n"
```

`GlobalData+0xD38` has consumer sites well outside `CommandLine.cpp` — e.g. `0x00636013`
reads it beside the `"cinematics"` literal, and `0x0096719A` does the same. Counting raw
`0xD38` immediates in `.text` gives 18 in Worldbuilder against 13 in `game.dat` (16 vs 12 for
`0xD3C`) — a coarse measure, but the editor is not the thinner of the two. The loose-file
search path the request actually wants is present.

### Both halves are reached from engine init — which is itself never reached

`0x00C9B6D0` is `GameEngine::init(argc, argv)` — it prints the `"Version %s (%s)"`,
`"Build date: %s"`, `"Built by: %s"` banner — and it calls both halves, in the right order:

```
00c9b781  push [ebp+0xc]               ; argv
00c9b788  push [ebp+8]                 ; argc
00c9b789  call 0x00C5A9A0              ; wrapper: pushes the startup table 0x01EA2670
   ...                                 ;   (the table that holds -mod)
00c9c40e  call 0x00C5AC10              ; ArchiveFileSystem::loadMods
```

`0x00C9B6D0` appears in exactly one vtable slot in the whole image (`0x01EAF4E8+0x38`), and
there is **no second, derived engine vtable** — every sibling slot is likewise referenced once.
So this is not a base-class `init` that some Worldbuilder subclass overrides and shadows; it is
the `init` that *would* run. §6 shows that in Worldbuilder it never does — the engine-side call
graph below is real, but nothing enters it.


## 3. The observed failure: MFC eats the mod path

Running the editor produced a modal dialog before anything else:

```
WorldBuilder
    Access to D:\Edain-Mod\_mod was denied.
                [ OK ]
```

That message is **not the engine's**. It is MFC's `AFX_IDP_FILE_ACCESS_DENIED`, and
Worldbuilder imports `MFC71.DLL` — 544 slots — so it is a `CFileException` with
`CFileException::accessDenied`, which is exactly what `CFile::Open` returns when it is handed a
**directory** instead of a file. Nothing in the engine's `parseMod` can raise it: that path
`stat()`s the argument and branches on `S_IFDIR` (§1) rather than opening it.

So Worldbuilder is an MFC app whose document layer is racing the engine for the same argument
vector, and losing gracelessly:

- `CWinApp::ParseCommandLine` walks `__argc`/`__argv` and calls
  `CCommandLineInfo::ParseParam(param, bFlag, bLast)` for each token.
- A token is a *flag* only if it starts with `-` or `/`. `-mod` is therefore a flag — an
  unknown one, which MFC silently ignores.
- `D:\Edain-Mod\_mod` starts with neither, so it is **not** a flag. It becomes
  `m_strFileName`, and `ParseLast` promotes `m_nShellCommand` from `FileNew` to `FileOpen`.
- `ProcessShellCommand` then calls `OpenDocumentFile("D:\Edain-Mod\_mod")`, which tries to open
  a directory as a map document, and throws.

The engine's `-mod` handler and MFC's document opener are reading the same command line with no
knowledge of each other. `game.dat` never had this problem because it is not an MFC app.

### What this does and does not prove

It proves the process command line reaches MFC's parser intact, and that the mod path survives
as its own `argv` token. That makes it substantially more likely — but does **not** prove — that
`GameEngine::init` also receives it, since MFC's `ParseCommandLine` reads the CRT globals
directly and the engine's route to `argc`/`argv` (§2) is still the unresolved link.

The dialog may also be *masking* the answer. The usual `InitInstance` shape is

```cpp
if (!ProcessShellCommand(cmdInfo))
    return FALSE;          // -> the app exits
```

and `ProcessShellCommand` sets its result to `FALSE` when `OpenDocumentFile` fails. If
Worldbuilder follows that shape, the editor quits after the OK and the engine's mod loading
never gets a visible chance to show itself.

**Open question for the next run:** after clicking OK, does Worldbuilder open normally, or does
it close?

## 4. A workaround that needs no patch at all

`CCommandLineInfo::ParseParamNotFlag` assigns `m_strFileName` **only when it is still empty** —
the first non-flag token wins and every later one is discarded. So giving Worldbuilder a real
map to open *before* `-mod` should leave the mod path with nowhere to land:

```
Worldbuilder.exe maps\<some_map>\<some_map>.map -mod D:\Edain-Mod\_mod
```

- `…\<some_map>.map` → first non-flag → `m_strFileName`, `FileOpen` succeeds, no dialog.
- `-mod` → flag, unknown to MFC, ignored.
- `D:\Edain-Mod\_mod` → non-flag, but `m_strFileName` is taken → **discarded by MFC**.
- The engine's own parser walks the same `argv` independently and still sees `-mod` followed by
  its path.

This is MFC's documented behaviour rather than something recovered from this binary — `MFC71.DLL`
exports 6,443 symbols entirely by ordinal, with no names, so pinning `ParseParamNotFlag` down
statically is a Ghidra job in its own right. It costs one run to test, and if it holds it both
dismisses the dialog and finally answers §3: load a map, then look at whether the object palette
carries mod content.
The map-first ordering **works** — the dialog is gone and the editor opens the map. It does not,
however, make `-mod` do anything, for the reason in §6.

## 5. What `-mod <dir>` is supposed to do

Correcting a first reading of `loadMods`: its directory branch is not archive-only. It calls one
self-contained function, `0x01682780`, which does three things:

```
01682780  mov  eax, [esp+4]           ; the mod directory
01682790  ...                         ; copy it into the global buffer at 0x22D4820
016827a7  mov  byte [0x22D4818], 1    ; the "a mod is active" / prefer-local flag
016827a2  push 0x1fd9814              ; "*.BIG"
016827b0  push 0x22D4820              ; ...in the mod directory
016827b5  call [eax+0x20]             ; enumerate recursively and mount each archive
```

So a mod directory gives you **both** halves: every `.BIG` under it is mounted, *and* the
directory becomes a loose-file root. The loose half is the file-open path at `0x01683704`:

```
01683704  mov al, [0x22D4818]       ; the flag above
01683716  je  ...                   ; clear -> skip the mod lookup entirely
01683732  mov al, [0x22D4820]       ; the mod directory
01683745  push 0x1e745dc            ; "%s\%s"  ->  <modDir>\<requested file>
01683763  call [edx+0xc]            ; LocalFileSystem::openFile
0168376a  je  ...                   ; miss -> fall through to the normal search
```

Every file the engine opens is tried under the mod directory first, falling back to the usual
search on a miss. Loose, uncompiled `data\ini\…` overriding a shipped `.big` is exactly the
designed behaviour — which is what the request asked for.

## 6. The engine never receives it — measured, not inferred

Read out of a live `Worldbuilder.exe` (PID 10648) launched with
`"…\luhn.map" -mod "D:\Edain-Mod\_mod"`:

| global | meaning | value |
|---|---|---|
| `0x22D4818` | mod-active / prefer-local flag | **`0`** |
| `0x22D4820` | mod directory buffer | **empty** |
| `GlobalData+0xD38` | `m_modDir` | **NULL** |
| `GlobalData+0xD3C` | `m_modBIG` | **NULL** |

The flag is decisive. Worldbuilder's `parseMod` sets it **unconditionally on entry**, three
instructions in, *before* the `TheWritableGlobalData` null check that would otherwise make it
bail silently:

```
00c598a8  mov byte ptr [0x22D4818], 1   <- unconditional
00c598af  cmp dword ptr [0x22CA7D8], 0
00c598b6  je  0xc5a046                  <- the silent bail
```

A flag still reading `0` therefore means `parseMod` **was never called at all** — not that it
ran and gave up.

And the reason it was never called: **no `GameEngine` is ever constructed.** Scanning all 1,047
readable regions of the live process for the engine vtable `0x01EAF4E8` finds it at exactly two
addresses, `0xC9AE5E` and `0xC9B59C` — both of them the static `mov [reg], vtable` stores in the
constructor and destructor. No live object carries it.

`GameEngine::init` is the **only** caller of the startup command-line parser and of `loadMods`
(§2). No engine object means neither ever runs. Meanwhile the subsystems are all up and healthy,
initialised by Worldbuilder's own MFC startup instead:

| global | live value | vtable |
|---|---|---|
| `TheWritableGlobalData` `0x22CA7D8` | `0x07F9E288` | `0x01E8B800` |
| local file system `0x22D4920` | `0x04D5F400` | `0x01FD97A4` |
| file system `0x22D507C` | `0x04D5F318` | `0x01FDA268` |
| file system `0x22D5088` | `0x04D5F418` | `0x01FDA2E8` |

So the whole `-mod` pipeline in `Worldbuilder.exe` — table entry, handler, `loadMods`, the
loose-file lookup — is **linked but unreachable**. It is dead code inherited from the shared
engine library, sitting behind an `init` that Worldbuilder never calls. That is why BARK is
invisible: not an INI problem, not a path problem, not MFC. The editor simply never learns a mod
was requested.
## 7. The patch

[`worldbuilder-mod`](../patches/worldbuilder_mod.py) calls `0x01682780` with the `-mod` argument
during Worldbuilder's own startup. Everything downstream — mounting, the loose-file prefix, the
fallback — already works and is not touched.

**The hook.** `CWorldBuilderApp::InitInstance` reads its first INI at `0x0069017A`:

```
00690155  mov ecx, [ebp-0x1758]    ; <- replaced by: call <cave>; nop
0069015b  mov [ebp-0x1014], ecx
...
00690169  push 0x01E20A28          ; "Data\INI\Default\SubSystemLegendExpansion1.ini"
0069017a  call 0x004097BE          ; the first INI read
```

`0x00690155` is the last six-byte instruction before it, and **there is no call between the two**,
so the archive file system that `0x01682780` dereferences is necessarily already up. Both paths
into the region converge there — the `jmp` at `0x00690149` targets it directly, and the `je` at
`0x006900E1` arrives via `0x0069014B` — so the hook runs exactly once. `GameData.ini`
(`0x0069020A`) and every `Data\INI\Object\…` file load later still, which is what puts the mod
directory in front of the object definitions the editor's palette is built from.

**The cave.** `pushad`/`pushfd` bracket the body, since this runs mid-function and must not
disturb a register or flag. It bails if the archive file system is null, takes `GetCommandLineA`
(Worldbuilder imports no `__argv`), scans for a `-mod` token delimited by whitespace on *both*
sides, copies the token after it while stripping one level of quoting, and calls `0x01682780`.
Then `popfd`, `popad`, the displaced `mov ecx, [ebp-0x1758]` re-run after the restore, and `ret`.

Two details are load-bearing:

- **The trailing delimiter check.** A mod under `D:\Edain-Mod\…` puts the literal text `-Mod`
  inside another argument. Only requiring whitespace *after* the token rejects it.
- **The 128-character bound.** `0x01682780` copies into its fixed buffer at `0x022D4820` with an
  unbounded byte loop, and the next global anything references is `0x022D48B8` — `0x98` bytes
  later. Over-long paths are dropped rather than truncated: a truncated path names a *different*
  directory, which fails worse than not arming the mod at all.

### Verified

Applied to the shipped `Worldbuilder.exe`, deployed alongside it, and launched as
`Worldbuilder_mod.exe -mod "D:\Edain-Mod\_mod"`. Reading the two globals out of the live process:

```
t= 19.5s  flag [0x22D4818] = 00   modDir [0x22D4820] = ''
t= 21.0s  flag [0x22D4818] = 01   modDir [0x22D4820] = 'd:\edain-mod\_mod'
```

The mod directory is armed, from the real command line, in the real binary — the exact state §6
measured as absent. (The engine lower-cases the path on the way in; the file system is
case-insensitive, so this is cosmetic.)

Then end to end, in the editor: with `-mod` pointed at a directory holding one edited
`data\ini\object\civilian\civilianbuildings.ini`, a new `Object BARK` added to that file
**appears in Worldbuilder's object palette** under its `Side`/`EditorSorting` node, with no `.big`
built. That is the whole request, working.

The suite in [`test_worldbuilder_mod.py`](../../tests/sage_patch/test_worldbuilder_mod.py) is
data-free, against a sparse stand-in. It disassembles the cave back and asserts what cannot be
checked by reading: that the hook is a `call` landing exactly on the cave's entry with the window
`nop`-padded, that the body opens with `pushad`/`pushfd` and closes with
`popfd`/`popad`/displaced-instruction/`ret`, that the only direct call is `0x01682780` with its
one cdecl argument pushed and popped, that the path buffer lives inside the cave's own section,
and that mutating any anchor or the hook window makes `apply` refuse.

## 8. Known limitation: a whole mod tree still kills the editor

`-mod` pointed at a *subtree* works. Pointed at a full Edain mod directory, the editor dies
during startup. **This is not the patch** - an empty mod directory arms cleanly and the editor
runs, so the failure is about what the directory serves, not about whether the hook fired.

### It is not scale

The first reading of this was that the editor could not cope with the number of files, since
25 files worked and 1122 did not. That is wrong. Bisecting the served set finds single files -
and then single *blocks* - that are fatal on their own:

```
data/ini/object/goodfaction/structures/belfalas/belfalasbarracks.ini   1 file  -> dies
    ChildObject BelfalasBarracksFreeBuild BelfalasBarracks             3 lines -> dies
```

Conversely the eight object files that are byte-identical to the installed archive are fine, and
so is every file whose content is self-contained. The axis is content, not count.

### The rule the editor actually follows

Three behaviours, each reproduced against files written for the purpose rather than against
Edain's data, so they are statements about the engine:

| served content | result |
|---|---|
| an object under a name nothing else defines | fine |
| an object under a name an **unshadowed archive file** also defines | dies |
| `ChildObject` whose parent is defined in the mod directory | fine |
| `ChildObject` whose parent is defined **only in the archive** | dies |
| a file shadowing an archived one but dropping definitions others still reference | dies |

The second and fourth rows together pin the load order down: a mod-directory file is parsed
**before** the archive files, which is why a loose `ChildObject` cannot inherit from a parent
that lives in a `.big`, and why a name the mod defines is then defined a second time when the
archive's own copy is parsed afterwards.

The third mechanism is the one that makes partial serving treacherous: the mod directory
shadows an archive file **by path**, wholesale. Serving a half-written `fxlist.ini` - or an
`fxlist.ini` that is simply newer than the installed archive and has dropped an entry - removes
every FXList the archive's other files still name. An empty `fxlist.ini` alone is enough to kill
the editor.

### Why that bites so hard here

The installed archives are far behind this mod's source tree: of the 1122 files in
`data/ini/object`, **1096 differ** from `__edain_data.big` and only 8 are identical, and 265
archive `data/ini` files have no counterpart in the tree at all. Serving any subtree therefore
mixes a current file with stale neighbours, and each of the three mechanisms above becomes
reachable. `ElphirOffiziereSpawner`, for instance, moved from `barracks.ini` to
`belfalasbarracks.ini` between the release build and now; serving only the new file defines it
twice, because the archive's `barracks.ini` is not shadowed and still carries it.

`game.dat` does not have this problem, which is what made the editor look uniquely fragile. The
difference is not established here.

### `--full` is still unexplained

Serving the whole tree removes the mixing - the tree is internally consistent (all 3083
`ChildObject` parents resolve within it, and exactly one name, `RohanFarmMultiplayer`, collides
with an unshadowed archive file) - and it still dies, at about two seconds, with a stack running
through the particle-system code. Ruled out along the way:

- **scale** - see above
- **the one predicted duplicate** - shadowing `object/obsolete/rohan/farm.ini` does not help
- **new dangling references** - modelling the editor's view as `[archives, mod]` in
  `sage_ini.load_game` and running the dangling-reference rule finds no reference that layering
  introduces; the eight in the archive's `roads.ini` are pre-existing and present in the stock
  game too
- **the stale archive-only files as a group** - emptying all 265 (or either half) makes the
  editor exit cleanly instead of crashing, because most of them are ordinary base-game files
  rather than stale ones, so that axis cannot be bisected by emptying

What would settle it is an installed archive rebuilt from the current tree: with nothing stale
underneath, every mechanism above is out of reach, and a full mod directory is just the tree.

Until then the usable arrangement is a mod directory holding only the subtree being edited -
and, given the mechanisms above, a subtree that is self-contained: one that does not rely on a
name defined in a file it does not also serve.

## 9. Constraints

- **The MFC collision of §3 is not fixed by this patch and still bites.** `-mod`'s argument is a
  bare path, and `CCommandLineInfo::ParseParam` still claims it as `m_strFileName`. Pass a map
  before `-mod` (§4) so it has nowhere to land:
  `Worldbuilder.exe <some>.map -mod <dir>`. Widening the patch to force `m_nShellCommand` back to
  `FileNew` would remove the requirement, and needs the `InitInstance` call site §3 could not pin
  down.
- Mod paths of 128 characters or more are ignored, per §7.
- `-mod` must name a directory that exists. `0x01682780` validates nothing — in the stock flow
  `parseMod` had already done it, and `parseMod` is exactly what never runs here.
- Editor and game must be given the same mod. Nothing enforces this; a map authored against
  mod A and opened against mod B resolves against B silently.
- Second binary, second deploy step. Per the install notes, a patched file has to be copied
  into `C:\Program Files (x86)\Games\bfme\rotwk` before it can be tested — an unpatched
  `Worldbuilder.exe` sitting there looks exactly like a failed patch.
- `mfc71.dll` ships beside `Worldbuilder.exe` in the install. It is a shared runtime and is not
  a patch target: the fix belongs on Worldbuilder's side of the call.
