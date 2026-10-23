# Letting an AI-owned plot build its own building

The reverse-engineering behind [`patches/ai_plot_autobuild.py`](../patches/ai_plot_autobuild.py).
ROTWK `game.dat` build `2.01.2614.37001`, ImageBase `0x400000`, recovered statically 2026-10-23,
and played the same day in an Edain skirmish (Edain-Mod `tests/test_ai_dunedain_outpost_plots.py`).

## TL;DR

- **The skirmish AI only builds what a build list names.** Its structure requests (vtable
  `0x00C857A8`) are made from an `AIBase` layout for its start castle (`0x0082F787` turns the
  `.bse` objects into requests), or by library scripts (`BUILD_BASE_BUILDING`,
  `BUILD_BUILDING_ON_FOUNDATION`) naming a base and a slot. An outpost or camp unpacked
  mid-match has neither: its layout lists plots only, under the base name `BASE`, and none of
  them has a name. **Seen live:** a Brutal Imladris AI left all three plots of its Dunedain
  outpost empty for 228 game seconds with 4,000-6,000 in the bank, and filed no request for any
  of their buildings.
- `FS_BASE_DEFENSE` / `BASE_DEFENSE_FOUNDATION` do not change that
  ([`fs-kindof-flags.md`](fs-kindof-flags.md) §2.4): they decide which plot a building fits,
  never whether anyone builds it.
- The fix is the foundation-side design `fs-kindof-flags.md` §5 scoped, with the INI switch on
  the module rather than a new `KindOf`. Three fields on `FoundationAIUpdate`:

  | field | type | default | meaning |
  |---|---|---|---|
  | `AIAutoBuild` | Bool | `No` | the plot builds for a computer owner |
  | `AIInitialBuildDelay` | Duration (ms) | 0 | from the plot first standing empty |
  | `AIRebuildDelay` | Duration (ms) | 0 | from the plot's building going (dying, being sold) |

- When the delay has run out, the plot's tick walks its **current** command set (overrides first,
  so a `CommandSetUpgrade` AI set is what it sees) and presses the first `FOUNDATION_CONSTRUCT`
  button `BuildAssistant`'s production gate accepts, through `buildObjectNow` with the plot as the
  constructor. That is the call the AI's own structure requests make (`0x009ED970`), and a
  `BASE_FOUNDATION` constructor routes it into the plot's own build-here (`0x00858701`). So the
  building is a real construction site, the plot is its producer and is marked occupied, and the
  price is withdrawn the way a plot build withdraws it.
- **Seen live 2026-10-23**: every plot built its building 46 frames into the match (2 s initial
  delay), each first seen `UNDER_CONSTRUCTION` with the plot as producer; a tower destroyed by
  rams was rebuilt on its plot 318-351 frames later against a 300-frame (60 s) `AIRebuildDelay`.

## 1. Where the AI's structure builds come from

`0x0097DE1A` constructs a structure request (`0x00C857A8`). Its callers:

| caller | what it is |
|---|---|
| `0x0082F7D2` (fn `0x0082F787`) | the `AIBase` loader: one request per object of the `.bse` layout, named by `objectBaseName`, prioritised by `objectBasePriority` / `objectBasePhase` |
| `0x009BC9A6`, `0x009BD001`, `0x009BCD2F` | script-driven base building (`0x009BC7CF`, called from the script action switch `0x0090B1F4`): a template at a position, skipped when a free builder already stands near it |
| `0x009EFF39` | a batch of plain requests |
| `0x0099F2E2` | the farm subclass (`0x00C88090`), not a structure |

A start castle's layout (`hd - men.bse` for example) lists the **buildings** -
`GondorBarracksWOTR`, `GondorForgeWOTR` ... - each with `objectBaseName = FestungX`; that is what
the live queue shows as `structure ImladrisBarracksWOTR` and the like. Outpost and camp layouts
(`dunedain_outpost.bse`, `imladris_camp.bse`) list only plots and props, so nothing in the AI
ever asks for a building on them.

A request starts at `0x009ED8C4`: it finds the template by name, its builder by id, and calls
`TheBuildAssistant` slot `+0x38`, `buildObjectNow(builder, template, &pos, angle, player)`,
storing the new object's id.

## 2. The plot's build path

`buildObjectNow` (`0x00797796`) does not charge. For a constructor with `BASE_FOUNDATION`
(`tmpl+0x115` bit 1) it gets the foundation interface (`0x0068C3C3`) and calls its `+0x1C` with
`(template, pos, angle, player, 0, 0)`.

On a plot that is `FoundationAIUpdate`'s `0x00858701`. It refuses when the plot's castle is not
ready (`0x0079A09D`), creates the object (`0x006D165E`), makes the plot its producer
(`0x0068B6A1`), sets `UNDER_CONSTRUCTION` (`0x0062684D`, status 2), and, when both the new
object and the plot carry `CastleMemberBehavior` and the sixth argument is 0, prices the template
(`ThingTemplate` `0x0073C25F(player, plot, -1)`) and withdraws that from `Player+0x90`
(`Money::withdraw`, `0x00858B13`). `Money::withdraw` clamps to what the player has, so
affordability has to be decided before the call.

`Object::doCommandButton` cannot do this: its `FOUNDATION_CONSTRUCT` case (`0x006977C5`) asks the
object for a production interface (`0x0068C327`) and does nothing without one, and a plot has
none. A `DoCommandUpgrade` on a plot is therefore a no-op.

## 3. The gate

`BuildAssistant` slot `+0x64` (`0x00793ECB`), `(producer, template, reviveIndex)`, `ret 0xC`:

| answer | meaning |
|---|---|
| 0 | can build |
| 1 | `canMakeUnit`: the producer's command set has no button for it |
| 2 | not affordable (`0x0073C25F` against `Player+0x94`) |
| 3 | the producer is disabled, or its production interface refuses |
| 6 | the template's maximum count is reached |
| 7 | command points |

A producer without a production interface passes the first check, so the gate works for a plot.

## 4. The module

`FoundationAIUpdate` registers at `0x00659F2F`: instance factory `0x0064A713` (`operator new(0x30)`,
constructor `0x00858217`), `ModuleData` factory `0x00653209` (`operator new(0x10)`), field table
`0x00C06338` (`RepairHealthPercentPerSecond` `+0x8`, `BuildVariation` `+0xC`), named by the `push`
at `0x006531FE`.

Instance: vtables at `+0x0` (`0x00C56E30`), `+0xC`, `+0x10` (`UpdateModule`, the `this` of
`update`), `+0x20` (the foundation interface `0x00C30DE8`, shared with `CastleBehavior`); `+0x24`
a dword the constructor sets to 1; `+0x28` the built-on id; `+0x2C` the adopt-scan flag.

`CastleBehavior` derives from it: its parse also names `0x00C06338` (at `0x0079D0E8`) and its
instance has fields of its own past `+0x30`. So the patch repoints only `0x006531FE`, and the
update stub tests the module's vtable before it reads the new bytes.

`update` (`0x008584DB`) runs the one-shot adopt scan, then reaches `0x00858579` on every path:
`mov edi,[esi-8]` / `test byte [edi+0x458],1`, then the occupancy poll at `0x008585EC`. The poll
and its clear are anchored by `foundation-rebind`, which is why the hook is the join before it.

## 5. The patch

| site | edit |
|---|---|
| `0x0064A71E` | `push 0x30 / call new` -> a stub allocating `0x38` and zeroing `+0x30` (next build frame) and `+0x34` (state) |
| `0x0065320A` | `push 0x10 / call new` -> a stub allocating `0x20` and zeroing `+0x10`..`+0x1C` |
| `0x006531FE` | the table `push` -> a rebuilt table: the two stock rows, `AIAutoBuild` (`parseBool`, `+0x10`), `AIRebuildDelay` (`parseDuration`, `+0x14`), `AIInitialBuildDelay` (`parseDuration`, `+0x18`) |
| `0x00858579` | 10 bytes -> the update stub, which re-executes them and rejoins at `0x00858583` |

The update stub, all registers saved:

1. Not a plain `FoundationAIUpdate` (vtable), or no `AIAutoBuild`: stock.
2. The built-on id resolves: state 1 (occupied).
3. Empty, state 0: arm `now + AIInitialBuildDelay`, state 2. Empty, state 1: arm
   `now + AIRebuildDelay`, state 2.
4. Armed and due, on this plot's frame (`(id + frame) & 7 == 0`), owner a computer player
   (`Player+0x5C != 0`): walk the 33 stock slots of the plot's set; the first
   `FOUNDATION_CONSTRUCT` button whose template the gate answers 0 for is built with
   `buildObjectNow(plot, template, &plot+0x38, [plot+0x44], player)`.

A refusal leaves the plot armed, and it tries again on its next frame: an AI saving up builds as
soon as it can afford the building.

## 6. What to know when using it

- **The plot builds its command set's first acceptable button.** Give an AI plot a one-button set
  (a `CommandSetUpgrade` on `Upgrade_ObjectUnderAIControl`), or order the set by preference.
- **Set `AIInitialBuildDelay` past the AI set's arrival.** Edain grants
  `Upgrade_ObjectUnderAIControl` 500 ms after creation; until then a plot shows its player set,
  and a 0 initial delay could build from it.
- **The state is not saved.** A loaded plot starts fresh and waits its initial delay again.
- **Human plots are never touched**, whatever they declare.
- A `CastleBehavior` plot (the flag a camp or castle unpacks from) is not covered.

## Status

Applied, verified and composed with Edain's 97 other patches on 2026-10-23; unit-tested under
Unicorn (`tests/sage_patch/test_ai_plot_autobuild.py`); seen live the same day for the first
build and one rebuild. Not yet seen: payment for a priced building (the Dunedain AI buildings cost
0), several AI players at once, a save and reload, and a multiplayer game.
