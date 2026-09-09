# All ShareExperienceBehavior instances

`share-experience-all` is a regular engine patch for ROTWK `game.dat` build
`2.01.2614.37001`. Declare multiple `ShareExperienceBehavior` blocks with distinct
ModuleTags. Every matching runtime behavior receives the same original XP, in the
existing deterministic module order. Each behavior retains its own sharing rules.

```python
from sage_patch import ShareExperienceAllPatch, apply_patches

apply_patches("game.dat.backup", [ShareExperienceAllPatch()], output="game.dat")
```

CLI: `sage-patch apply share-experience-all --help` shows the standard file options.
The patch is registered, exported, detectable and verifiable through the existing
patch framework. It is not marked experimental.

## Scope and evidence

The supplied Ghidra disassembly and runtime observations establish these ROTWK facts:

| Fact | Confirmed value |
| --- | --- |
| Runtime constructor / size | `0x0088314A` / `0x24` |
| ModuleData constructor / size | `0x008830ED` / `0x18` |
| Runtime layout | primary vtable `+0`, ModuleData `+4`, owner `+8`, interface vtables `+0x0C`, `+0x10`, ShareExperience interface `+0x20` |
| ShareExperience interface vtable | `0x00C5ED9C` |
| Interface slot 0 | `0x008832F0`, `ShareExperience(float)`, `__thiscall`, `ret 4` |
| Object module list | null-terminated `BehaviorModule**` at `Object+0x24C` |
| First-match helper | `0x0088305B`, queries `module+0x0C`, virtual slot `+0xA4` |
| Local XP dispatch | `0x00695588` through `0x0069559F`, resumes at `0x006955A0` |

Runtime observations showed two distinct instances per owner:

| Owner | Runtime instances | Shared ModuleData pointers |
| --- | --- | --- |
| `0x0D14DF10` | `0x0CE6BF70`, `0x0CFBAD38` | `0x3226B498`, `0x32271DB8` |
| `0x0D188238` | `0x0D0D93A8`, `0x0D13AED0` | `0x3226B498`, `0x32271DB8` |

These are observations, not addresses embedded in the patch. Parsing and factory
instantiation already support multiple declarations; the first-match dispatch loses
the later instances. No parser, factory, object layout or savegame changes are needed.

## Hook and ABI

Before allocation or mutation, all 24 stock bytes must match:

```text
56 E8 CD DA 1E 00 85 C0 59 74 0D D9 45 08 8B 10 51 8B C8 D9 1C 24 FF 12
```

They decode to `push esi; call 0x0088305B; test eax,eax; pop ecx; je
0x006955A0`, followed by the single interface call using `[ebp+8]` as a float.
The replacement is:

```asm
push dword ptr [ebp+8]
push esi
call DispatchAllShareExperienceBehaviors
add esp, 8
; twelve NOPs, then natural fallthrough to 0x006955A0
```

The helper uses `__cdecl (Object*, float)`, saves EBP and ESI, leaves EBX and EDI
untouched, and allows EAX/ECX/EDX to be clobbered as the stock calls do. It walks the
same null-terminated module array and queries the same virtual slot. For every
non-null result it sets ECX to the returned interface and invokes its slot 0.
It reloads and pushes the original XP bits for **each** invocation, since
ShareExperience mutates its own stack argument. Its `ret 4` consumes that copy;
the hook cleans up the helper's two arguments. No x87 operations are introduced.

The first-match helper `0x0088305B` remains byte-for-byte stock,
so other callers retain first-match semantics. There is no new persistent state, static scratch storage or
serialization surface. Nested invocations have independent stack frames.

## Composition and validation

The read/execute `.sharexp` section is allocated through `allocate_section`, after
existing sections; no file offset or cave RVA is hardcoded. Verification finds it
by name and checks the entire emitted helper and all hook bytes, including padding.
Unexpected signatures and duplicate application fail before modifying the image.

Data-free tests cover the signature, relative call target, fallthrough, section
permissions, unchanged stock bytes, corruption detection and all six application
orders with `maintenance-cost` and `auto-deposit-inflation`. Optional Unicorn tests
execute the emitted hook and helper against synthetic virtual methods, including
empty/mixed lists, multiple matches, volatile-register clobbering and a callee that
overwrites its argument. They check module order, identical XP bits and balanced
stack/nonvolatile registers. Run with `python -m pytest -q
tests/sage_patch/test_share_experience_all.py`; install `unicorn` to run execution tests.

The original 11,346,944-byte `game.dat.backup` was also checked: its complete
dispatch, recipient calculation and full DropOff signatures match; applying and verifying succeeds,
and the stock first-match helper remains unchanged.

The supplied runtime evidence confirms instance creation and the dispatch diagnosis;
it is not an in-game run of this newly emitted helper. Remaining acceptance work is
an in-game multi-behavior XP scenario, save/load and multiplayer/replay checks.
The walk relies on the owner/module array staying alive during sharing and on the
confirmed virtual-call ABI. No additional unconfirmed ROTWK addresses are used.
Deterministic order is preserved, but the simulation result intentionally changes:
all multiplayer peers and replay playback must use the same patch configuration.


## Independent recipient scaling and percentage DropOff

The recipient loop at `0x00883453` writes its scaled XP into `[ebp+8]` twice.
The next recipient therefore compounds both Percentage and DropOff. The replacement
redirects the complete calculation/call window through `0x00883494` to a helper.
It leaves the original argument untouched and uses one private stack float, preserving
the stock float32 rounding after each multiplication. The positive-XP test, tracker
pointer and call flags `(true, true, true, false)` are unchanged. Both paths discard
the private float before rejoining the stock iterator. No SEH/filter locals are reused.

`GetDropOffFactor` at `0x0088325B` receives a six-byte entry trampoline. For nonzero
radius it calls the same `Coord3D::GetLength` (`0x004054F5`) on the same 3D position
difference and computes `1 - clamp(distance / radius, 0, 1) * clamp(DropOff, 0, 1)`.
Zero/negative strength returns exactly 1 without computing distance. The ABI remains
`__thiscall`, ST0 float, `ret 8`; ESI/EBP are saved. For zero radius the displaced
prolog resumes the original function, retaining its original special/NaN behavior.
Finite INI values and ordinary nonnegative radii are the intended domain.

ModuleData fields are Radius `+8`, DropOff `+0x0C`, Percentage `+0x10`, and an
ObjectFilter-like target field `+0x14`; size is `0x18`. Runtime `DropOff=0.5` was
confirmed as `0x3F000000`. Percentage is not clamped and may exceed 1. No curve or
INI fields are added. The exact EA filter type and XP-add function name remain unknown.

All three stock windows (including the complete DropOff body used by the zero-radius
fallback) are checked before allocation. Verification covers all helpers and windows.
Data-free execution tests cover multiple recipients in both orders, Percentage above
one, nonpositive XP, clamped DropOff, 3D distance, radius-zero stock equivalence,
call flags, unchanged original XP and balanced nonvolatile registers/stack/x87 stack.
Existing all-behavior dispatch and nearby-patch composition tests remain in place.
In-game, save/load and multiplayer/replay acceptance still require a game session.
