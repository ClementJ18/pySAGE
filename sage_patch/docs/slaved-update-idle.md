# Deterministic SlavedUpdate idle intervals (RotWK 2.01)

`SlavedUpdateIdlePatch` alternates independent rest and wandering phases when
`GuardWanderRange > 0`. It suppresses only the optional `JA` at `0x008A615A`.
It never cancels an order or selects/resets an animation. The normal drawable
chooses idle animations; animation completion is not guaranteed.

```python
from sage_patch import SlavedUpdateIdlePatch, apply_patches

apply_patches(
    "game.dat.backup",
    [SlavedUpdateIdlePatch(
        wander_min_ms=10000,
        wander_max_ms=25000,
        idle_min_ms=2500,
        idle_max_ms=9000,
    )],
    output="game-slaved-idle.dat",
)
```

Equivalent CLI:

```console
python -m sage_patch apply slaved-update-idle --wander-min-ms 10000 --wander-max-ms 25000 --idle-min-ms 2500 --idle-max-ms 9000 --in game.dat.backup --out game-slaved-idle.dat
```

Defaults: wandering 6000..14191 ms, rest 3000..7095 ms. All endpoints are inclusive.
Only integers (not booleans) in 1..86400000 ms are accepted, with minimum <= maximum.
Each endpoint is converted in Python by `(ms + 199) // 200`, rounding up to the
200-ms simulation grid. Sampling is uniform modulo bias over the resulting inclusive
**frame** range, not over every millisecond followed by rounding. Defaults therefore
become wandering 30..71 frames and rest 15..36 frames. Even 1 ms becomes one frame;
two distinct endpoints may round to the same frame. No runtime float conversion occurs.
The one-day cap means at most 432000 frames, well below 2^31. Detection and `.sagepatch`
manifests recover all four original millisecond parameters, including their exact endpoints.
The `.slvidle` format marker is `SLVIDL02`; rebuild from the clean binary when replacing
an earlier version, rather than applying over an already installed hook.

## RotWK derivation

Inspected the RotWK reference executable, 11,346,944 bytes, image base 0x00400000.
SHA-256: `5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`.
All constants and original-byte contracts live in `sage_patch/addresses/ai.py`,
re-exported by the existing `sage_patch.addresses` package (there is no single
`addresses.py` in this repository). No BFME2 addresses were used.

The experiment's offsets are **correct** for this binary. Ghidra local names are
not literal EBP displacements: the saved frame pointer affects its stack naming.
The actual instructions establish:

| Instruction | Meaning at the hook |
| --- | --- |
| `008A5D07 mov esi,ecx`; `008A5D10 mov [ebp-8],esi` | `[ebp-8]` = embedded Update interface, complete module +0x10 |
| `008A5D4F mov ebx,[esi-8]`; `008A5D5B mov [ebp-4],ebx` | `[ebp-4]` = owner Object, complete module +8 |
| `008A5D55 mov edi,[esi-0xC]`; `008A5D58 mov [ebp-0xC],edi` | `[ebp-0xC]` = ModuleData, complete module +4 |
| `008A5686 mov ecx,[esi+8]`; `008A5689 mov ebx,[esi+4]` | Guard routine independently corroborates owner/data layout |
| `008A56A7 mov eax,[ebx+0x10]`; integer multiplication and `fild` | GuardWanderRange is a signed integer, not a float |
| `008A5123 mov eax,[ebx+0x74]` | ObjectID of the supplied Object; owner ID uses the shared `OBJECT_ID` constant |

The hook replaces `77 25 8B 45 F4`. Its first instruction tests the original flags:
`JBE` goes directly to the displaced `mov eax,[ebp-0xC]` and then `0x008A615F`.
When original JA is true, disabled wandering or an active wandering phase restores
registers/flags and goes to `0x008A6181`. Rest restores the same state and executes
the displaced MOV/fallthrough. There are no floating-point comparisons in the hook.

The original fallthrough at `0x008A615F..0x008A617F` compares squared owner/master
distance with squared `ModuleData+0x0C` (GuardMaxRange). It can still branch to
`0x008A6181` during rest when that range is exceeded. The guard call at `0x008A61D1`
and separate leash call at `0x008A6261` remain intact. Other entry paths including
the guard-object branch at `0x008A6106..0x008A612C` bypass this hook.

## State and lifecycle

A dynamically allocated `.slvidle` section holds configuration, a 4096-entry table,
and generated code. Entries are 32 bytes: complete module pointer, ObjectID,
32-bit deadline frame, phase (0 idle, 1 wandering), per-entry PRNG, reserved word,
initialization flag, padding.
The table occupies 128 KiB. Linear probing resolves collisions. Tombstones preserve
probe chains; they are reused only after checking for an existing key. A full table
leaves additional instances on stock behaviour. Existing entries are never evicted.
The table never dereferences its stored keys; it compares them with a currently live
module supplied by the engine. Multiple modules sharing ModuleData remain independent.

Constructor `0x008A4F67` and destructor `0x008A4EFC` detours invalidate a matching
entry and replay all displaced instructions. This protects even reuse of both ID and
address. A changed ObjectID also reinitializes an entry. First use starts in rest.
The SlavedUpdate snapshot entry `0x008A51F6` invalidates only while loading, using the
Xfer virtual predicate at +4. The stock UpdateModule snapshot at
`0x00850C8D..0x00850C98` uses this same predicate to reset its wake frame after load.
Save/checksum calls leave the patch state intact; no save format fields are added.
Phases restart after loading rather than being serialized: the next eligible update
starts idle at the restored simulation frame, with an ObjectID-derived seed. This makes
both clients agree even if their pre-load timer histories differed. Saving and checksum
transfers never reset phases. Reloading does not reproduce the exact pre-save phase;
all clients must participate in the same load. New games use the normal constructor/
destructor lifecycle. A changed ID and full address/ID reuse are both covered.

All hooks preserve GPRs and EFLAGS apart from displaced stock instruction effects.
The snapshot predicate call additionally preserves x87, MXCSR and XMM registers using
aligned FXSAVE/FXRSTOR storage on the stack. The update cave uses only integer arithmetic
and its private lookup routine: no OS calls, imported timers, global gameplay RNG,
x87 or SSE operations. A null GameLogic pointer leaves state and stock behaviour intact.
Every hook and relevant surrounding contract is checked before section allocation,
so conflicting patches, a second application and a mismatched build fail before mutation.
Caves and jumps use the existing `Asm` and PE section allocator, with checked rel32 encoding.

## Simulation clock and deterministic randomness

The patch reads `[*THE_GAME_LOGIC + GAME_LOGIC_FRAME]`, using the existing central
constants `THE_GAME_LOGIC = 0x00DE412C` and `GAME_LOGIC_FRAME = 0x40`. The pointer
is dereferenced; the global's address is never treated as a counter. The timebase is
five logic frames per second, independently of rendering speed and wall-clock speed.

Additional named evidence in the address package includes `GAME_LOGIC_SCHEDULE_UPDATE`
(0x00850C32), `GAME_LOGIC_SCHEDULE_ABSOLUTE_CANDIDATE` (0x0062B921), and the
DeletionUpdate constructor/lifetime-selection/update addresses. The candidate name does
not assert a fully recovered scheduler API. Existing `INI_PARSE_DURATION` (0x0073A429),
`SCRIPT_TIMER_FRAMES_PER_MS` (0x00D9F610), and `LOGIC_FRAMES_PER_SECOND` (0x00D9F608)
are reused rather than duplicated. Reviewed stock evidence:

- `00850C32 mov eax,[00DE412C]`; `00850C37 mov edx,[eax+40]`, then add the update interval.
- `0088B759 mov ecx,[00DE412C]`; `0088B75F mov ecx,[ecx+40]`, then add the selected lifetime.
- `0073A450 fmul [00D9F610]`, then ceil and integer conversion. The stored factor is
  `0ad7a33b` (float approximately 0.005); the logic rate dword is 5.

These instruction windows and initial rate values are byte-checked. The patch targets
the confirmed 5-Hz simulation; a mod that changes that rate changes the physical meaning
of a frame and is outside this fixed conversion contract.

Deadlines use `signed32(currentFrame - deadlineFrame) >= 0`. Wraparound is supported
provided observations are less than 2^31 frames apart (about 13.6 years at 5 Hz).
Identical-frame calls never consume extra random numbers. An expired phase toggles once
on the next eligible hook visit and schedules from **that actual frame**, not from a
call count. There is no loop catching up unobserved phases. Pausing the simulation freezes
timers; changing simulation speed affects elapsed wall-clock time, not phase decisions.

The specified per-instance PRNG is:

```text
initial state = ObjectID XOR 0x9E3779B9
on initialization or a phase transition:
    state = (1664525 * state + 1013904223) modulo 2^32
    sample = state XOR (state >> 16)
    durationFrames = minFrames + sample % (maxFrames - minFrames + 1)
```

This is a small deterministic generator rather than a stored explicit phase counter:
its state advances once per phase, giving the same stream for the same ObjectID and
transition history. Pointer values, table indices, process state, system time and
wall-clock observations never enter this calculation. The global gameplay RNG is not
called or reseeded. Different IDs generate distinct PRNG streams; individual durations
can coincide, as expected for a finite interval. Modules sharing an owner can have equal
streams while retaining completely independent state and deadlines.

Pointer hashing only locates state. The table never iterates over entries to update
simulation state. Every probe is bounded by the **entire** table size, with no partial
search or real-time budget. Thus different collision patterns cannot change success,
existing-state selection, phase or sampled duration. Before capacity exhaustion even
cross-object update reordering does not affect decisions. At capacity, the first 4096
eligible live instances retain entries; additional instances follow stock behaviour until
a slot becomes available. Which instances gain capacity relies on the synchronized
engine's lifecycle/update order, not local pointer order. Both clients need the same
logical lifecycle and per-instance update sequence, as with other lockstep AI state.
This bounded fallback is explicitly tested and never evicts a live entry.

## Multiplayer limits

The generated timer decisions are deterministic for identical IDs, configuration,
simulation frames and synchronized lifecycle/update histories, even with different local
memory layouts. This removes the timer's known wall-clock and pointer-seed desync sources.
It is **not a blanket guarantee of multiplayer compatibility**: both clients need the
same patched build and parameters; patches affecting scheduling, IDs, AI or the 5-Hz
rate must also agree. The side table is not part of the game's checksum/save payload,
so checksums do not directly expose a timer mismatch. Load reinitialization is deliberate.
Capacity overflow and synchronized load/deletion behaviour still need in-game stress tests.

## Validation

Data-free tests execute the generated x86 using Unicorn and inspect it with Capstone:

- Every original JA truth case, zero/negative wander range, GPR/EFLAGS/stack preservation,
  snapshot-call x87/SSE preservation, and the original near/far master-distance fallthrough.
- Ceil conversion, sub-frame/equal/custom/default bounds, unsigned frame wrap, frozen-frame
  repeated calls and sparse updates. No main-hook OS/RNG/float call is permitted.
- Two isolated clients over 1000 update rounds and 16 IDs with different object, stack,
  GameLogic and cave addresses, deliberately different collisions, and reversed cross-object
  iteration; PRNG, phase and deadline agree byte-for-byte after excluding local keys.
- Independent streams, tombstone collision chains, full-table fallback, deletion, constructor
  reset, ID/address reuse, and deterministic post-load restart despite different prior history.
- Atomic PE contract failures, relocated caves, CLI options, parameter detection, wrong
  configuration rejection and duplicate application. The `full` test applies and verifies
  against the local original RotWK executable.

The user reports the prior single-player mechanism working successfully. The deterministic
revision has not been tested in a running two-client match. Remaining gameplay acceptance:
standard wander/rest animations; many slaves; moving master; combat; repair/SpawnBehavior/
SlaveWatcherBehavior; death/respawn; save/load on both clients; pause and changed game speed.
Emulator checks do not establish those complete engine scenarios or multiplayer compatibility.
