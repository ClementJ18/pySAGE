# Only the last `-mod` survives

Why `-mod A -mod B` runs B alone, which parts of the mod pipeline are single-valued and which
were never single-valued at all, and what the `multi-mod` patch changes. Addresses recovered
statically from `game.dat` build `2.01.2614.37001` (ImageBase `0x400000`) with `pefile` +
`capstone`. The reading below is off the machine code, and the patch built from it is confirmed
in a running game.

## 1. The symptom

Pass `-mod` twice. The game starts, and behaves as though only the second one had been given: the
first mod's loose files are not read and its `.big`s are not mounted. There is no warning, because
nothing has gone wrong from the engine's point of view - the second switch simply overwrote the
first.

## 2. `-mod` is one assignment

`-mod` is row 1 of the 16-entry startup switch table `0x00C35DA8`, and its handler is
`0x007BADB9`. The handler is longer than it needs to be for what matters here, and only its ending
does:

```
007badc6  cmp dword [0x00DE4364], 0   ; TheWritableGlobalData - bail silently while it is null
007bade7  ...                         ; argv[1] -> an AsciiString in [ebp-0x10]
007bae11  push 0x3a / call 0x004353E0 ; is there a ':' - i.e. is the path already absolute
007baea6  call 0x00A14220             ; TheFileSystem::doesFileExist - bail if it names nothing
007baec5  call [0x00BD04B0]           ; _stat(path, &statbuf)
007baed1  test byte [ebp-0x41], 0x40  ; st_mode & S_IFDIR
007baed5  je  0x007BAF14              ;   not a directory
007baef1  ...                         ;   a directory: append '\' unless it already ends in one
007baf06  mov ecx, [0x00DE4364] / add ecx, 0xD38   ; -> m_modDir
007baf12  jmp 0x007BAF20
007baf14  mov ecx, [0x00DE4364] / add ecx, 0xD3C   ; -> m_modBIG
007baf20  lea eax, [ebp-0x10] / push eax
007baf24  call 0x00437BF0             ; AsciiString::operator=
```

So the whole outcome of one `-mod` is a single `AsciiString` assignment at `0x007BAF24`, into
whichever of the two `GlobalData` fields `_stat` selected. Nothing accumulates. The second `-mod`
reaches the same store and replaces what the first left there.

`0x00437BF0` is `AsciiString::operator=(const AsciiString &)`: `__thiscall`, one stack argument,
`ret 4`, returning `this`.

## 3. What the mount does with those two fields

`COMMAND_LINE_PARSE_AND_MOUNT_MODS` (`0x007BAA44`) parses the table and then mounts, at
`0x007BAA5B`-`0x007BAABD`, exactly twice - once per field:

```
if (!m_modBIG.isEmpty())  TheArchiveFileSystem->vtbl+0x14 (m_modBIG, 1);   ; loadArchive
if (!m_modDir.isEmpty())  0x00A14313(m_modDir);                            ; the directory mount
```

`0x00A14313` is three things in fourteen instructions: `strcpy(0x00DEC498, path)`, raise the flag
byte `0x00DEC490`, and `TheArchiveFileSystem->vtbl+0x20 (0x00DEC498, "*.BIG", 1)` - mount every
archive beneath the directory.

## 4. Archives already stack; loose files do not

This is the asymmetry the patch is built on.

**Archives are a shared map.** `TheArchiveFileSystem`'s vtable is `0x00C9341C`; slot `+0x14` is
`loadArchive` (`0x00A183AA`) and slot `+0x20` is `loadArchivesFromDir` (`0x00A17FB0`, which calls
`+0x14` per file at `0x00A18012`). `loadArchive` reads the archive's directory and inserts each
file into one map shared by every mounted archive, through `0x00A1829C`. Its last argument is an
**overwrite** flag, and `0x00A18384` is where it matters:

```
00a18384  cmp byte [ebp+0x14], 0    ; the overwrite flag
00a18388  jne 0x00A1838E
00a1838a  xor al, al                ;   clear: keep the entry already there, report failure
00a1838e  ...                       ;   set:   copy the new offset/size/archive over it
```

Every mod mount passes it **set** (`push 1` at `0x007BAA8C` and at `0x00A1432B`). So mounting
several archives already works, and the rule it follows is **last mounted wins**. Nothing about
the archive side needs changing - it only needs to be reached more than once.

**Loose files are one global, consulted four times.** `0x00DEC498` holds one path, and `xref`
finds exactly five references to it: the `strcpy` that fills it, and four file-system entry
points, each of which formats it into a stack buffer with `"%s\%s"` (`0x00BF5128`) and makes one
`TheLocalFileSystem` call:

| entry point | block | buffer | `TheLocalFileSystem` slot |
|---|---|---|---|
| `FileSystem::openFile` `0x00A149A2` | `0x00A14A06`-`0x00A14A45` | `[ebp-0x200]` | `+0x0C` |
| `FileSystem::doesFileExist` `0x00A14AEB` | `0x00A14B43`-`0x00A14B6B` | `[ebp-0x200]` | `+0x14` |
| `FileSystem::getFileInfo` `0x00A14BA8` | `0x00A14C13`-`0x00A14C3C` | `[ebp-0x104]` | `+0x28` |
| `FileSystem::getFileListInDirectory` `0x00A14D2B` | `0x00A14D62`-`0x00A14DD0` | `[ebp-0x124]` | `+0x18` |

All four are entered through the same guard, `cmp byte [0x00DEC498], 0` followed by a branch past
the block, so a run with no mod skips them entirely. The first three return the first hit; the
fourth has no success test at all, because the callee merges names into a `std::set` under their
*logical* directory (`0x00A18BF8` inserts `(arg1 ? arg1 : arg3) + subdir + filename`) - which is
why running it once per mod unions the trees instead of shadowing them.

None of the four blocks is jumped into from outside; `xref` on interior addresses of each finds no
branches, so each is replaceable as a unit.

## 4b. The asset cache is single-valued a third time, and not through the file system

`asset.dat` is the art cache's index - every `.w3d` model and every texture the engine will load,
with the byte range each asset occupies in its source file. A model whose entry the cache does not
hold does not draw; a texture whose entry it does not hold draws in the missing-texture magenta.

None of the four blocks above is involved, because the cache does not open its index through
`TheFileSystem` at all. `0x0052C9B0` is the loader, called once from `W3DDisplay::init`
(`0x004467B6`) with three arguments built at the call site:

```
004467a1  ...                         ; AsciiString copy of GlobalData+0xD38 -> arg 1 (m_modDir)
00446791  ...                         ; AsciiString copy of GlobalData+0xD3C -> arg 2 (m_modBIG)
00446789  push ecx                    ; GlobalData+0xD48 > 0                 -> arg 3
004467b6  call 0x0052C9B0
```

and it makes three attempts, in this order:

| where | how | site |
|---|---|---|
| `<arg 2>\asset.dat` | `_wfopen` on the wide concatenation with `L"\asset.dat"` (`0x00BE83F0`) | `0x0052CA49` |
| `<arg 1>\asset.dat` | the same, on the other argument | `0x0052CC08` |
| `asset.dat` | `fopen` in the process's working directory | `0x0052CC46` |

Each open file goes to `0x0052C577`, `__cdecl (FILE *, bool)`, which reads the `ALAE` header and
version `0x102` and walks section 1 - and it is the *only* consumer, so an `asset.dat` reached any
other way would be read on exactly the same terms.

Both arguments are copies of the same two single-valued `GlobalData` fields section 2 describes,
so **only the last `-mod` is ever consulted**, whatever else is mounted. That is the defect: with
`-mod A -mod B`, every model and texture A adds is absent from the cache and draws magenta, and
moving A's `asset.dat` into B is the only thing that fixes it.

### Precedence inside the cache is first-wins

Every asset name, of every type, passes one gate before it is registered:

```
0052c6e2  lea eax, [ebp-0x14c] / call [_strlwr]   ; names are matched lowercased
0052c6ef  lea eax, [ebp-0x14c] / push eax
0052c6f6  call 0x00A32D80                        ; does the cache already hold this name
0052c6ff  jne 0x0052C81C                         ;   yes - skip it entirely
```

`0x00A32D80` is a lookup on the cache singleton at `0x00DEF75C`, and the `jne` jumps past the
type dispatch - `TEX`, `MESH`, `HIER`, `HLOD`, `ANIM`, `BOX`, `AGGR`, `FXSH`, `PART` alike. So the
**first** file to name an asset is the one that keeps it, which is what makes the stock order put
the mod ahead of the working directory's base-game copy. It is also why a combined `asset.dat`
built base-first is not a mod override at load time: within one file, first-wins too.

## 5. The fix

Built as `multi-mod`, in [`patches/multi_mod.py`](../patches/multi_mod.py).

A `.modmul` section carries a sixteen-entry table of `{kind, path[260]}` plus a count, and six
sites are rewritten.

**Site 1** - `0x007BAF24`, `E8 C7 CC C7 FF` (`call 0x00437BF0`). Repointed to a stand-in that:

1. performs the assignment itself, unchanged, so the two `GlobalData` fields end up holding
   exactly what they always did - and so `ret 4` returning `this` is what the caller still gets;
2. reads the path back out of the **destination** field, which is the finished absolute path with
   its trailing separator, rather than out of the source;
3. tags it an archive when `ecx` was `GlobalData+0xD3C` and a directory otherwise - the two
   addresses at `0x007BAF06` and `0x007BAF14` are the only thing that distinguishes them;
4. appends it to the table unless `_strcmpi` (`0x00A3D79A`) already finds it there, and mounts it
   on the spot: `0x00A14313` for a directory, `TheArchiveFileSystem` slot `+0x14` with the
   overwrite flag for an archive.

Mounting from inside a switch handler is earlier than the stock mount, which runs a few
instructions after the parse returns. Both are after `0x0063AE22`, where `GameEngine::init` calls
`0x00A14275` to build `TheLocalFileSystem` and `TheArchiveFileSystem` - eight hundred bytes before
the parse is reached - so both singletons exist at either moment. That call is anchored for that
reason.

The stock mount block is **left alone**. It re-mounts the last archive and the last directory on
top of a table that already mounted them, which is idempotent in both cases (the same path
re-copied; the same file entries re-inserted at the same offsets, with overwrite set) and happens
in the stock order, archive then directory. Two things follow: the stock rule that a `-mod`
directory outranks a `-mod` archive survives unchanged, and `mod-load-order` - which replaces that
block wholesale - and this patch touch no byte in common, so they compose in either order.

**Sites 2-5** - the four blocks in the table above. Each is replaced by a `call` into a cave
routine that runs the same formatting and the same `TheLocalFileSystem` call in a loop over the
recorded directories, nop-padded out to the block's length. The routines keep the calling
function's `ebp`, so the buffer and arguments they read are the caller's own frame; each preserves
what the code after its block still uses and leaves the answer where that code expects it - `esi`
for `openFile`, `al` for the two predicates, nothing for the listing merge.

The stock guard in front of each block is kept, so a run with no mod takes exactly the stock path.

**Site 6** - `0x0052CA0C`, `8B 45 0C 85 C0`, the `mov eax, [ebp+0xc]` / `test eax, eax` that opens
the asset loader's first attempt. Five bytes for five, so nothing pads. The routine it calls runs
the table backwards and, for each recorded directory, builds `<dir>\asset.dat` with the same
`sprintf` and the same `"%s\%s"` the file-system loops use, `fopen`s it `"rb"`, and hands the file
to `0x0052C577` with the loader's own third argument forwarded from `[ebp+0x10]` - so whether
textures are registered is decided exactly as it is for the loader's own three attempts. Each file
is closed before the next is opened.

Three things fix that site rather than the `call` at `0x004467B6`:

- it is **inside** the loader, past the three one-time resets at `0x0052C9E2`-`0x0052CA07`, which
  would otherwise throw away everything the loop had just registered;
- the loader keeps its frame pointer, so the routine reads the loader's arguments as frame locals
  the way the other four read their callers' buffers;
- the stock three attempts still run afterwards, and first-wins makes every one of them a no-op
  for an asset the loop already registered - including the working directory's base-game
  `asset.dat`, which stays exactly where it was, underneath every mod.

The `je` at `0x0052CA11` is left standing and branches on the flags the replaced pair sets, so the
routine ends on that same pair with `ret` after it - the one return that leaves `EFLAGS` alone.

### Precedence

The table is walked **backwards** - last `-mod` first - because that is what the archive side
already does, and the two halves have to agree or a file present loosely in one mod and packed in
another would resolve differently depending on how it was shipped. Mounting therefore runs
forwards, in command-line order, and searching runs backwards.

The asset cache lands on the same order from the other direction. It keeps the *first* file to
name an asset rather than the last, so reading the directories backwards is what makes the last
`-mod`'s `asset.dat` the one whose entries survive - the same answer the loose search gives, for
the opposite reason.

### Bounds, and what happens past them

Sixteen mods, and paths shorter than 260 bytes. A path past either bound is not recorded and not
truncated. The loop then falls back to `0x00DEC498` itself when the table holds no directory at
all, so such a run degrades to the stock single-mod lookup rather than to no lookup.

The asset routine takes the other half of that: it returns before its loop when the table's count
is zero, so a run with no `-mod` reaches the loader having done nothing at all and takes exactly
the stock three attempts. A path the table declined to record is still covered, because the
loader's own attempt on `m_modDir` is left standing.

### What this does not change

- **`-preferLocalFiles`** raises the same flag byte with no directory, and is untouched.
- **Which of the two kinds wins.** A `-mod` directory still outranks a `-mod` archive whatever
  order they were given in, because the stock mount re-mounts the last archive before the last
  directory. Only the ordering *within* each kind is now the command line's.
- **When the mod is mounted.** That is `mod-load-order`'s subject, not this one: without it, every
  `-mod` here is still mounted after `GameData.ini` has been read.

## 6. Testing

Static assertions on the stock bytes at all six sites and the twenty-seven windows the cave reads,
a disassembly of the cave, and an apply/verify/detect round-trip are the floor, and are what
[`tests/sage_patch/test_multi_mod.py`](../../tests/sage_patch/test_multi_mod.py) covers.

The claim only becomes real in a running game. The cheapest check: two loose trees, each with a
`Data\INI\` file the other does not have and one file both have with different values, launched as
`-mod A -mod B`. Both trees' unique files should take effect, and the shared one should read as
B's. `sage_live` can read a `GameData` field back to confirm the last-wins half without leaving
the game.

The asset half needs its own check, because nothing about it shows up in an INI value: give each
tree an `asset.dat` naming art only that tree ships, put a unit from each on the map, and look at
them. Both should draw. Before this site existed, only the second tree's did and the first's came
up magenta.

## 7. What is still unknown

- Whether anything besides the mount and the asset loader reads `GlobalData+0xD38` / `+0xD3C`. The
  patch does not need to know - it leaves both fields holding exactly what they held before - but
  a future change that wanted to *stop* the stock mount re-running would. The asset loader is the
  one such reader found so far, and it was found by looking, not by an exhaustive `xref`.
- What `GlobalData+0xD48` is. It is the asset loader's third argument, and inside `0x0052C577` a
  nonzero value skips every `TEX` registration while leaving models alone. The cave forwards
  whatever the loader was given rather than deciding for itself, so the answer is not load-bearing
  here.
- Whether the loader's **first** attempt, `<m_modBIG>\asset.dat`, can ever open anything.
  `m_modBIG` names a `.big` *file*, so the concatenation is a path through a file rather than a
  directory. It is left standing untouched either way.
- Whether `loadArchivesFromDir` on a directory already mounted is as cheap as it is harmless. It
  is re-run once per launch for the last `-mod` directory, so the cost is bounded by one
  directory's archives, but it has not been measured.
