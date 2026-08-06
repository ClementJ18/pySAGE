"""A scripted bot that plays a skirmish: build an economy, upgrade, and take the map.

The point is not the strategy - it is deliberately the simplest thing that can beat an Easy
AI - but the **control loop**, which is what an ML policy would later replace. Everything
below the `decide` boundary is reusable: attach, resolve names, find plots, verify that an
order did something, and notice the match ended.

    python -m sage_mods.edain.bot --game "C:/Program Files (x86)/Games/bfme/rotwk"
    python -m sage_mods.edain.bot --game ... --dry-run    # decide, print, send nothing

**One class, split across files in the order it is built up.** `Bot` is a linear chain of base
classes rather than one long module, so each file is a layer that only depends on the ones below
it and can be read on its own:

- `tuning` - every threshold, with the measurement that put it there. Start here when a run goes
  wrong: it is usually one of these.
- `plans` - the build order per faction, and `ledger` - what each order type achieved.
- `state` - everything a run remembers between cycles.
- `world` - reading the board: the army, the plots, the nests, who is hostile.
- `orders` - issuing orders and proving they did something.
- `economy`, `powers`, `recruiting`, `warfare` - the stages, which are where the decisions live.
- `bot` - `decide`, `finished`, `run`; `cli` - attach, load the ini tree, report, play.

**Every order is verified, never assumed.** Game logic silently discards a malformed or
unaffordable order *after* the stream has taken it - no error, no diagnostic, and it still
reaches the replay. So nothing here counts as done until the game visibly does it: a recruit
until the building's *queue* grows, a move until units move, a build until something stands on
the plot.

**The queue, not the gold.** An earlier version confirmed spends by watching the balance fall,
which is wrong in both directions in a real match: an enemy ability can steal gold, so it falls
with no spend of ours, and a grant of 500-1000 can hide a real spend under a net rise. The
queue belongs to the building the order named and nothing else can forge it.

**Classification comes from `KindOf`, not from names.** A live object carries a template name
and nothing else, and the interesting categories are not guessable from it:

- A **build plot** is `BASE_FOUNDATION` or `BASE_SITE`. It cannot be found by looking for an
  object with no body - a plot has an `ImmortalBody` of 15,000 - and its name follows no
  convention that holds across factions (`GondorBuildingFoundation`, but also
  `MordorFortressExpansionPadCorner`).
- A **defeated player** owns nothing carrying `MP_COUNT_FOR_VICTORY`. Note that an economy
  building is explicitly `IGNORE_FOR_VICTORY`, so counting buildings is not the same test.
- An **army** is what is selectable, mobile, and neither a structure nor a builder - which is
  how a porter (`DOZER PORTER`) stays out of the push and off the casualty list.

That join lives in `sage_live.utils.statics` and costs one ini load at startup, about 35 seconds.

**Names, not ids.** Ids come from `sage_live.utils.resolve.Resolver` - the ini path - rather than
from the engine's own live table. The two disagree (the live walk reads ten more templates),
and only the ini rule is corpus-validated: 491/491 `FOUNDATION_CONSTRUCT` orders across 12
fixtures resolve faction-consistently, per `order_space_map.md` section A. That section also
warns that ids must be resolved against a **live-install mount** and not against Edain's
`_mod` overlay tree, whose table is shifted one low - so pass the install folder to `--game`.

**Upgrades are two tiers, and the first alone does nothing.** A faction tech is `PLAYER`
scope, bought once at a building, and it changes no unit - what it does is unlock an `OBJECT`
scope button on the battalions, which is where the armour actually lands. `GondorForge` sells
`Upgrade_TechnologyGondorHeavyArmor`; `GondorFighterHorde` sells `Upgrade_GondorHeavyArmor`
and is gated on it. Stopping after the tech spends the gold for no combat effect and nothing
in the game reports it, so this buys both halves.

Which upgrades exist is never listed here. `Statics.upgrade_buttons` walks the target's own
`CommandSet`, so the set is whatever that build offers - and because a button that exists on
the command set is a button the control bar would have shown, ordering only from that set is
also what keeps this automation rather than cheating.

**And the command set a building shows is not the one its template declares.** Edain builds a
structure's levels as a chain of `CommandSetUpgrade` modules: a `GondorBarracks` offers
`Upgrade_GondorStructureLevel2`, buying it swaps the palette to
`GondorBarracksCommandSetLevel2`, and only *that* set offers
`Upgrade_GondorStructureLevel3_Barracks`. Reading the static field sees one rung of a
three-rung ladder - and misses the units on the other two, because the level-gated recruit
buttons carry a `NeededUpgrade` as well. So every walk here is done against the upgrades the
object actually holds, which is what turns a barracks from a shop selling two battalions into
one selling four.

**Spellbook points are a second currency, and not spending them costs nothing to notice and
everything to leave.** They accrue on their own clock and buy only powers, so `stage_powers`
competes with no other stage for the one purse the rest of this bot argues over - which is why
it needs no floor, no reservation, and no place in the build order's priority list. It runs in
the opening for the same reason it runs at the end: a point banked is a point doing nothing.

The book is read the same way everything else here is - off a command set. A faction's
`PurchaseScienceCommandSetMP` is the palette the spell store puts on screen, so a purchase from
it is a purchase a player could have clicked; the padding slots every book carries
(`Command_PurchaseSpellEmpty`) drop out by what the data says rather than by their name. What is
*already held* is read live rather than remembered, and that is not bookkeeping hygiene: a
skirmish AI is granted spells by script with the ini's prerequisites bypassed, so a bot handed
one the same way would spend the rest of the match trying to buy what it already had.

Which power to buy is the one decision here with no measurement behind it. Cheapest first, on
the reading that the book is a tree whose good spells are gated behind two rungs of cheap ones -
so there is no route to the top that does not go through the bottom, and spending as the points
arrive *is* the fast route. That is an argument, not a result; see `powers.py`.

**A plan does build a shop, and only out of a surplus.** An earlier version laid Gondor's
marketplace and forge unconditionally and it cost a match: 1800g and two of a castle's handful
of plots, spent in an opening, on buildings it then bought nothing from. What was wrong was the
timing rather than the buildings - `GondorForge` sells all three armour techs and every one is
gated on a marketplace upgrade, so without the pair there is no armour in the match at all.
`RESEARCH_FLOOR` puts them behind a bank of 1500, which is a state the same match reached by
cycle 7 and then sat in for 145 cycles with nothing to spend on.

**Every stage runs every cycle.** `decide` is not a chain of `if ... return` - it gives each
stage a turn, so one cycle recruits *and* builds *and* expands. The chain version was the
single biggest waste: a bot still laying its economy was not recruiting, so the barracks stood
idle through the whole opening and the army arrived minutes late.

**The army is one force rather than three, and the push comes last rather than never.** The
first is a deletion of something measured; the second is a deletion that has now been partly
undone, on evidence, and it is worth reading the history before touching it.

Splitting was the first. A capture squad of three, a raiding party of six and a guard each held
battalions by id, so an army of twelve fought on three fronts and lost all three separately -
and the squad's fixed three was also a fixed ceiling on the map, because `CONTEST_ODDS` is
measured against whoever is sent. Measured across six runs: `unpack` landed 3/15 and 7/19,
twelve flags were abandoned for "the squad was not getting there", and map control never once
passed 44%. Three battalions do not take a flag that a lair keeps a dozen wildmen standing on,
however many cycles they are given.

The push was the second. It aimed the army at whatever counts for victory, and the two ways of
deciding when to fire it were both wrong: a battalion threshold asked "am I strong enough",
which is unanswerable from inside a match where the army is spent as fast as it is built, and a
map-control gate asked a question the bot could not reach the answer to. The stalemate timer that
finally forced it made things strictly worse - a 600-cycle run that survived undefeated became a
394-cycle defeat, because committing did not create an army that could win, it only stopped the
expansion that was paying for one.

So for most of a match the whole army is one **field force** with one job: take the map, flag by
flag, and take back what was lost. Everything else it does - razing a lair, breaking an expansion,
meeting a raid at home - is a step in that job rather than a front of its own. The only battalions
ever held back are the party still forming and whatever `stage_defend` needs this cycle.

**And then there is an endgame, because taking the map turned out not to end anything.** Run 4
held 94% of it, razed every lair, sat at 1440 of 1500 command points for four hundred cycles with
105,012 gold banked, and finished undecided. Both of the conditions `stage_push` now fires on were
true from cycle 619 of 1400.

Two things had to be true for that to be safe rather than a third repetition of the above. The
first is the gate: `PUSH_CONTROL` *and* `PUSH_ARMY` together describe a bot that has run out of
map and out of army at the same time, so unlike a battalion threshold it is answerable and unlike
a stalemate timer there is no expansion left for it to stop. The second is that the earlier push
could not have worked anyway - its target list was `hostile(o) and counts_for_victory(o)`, and
`hostile` excludes structures while 573 of the game's 574 victory-counting templates are
structures. It was unreachable code, and every documented correction to its gate was made to a
branch with no target. See `World.victory_targets`.

**What to recruit comes from the faction's own skirmish-AI army definition.** Massing one
template was the simplest thing that could work and it is also the thing an opponent counters
for free - a wall of swordsmen loses to spears it never had an answer to. `skirmishaidata.ini`
already carries the mix the shipped AI plays: `ArmyDefinition MenOfTheWestArmy` lists 57 units
with a target share of the army at each of three phases, so the bot builds toward that mix
instead of toward a number.

**That list is a pool with weights, and nothing else.** Most of its entries are unreachable in
any given match - other sub-factions' rosters, and AI-only stand-ins that no command set offers,
only some of which are named `_AI`. So the pool is intersected with what the buildings actually
owned can recruit (`Statics.recruits`), which is the same command-set rule everything else here
obeys, and the definition is trusted only for the part it is authoritative about: the ratio.

**And the ratio knows nothing about who it is playing, so the engine's own numbers tilt it.**
The definition asks for the same quarter archers whether the opponent is massing horses or
pikes. What beats what is not a judgement this file has to make either: a weapon declares a
`DamageType` and an armour block prices every type against itself, so `GondorPikemanWeapon`
deals `SPECIALIST` and `EdainCavalryArmor` takes 170% of it while `EdainInfantryArmor` takes
65%. `Statics.effectiveness` joins the two, `counter_score` weights it by what the opponents
have standing, and the mix moves toward the answer without anything here naming a matchup -
"pikes are required against Mordor" is a thing the data says, for this mod and for the next.
It is a tilt rather than a switch (see `COUNTER_RANGE`): a wall of one counter loses to
whatever counters *it*, which is the failure the mix exists to avoid in the first place.

**An order that costs more than the balance fails exactly like a broken one.** Logic discards
it in silence, so it returns as "NOT QUEUED" alongside malformed arguments and unmet
prerequisites - and the retry logic then benches a perfectly good action for two minutes. Every
spend here is checked against `charged_cost` first, which is the ini's quoted `BuildCost` after
the `CostModifierUpgrade` ladders the standing buildings have earned.

**Those ladders are most of what an Edain economy building is for, and the quote misses all of
it.** A `GondorWohnhaus` marks the faction's elites and `CPObject` down by a further slice with
every copy built, to -30% at six; a `GondorForge` does the same to the five per-object unit
upgrades. Pricing against the quote refused recruits the balance covered - a citadel guard quoted
at 600 is charged 420 behind six houses - and it refused them exactly where `succession` is trying
to move the army onto those units.

It is still a floor rather than an exact price, and deliberately so: a carrier that cannot be seen
in the observation contributes nothing, and where several ladders apply the least generous wins.
Both choices err upward, because the two errors are not symmetrical - too high delays an order,
too low sends one that logic discards in the silence this whole check exists to avoid.

**The command-point cap is real and enforced, and it took two wrong readings to see it.** The
engine checks a *base* plus a *bonus*: the base is a flat 500 for every seat and never moves,
and each built `CPObject` adds to the bonus. `MemoryBackend` used to report the base alone as
the cap, so usage appeared to sail past its own ceiling - 1262 against 500 - and that was read
here as the cap not being enforced at all. It is: measured live across every seat of one match,
usage pressed hard against `base + bonus` and never crossed it, on both sides. The reader now
sums the two, so `cap - used` is genuine headroom.

What that misreading cost is worth remembering, because it points the wrong way twice. Gating
production on the base alone stops a bot recruiting a third of the way in, which is the failure
that got the gate removed; but concluding from the same numbers that there is no ceiling means
never buying the `CPObject` that lifts it, and the recruits then vanish in silence. The direct
signal settles both - a recruit that does not queue - and it needs no offset to be right.

**And a `CPObject` is built, not granted.** It sits in the keep's queue for its build time, so
the jam it clears stays jammed until it finishes - which reads as the purchase having failed,
and buys another, and another. One at a time, checked against the queue.

**A selection order can be dropped, and then every order after it goes to the wrong thing.**
The bridge's command buffer holds 24 arguments and a selection spends one on its replace flag,
so 24 battalions do not fit; the encoder refuses the whole order, the engine keeps the previous
selection, and the attack that follows is issued by whatever was selected last.
`Session.select` splits a large selection across orders, and nothing here issues an order
without checking that the selection it depends on actually landed.

**A settlement flag is taken by standing on it, not by an order.** There is no capture order;
`WirtschaftPlotFlag_Real` becomes yours because your units are near it and no enemy is. So an
expansion is three problems - clear what guards it, stand next to it, then `castle_unpack` -
and only the last is an order this API issues. **The field force goes, not a detachment**,
because a capture is a fight and what decides a fight is how much of the army turned up: the
squad of three this replaces died on approaches it was never going to survive, and declined
every flag it might have taken by measuring the odds against three.

**A settlement's defenders are output, not opposition.** They come out of a creep lair, which
replaces every one that dies, so the fight around a flag has no end and no amount of patience
wins it - `DunlandGoblinLair` keeps twelve wildmen standing, and a measured map had six of
them. What ends it is the building: `Statics.spawns` finds a lair by the `SpawnBehavior` that
garrisons it, which needs no name list and holds for every lair on every map.

**And a razed lair leaves a hole that rebuilds it.** `RebuildHoleExposeDie` puts a
`REBUILD_HOLE` stump where the lair stood, and `RebuildHoleBehavior` raises the lair again two
minutes later. The stump is `NOT_AUTOACQUIRABLE`, so no army will ever attack it by itself and
an `attack_move` walks straight past: clearing a lair for good means naming the hole in an
attack order, which is the one place here that orders something a player would have had to
click deliberately too.

**Taking a map and holding one are different jobs.** `stage_expand` walks to flags nobody has
built on, and a settlement the opponent took - or took back - is invisible to it: it is not a
free flag, because a building stands on it. A map could therefore be conquered flag by flag and
quietly conquered back with every stage reporting success. `reclaim_targets` is the answer and
it is the same order as any other attack: enemy buildings on plots on this side of the map, and
anything of theirs standing inside the base, ranked ahead of the raid's ordinary business.
Razing one puts its flag straight back on `external_plots` for the field force to walk onto.

**Nothing counts the players.** A skirmish with no opponent at all is not a special case to
detect, it is the ordinary case with one of the target lists empty - so `raid_target` ranks
*what is on the map* rather than what one seat owns, and a bot alone on a map spends its army
on lairs and flags instead of standing in its base reporting that no opponent holds anything.

**A rabbit is not a raider, and the engine says so.** Map wildlife is owned by the civilian
seat, is mobile, has a body, and is not a structure - which was every test `hostile` applied,
so six fish and ten rabbits read as an army at the gates. `stage_expand` and `stage_raid` both
stood down while that was true, which is to say permanently. The flag that settles it is
`INERT`, and reading it needed `KindOf` macros expanded (see `statics`).

**Fog is off by default, and that is privileged information.** Left off, this reads the whole
map, so finding the opponent's base is a lookup rather than a scouting problem - an advantage a
human does not have, stated here rather than hidden.

`--fog` turns it on, and then the bot sees only what its seat can see: an opponent's army has to
be scouted, `enemy()` returns None until something of theirs has been sighted, and `enemy_army()`
becomes a sighting report rather than a census. One thing does not become observable, so the run
loop stops inferring it - victory is not decidable when the enemy's last buildings are merely out
of sight, so a fogged run ends on the match ending rather than on a holdings count. There is also
no memory of what was seen: a scouted building disappears again when the scout leaves, where a
real player would still see it drawn. See `sage_live.api.shroud`.
"""

from sage_mods.edain.bot.bot import Bot
from sage_mods.edain.bot.cli import main
from sage_mods.edain.bot.ledger import Ledger
from sage_mods.edain.bot.plans import PLANS, Plan

__all__ = ["PLANS", "Bot", "Ledger", "Plan", "main"]
