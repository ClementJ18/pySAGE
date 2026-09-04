# The engine's own out-of-sync instrumentation, and which of it still works

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`. Read **statically** on 2026-09-01 with the skill's `explore.py`.

This is the companion to [`desync-detection.md`](desync-detection.md), which answers *has this
client gone out of sync* from outside the process. The question here is the next one: **when, and
because of what.** The engine was built with a full desync-debugging toolkit and shipped with all
of it unreachable, because every switch that arms it lives in the orphaned command-line region
[`headless.md`](headless.md) §5 documents - a block of handlers with no dispatch-table row, no call
site and no pointer anywhere in the image.

So the switches are `.data` bytes with initialisers and **no live writer**. Setting them in the PE
image is the whole patch; see [`../patches/desync_debug.py`](../patches/desync_debug.py).

Three of them do something. The rest are recorded here so the next reader does not spend the
afternoon finding out they don't.

## 1. The complete switch table

Recovered from the flag-reporting function at `0x006306E9`-`0x0063084F`, which prints one line per
switch that is set. That function is itself only reachable from the same dead region, so it is a
listing of the toolkit rather than a way to use it.

| global | switch | stock | what reads it |
|---|---|---|---|
| `0x00DA1880` | `NetCRCInterval` (`-crcInterval %d`) | **100** | §2 - three live readers |
| `0x00DA62EC` | the focus frame | `-1` | §3 - six live readers |
| `0x00DE87C5` | `-verifyClientCRC` | 0 | `0x006CF692`, the `CLIENT_DESYNC_*.txt` writer |
| `0x00DE87C6` | `-deepCRC` | 0 | `0x0062E774` - §4, the log goes nowhere |
| `0x00DE87C7` | `-liteCRC` | 0 | **written at runtime** - §5 |
| `0x00DE87C9` | `-binaryDeepCRC` | 0 | reporter only |
| `0x00DE87BC` | `-xObjectCRC` | 0 | §5 - inert on the stock path |
| `0x00DE87BD` | `-xPartitionCRC` | 0 | §5 |
| `0x00DE87BE` | `-xCollisionCRC` | 0 | §5 |
| `0x00DE87BF` | `-xShroudCRC` | 0 | §5 |
| `0x00DE87C0` | `-xTaintCRC` | 0 | §5 |
| `0x00DE87C2` | `-xTerrainLogicCRC` | 0 | §5 |
| `0x00DE87C3` | `-xPlayerCRC` | 0 | §5 |
| `0x00DE87C4` | `-xAICRC` | 0 | §5 |
| `0x00DE87C8` | `-xLWCRC` | 0 | §5 |
| `0x00DE87CA` | declaration filter | 0 | `0x006290DE`, `0x0062A561` |
| `0x00DA62E4` | `-debugCRCFromFrame %d` | `-1` | **reporter only** - §6 |
| `0x00DA62E8` | `-debugCRCUntilFrame %d` | `-1` | **reporter only** - §6 |

The names are the engine's own, taken from the `.rdata` literals the reporter pushes
(`0x00BFDCE4` `"\n    NetCRCInterval: %d\n"`, then `0x00BFDD30`-`0x00BFDDE4` for the rest). The
`0xDA62E4`/`0xDA62E8`/`0xDA62EC` handlers all `atoi` their argument and reject a non-positive
value; the byte flags are set to 1 unconditionally.

## 2. `NetCRCInterval` - the one that matters

`0x00DA1880` holds `0x64` = **100**, and it is the cadence of the `MSG_LOGIC_CRC` (`0x44A`)
heartbeat: the resolution of every out-of-sync answer this engine can give. Its only writer is
`0x007BA6F5`, in the dead region. It has **three** live readers, and between them they cover both
halves of what a desync investigation needs.

**The emitter.** `GameLogic::update` divides the frame by the interval:

```asm
0062e714  mov  eax, [0xde892c]        ; TheGameInfo
0062e719  mov  ecx, [eax + 0xc]       ; its CRC interval
0062e71c  mov  eax, [esi + 0x40]      ; the logic frame
0062e71f  xor  edx, edx
0062e721  div  ecx                    ; edx = frame % interval
0062e723  mov  ebx, edx
0062e725  neg  ebx
0062e727  sbb  bl, bl
0062e729  inc  bl                     ; bl = (frame % interval == 0)
0062e72b  cmp  dword [esi + 0x110], 2
0062e732  jne  0x62e736
0062e734  xor  bl, bl                 ; game mode 2: never
```

**`div ecx` is why the interval can never be 0.** There is no guard: a zero interval is an integer
divide-by-zero on the logic thread, on the first frame of the first match.

**`GameInfo::+0xC` comes from the global.** The `GameInfo` constructor initialises it directly and
unclamped:

```asm
00801ae1  mov  eax, [0xda1880]
00801aee  mov  [esi + 0xc], eax
```

The skirmish path re-sets the same field on match start, and **clamps in one direction only**:

```asm
0077ed5d  mov  ecx, [0xda1880]
0077ed63  cmp  ecx, 0x64
0077ed66  jl   0x77ed6b               ; below 100: keep it
0077ed68  push 0x64 / pop ecx         ; at or above 100: 100
0077ed6b  mov  [eax + 0xc], ecx       ; TheSkirmishGameInfo
```

So **lowering** the interval passes through untouched on every path; raising it above 100 is
ignored for skirmish and honoured elsewhere. A patch that wants finer resolution is pushing on the
unclamped side of that branch, which is the reason this is a one-dword edit and not a code hook.

**The replay records it.** The recorder copies the same global into its header block, which is the
`crc_interval` field `sage_replay` reads back:

```asm
0077d260  mov  ecx, [0xda1880]
0077d269  lea  edi, [esi + 0xec0]
0077d26f  mov  [edi], ecx
```

That is the half that makes the interval worth changing rather than merely worth knowing. Every
`0x44A` heartbeat carries this client's CRC and is written into that client's own replay, so two
players' recordings of one match are diffable frame by frame -
`sage_replay.replay.OrderType.ChecksumHeartbeat`. At 100 the diff says "you parted somewhere in
these hundred frames"; at 1 it names the frame.

## 3. The focus frame - `0x00DA62EC`

Set to a positive frame number, it **overrides the interval entirely** in a window ending on that
frame, and silences the heartbeat everywhere else:

```asm
0062e736  mov  eax, [0xda62ec]
0062e73b  cmp  eax, -1
0062e73e  je   0x62e75d               ; unset: use the modulo result in bl
0062e740  mov  edi, [0xde4364]
0062e746  mov  ecx, [esi + 0x40]      ; frame
0062e749  mov  edx, eax               ; target
0062e74b  sub  edx, [edi + 0xc18]     ; ... minus the net's frame-ahead window
0062e751  dec  edx
0062e752  dec  edx
0062e753  cmp  ecx, edx
0062e755  jb   0x62e75b               ; before the window: suppress
0062e757  cmp  ecx, eax
0062e759  jbe  0x62e765               ; inside it: EMIT, whatever bl says
0062e75b  xor  bl, bl                 ; past the target: suppress
```

That is the precision instrument once a first pass has told you roughly where the divergence is:
per-frame checksums across the approach to one frame, at no cost on any other.

**It is the knob with unread edges.** `0x00DA62EC` has six live readers - this one, three inside
the declaration routine (`0x006290E7`, `0x00629137`, `0x006291B2`) and two in the message handler
(`0x0062A43E`, `0x0062A56D`) - and only the first and the `0x006290E7` one (below) have been read.
What the other three do with a set focus frame is not established here.

The `0x006290E7` reader is gated by `0x00DE87CA`, and the two are **separate switches** with
separate handlers (`0x007BA690` sets the frame, `0x007BA6B0` arms the filter), so the frame can be
set without arming it. Armed, it turns the declaration into "report a desync only if it happens on
exactly this frame" - a filter, not a trigger. Left at 0, the declaration and its message box
behave normally, which is what you want while the frame is only being used to steer the heartbeat.

## 4. `-deepCRC` writes its log to nobody

`0x00DE87C6` selects a second route through the emitter that formats the frame number, builds a
named sink, and hands it to the CRC producer to log into:

```asm
0062e774  cmp  byte [0xde87c6], 0
0062e77e  je   0x62e7e4               ; off: the plain path
0062e784  push [esi + 0x40]           ; frame
0062e78a  push 0xbd4194               ; "%d"
0062e794  call 0x437a90               ; AsciiString::format
0062e7ae  call 0xa1611e               ; new sink(name)
0062e7b3  mov  ebx, 0xbfdc38          ; "crc"
0062e7b8  call 0xad9ab0               ; open the named channel
0062e7c8  call 0x625886               ; the CRC producer, with the sink
0062e7d0  call 0xad98f0               ; close it
```

The sink is allocated at `0x00A1611E` (0x28 bytes, vtable `0x00C932C8`) and its write
implementation is `0x00A15F27`, which appends into a **growable heap buffer** - `+0x14` base,
`+0x1C` cursor, `+0x20` capacity, `realloc` at `0x00430150`. There is no `fopen` and no file handle
on the path. The channel name `"crc"` is looked up at `0x00AD9AB0` against a 0x1C-stride table at
`[0x00DF1F40]` whose length is `[0x00DF1F44]`, i.e. EA's `Debug` named-sink registry - the same
registry the crash text is written to and dropped by, per
[`crash-dump.md`](crash-dump.md).

**So enabling `-deepCRC` on a retail build buys a per-frame allocation nobody drains.** Not a log
file. It is left alone.

## 5. The `-x<Subsystem>CRC` exclusions are inert on the stock path

They look like a bisection tool - drop one subsystem out of the checksum and see whether the
desync goes away - and they are gated in a way that stops them working.

Inside the CRC producer at `0x00625886`, each subsystem's contribution is guarded by a pair:

```asm
006258d3  cmp  byte [0xde87c7], bl    ; bl = 0; liteCRC
006258d9  jne  0x6258e3               ; set: include, ignore the exclusion
006258db  cmp  byte [0xde87bc], bl    ; xObjectCRC
006258e1  jne  0x62590a               ; excluded: skip the object list
006258e3  <the object loop>
```

The same shape repeats for the partition manager (`0x00DE4354`), collision (`0x00DE4360`), the
shroud manager (`0x00625983`) and the rest. The exclusion is only consulted when `liteCRC` is
clear - and the plain emitter path **sets `liteCRC` for the duration of the call**:

```asm
0062e7e4  push 0
0062e7e8  mov  byte [0xde87c7], 1
0062e7ef  call 0x625886
0062e7f6  mov  byte [0xde87c7], 0
```

So on the route a retail build actually takes, every subsystem is included unconditionally and the
nine exclusion flags change nothing. They bite only via the `-deepCRC` route in §4, which brings
its own leak. That is why this patch exposes none of them, and why
[`binary-attest.md`](binary-attest.md) is right to say the shroud contribution is "always
included": `-xShroudCRC` cannot take it out of a stock game.

## 6. `-debugCRCFromFrame` / `-debugCRCUntilFrame` do nothing at all

`0x00DA62E4` and `0x00DA62E8` have exactly two references each: the orphaned handler that sets
them (`0x007BA5D3`, `0x007BA5FC`) and the flag reporter that prints them (`0x006307FB`,
`0x00630822`). Nothing in the simulation reads either. Whatever they once bounded, this build
does not consult them - the focus frame in §3 is what survived.

## 7. What this still cannot tell you

Everything [`desync-detection.md`](desync-detection.md) §4 says still holds, and the interval only
moves the last of them:

- **Not which peer diverged.** A finer heartbeat gives you two CRC streams that part at a known
  frame; it does not say whose is wrong. That is what diffing the two players' replays against a
  third opinion is for.
- **Not why.** The first divergent frame is where to start; the state that produced it is earlier.
- **Not silent divergence.** If the mismatch is never exchanged, nothing latches, at any interval.
- **Resolution, now a parameter.** At interval N the declaration is an upper bound N frames wide
  rather than 100. It is still an upper bound.

## 8. Related

- [`desync-detection.md`](desync-detection.md) - the latch at `TheGameLogic + 0x1BC`, the
  declaration routine, and the `CLIENT_DESYNC_*.txt` writer this patch's second switch unlocks.
- [`message-stream.md`](message-stream.md) §1 - the `0x44A` emitter itself.
- [`binary-attest.md`](binary-attest.md) - mixes a `.text` hash into this same CRC on purpose.
- [`headless.md`](headless.md) §5 - the orphaned command-line region every switch above is
  stranded behind.
- `sage_replay.coverage` asserts `crc_interval == 100` across the corpus, which is a statement
  about recordings made by a **stock** build; a replay from a patched one carries the patched
  cadence in its header and reports as a distinct value there.
