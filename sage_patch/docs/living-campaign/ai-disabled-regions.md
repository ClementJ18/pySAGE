# Why a scenario with `DisableRegions` crashes the War of the Ring AI

Engine build `2.01.2614.37001`, ImageBase `0x400000`. **Read out of crash dumps and the
disassembly, 2026-09-13.** The fix, [`ai-disabled-regions`](../../patches/experimental/ai_disabled_regions.py),
is static only.

## The crash

Three full-memory dumps from `C:\RotWK` (written with the `crash-dump` patch) fault on the same
instruction. Two came from `WOTRScenarioMordor` at 20:48 and 21:03; the third, at 18:25, predates
that scenario, so the crash is not specific to it:

```
ExceptionCode 0xC0000005, read at 0x00000004
00905674  cmp dword ptr [eax + 4], ebx      ; eax = [src] = 0
```

The stack, read by walking saved `ebp`s through the dump's heap:

```
00905643  copy of a 12-byte neighbour list (src = 0x044645CC, all zeroes)
00906431  copy of a region's lists, one 12-byte list after another
009A4205  AI planner                        <- lookup at 0x009A47AA
009008A6  living-world AI per-player state machine, state 3
006BE20A  LivingWorldLogic::updateTurnPhase
006BE50E  LivingWorldLogic::update
```

The 18:25 dump reaches the same copy from the planner's other lookup, at `0x009A5A5E`.

## The unchecked lookup

The planner (`0x009A4205`) walks the regions it knows about - records whose `+0x10` points at a
region info object; the one it died on reads `{31, -1, 0x14}`, region id 31, no owner - and for each
one does:

```asm
009a47a2  push dword ptr [ebp - 0x18]      ; &region id
009a47a5  mov  ecx, ebx                    ; ebx = 0x00DE9F9C, the region graph
009a47aa  call 0x6b4e57                    ; std::map<int, ...>::find
009a47af  add  eax, 0x14                   ; the value - no comparison with the head node
009a47b9  call 0x906431                    ; copy it
```

`0x006B4E57` returns the map's head node when the key is absent, and the head node's value is
zeroes. Its other caller in the AI, `0x00905DA7`, does compare with `[0x00DE9F9C]` and returns
9999 ("unreachable"); the planner's two sites do not.

## Why region 31 is missing: the builder skips disabled regions

`0x00908010` builds the graph, and only while it is empty (`cmp dword [0x00DE9FA0], 0`):

```asm
00908060  mov  eax, [edi]                  ; the region store's regions
00908065  mov  ecx, [eax + ecx*4]          ; region i
0090806c  cmp  byte ptr [ecx + 0x1c2], 0   ; Region::m_enabled
00908073  mov  [ebp - 0x18], ecx
00908076  je   0x009081a0                  ; disabled -> no node, on to the next region
          ...                              ; enabled: a neighbour list per other region, then insert
```

So every region disabled when the graph is built has no node. In `WOTRScenarioMordor` that is 93 of
100, and region 31 (0-based `Eregion`, 1-based `Erebor_Dale`) is one of them either way: disabled
and unowned, matching the `-1` in its info record. Nothing rebuilds the graph once it has entries,
so a region an act enables later never gets a node either.

The graph is cleared by `0x006BCE1F` - at campaign start (`0x006BE0D0`), on load (`0x006BD1F5`)
and on reset (`0x006BD089`, immediately followed by the build at `0x006BD093`).

## The fix

[`ai-disabled-regions`](../../patches/experimental/ai_disabled_regions.py) turns the `je` at
`0x00908076` into six `nop`s. Every region gets a node; the neighbour lists are computed for all of
them exactly as they are today for enabled ones.

The alternative - an end check at both planner sites - needs a cave per site and a decision about
what the planner should do with a region it cannot evaluate, and still leaves later-enabled regions
out of the AI's picture. Including every region answers both.

## Not established

| | question | how to settle |
|---|---|---|
| 1 | Does the AI now plan moves into a region that is still disabled, and is the move refused? | play a scenario with `DisableRegions` on the patched binary and watch the AI's first turns |
| 2 | Are there other readers of the graph that assume enabled-only nodes? | the remaining references to `0x00DE9F9C` in `0x00904000`-`0x0090A000` and `0x009A4000`-`0x009A8000` |
| 3 | Which scenario produced the 18:25 dump? | its campaign manager is not readable - the dump holds no `game.dat` `.data` |
