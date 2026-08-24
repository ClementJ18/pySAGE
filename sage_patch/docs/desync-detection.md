# Knowing that a client has gone out of sync

Engine build `2.01.2614.37001`. Addresses are VAs (ImageBase `0x400000`, no ASLR); the file offset
is `VA - 0x400000`. Read **statically** on 2026-08-23 with the skill's `explore.py` from a clean
`game_original.dat` (11,346,944 bytes), which carries no patch at any site cited here, and
**confirmed in a live match on 2026-08-24** — see [§5](#5-what-the-latch-did-in-a-real-desync).

**The question.** A match desyncs. An external read-only observer wants to know *when*, to the
logic frame, so it can stop and hand back the state of the frames leading up to it.

**The answer is one byte.** `TheGameLogic + 0x1BC` is zero for the life of a match and becomes 1
the instant this client declares itself out of sync. It is a latch, not a pulse: nothing clears it
short of the next `GameLogic` construction, so a poller cannot miss the edge by sampling late.

## 1. The declaration routine — `0x006290C7`

A `GameLogic` method (`this` in `ecx`, three stack arguments), reached from exactly two call sites,
both inside the message handler at `0x0062A6xx` that touches `TheMessageStream` (`0x00DE6398`):

| site | call |
|---|---|
| `0x0062A6EA` | `push [eax+8]` / `push [ebp+0x10]` / `push [ebp+0xC]`, `ecx = esi` |
| `0x0062A7BB` | `push [edi+0x10]` / `push 0` / `push [ebp+0xC]`, `ecx = esi` |

Its head, and the latch:

```asm
006290c7  mov  eax, 0xb83df0            ; SEH frame
006290d1  sub  esp, 0x120
006290d8  mov  ebx, ecx                 ; this = TheGameLogic
006290da  mov  byte ptr [ebx + 0x71], 1
006290de  cmp  byte ptr [0xde87ca], 0   ; forced-desync-on-frame armed?
006290e5  je   0x6290f5
006290e7  mov  eax, dword ptr [0xda62ec]   ; ... the frame it is armed for
006290ec  cmp  eax, dword ptr [ebx + 0x40] ; ... against the current logic frame
006290ef  jne  0x629648                    ; ... not that frame: say nothing
006290f5  lea  eax, [ebx + 0x1bc]
006290fb  cmp  byte ptr [eax], 0
006290fe  jne  0x6291c7                 ; already declared: skip the box, go on to the rest
00629106  mov  byte ptr [eax], 1        ; THE LATCH
```

**`ebx` is `TheGameLogic`.** `[ebx+0x40]` is compared against a frame global at `0x006290EC`, and
`+0x40` is the logic frame on this build — independently fixed by the desync file writer in §3,
which reaches the same field as `mov eax, [0x00DE412C]` / `mov eax, [eax+0x40]`, and by
`sage_live`'s `EngineLayout.gl_frame`, which is runtime-confirmed.

Past the latch the routine raises the message box, through `TheInGameUI`'s string lookup
(`[0x00DE4B04]`, virtual `+0x3C`) on the two label keys and a display call at `0x0081A375`:

```asm
0062914a  push 0xbfd934                 ; "GUI:DesyncText"
00629161  push 0xbfd924                 ; "GUI:DesyncTitle"
00629172  push 4
00629178  call 0x81a375
```

So the latch and the thing the player sees are the same event, and the latch is written **first**.

## 2. It is cleared once, in construction

A scan of every `+0x1BC` access in `.text` (156 sites, most of them unrelated classes at the same
offset) leaves two inside the `GameLogic` code range:

| site | instruction |
|---|---|
| `0x0063027D` | `mov byte ptr [esi + 0x1bc], bl` — `bl` is 0, immediately after `mov dword [esi+0x1b8], ebx`, in the run of field initialisers that also touches `+0x1C4` |
| `0x006290F5` | the latch above |

One zeroing initialiser and one setter. Nothing resets it mid-match, which is the property a
watcher wants: sampling at 5 Hz cannot step over the transition.

## 3. `CLIENT_DESYNC_<name>.txt` — the file the engine would write, and does not

`0x006CF681` is a second, separate path: a per-client-frame self-check that recomputes this
client's own CRC and compares it against a caller-supplied value, and on a difference appends to a
file.

```asm
006cf692  cmp  byte ptr [0xde87c5], bl   ; gate: 0 -> return immediately
006cf6a9  call 0x441b60                  ; GameLogic::isInGame
006cf6b9  call 0x625886                  ; the frame CRC producer -> esi
006cf6c6  call 0x441b7c                  ; isMultiplayerGame
006cf6d3  cmp  dword ptr [edi], esi      ; expected vs freshly computed
006cf6d5  je   0x6cf80b                  ;   equal: nothing happened
...
006cf73f  push 0xc18464                  ; "CLIENT_DESYNC_%s.txt"
006cf76d  call dword ptr [0xbd0554]      ; fopen(name, "a")
006cf77b  call dword ptr [0xbd01d4]      ; GetLocalTime
006cf7ab  push 0xc18430                  ; "Desync detected on frame %d on %u-%u-%u %u:%u:%u\n\n"
006cf7d8  call dword ptr [0xbd053c]      ; fwrite
006cf7df  call dword ptr [0xbd0560]      ; fclose
```

**The gate is off and cannot be turned on from the command line.** `0x00DE87C5` has exactly one
writer, `0x007BA6D3`, inside the orphaned command-line region
[`headless.md`](headless.md) §5 documents — a handler with no table row, no call site and no
pointer anywhere in the image. Its switch is `-verifyClientCRC` (`0x00BFDD58`), whose only
reference is the flag-reporting function at `0x006307B0`, not a dispatch table.

So on a retail build **no `CLIENT_DESYNC_*.txt` is ever written**, and a watcher must not wait for
one. The byte is writable from outside, and the check it unlocks is pure — a CRC read, a compare,
a file append, none of it simulation state — but the value it compares against comes from a
caller stack local (`lea ecx, [ebp-0x10]` at `0x0063251C`) whose provenance is not established
here. Left alone.

## 4. What this does not tell you

- **Not which peer diverged.** The latch says "this client no longer agrees", nothing more. Only
  the two clients' recorded CRC streams say who moved.
- **Not why.** The first divergent frame is where to *start* looking; the state that produced it is
  a frame or more earlier.
- **Not silent divergence.** If a client desyncs and the mismatch is never exchanged — the match
  ends first, the connection drops — the latch stays 0. Absence of the latch is not proof of sync.
- **Not the moment of divergence.** The latch fires when a *peer's* mismatching checksum arrives,
  and those arrive only every `REPLAY_CRC_INTERVAL` = **100** frames. So the declaration is an
  upper bound on when the simulations parted, never the event itself, and the resolution of this
  instrument is 100 frames. A desync declared at frame 102 means "diverged somewhere in 1..100",
  not "diverged at 102".

## 5. What the latch did in a real desync

Observed 2026-08-24 with `sage-live desync-watch` against live online matches on the 60 fps build,
sampling `TheGameLogic+0x1BC` every logic frame from frame 1:

| match | latch set at | replay `abnormal_end_frame` |
|---|---|---|
| one | frame 102 | — |
| two | frame 103 | **103** |

**The read is right.** The second match's recording carries its own `abnormal_end_frame` of 103 —
the engine's independent record of where that replay stopped — and the latch was observed setting
on the same frame. Two mechanisms with nothing in common agreeing to the frame is what promotes
this from a plausible disassembly reading to a fact.

**Nothing in the local simulation saw it coming.** Both matches paced at 5.0 Hz through the
declaration, and per-seat object counts were static across the twelve frames before it — 1170
objects over six seats, unchanged. That is the expected shape and worth stating so the next reader
does not go hunting for local symptoms: this client's copy of the simulation is *fine*, it simply
no longer matches somebody else's.

**Both landed at the first possible heartbeat.** `crc_interval` is 100 in every replay from this
install, so frame 100 is the earliest a mismatch can be exchanged at all. Two independent desyncs
declaring at 102 and 103 is therefore not a fact about frame 102 - it says both matches were
already divergent before anyone checked, which points at the peers *starting* from different state
rather than drifting into it. A gradual divergence would be caught at some later multiple of 100.

For contrast, a match on the same build and the same day ran 18.5 minutes - eleven heartbeats -
with the latch clear throughout, so the configuration is capable of staying in sync.

## 6. Related

- The CRC that is compared is produced at `0x00625886` and emitted as `MSG_LOGIC_CRC` (`0x44A`)
  from `0x0062E7FD` — [`message-stream.md`](message-stream.md) §1, and
  `LOGIC_CRC_EMIT` in [`../addresses.py`](../addresses.py).
- That same `0x44A` heartbeat is recorded in every replay, which is what makes two players'
  replays of one match diffable after the fact — `sage_replay.replay.OrderType.ChecksumHeartbeat`.
- [`binary-attest.md`](binary-attest.md) mixes a hash of `.text` into that CRC on purpose, so a
  differently-patched peer desyncs through this very path.
