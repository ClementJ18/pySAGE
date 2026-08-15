# Binary attestation — making a modified `game.dat` desync

Recovered against RotWK 2.01 `game.dat` build `2.01.2614.37001` (ImageBase `0x400000`), 2026-08-14.
Static recovery with `pefile` + `capstone` via [`../scripts/pe.py`](../scripts/pe.py); no runtime
needed for any address below.

**Verdict up front.** Fog of war is **already in the sync hash** — the frame CRC xfers
`TheShroudManager` like every other logic subsystem. So the question this work started from
("could a modified fog of war be made to cause an out of sync?") has a shorter answer than
expected: for a cheat that changes shroud *state*, it already does. What is not covered is a
cheat that changes only *code*, and `binary-attest` covers that by folding a hash of the
image's own executable bytes into the same checksum.

## 1. Fog of war is already attested

`GameLogic::update` computes the frame checksum at `0x00625886` and emits it as `MSG_LOGIC_CRC`
(`0x44A`), the heartbeat [`message-stream.md`](message-stream.md) §1 uses as its worked example.
The producer is a chain of subsystem xfers into an `XferCRC`, each one guarded by a debug flag:

```asm
00625973  cmp  byte ptr [0x00DE87C7], bl   ; -deepCRC     -> include regardless
00625979  jne  0x625983
0062597b  cmp  byte ptr [0x00DE87BF], bl   ; -xShroudCRC  -> exclude
00625981  jne  0x6259a5
00625983  mov  eax, dword ptr [0x00DE4358] ; <- TheShroudManager
00625988  mov  ecx, eax
0062598a  add  eax, 0xc                    ;    its Snapshot base
0062598d  neg  ecx
0062598f  sbb  ecx, ecx
00625991  and  ecx, eax                    ;    null-safe: 0 stays 0
00625993  mov  eax, dword ptr [ebp - 0x58]
00625996  push ecx
00625997  lea  ecx, [ebp - 0x58]
0062599a  call dword ptr [eax + 0x30]      ;    XferCRC::xferSnapshot
```

`0x00DE4358` is `TheShroudManager` — the same global [`fog-of-war.md`](fog-of-war.md) §1 names,
confirmed there by reading the subsystem's own `AsciiString` back at `+0x08`.

**How the flags were found.** Eleven `-x*CRC` command-line strings live in `.rdata`, each
referenced exactly once, from a run of identical five-instruction blocks
(`cmp byte [flag],0` / `je +12` / `push <string>` / `mov ecx,esi` / `call`) at `0x00630700`. That
block echoes the active debug flags; pairing each global with the string beside it names all of
them at once, with no need to find the parser:

| flag global | switch | subsystem xfer'd |
|---|---|---|
| `0x00DE87BF` | `-xShroudCRC` | `TheShroudManager` `0x00DE4358` |
| `0x00DE87C0` | `-xTaintCRC` | `TheTaintManager` `0x00DE435C` |
| `0x00DE87C1` | `-xTerrainLogicCRC` | `0x00DE4938` |
| `0x00DE87C3` | `-xPlayerCRC` | `ThePlayerList` `0x00DE4928` |
| `0x00DE87C4` | `-xAICRC` | |
| `0x00DE87C5` | `-xLWCRC` | |
| `0x00DE87C6` | `-verifyClientCRC` | read at `0x0062E845`, in the emitter |
| `0x00DE87C7` | `-deepCRC` | read at `0x0062589D` and at every exclusion gate |

Each switch **excludes**; absent it, the subsystem is folded in. Default play therefore hashes
the shroud, and `-deepCRC` overrides every exclusion at once.

**The consequence, stated plainly.** A client that writes revealer counts into the shroud grid —
which is what a memory-editor maphack does — diverges from its peers on the very next heartbeat
and goes out of sync with no help from any patch. That was already true before this work started.

## 2. What is *not* covered, and why a state hash cannot cover it

The engine decides visibility at `0x00B4FAB0` ([`fog-of-war.md`](fog-of-war.md) §4). It computes
"not visible", then collapses that to "visible" when the fog byte at `ShroudImpl+0x68` is clear.
The draw path *consults* that answer; it does not produce it.

So there are two entirely different things a cheat can do, and only one of them is state:

| cheat | shroud grid | caught by the state hash |
|---|---|---|
| write revealer counts (`reveal`) | changed | **yes**, already |
| clear the fog byte at `+0x68` | unchanged | no |
| nop the shrouded-drawable branch in the renderer | unchanged | no |
| external process reading the object table | unchanged | no, and never |

The middle two change no simulation state at all: every shroud level is byte-for-byte what an
honest client holds. Hashing more state cannot reach them, because the state is identical. The
only thing that differs is the code.

The last row is unreachable by anything in this document and is worth naming so the patch is not
oversold: lockstep hands every client the whole object table, so a second process that only
*reads* memory — which is what `sage_live` itself is — needs no change to `game.dat` at all. That
is structural to deterministic lockstep, not a gap in any checksum.

## 3. The hook

`MSG_LOGIC_CRC`'s emitter, verbatim from [`message-stream.md`](message-stream.md) §1, with the
two producing paths above it:

```asm
0062e7cd  push ebx
0062e7ce  mov  edi, eax                    ; path A: edi = the frame CRC
...
0062e7e2  jmp  0x62e7fd
0062e7e4  push 0
...
0062e7f4  mov  edi, eax                    ; path B: edi = the frame CRC
0062e7f6  mov  byte ptr [0x00DE87C7], 0
0062e7fd  mov  ecx, dword ptr [0x00DE6398] ; <- the hook site (6 bytes)
0062e803  mov  eax, dword ptr [ecx]
0062e805  push 0x44a
0062e80a  call dword ptr [eax + 0x48]      ; appendMessage
0062e80d  mov  ebx, eax
0062e80f  push edi                         ; <- the value that goes on the wire
0062e810  mov  ecx, ebx
0062e812  call 0x7111e5                    ; appendIntegerArgument
```

`0x0062E7FD` is the **join**: both paths reach it, so one hook covers every route to the emit.

| | |
|---|---|
| patch | `0x0062E7FD`: `8B 0D 98 63 DE 00` → `E9 <rel32> 90` |
| cave | mix a hash of the image's own code into `edi` |
| tail | re-emit `mov ecx, [0x00DE6398]`, then `jmp 0x0062E803` |

**The six bytes can be taken whole.** `0x0062E7E2` jumps to exactly `0x0062E7FD` — the first byte
of the `jmp` that replaces it, which is fine — and a linear disassembly of the enclosing
`GameLogic::update` (`0x0062E4E8`, per [`message-stream.md`](message-stream.md) §4a) finds **no**
branch target in `0x0062E7FE`..`0x0062E802`. The sixth byte becomes a `nop` so that
`0x0062E803` stays an instruction boundary rather than being reached mid-jump.

**Only `edi` is modified.** `eax`, `ecx`, `edx`, `esi` and the flags are saved and restored; the
emitter is mid-way through building a message and `ecx` in particular is about to be
`TheMessageStream`, which is exactly what the re-emitted instruction puts back.

## 4. What is hashed

Two ranges, folded with FNV-1a over little-endian 32-bit words:

| range | |
|---|---|
| `.text` | `0x00401000`, `0x007CF000` bytes |
| the cave's own code | `.attest + 0x10` through `.attest + 0x200` |

FNV-1a is chosen for the shape of its inner loop, not its statistics — `xor eax,[esi]` then
`imul eax, eax, 0x01000193` is two instructions with a carried dependency, so there is no table
to place in the cave, and unlike an additive sum there is no way to compensate for an edit by
adjusting bytes elsewhere. The whole fold is ~135 bytes of code.

**The value is a property of the file, not a secret of the process.** The image carries no
`.reloc` and does not set `DYNAMIC_BASE`, so the loader maps `.text` at `IMAGE_BASE` and never
rewrites a byte of it: what the running game folds is what is on disk.
`sage_patch.patches.binary_attest.expected_hash` recomputes it offline, so two people can compare
binaries without either of them starting a game — and `sage-verify attest` reads the live value
out of a running process to check that the running game is the file it claims to be.

Computed once and cached behind a flag in the section (a flag rather than "nonzero means done",
so the one image in four billion that folds to zero is not rehashed every heartbeat). The fold is
~8 MB and costs a few milliseconds, once, at the first heartbeat.

**Including the cave's own code** means an attacker wanting the honest value back has to edit the
routine that computes it, rather than nop a branch somewhere in `.text` and leave the attestation
untouched. It does not make that impossible — see §6.

## 5. Playback is exempt

When `TheRecorder`'s `m_mode` (`+0x1C`) reads `PLAYBACK` (1), the routine leaves `edi` alone.

The reason is that a replay is watched against its **own recorded** checksums. Mixing during
playback would make every recording from any other build read as a mismatch, which would break
watching old replays and would break [`sage_verify`](../../sage_verify/README.md), whose whole
method is to follow a replay playing back on a live client.

**It cannot be abused to evade.** A live game has no playback recorder, and a client that somehow
suppressed the mix would publish an *unmixed* checksum while its peers published mixed ones —
the same desync by the other route. The exemption can only cause self-desync, never concealment.

That mode is also the reason the emitter carries a fourth Boolean argument: `0x0062E831` calls
`0x007B0F25` (`mov eax,[ecx+0x1c]; ret`) on `TheRecorder` and reduces it with
`dec/neg/sbb/inc` — the idiom for `mode == 1` — so the recorded message already says whether it
came from a playback.

## 6. What this buys, and what it does not

**It buys:** every code-level cheat now needs a second, separate edit inside the attest routine
to stay quiet. A casually modified binary — a downloaded "no-fog" `game.dat`, a hex-edited
branch, a build with a different mod version — fails at the first heartbeat, visibly, through the
engine's own `GameCRCMismatch` path rather than by nobody noticing.

**It does not buy:** protection against someone who reads this document. The hash is computed by
the client it attests; whoever can patch the fog branch can patch this routine to return the
value an honest build produces. That is one more edit, not a wall. Client-side integrity checks
always lose to a debugger, and the honest claim is that this raises the floor, not the ceiling.

**It buys nothing at all** against an external read-only overlay, for the reason in §2.

**The behavioural approach does not have this weakness**, because it runs on the observer's
machine after the fact and there is nothing in it for the cheater to patch. That is
[`sage_verify`](../../sage_verify/README.md), and it is the other half of this work.

## 7. Operational consequences

- **Every peer must run the byte-identical `game.dat`.** That is the property being enforced, so
  it is not a side effect — but it does mean a mod shipping this patch has committed to
  lockstepping its binary across its whole player base.
- **Applying any other patch changes the attested value**, including applying the same set in a
  different order: `allocate_section` appends past the highest existing section, so the cave's
  address moves and the hook's relative displacement with it. Two builds with the same patches
  in a different order are different files and are treated as such.
- **Replays from an attested build carry mixed checksums.** They play back correctly on that
  build (§5) and their `0x44A` values will not match an unpatched build's for the same inputs.
- **A protector that rewrites `.text` in memory would break this.** The image carries SecuROM-era
  sections (`stxt774`, `stxt371`, `.mackt`), and the assumption in §4 is that none of them
  modifies `.text` after load. This holds for the binary measured here — `expected_hash` and the
  live value agree — and `sage-verify attest` is the check to run if that is ever in doubt on
  another build.

## 8. Reproduction

```
python sage_patch/scripts/pe.py                       # section table
sage-patch apply binary-attest --in game.dat --out patched.dat
sage-patch verify binary-attest --in patched.dat
python -c "import pathlib; from sage_patch.patches.binary_attest import expected_hash; \
           print(hex(expected_hash(pathlib.Path('patched.dat').read_bytes())))"
```

Method, in the order it worked:

1. Regex `-x[A-Za-z]*CRC\0` over the image → eleven switch strings in `.rdata`.
2. `find_imm_refs` on each → one reference apiece, all inside one block at `0x00630700`,
   which pairs each switch with the `.data` global beside it.
3. `find_imm_refs` on those globals → the second reader of each is inside `0x00625886`, the CRC
   producer, which is what says the flags gate checksum contributions rather than logging.
4. Read the producer's xfer chain and match each guarded block to its subsystem global; the
   shroud manager's is `0x00DE4358`, already named in [`fog-of-war.md`](fog-of-war.md).
5. For the hook: linear-disassemble `GameLogic::update` from `0x0062E4E8`, collect every branch
   target, and confirm none lands inside the six bytes at `0x0062E7FD`.
