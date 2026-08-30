# `MergePlayerArmy` and `DespawnArmy` — what BFME1's verbs do, and how RotWK gets them back

Engine build `2.01.2614.37001`, ImageBase `0x400000`, against `C:\BFME1\lotrbfme.exe`. Static
analysis 2026-08-27. **Nothing here has been run in game.**

**Built.** The scope below became [`campaign-army-verbs`](../../patches/experimental/campaign_army_verbs.py)
— both verbs in one patch, since they share every piece of scaffolding. What the build changed
about the scope is recorded in §9.

This closes unknown 4 of [`bfme1-act-verbs.md`](bfme1-act-verbs.md) — *"what does BFME1's
`MergePlayerArmy` runtime actually move — templates, or a sub-army object?"* Neither: it moves
**`ArmyEntry` records**, and `SplitArmyTemplate` is a manifest naming which ones.

## 1. BFME1, traced end to end

```
verb table row          0x010EC9D8 + n*16, parser 0x007B8500
field table             0x010ED258
    SourceArmy          +0x04  AsciiString
    SplitArmyTemplate   +0x08  AsciiString
    DestArmy            +0x0C  AsciiString
    SplitArmy           +0x10  Bool
append                  0x007B19E0 -> act+0x6C vector, stride 0x14
executor                0x007ADC30 -> once per record:
                            [0x012F1024]->merge(rec+0x04, rec+0x0C, rec+0x08, rec[0x10])
implementation          0x007B4510
```

`0x007B4510`, with the thunks resolved:

```c
src = TheLivingWorld[0x012F0898]->findPlayerArmyByName(SourceArmy);   // 0x00783870
dst = TheLivingWorld[0x012F0898]->findPlayerArmyByName(DestArmy);
if (!src || !dst) return;
if (!SplitArmy) { src->absorbInto(dst); return; }                     // 0x00765570
tmpl = this->findPlayerArmyByName(SplitArmyTemplate);                 // 0x007B43D0
if (!tmpl) return;
tmpl->splitOut(src, dst);                                             // 0x00765630
```

**`absorbInto` (`0x00765570`)** appends every record of `src`'s roster (`src+0x30..+0x34`, stride
`0xB4`) to `dst`'s. It does **not** empty the source — that is why BFME1's campaign pairs the merge
with `DespawnArmy` on the next line.

**`splitOut` (`0x00765630`)** walks the *manifest's* records; for each, finds the entry of the same
`ThingTemplate` in `src`, appends it to `dst`, then erases it from `src` by shifting the tail down
and shrinking `end` by `0xB4`. So the manifest is a list of names, and the records that move are
the source's own.

### The INI says the same thing, unambiguously

`gondorcampaign.ini`, the Fellowship breaking up outside Fangorn:

```
SpawnArmy   Name = MerryAndPippin   PlayerArmy = MerryAndPippinPlayerArmy   ...   End
MergePlayerArmy
    SourceArmy        = FellowshipPlayerArmy
    DestArmy          = MerryAndPippinPlayerArmy
    SplitArmyTemplate = MerryAndPippinSplitArmy
    SplitArmy         = Yes
End
```

with, further down the same file:

```
LivingWorldPlayerArmy  Name = MerryAndPippinPlayerArmy   DisplayNameTag = LWA:Fellowship  End
LivingWorldPlayerArmy  Name = MerryAndPippinSplitArmy
    ArmyEntry { ThingTemplate = RohanMerry;  Quantity = 1 }
    ArmyEntry { ThingTemplate = RohanPippin; Quantity = 1 }
End
```

The destination is declared **empty** and gets filled by the act. All three names are
`LivingWorldPlayerArmy` blocks — not `SpawnArmy` names, which in that file are `Fellowship`,
`Eomer`, `Isengard_1` and so on.

## 2. Why RotWK cannot copy that literally

BFME1 mutates **templates** because templates are the only strategic state it has: every battle
re-instantiates an army from its roster and nothing writes back
([`hero-permadeath.md`](hero-permadeath.md)).

RotWK inverted that. A live army's roster is its own object, built in the army constructor
(`0x0071BC70`): `operator new(0x68)` → `0x00810FBE` → stored at `army+0x78`, then seeded from the
template by `0x0071AD41` and **written back after every battle** by the harvest at `0x00811E1F`.

So in RotWK a template is a seed, not the state. Mutating `FellowshipPlayerArmy` would change what
armies spawned *later* contain and do nothing to the army standing on the map. **`SourceArmy` and
`DestArmy` must therefore name live armies by `ScriptingName`**, and only `SplitArmyTemplate` stays
a `LivingWorldPlayerArmy`.

That is also what Edain already assumes. `wotrscenarioangmar.inc`, commented out with
`; Doesn't work ;( - Necro`:

```
; MergePlayerArmy
;     SourceArmy = Zaphragor_Army          <- a SpawnArmy ScriptingName
;     DestArmy = WitchKing_Army            <- a SpawnArmy ScriptingName
;     SplitArmyTemplate = ZaphragorSplitArmy
;     SplitArmy = Yes
; End
; DespawnArmy = Zaphragor_Army
```

**This is a deliberate divergence from BFME1 and the one design decision in the patch.** It should
be stated in the patch description, because a mod porting BFME1 campaign INI verbatim will hand it
template names and get nothing.

## 3. The RotWK primitives — all present, all verified

`sizeof(LivingWorldPlayerArmy) = 0x68`, and **the live roster container is the same class as the
INI template**: `0x007B98EC` strides its store by `0x68`, `0x0071BC70` allocates `0x68` for
`army+0x78`, and `0x0081176F` deep-copies one onto the other field for field.

| what | address | notes |
|---|---|---|
| `TheLivingWorldLogic` | `0x00DE4950` | |
| `TheLivingWorldCampaignManager` | `0x00DE87AC` | holds the `LivingWorldPlayerArmy` store at `+0x20..+0x24` |
| `findArmyByScriptingName(AsciiString*)` | `0x006B53A4` | thiscall on `TheLivingWorldLogic`, `ret 4`, walks `+0x8C..+0x90` |
| `findPlayerArmyByName(AsciiString*)` | `0x007B98EC` | thiscall on the campaign manager, compares `entry+0x18` (`Name`) with `0x004065AA` |
| roster container | `army+0x78` | records at `+0x40..+0x44`, stride 8, the record pointer at element `+4` |
| `getRecord(index)` | `0x0080F590` | thiscall on the container |
| `cloneAndAppend(record*)` | `0x0081205B` | allocates `0xD8`, copy-ctor `0x0081019B`, appends. **Zero direct callers — reached by vtable, so confirm it is what it looks like before relying on it** |
| `appendExisting(record**)` | `0x00811951` | takes a reference, bumps `record+0xC0` |
| `eraseAt(&out, index)` | `0x00810840` | |
| record fields | | `+0x04` `ThingTemplate` AsciiString, `+0xA0` `Quantity`, `+0xC0` refcount, `+0xD5` `Default` |
| `AsciiString` ctor / dtor / compare | `0x004374E0` / `0x00435D50` / `0x004065AA` | already named in `addresses.py` |
| destroy an army | `0x006B9679` | for the optional `DespawnSource`, below |

## 4. The blocker, and why it does not stop the patch

**The Act struct is `0xB8` bytes and full.** Its constructor `0x0096E5E9` initialises a vtable at
`+0x00`, the act's name (`AsciiString`) at `+0x04`, **fourteen** 12-byte vectors at `+0x08`,
`+0x14`, `+0x20`, `+0x2C`, `+0x38`, `+0x44`, `+0x54`, `+0x60`, `+0x6C`, `+0x78`, `+0x84`, `+0x90`,
`+0x9C`, `+0xA8`, `JumpToAct`'s `AsciiString` at `+0x50`, and `EndAct`'s bool at `+0xB4`. The
campaign's act vector strides by `0xB8` (`0x00934188`), so **three padding bytes are all that is
spare** — no room for a fifteenth vector.

Growing the struct would mean rewriting the constructor, the copy-constructor, the destructor
(`0x0096DB26`), the vector stride, and the `0xD8` stack frame in the act parser — a much larger and
more fragile patch than this verb is worth.

**So the records live in the cave, keyed by act name.** The parse function reads the act's name from
`act+0x04` and stores it alongside the four fields; the executor, hooked into the act runner, reads
`act+0x04` again and runs every cave record whose name matches. Act names are already the engine's
own key for acts — `CallActSubroutine` resolves them through `[0x00DE87AC]->0x007B97B0`
(`0x0096E3B5`), so they are unique within a campaign.

## 5. The patch

### Sites

| site | stock | becomes |
|---|---|---|
| `0x0096E7F3` | `push 0x00C84030` (immediate) | `push <cave verb table>` |
| `0x0096E39D` | `call 0x0096C4AB` (pass 9 of 10) | `call <cave executor trampoline>` |

Two five-byte sites, neither splitting an instruction, neither touched by any shipped patch. Every
other byte is new section, allocated with `allocate_section`.

### Cave contents

1. **The verb table**, 15 stock rows copied verbatim + a 16th `{"MergePlayerArmy", parse_fn, 0, 0}`
   + terminator. `0x0100` bytes of stock table plus `0x20`.
2. **The field table** for the new block, four rows using the engine's own parsers — `0x0042EE5E`
   (AsciiString) for `SourceArmy`/`DestArmy`/`SplitArmyTemplate`, `0x0042E558` (Bool) for
   `SplitArmy`, and `0x0042E558` again for the optional `DespawnSource`.
3. **The side table**: a fixed-capacity array of records `{char actName[64], char src[64],
   char dst[64], char tmpl[64], u8 split, u8 despawn}` plus a count. Fixed `char` buffers rather
   than `AsciiString`s so the parse side owns no heap and no destructor: the parse function lets
   the engine's `AsciiString` parser fill a scratch record, copies the characters out, and
   destructs the scratch.
4. **`parse_fn`**, modelled line for line on `SetPlayerControlOfArmy`'s `0x008E6185`: null-check
   both arguments, build a local record, `INI::parseFields` (`0x0042DB80`) against the field table,
   copy into the side table with the act name from `act+0x04`, destruct the local.
5. **The executor trampoline**: `push ecx; call 0x0096C4AB; pop ecx; call merge_pass; ret`, so the
   displaced pass still runs and the new one runs after it.
6. **`merge_pass(act)`**, the runtime below.

### The runtime

```c
for (r in side table where streq(r.actName, act->name)) {
    src = TheLivingWorldLogic->findArmyByScriptingName(r.src);
    dst = TheLivingWorldLogic->findArmyByScriptingName(r.dst);
    if (!src || !dst || !src[0x78] || !dst[0x78]) continue;
    S = src[0x78];  D = dst[0x78];

    if (!r.split) {
        for (i = 0; i < count(S); i++) D->cloneAndAppend(S->getRecord(i));
        for (i = count(S) - 1; i >= 0; i--) S->eraseAt(i);
    } else {
        T = TheLivingWorldCampaignManager->findPlayerArmyByName(r.tmpl);
        if (!T) continue;
        for (e = 0; e < count(T); e++) {
            i = indexOf(S, T->getRecord(e)->name);     // 0x004065AA on record+0x04
            if (i < 0) continue;
            D->cloneAndAppend(S->getRecord(i));
            S->eraseAt(i);
        }
    }
    if (r.despawn && count(S) == 0) TheLivingWorldLogic->destroyArmy(src);   // 0x006B9679
}
```

Two deliberate differences from BFME1, both to be named in the description:

- **The unsplit merge empties the source.** BFME1's leaves it populated and relies on `DespawnArmy`,
  which RotWK does not have. Leaving a duplicate roster behind in RotWK would mean the units exist
  twice and both copies deploy.
- **`DespawnSource` is a new optional field**, not a BFME1 one. It exists because `DespawnArmy` is
  the other missing verb and the pair is how BFME1's INI is actually written; without it the source
  army sits on the map as an empty icon. Default `No`.

### Running order

Pass 10 of 11, after `SetPlayerControlOfArmy` and after `SpawnArmy` (pass 3). That ordering is
required: BFME1's own usage spawns the destination army in the same act and then splits into it,
and within an act the engine orders by pass, not by INI line order.

## 6. What to confirm before writing assembly

| | question | how |
|---|---|---|
| 1 | Is `0x0081205B` really clone-and-append? It has **no direct callers** | read `0x0081019B`'s field copies against the `0xD8` record layout; if it is not, build the clone in the cave from `operator new(0xD8)` + `0x0081019B` + `0x00811951`, which is what `0x00811CF9` does for `ArmyEntry` |
| 2 | Does `0x00810840` renumber or leave a hole? | read it; the loop erases descending to be safe either way, but a hole would break `getRecord` |
| ~~3~~ | ~~Does the harvest at `0x00811E1F` append to or replace the roster?~~ | **settled 2026-08-28 by measurement: the roster is replaced.** Four entries in, three survivors out, each carrying the upgrades it earned. The static "it appends" answer written earlier the same day was wrong — records are consumed at deployment by `0x0071AE2D`. See [`hero-permadeath.md`](hero-permadeath.md) |
| 4 | Is `act+0x04` still the name at run time? | it is set by the constructor and copied by the act copy-constructor; confirm the copy-ctor at the vector push (`0x0093402E`) carries it |

Question 3 is the one that can invalidate the feature rather than the code. **Settled 2026-08-28 by
reading two saves:** an army's roster is *replaced* across a battle — its records are consumed as
they deploy (`0x0071AE2D`) and the harvest puts the survivors back, each carrying the upgrades it
earned. Good news for these verbs: the roster a merge sees is a clean list of what the army
currently has, not an accumulation. The one consequence to know is that a hero record leaving a
roster is also filed on the owning player (`0x006E4853` → `LivingWorldPlayer+0x1D4`), so moving a
hero between armies with `MergePlayerArmy` touches a structure the verb does not know about.

## 7. Tests

Following the house pattern (`test_scenario_player_factions.py`, 469 lines for 375 lines of patch):

- stock bytes asserted at both sites, and the stock 15-row table decoded and compared row for row
  against the copy the patch writes;
- apply → verify → detect round-trip, and detect on an unpatched image returning `None`;
- the relocated table parses back through `explore.py table` semantics: 16 rows, terminator intact,
  the 15 stock rows byte-identical, row 16 pointing inside the cave;
- the field table's parser pointers are the engine's own (`0x0042EE5E`, `0x0042E558`), not cave
  addresses;
- the trampoline still calls `0x0096C4AB`, and the hooked call at `0x0096E39D` resolves into the
  cave;
- composition: applies in either order with `objectives-screen` and `scenario-player-factions`,
  which touch no shared byte;
- `ini_surface` names `MergePlayerArmy` and its five keywords.

All static. The patch ships **experimental** until a scenario run shows an army actually splitting.

## 8. Cost

| part | size | confidence |
|---|---|---|
| table relocation + verb row | ~40 lines | high — one dword, the pattern is already used |
| field table + `parse_fn` | ~80 lines | high — `0x008E6185` is a line-for-line model |
| side table + name keying | ~60 lines | medium — the design is forced by the `0xB8` Act, not chosen |
| `merge_pass` runtime | ~150 lines | medium — every primitive is identified, question 1 is the risk |
| tests | ~450 lines | high |

Comparable to `scenario-player-factions` (375 + 469 lines) and larger than `objectives-screen`
(264). The runtime is the cost, exactly as [`bfme1-act-verbs.md`](bfme1-act-verbs.md) predicted —
but less than it estimated, because the record model turned out to be shared between INI template
and live roster, so no new data structure has to be invented.

**`DespawnArmy` is the cheaper neighbour and shares all this scaffolding**: same table relocation,
same side table, one `AsciiString` instead of five fields, and `0x006B9679` as the entire runtime.
Building the two together costs barely more than `MergePlayerArmy` alone, and Edain's INI already
has the line written for it.

## 9. What the build changed about this scope

[`campaign-army-verbs`](../../patches/experimental/campaign_army_verbs.py) is written, applies to
the shipped `game.dat`, verifies, and round-trips through `detect`/`sagepatch`. Four things came
out different from the scope above.

**Records move; nothing is cloned, and question 1 is moot.** `0x00810840` addresses the source
roster's element *and hands the caller a reference to it* (`0x008108A9` bumps `record+0xC0` after
storing the pointer through `out`, then drops its own temp reference). So the sequence is
`erase(&tmp, i)` → `append(D, &tmp)` → `release(tmp + 0xBC)`, and `0x0081205B` — the clone helper
with no direct callers, and the biggest risk in the scope — is never used. A move is also the
right semantics: a record carries `Quantity`, `Default` and whatever the harvest last wrote into
it, and a copy would have to be kept in step with all of it.

**No string comparison of army names.** The scope had the cave walking the army vector itself. It
does not: it builds an `AsciiString` from the record's characters and calls the engine's own
`findArmyByScriptingName` / `findPlayerArmyByName`, so the patch inherits whatever the engine
considers an equal name instead of deciding that again. `ASCII_STRING_COMPARE` (`0x004065AA`) is
**`strcmp`-shaped — zero means equal** (`0x004052F9` returns `memcmp`, else the length
difference), which is the one place a plausible misreading would have inverted the manifest match.

**Every field is read by an engine parser.** The new field table's five rows point at
`0x0042EE5E` (AsciiString) and `0x0042E558` (Bool) — the same two the stock Act verbs use — so the
cave contains no scalar parser at all. A row is called
`__cdecl parse(INI *ini, void *instance, void *store, const void *userData)`, read off the
dispatch at `0x0042D58D`.

**`0x0096DF5D` appends a 16-byte record, not a 12-byte one.** A correction to
[`living-world-parity.md`](living-world-parity.md) §2, which described
`SetPlayerControlOfArmy`'s list as 12-byte entries; the vector strides by `0x10`
(`0x0096DF7F`), the record being `{vtable, AsciiString, Bool, pad}`.

### What is still unknown

Question 3 of §6 is **settled, 2026-08-28, by measuring two saves: the roster is replaced.** Its
records are consumed as they deploy (`0x0071AE2D`) and the harvest puts the survivors back with the
upgrades they earned — four entries went into a battle, three came out. A static argument written
earlier the same day concluded "appends" from the absence of a clear call; it was wrong, and it is
left in [`hero-permadeath.md`](hero-permadeath.md) with the correction rather than deleted.

For these verbs that is the good outcome: the roster a merge reads is a clean list of what the army
holds now. The one thing to know is that a `KindOf HERO` record leaving a roster is also filed on
the owning `LivingWorldPlayer` at `+0x1D4` (`0x006E4853`), a structure `MergePlayerArmy` does not
touch — so moving a hero between armies is worth watching for a double entry in the hero pool.

What remains untested is everything about the verbs themselves: that the new rows parse, that a
split moves the manifest's entries and nothing else, and that the world map shows the result.
