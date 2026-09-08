# `HeroBuildOrder`, and when the skirmish AI spends its purse on a hero

How the skirmish AI decides which hero to recruit next, why it does that from the first minute of
a match, and where a per-hero "not before N seconds" gate goes. Targets RotWK
`game.dat` 2.01.2614.37001.

The patch built on this is [`ai_hero_build_delay.py`](../patches/ai_hero_build_delay.py).

## 1. The keyword

`HeroBuildOrder` is row 29 of the `ArmyDefinition` field-parse table at `0x00C52B40`:

```
[29] 'HeroBuildOrder'  parse=0x0042EED6  userData=0  offset=0x8C
```

`ArmyDefinition` itself is a top-level INI block (`0x00DADAA8` names it, `0x0083027B` parses it):
`operator new(0xEC)`, construct at `0x0082FF49`, `INI::parseFields` against `0x00C52B40`, then
insert into `TheArmyDefinitionManager` (`0x00DE8BEC`, named at `0x0063C416`) keyed by the block's
own `Side`. `0xEC` is exactly the field table's extent, so the struct has no members the keywords
do not name.

`0x0042EED6` is the generic **string-list** parser, shared with `OffensiveBuildings` and
`ScavangedResourceBuildings`: it erases the target vector and hands
`INI::parseAsciiStringVectorAppend` (`0x0042E59E`) the token loop. So `ArmyDefinition+0x8C` is a
`std::vector<AsciiString>` — *names*, not resolved templates — and nothing resolves them at parse
time. That is what makes a `Name:Seconds` token cheap to support: the delay can be stripped and
recorded while the list is still text, and every consumer downstream then sees a stock list.

Two references name the table, and a patch that repoints one row must find it through them rather
than through the constant: `0x00830103` (`mov eax, 0xC52B40`, a getter) and `0x008302A0`
(`push 0xC52B40`, the `parseFields` call).

## 2. Who reads the list

`ArmyDefinition+0x8C` is touched in exactly two places in `.text` — the constructor
(`0x0082FFEC`) and the destructor (`0x00830198`). Every consumer works from a **copy**, made
once at `0x009A10D8`:

```
009a10d8  push esi / push edi
009a10da  mov  esi, ecx                 ; the AI's hero builder
009a10dc  call 0x009a0383               ; -> the AI data this player runs on
009a10e1  mov  eax, [eax+0x160]         ; -> its ArmyDefinition
009a10e7  add  eax, 0x8c                ; -> &HeroBuildOrder
009a10ec  lea  edi, [esi+0x4c]
009a10f2  call 0x004bd2d5               ; vector<AsciiString>::operator=
009a10fa  call 0x0090ce35               ; the player's created hero, if any
009a1111  call 0x0042d8ee               ; ...appended to the same list
```

So **`builder+0x4C` / `+0x50` is `HeroBuildOrder`**, plus the player's Create-A-Hero at the tail
when they have one. The builder is a sub-object of `AIPlayer` at `+0x38` (`0x008F06CB`,
`lea ecx, [edi+0x38]`), and the list is logic state: `0x009A11C8` xfers it, so it is saved into
a `.sav` and folded into the per-frame CRC.

Its other fields, as far as this patch needs them:

| offset | what |
|---|---|
| `+0x08` | map of buildable thing → producer, filled by `0x009A0838` |
| `+0x14` | the heroes already queued, counted by name at `0x009A0566` |
| `+0x30` | `Player*` |
| `+0x38` | the hero index currently being worked toward, `-1` for none |
| `+0x3C`/`+0x40` | `vector<int>` of indices already requested and not yet delivered |
| `+0x4C`/`+0x50` | **the hero build order** |

## 3. Picking a hero: `0x009A05DB`

`pickHeroIndex` returns an index into the list at `+0x4C`, and has three rules in order:

1. **Retry.** Walk `+0x3C` — the indices a request was already made for. The first whose hero is
   neither already fielded (`0x008E3FD6`) nor already queued (`0x009A0566`) is taken, erased from
   `+0x3C`, and stored in `+0x38`.
2. **Anything.** If `+0x38` is still `-1`, `GameLogicRandomValue(1, count-1)` at `0x009A066C`.
   The range starts at **1**, not 0, because position 0 is the Ring-hero slot.
3. **The Ring overrides both.** `0x009A06A5` asks the player for the science named at
   `0x00C795B0`; holding it forces `+0x38` to `0`.

Rule 2 is the whole of the AI's judgement about *which* hero. There is no cost term, no phase
term, and no clock: on the first frame it is asked, every hero in the list is equally likely.

## 4. Committing to it: `0x009A0993`

`createHeroBuildRequest` is the only caller of `pickHeroIndex`, and has exactly one caller of its
own, `0x009A1063`:

```
009a1051  call 0x009a03a1              ; should a hero be considered at all?
009a105f  je   0x009a106f
009a1063  call 0x009a0993              ; the hero request
009a106d  jne  0x009a107d
009a106f  call 0x009a0f66              ; ...otherwise a unit request
```

That shape matters for the gate: a hero request that answers NULL is **not** a wasted tick. The
AI falls straight through to its unit builder in the same call.

Inside `createHeroBuildRequest`:

```
009a09ca  mov  eax, [esi+0x4c]
009a09cd  cmp  eax, [esi+0x50]
009a09d0  je   0x009a0b15              ; empty list -> NULL
009a09d8  call 0x009a05db              ; eax = pickHeroIndex()
009a09dd  mov  ecx, [esi+0x4c]
009a09e0  lea  edi, [ecx+eax*4]        ; edi = &list[idx]
009a09e3  mov  ecx, [0x00de4a40]       ; TheThingFactory
009a09e9  push edi
009a09ea  mov  [ebp-0x20], eax         ; the index, kept for the retry list
009a09ed  call 0x006d1305              ; findTemplate
   ...
009a0a09  cmp  [ebx+0x628], eax        ; is the hero affordable?
009a0a37  jne  0x009a0ae1              ; already fielded or queued -> reject
009a0a3f  je   0x009a0ae1              ; no producer for it -> reject
   ...
009a0ad7  call 0x0090be00              ; success: push idx onto the retry list at +0x3c
009a0ae1  or   dword [esi+0x38], -1    ; reject: forget the choice, so the next tick re-picks
009a0ae5  mov  edi, [ebp-0x14]
009a0aea  je   0x009a0b15              ; -> NULL
```

The cost test at `0x009A0A09` is the only thing standing between the AI and an early Gandalf, and
it is not a policy — it asks whether the purse currently covers the hero, so the AI saves up and
then spends everything the moment it can. That is the behaviour this patch exists to bound.

## 5. Where the gate goes

`0x009A09E3` — the six bytes `8b 0d 40 4a de 00` between "the name is resolved" and "the template
is looked up". Four properties make it the site:

- **`edi` holds the hero's name** and nothing has been committed yet. No queue entry, no cost, no
  producer search.
- **`0x009A0AE1` is the engine's own rejection edge**, reached from two stock branches at the same
  stack depth, so a gate can hand a rejected hero to it and inherit the whole unwind for free.
  `[ebp-0x14]` — the local it reads two instructions later — is zeroed at `0x009A09B6`, before the
  hook, on every path.
- **Rejecting resets `+0x38` to `-1`**, which is what makes the delay per-hero rather than a stop.
  The next tick re-picks, so the other heroes in the list stay reachable while one is on the clock.
- **Nothing branches into the window.** A sweep of every branch displacement and imm32 in `.text`
  finds no inbound edge at `0x009A09E3`..`0x009A09E8`; the only way in is fallthrough from the
  `lea` above it.

`eax` is live across the hook — it is the index, and it is stored to `[ebp-0x20]` one instruction
*after* the site — so a cave here must preserve it. `ebx`, `ecx` and `edx` are dead (`ecx` is
about to be overwritten by the displaced instruction), and nothing downstream reads flags.

## 6. The clock

RotWK simulates at **5 logic frames per second** — `0x00D9F608` holds `5`, and the `30` four bytes
above it at `0x00D9F60C` is the *client* rate. `TheGameLogic` (`0x00DE412C`) counts logic frames at
`+0x40` from zero at the start of a match, so a delay in seconds is `frame < seconds * [0x00D9F608]`,
with the rate read from the global rather than baked in.

## 7. What a delay cannot key on

The list a builder walks is a copy, and the only thing the gate holds at `0x009A09E3` is the
hero's name. So a recorded delay is keyed by **name**, through
`TheNameKeyGenerator::nameToKey` (`0x0049F474` on `0x00DD90E4`), which is the same interning the
engine itself applies to these names at `0x009A08B6` and `0x009A0948`.

The consequence is that a delay is global to a hero name, not per-`ArmyDefinition`: a name listed
by two factions with two different delays keeps the last one parsed. Keying on the
`ArmyDefinition` instead would be exact — the gate could re-derive it through `0x009A0383` — but
those objects are re-allocated whenever the block is parsed again, and a recycled pointer would
silently hand one faction another's delay. A name cannot be recycled, so name-keyed is the reading
that cannot be wrong about something else.

## 8. What is still open

- **Not runtime-verified.** Everything above is read out of the machine code. Section 4's claim
  that a NULL hero request costs the AI nothing is read off `0x009A1051`'s branch structure, not
  observed.
- **`0x009A03A1`** — the "consider a hero at all?" predicate ahead of `createHeroBuildRequest` —
  has not been disassembled. It gates how *often* the delay is consulted, not what it answers.
- **`0x009A0838`'s second loop** walks the same hero list to fill the builder's producer map at
  `+0x08`, and is deliberately left alone: knowing *where* a hero could be recruited costs nothing
  while the gate refuses to recruit it.
- **The Create-A-Hero appended at `0x009A1111`** is not an `ArmyDefinition` entry, so it can never
  carry a delay.
