"""Every threshold this bot plays by, and what measurement put it there.

Kept in one file because they are the knobs: a run that goes wrong is usually one of these
being wrong, and reading them together is how that gets noticed.
"""

from __future__ import annotations

# How long to wait for an order to take effect now lives in the library, as
# `session.DEFAULT_CONFIRM` and `BUILD_CONFIRM` - every consumer needs the same windows and
# they were arrived at the same way, by watching orders that did nothing.

# How near a plot a structure must stand to be the thing built on it. **A plot is not consumed
# by building on it** - the `GondorBuildingFoundation` object stays put underneath, so "is this
# plot free?" is a question about what is standing there, not about whether the plot still
# exists. Measured spacing between adjacent plots in a Men castle is about 150, so this is
# comfortably tight enough not to let one plot claim its neighbour's building.
PLOT_RADIUS = 100.0

# **How long a plot or flag stays unbuildable after whatever stood on it goes away** - the
# engine's own rule, in *game* seconds.
#
# Nothing in an observation reports this. A plot whose building has just been destroyed reads as
# free by every test the bot has - it is owned, nothing is standing on it, `free_plots` offers it
# on the very next cycle - and an order aimed at it is taken by the stream and discarded by logic
# with no error, which is the failure mode this codebase keeps rediscovering.
#
# It is the whole of the "placement pathology" that cost three matches. Every mid-match refusal in
# run 9 has one shape: `eco` falls as a building dies, `plots` rises by exactly one, the
# replacement is ordered onto that plot on the next cycle, and it is refused. Plot 527 was paid
# for five times that way in one match, at two four-second confirmation windows an attempt. Run
# 12, in which nothing of ours was destroyed at home, refused nothing at all in 388 cycles.
#
# **Counted in logic frames, not in wall-clock seconds, and that is not a detail.** The engine
# advances at roughly 4-6 logic frames per second against its nominal 30 under the bridge, so
# twelve game seconds is a minute or more of real time - a wall-clock rest of twelve seconds would
# expire while the plot was still refusing, which is the bug wearing a fix. Every other rest in
# this bot (`PLOT_COOLDOWN`, `FLAG_COOLDOWN`) is a *heuristic* about contested ground and is
# rightly wall-clock; this one is a *game rule* and has to be measured in the game's own clock.
#
# 14 rather than 12: the figure is approximate, a cycle samples every two seconds or so, and being
# one cycle late costs nothing while being one cycle early costs the whole confirmation window.
PLOT_REBUILD_SECONDS = 14.0

# How close something hostile has to be to a plot or flag before a building will not go up on it.
#
# **The second reason ground refuses a building, and it is independent of the first.** A plot can
# be inside its rebuild cooldown, or have a raider standing on it, or both at once - they are
# different rules with different clocks, and a plot that clears one may still be refused by the
# other. An earlier version of this file had only this rule and attributed the archived runs'
# refusals to it; that was a correlate, not the cause (the raiders were there *because* they had
# just destroyed the building, and the building's death is what started the cooldown). The
# evidence for the timer lives on `PLOT_REBUILD_SECONDS`, where it belongs.
#
# So this is here on the game's rule rather than on a measurement: the engine will not place a
# structure on ground somebody is standing on, and nothing in an observation reports it. It costs
# a plot skipped for a cycle; the alternative is an order taken and silently discarded, which is
# the more expensive half of the trade at two four-second confirmation windows an attempt.
#
# 120 rather than `PLOT_RADIUS`: this asks about a footprint plus whatever is milling around it,
# where that one asks whether a building's centre belongs to this plot. The two only look alike.
PLOT_CONTESTED = 120.0


# How far from the last known base centre a building still counts as part of the base.
#
# **This anchors `base_centre`, and without it the base walks off across the map.** The centre
# is the mean of the immobile things owned, so every settlement claimed drags it further out -
# a bot eight expansions into a map read its "base" as a point in the middle of the map, put
# `DEFEND_RADIUS` around that, and answered every wandering creep on the map as an attack on
# its base. `free_plots` was measured against the same drifting point and stopped seeing its
# own castle plots. Each reading is therefore taken over the buildings near the previous one,
# which keeps the anchor on the base it started on and still lets it re-seat if that base dies.
BASE_RADIUS = 900.0

# How far the field force's target must move before it is re-aimed. A building does not move, so
# this only fires when the current target dies and the next-nearest one is somewhere else.
AIM_STANDOFF = 250.0

# How many **units** the bot will leave queued at one building, and how many **upgrades**.
#
# Counted separately because they are separate decisions and one queue holds both. A building
# with four battalions and an upgrade waiting behind them delivers the upgrade last, which is the
# opposite of what an upgrade is for: armour on the battalions that already exist beats a fifth
# battalion, and a level-up changes what every later order can even be.
#
# **Two, not four, and four rather than twelve before that.** Depth costs nothing to hold and
# everything to be wrong about: gold spent into a queue is gold committed several minutes ahead of
# the fight it was meant for, and the army the bot needs at cycle 300 is not the mix it wanted at
# cycle 240. A measured run put 229 recruit orders into four buildings and fielded 87 of them -
# the rest were still queued when the base fell, which is 140 battalions' worth of gold that never
# arrived. Shallow queues also let `next_recruit` re-decide the mix against what the opponent is
# actually fielding, which is the whole point of having a counter model.
#
# Four was still too deep against an opponent that attacks early. A match lost to a Medium
# Isengard rush went 2 battalions to 0 by cycle 81 while gold sat committed in queues behind
# buildings that were themselves being razed - and a battalion queued in a barracks that falls is
# worth exactly nothing, where the same gold in a battalion that exists can at least fight. Two is
# deep enough to keep a building busy between cycles and shallow enough that a lost base loses
# little with it.
QUEUE_TARGET = 2
UPGRADE_QUEUE = 1

# What a destroyed keep charges to put itself back up.
#
# **A keep that falls is not a keep that is gone.** It stands as rubble at zero health wearing the
# engine's `RUBBLE` condition, and its own control bar offers `Command_StartSelfRepair` to raise
# it again - which is far cheaper than the ground it sits on is worth, and cheaper than losing the
# base it anchors.
#
# **Not in the ini, and 800 was the wrong half of the answer.** `Command_StartSelfRepair` carries
# no cost of its own, neither keep declares a `BuildCost`, and nothing in `gamedata` prices the
# repair - the figure lives in the engine. A castle keep charges **1000** and an outpost keep 800,
# so a gate at 800 let the order through into the band where it is guaranteed to be discarded.
# Measured live: one attempt at cycle 283 holding ~800, "NOT CHARGED - logic discarded it", and
# the castle keep then stood in rubble until cycle 361 - seventy-eight cycles, about two and a
# half minutes, with no spellcasting and no building anywhere inside the castle. Nothing here
# notices either of those, so the whole cost of the wrong figure was invisible from the loop.
#
# Priced at the dearer of the two, deliberately. Overpricing an outpost's repair delays it by the
# seconds it takes to bank another 200; underpricing a castle's sends an order that cannot work,
# which is the failure this whole check exists to prevent.
SELF_REPAIR_COST = 1000

# What a rubbled keep is allowed to hold back from every other stage while it saves up.
#
# **Running first is not being paid first.** Repair leads the stage order and still waits on
# chance: it can only spend what recruiting has not already taken, so whether the keep goes back
# up this minute or next depends on where the balance happens to be at the instant the stage is
# asked. In the run above that gap was seventy-eight cycles - the balance did climb past the price
# eventually, three times, and each time the repair worked; what it never did was climb *on
# purpose*.
#
# So the repair takes a keyed reservation like a capture does. The point is not that the gold is
# unreachable, it is that reaching it should not be luck.
#
# **Bounded, and the first version was not - which lost a match.** An unbounded promise against a
# balance that is not growing is a freeze rather than a promise: measured at cycle 251 of a run,
# 875 gold with 1200 reserved meant `spendable` of zero, so nothing could be recruited while the
# base was being taken apart, and the run went from `army 8` to defeat. The keep is worth banking
# for only while something is standing to defend it and something is standing to rebuild it - see
# `stage_repair`, which drops the reservation when either is gone. An army is the one thing that
# *is* worth more than the keep, because losing it loses the match and the keep does not.
REPAIR = "repair"

# `KindOf` flags that disqualify an object from the army: structures and plots do not move,
# and a builder sent to the front is a builder lost.
NOT_ARMY = ("STRUCTURE", "IMMOBILE", "DOZER", "PORTER", "BASE_FOUNDATION", "BASE_SITE")

# The engine's own words for the three roles this bot treats differently, read off the **fighting
# member** rather than the horde container - a `GondorKnightHorde` carries nothing useful, and its
# payload `GondorCavalry` carries `CAVALRY`. See `Statics.fighting_template`.
#
# `CAVALRY` is tested before `INFANTRY` because a horse carries both.
CAVALRY = "CAVALRY"
ARCHER = "ARCHER"
SIEGE = "SIEGEENGINE"

# The engine's own word for a spear line, and the one thing a horse must never ride into.
#
# **What punishes the charge is `CrushRevengeWeapon`, not bracing.** An earlier version of this
# comment claimed bracing was "a formation in this engine rather than a property"; that is wrong.
# The charge is not refused - it lands, and then the crushed unit bills the horse through its
# revenge weapon. The shared weapons state the intent plainly:
#
#     ANTI_CAVALRY_INFANTRY_CRUSH_REVENGE_DAMAGE   250
#     BASIC_INFANTRY_CRUSH_REVENGE_DAMAGE           10
#     RANGED_INFANTRY_CRUSH_REVENGE_DAMAGE           5
#
# **So why is this still a flag and not that number?** Because the number was tried and measured,
# and it does not survive contact with the tree. Edain scales revenge per unit rather than using
# the shared weapons - `GondorPikemanCrushRevenge` is `#MULTIPLY( BASE_DAMAGE_PIKEMAN_15
# CRUSH_REVENGE_MULT_PIKEMAN_15 )` - with three consequences, each fatal to a threshold:
#
#   - the absolute figure carries the unit's own power, so a Gondor **swordsman** bills 160 while
#     a Mordor **pikeman** bills 84: any cutoff refuses the charge that beats swords and permits
#     the one that kills the horse;
#   - the ratio to the unit's own damage does not separate them either - Gondor's swordsman and
#     pikeman both read 4.0 - because the revenge and the damage scale together through upgrades;
#   - and many spear lines declare no revenge weapon at all. `IsengardUrukPikeHorde`,
#     `MordorCirithUngolHorde` and `RohanSpearmanHorde` all read 0.0, so a revenge rule would
#     happily charge three of the game's pike units.
#
# The flag is coarse and has to be maintained, and it is still what carries the rule. See
# `CRUSH_REVENGE_CHARGED` for the data-derived half that now sits beside it.
PIKE = "PIKE"

# The roles above read as a **partition** rather than as four independent questions, in this
# order, with `INFANTRY` as what is left over.
#
# **The order is the whole content of it, and every entry is there because some unit carries two
# flags.** A horse is `CAVALRY INFANTRY`, Gondor's spear line is `INFANTRY PIKE`, and the Morthond
# bowmen are `INFANTRY ARCHER` - so read in this order and stopped at the first hit, each lands in
# the bucket that says what it is *for*; read with `INFANTRY` anywhere but last, every fighting
# unit in the game is infantry and the partition says nothing.
#
# This is a coarser reading than `Statics.effectiveness`, and deliberately so: a matchup is a
# number about two specific templates, where this is the question "what kind of thing is the army
# short of" - which has to survive units the plan has never heard of. See `World.role_of`.
ROLES = (CAVALRY, SIEGE, ARCHER, PIKE)
INFANTRY = "INFANTRY"

# How much better a summon one charge away must be for the signal fire's rider to hold rather than
# spend, measured in the share of the army the summon fills. Below this the two are answering the
# same shortage and 75 seconds of accrual is not worth a coin-toss between them; above it the
# rider is being asked to buy the wrong unit because it happened to be affordable first, which is
# what `stage_signal_fire` did for three whole matches. See `signal_fire.role_wait`.
ROLE_PATIENCE = 0.05

# The crush-revenge multiplier at or above which a charge is refused, whatever flags the target
# carries. See `Statics.crush_revenge_multiple` for where the number comes from.
#
# **A second clause, not a replacement, and the measurement says why.** Over the whole tree, all
# 69 non-`PIKE` battalions declaring a multiplier read exactly 2.0, and the 48 `PIKE` ones read
# 2.0 to 6.0 - so 2.5 catches 44 of the 48 pikes and *nothing* that is not a pike. That is a
# perfect false-positive record and a strictly smaller catch than the flag, which is the whole
# reason it is an `or` rather than a swap: on this tree it changes no behaviour at all.
#
# What it buys is the case the flag cannot cover - a mod unit built to punish cavalry that nobody
# tagged `PIKE`. The flag needs a human; this needs the unit to have been given its revenge
# weapon, which whoever balanced it had to do anyway for the unit to work.
CRUSH_REVENGE_CHARGED = 2.5

# How close a hostile must be to an archer battalion to count as being *on* it rather than merely
# near it - the line between "shooting from range", which is what an archer is for, and "in
# melee", where it is a poorly-armoured swordsman. Sized just above a battalion's own spread so
# that a unit standing in the formation counts and one trading arrows across a field does not.
ARCHER_CONTACT = 120.0

# How far behind the melee line a withdrawing archer group is put. Far enough that the pursuer
# meets the melee first, near enough that the archers are still shooting the same fight.
ARCHER_BEHIND = 150.0

# Siege is not recruited at all for now. It is slow, it is escorted or it is dead, and this bot
# has no concept of an escort - a measured run bought eight battering rams that walked to their
# targets alone and achieved nothing that the same gold in infantry would not have. The ban is a
# `KindOf` test rather than a template list, so it holds for every faction's siege.
RECRUIT_NEVER = (SIEGE,)

# What an object must carry to be part of the army: **every order below acts on a selection**,
# so a thing that cannot be selected cannot be commanded, whatever else is true of it.
#
# **Owning something that moves is not the same as commanding it**, and the gap was expensive.
# An economy building spawns civilians (`GondorZiviliist01`), a bought ceiling is an object
# (`CPObject`), and a battalion's standard is one too - all mobile, all with a body, none of
# them a structure, so all of them counted as army. A measured match read 45 where 24 were
# real, and because ids run oldest-first the fakes were at the front of the list detachments
# are taken from: seven civilians were sent to take the map's last settlements.
#
# This flag alone retires the `CPObject` and the banner carrier. What it does not retire is the
# civilian, which is exactly as selectable as a battalion - that is `Statics.is_slaved`'s half
# of the answer, and the two together are the whole test.
SELECTABLE = "SELECTABLE"

# `KindOf` flags marking something that cannot be fought, so it is neither a threat to answer
# nor a target to send an army at.
#
# **This is what a spellbook effect looks like from the object table**, and it cost a whole
# match. Mordor's `EyeOfSauron` is `UNATTACKABLE CLICK_THROUGH NO_COLLIDE NOT_AUTOACQUIRABLE`
# and also `AIRCRAFT HERO` - so it is enemy-owned, has a body, is not a structure and is not
# immobile, which is every test `raiders` applied. It drifts over the base while the Mordor
# player scouts, and the bot answered by ordering its entire army to attack a thing that takes
# no damage. Worse than the wasted orders: every stage that sends units anywhere stood down
# while raiders were home, so one hovering eye switched the second half of the bot off.
#
# Read as flags rather than by name because every faction has some of these and none of them
# share a naming convention.
UNTOUCHABLE = ("UNATTACKABLE", "CLICK_THROUGH")

# `KindOf` marking something that is not a combatant at all - the engine's own word for map
# furniture that happens to walk about.
#
# **Ten rabbits, nine raccoons, six fish and three goats.** That is what one live skirmish had
# standing around, all of it owned by the civilian seat, all of it mobile with a real body and
# none of it a structure - which was every test `hostile` made. So `raiders` reported an attack
# on the base whenever a goat grazed within `DEFEND_RADIUS`, and `stage_expand` and `stage_raid`
# each stand down while that is true. One animal switched off the entire second half of the bot,
# and `defenders` counted the same animals as holding a flag.
#
# Only readable because `Statics.kind_of` expands `#define`s: every animal in the tree writes
# `KindOf = NATUREUNITS_KINDOF` and nothing else.
HARMLESS = ("INERT",)

# `KindOf` marking something in flight rather than something standing - ammunition, not an enemy.
#
# **A bolt in the air passes every test `hostile` makes.** `StahlbolzenProjectile` is
# `KindOf = PROJECTILE NO_COLLIDE HIDE_IF_FOGGED` over an `ActiveBody`, so it is owned by them,
# has hit points, is not a structure, is not `UNATTACKABLE` and is not `INERT` - and a measured
# run sent battalions at it twice, once counting six of them as an attacking force: `defend: 5
# sent at 6 (StahlbolzenProjectile)`. They cannot be caught, they despawn on impact, and every
# order aimed at one is an order not aimed at whatever fired it.
IN_FLIGHT = ("PROJECTILE",)

# The engine's own flag for something that does not deny a base capture. Exactly the question
# `defenders` asks, so it is the flag `defenders` reads rather than a guess about which
# templates can fight.
NO_BASE_CAPTURE = "NO_BASE_CAPTURE"

# How far from a flag a lair still counts as the thing garrisoning it. Its slaves keep to
# `GuardMaxRange` of it - 350 for the shipped ones, plus their wander - and measured lairs sat
# 109 to 185 from the settlement they were denying.
LAIR_RADIUS = 400.0

# The object that raises the command-point ceiling. Every faction's keep sells it, under a
# differently-named button each time, so the producer is found by asking each owned building
# what it can build rather than by naming a keep per faction.
CP_OBJECT = "CPObject"

# Free command points below which the ceiling is raised.
#
# **Now measured against a cap that is actually the cap**, which is what makes this a threshold
# rather than a wish: `command_points_free` reads `base + bonus - used`, and the engine enforces
# that sum. It used to be measured against the base alone, which reported a player at 1262/500 -
# free capacity of zero at every moment - so this fired constantly at one stage of a match and
# never at another, for reasons that had nothing to do with the army.
#
# Sized above a battalion rather than at a round number. Gondor's infantry runs 12 to 60 points a
# horde, so a floor under that lets the last slot sit unusable while the trigger reports room.
# It remains a decision about when more ceiling is *worth* buying; nothing here stops producing
# on the strength of it, because a recruit that does not queue is the better signal - see
# `stage_recruit`.
CP_FLOOR = 80

# An **external plot** is any plot standing outside a base that a faction can claim and unpack:
# in Edain the settlement (`WirtschaftPlotFlag_Real`), the outpost (`ExpansionPlotFlag`), and
# the castle and camp flags (`FestungPlotFlag<XX>_Real`, `LagerPlotFlag<XX>_Real`). They are
# **not** found by name here: a plot is external if its own unclaimed command set carries an
# unpack button, which `Statics.unpack_buttons` answers and which holds for every faction and
# map without a table to maintain. Naming one template found settlements and silently walked
# past every outpost, castle and camp on the map.
#
# Claiming one is three separate problems - the enemies near it, the standing next to it, and
# the building order - and only the last is an order the API issues directly.
#
# **`owner_index is None` means occupied, not free.** A free plot belongs to the civilian
# player (a small positive index) and flips on approach; `None` marks one an existing base
# already stands on, and no amount of standing there will move it. A force was parked 43-64
# units off such a castle for 90 seconds with nothing happening at all.
OCCUPIED = None
# The name the capture reservation is filed under, and what it holds back before the exact
# price is knowable.
#
# **An unclaimed flag quotes no price.** Claiming swaps its palette, so until the force is
# standing on it the only button offered is the argument-less claim - which names no template and
# so costs nothing this side of arrival. Edain's settlement buildings start at 200, which is what
# this covers; the moment the flag flips, `capture_price` reads the real number off the palette.
#
# Erring high is the cheap direction. Over-reserving delays one battalion by a few seconds;
# under-reserving loses the walk, the fight and the capture, which is the failure this exists for.
CAPTURE = "capture"
CAPTURE_RESERVE = 200

# How near the flag a unit has to stand for ownership to transfer. The engine's own figure is
# about 10; this is the distance the force is *sent* to, so it allows for pathing spread.
CAPTURE_RADIUS = 35.0
# Enemies within this of the flag deny the capture and are cleared first.
CONTEST_RADIUS = 150.0
# How many enemy fighters near a flag one battalion of the force is willing to face. Above this
# the flag is left alone.
#
# **A capture is a fight, and the bot had no test for whether it was a fight worth having.** A
# measured match sent the same three battalions at a flag held by eight to twelve defenders for
# sixty consecutive cycles, logging "0 in range" every one of them: they never arrived, because
# they were being killed on the way and replaced from the barracks. The army fell 17 to 13 while
# the main force stood at home. Better below one - a battalion trades roughly evenly with a
# battalion, and the force is away from its own base while the defenders are at theirs.
CONTEST_ODDS = 0.75
# How many consecutive cycles the force may fail to make progress toward its flag before it is
# given up on. Progress is closing the distance **or** standing in the fight for it - see
# `stage_expand`, where arriving and killing the lair stops looking like a stall.
EXPAND_PATIENCE = 8
# How many cycles the force may stay committed to one flag however well it seems to be doing.
# The engaged-is-progress rule above has no natural end on its own: a force parked next to a lair
# it cannot break reports progress for ever. About two minutes at the default interval, which is
# several times what taking a guarded settlement actually costs.
FLAG_PATIENCE = 40
# How much nearer counts as nearer. Units jostle and path around terrain, so a stricter test
# would read a step sideways as progress and never run out of patience.
CLOSING = 20.0
# How long a flag sits out once it has been given up on. Long enough for the match to change -
# the defenders may leave, and the force may kill them on its way somewhere else.
FLAG_COOLDOWN = 120.0
# How long a move order is left alone before being reissued. A battalion crosses a map in tens
# of seconds, and every reissue restarts its path from a standing start.
FIELD_REORDER = 12.0
# How long an attack order is left alone. Longer than a move, because what confirms it is the
# target taking damage and that cannot happen until the walk is over.
ENGAGE_REORDER = 15.0
# Cavalry ride on their own, and the reason is the one thing they have that nothing else does.
#
# **Speed is only an advantage if it is spent.** Folded into the main force, a horse walks at the
# pace of the spearmen next to it and fights whatever the infantry was going to fight anyway -
# which is the matchup it is worst at, because a wall of pikes is what cavalry loses to. Ridden
# separately it reaches the two things in an enemy army that cannot answer it and that everything
# else struggles to reach: the siege engines shelling our buildings from outside the fight, and
# the archers standing behind their own line. Both are `KindOf` questions (`SIEGEENGINE`,
# `ARCHER`), so this needs no table and works against any faction.
#
# The minimum is two because one battalion of horse is a gift to any formed line, and this mission
# deliberately rides past whatever is in the way rather than clearing it.
CAVALRY_MIN = 2
# How long a cavalry order is left alone. Shorter than the field force's: what they chase moves,
# and they are fast enough that a stale order wastes more than a fresh one costs.
CAVALRY_REORDER = 10.0
# How many battalions ride in one party once the horse have run out of siege and archers to hunt.
#
# **Small, because what they are sent at cannot fight back.** An undefended settlement building is
# a stationary pile of hit points with no weapon: two battalions of horse take it down and four
# take it down no faster, so every pair past the first is better spent standing on a different
# building somewhere else on the map. This is the one job where splitting is strictly better than
# massing, and it is only available to cavalry - infantry sent the same way arrives after the
# building has been rebuilt.
CAVALRY_PARTY = 2
# The most cavalry parties given a fresh order in one cycle. Same bound and same reason as
# `MAX_RESPONSES`: each costs a selection and a confirmed attack, and a party already riding needs
# no order at all.
MAX_CAVALRY_ORDERS = 2

# How far **past** the target the ride-through is aimed.
#
# **A trample is a move order, and that is the whole mechanic.** `attack` names an object, so the
# engine walks the horse up to it and stops it there to swing - which is the one thing a horse is
# worst at doing. Riding *through* the same battalion knocks it down, damages it and costs the
# rider only some speed, and the only difference in the order is that it names a point on the far
# side instead of naming the battalion. See `Statics.crushes` for which battalions that works on.
#
# Past rather than at: aimed at the target's own position the horse arrives and stops, which is
# the stationary fight again with extra steps. A battalion is roughly 100 units across in this
# tree, so this clears the far edge of one and leaves the party gathered rather than strung out
# across the map.
TRAMPLE_OVERSHOOT = 200.0

# How much room the horse needs before a ride-through is worth ordering.
#
# **A crush is a momentum check, not a collision.** Every crusher in the tree carries a
# `MinCrushVelocityPercent` alongside its `CrusherLevel` - `GondorKnightHorde` names
# `CAVALRY_CRUSH_MIN_VELOCITY_10_ELITE_HORDE` - so a horse that starts its charge already
# standing on the enemy walks through at a fraction of top speed and flattens nothing. Below this
# the target is simply attacked, which is what the horse would end up doing anyway.
TRAMPLE_RUNUP = 250.0

# How long the ride-through is left to happen before the party is told to turn and fight.
#
# The charge ends when the horse is out the other side, and nothing observable says when that is:
# the party is spread, the target moves, and "arrived" is a question about fifteen riders rather
# than one. So it is timed. Long enough to cross `TRAMPLE_RUNUP` plus `TRAMPLE_OVERSHOOT` at a
# cavalry pace, short enough that the party is not still walking away from a fight it started.
TRAMPLE_SECONDS = 8.0

# How far an enemy building has to be from the enemy's own centre to be worth going after. Their
# keep is defended by everything they own and razing it wins nothing this bot needs - the ground
# it is trying to take is outside, and see the module docstring for what came of attacking keeps.
RAID_STANDOFF = 600.0
# How near the base an enemy has to be to count as an attack rather than a distant war. A base
# under attack is not a base to leave, and a bot that only fights at a fixed army size loses
# with gold 0 and five battalions while it waits to reach twenty-four.
DEFEND_RADIUS = 700.0
# How near one of our buildings an enemy has to be to count as attacking it. Smaller than
# `DEFEND_RADIUS`, which asks the same question about the base as a whole: a farm out on a
# settlement has no wall and no spread, so anything this close to it is on it.
HOLDING_RADIUS = 350.0

# How much stronger than the threat a response group is sent. **Slightly**, and the word is the
# specification: a group matched one-for-one trades evenly and loses to the reinforcements, and a
# group sent at twice the odds is a second army the map is paying for. Rounded up, so two orcs at
# a farm are answered by three battalions rather than by two and a half.
RESPONSE_ODDS = 1.25

# The most threats answered with their own group in one cycle. Each costs a selection and a
# confirmed attack order, and the cycle still has to recruit, build and expand - so the rest wait
# a cycle rather than turning the loop into a queue of confirmation windows. Ranked, so the two
# that get answered are the two that matter: see `threats`.
MAX_RESPONSES = 2

# How many battalions answer one raider. **Defence used to be all or nothing, and "nothing
# else happens" was the expensive half.** Every other stage stood down while anything hostile
# was near home and the whole army was recalled to deal with it, so a single creep that
# wandered in stopped the expansion and the raid for as long as it lived - and on a map covered
# in creeps that is most of the match. A guard is sized to what is actually there instead, and
# only escalates to everything when the base is genuinely outnumbered.
GUARD_PER_RAIDER = 2
# Defence re-aims faster than anything else: raiders move, and the nearest one changes.
DEFEND_REORDER = 8.0

# How long a group holds an order against a raider that has **not** moved and has **not** been
# replaced as the nearest.
#
# **`DEFEND_REORDER` is the re-*aiming* interval, and using it as the re-*ordering* interval was
# a different decision made by accident.** A group walking to a raider was re-issued the same
# attack on the same target every 8 seconds for the whole approach, each one costing a selection
# and a confirmation window, and each one recorded as a failure because a group that has not
# arrived cannot have hurt anything. Measured over one match: the same `IsengardWargRiderHorde`
# attacked at 313, 319, 330, 336, 349 and 362 seconds, and a `defend` ledger of 11/46.
#
# The raider moving is still answered immediately - that is the 200-unit test in `hold`, which is
# what `DEFEND_REORDER` was actually for. This only governs re-sending an order nothing has
# invalidated, which is a keep-alive rather than a decision.
DEFEND_KEEPALIVE = 30.0

# How close a hostile has to be to a group's battalions to count as **contact** - the test that
# keeps a group together while it is actually fighting.
#
# Tighter than `HOLDING_RADIUS`, and that gap is the whole point. A holding is threatened by
# anything within 350 of the *building*; a group is in contact only when something is within
# fighting distance of the *battalions*, wherever they have got to. Using the holding's radius for
# both is what made the rule self-cancelling - the group walks out to meet the raider, both leave
# the holding's circle together, and the group is released mid-fight.
DEFEND_CONTACT = 250.0

# How long a group survives after it has neither a threatened holding nor anything in contact.
#
# **Hysteresis, because a raider that steps out of range for one cycle has not been beaten.**
# Measured live, a group formed at cycle 122 and was gone by 125 - four seconds - while the raider
# it was raised against was still alive; its battalions turned twice and went back to marching. A
# release rule with no delay turns every raider that backs off into a free order-cancel on two of
# our battalions, which is a move an opponent gets for nothing.
#
# 12s rather than the 30 of `DEFEND_KEEPALIVE`: this holds battalions *out of* the rest of the
# army's jobs, so it is the more expensive of the two to overshoot, and six cycles is already far
# longer than the flicker it exists to absorb.
DEFEND_COMMITMENT = 12.0

# How many battalions the guard needs per raider before it goes at them, rather than gathering.
#
# **A guard that is losing must stop arriving one at a time.** Nothing used to test whether the
# fight was winnable: the guard was refilled from survivors and fresh recruits every cycle and
# sent straight in, so a measured match answered fourteen raiders with "5 sent", then 4, 2, 3,
# and 1 - each rebuilt battalion walking into the mass separately and dying separately, while the
# base was razed around them. The army had been 34 twenty cycles earlier.
#
# Below this the guard is ordered to the base centre instead, which is where reinforcements
# appear and where it is nearest to everything worth holding. That is not a retreat: units under
# attack fight back wherever they stand, so the only thing given up is the *walk* into the
# enemy's mass - and gathering is the one thing that can turn the fight, because nothing else the
# bot does adds battalions to it.
#
# Below one on purpose, and well below it: a battalion at home trades better than a battalion
# that has walked, half the map's raiders are creeps rather than an assault, and the alternative
# to fighting at 0.6 is not fighting at 1.0 - it is being razed while gathering to a number the
# match will never allow.
GUARD_ODDS = 0.6
# How many battalions make a full expansion party, and the fewest a raid will set out with.
#
# **A party works from the moment it exists and fills up as it goes.** The starting battalions
# are a party on the first cycle and go straight out; recruits join them until the party is at
# strength, and only then does the next one begin forming - so units idle waiting for a *group*,
# never waiting for the army as a whole. Gating the stage on army size instead left the two
# starting battalions standing in the base through twenty cycles with fifteen free flags on the
# map, because `opening()` ends the moment the first barracks stands and this build raises one
# on cycle 1.
#
# What stops an under-strength party throwing itself away is `CONTEST_ODDS`, measured against
# the party that would actually go - so two battalions take an empty settlement and decline a
# lair, which is the judgement the old army-size gate was a blunt proxy for. That gate cost a
# measured run its army: 5 -> 3 while the force walked to a contested flag it never reached.
EXPAND_PARTY = 4
EXPAND_MIN_ARMY = 6

# The fewest battalions a party will set out on a *raid* with.
#
# A capture is a walk and a build, so an under-strength party is still worth sending; a raid
# is a fight with something that is usually guarded, and a remnant sent at a lair is a
# remnant given away. Equal to a full party, so raiding is what parties do when they are
# whole and have run out of settlements - and a party ground down below strength waits to be
# topped up instead.
RAID_PARTY = EXPAND_PARTY

# How far from an archer a live enemy is still worth shooting instead of the building in front
# of it.
#
# **An archer put on a structure stops being an archer.** The party attacks one thing - the lair
# that garrisons a flag, the farm being razed - and the bow battalions walk up to it and shoot
# masonry while the wildmen it keeps spawning kill the infantry beside them. Archers outrange
# every foot soldier in the game and that reach is the whole of what they are bought for; spent
# on a wall it buys nothing that a fighter would not have bought more cheaply.
#
# Deliberately a little past bow range rather than exactly it: a target barely out of reach is
# one step away, and ordering the shot is what closes that step. Too generous and the archers
# wander off the party's fight to chase something across the field, which is the failure this
# has to stay short of.
#
# Widened by a third from the 250 it started at, on watching a run: the bows were leaving live
# targets standing just outside it while they shot a lair, which is the exact trade this
# exists to stop.
ARCHER_REACH = 333.0

# How near an enemy has to be for the party to leave somebody fighting it rather than sending
# every battalion at the building.
#
# **The case this exists for is a party knocking down a lair while the lair's own output hits it
# in the back.** Nothing in the party was answering that: a structure is the target, so every
# order went to the structure, and the troops around it fought unopposed for as long as the
# demolition took. One battalion turning round is cheap - the building is not going anywhere and
# does not fight back - and it is the difference between taking losses for free and trading.
#
# Sized to `ARCHER_REACH`, deliberately the same number: that is already the distance at which
# this bot considers something "in reach" of a party, and a second nearly-equal radius would be
# two constants describing one idea.
SCREEN_REACH = ARCHER_REACH

# How well a battalion must trade into what is standing on the party before it is peeled off to
# fight it rather than left on the building - `Statics.effectiveness`, where 1.0 is an even
# matchup.
#
# **This is what makes a lair a pike job without naming a warg or a troll.** The armour blocks say
# it outright: every troll armour in the tree takes `SPECIALIST` at 90-170% and `SLASH` at 20-50%,
# and `WargpackEdainArmor` reads `SPECIALIST 170%` against `SLASH 100%`. So a spear line clears
# this comfortably against either and a swordsman is nowhere near it - which is the whole content
# of "swordsmen take too much damage at these", arrived at from the data rather than from a list
# of lairs that a mod would invalidate.
#
# Set above 1.0 rather than at it because the peel has to be worth the order. At 1.0 any unit the
# matchup does not actively punish would qualify, which is most of an army against most things,
# and `screen` would stop being a screen and become "everybody attack the nearest thing" - the
# arrangement it exists to prevent. A quarter better than even is a real edge and it is roughly
# where the tree's own numbers separate: the counters sit at 1.35-1.7 and the neutral matchups at
# 0.9-1.1, with very little in between.
COUNTER_EDGE = 1.25

# **In the opening the starting battalions are exactly what claims plots**, so the rule above
# is suspended until the first production building stands. That is not a contradiction of it:
# the opening runs before anyone can contest a flag, the units have nothing else to do until
# there is a barracks to defend, and a plot claimed in the first minute pays for the whole
# match. `EXPAND_MIN_ARMY` starts mattering the moment there is something to lose.
OPENING_EXPAND_MIN_ARMY = 1
# Battalions before the command-point ceiling is worth buying. Raising it early spends a keep's
# queue slot on nothing: the cap only binds once there is an army near it, and the opening's
# gold belongs to the barracks.
CP_MIN_ARMY = 4
# How long a plot that refused a build sits out, and how many refusals retire an upgrade. Also
# how long a plot just *built* on rests, so a building razed at 0% is not instantly re-bought -
# measured live at four builds and four razings on one plot inside five seconds.
PLOT_COOLDOWN = 45.0

# How far from an outlying holding a lone tower is put, on the side the enemy will come from.
#
# **Inside `HOLDING_RADIUS`, and that is the whole point.** A tower placed to cover a settlement
# has to be near enough that whatever comes for the settlement is in its arc; put further out it
# is a lone building in a field, which is what the base-centred placement it replaces amounted
# to. Comfortably short of the 350 that counts as "on" a holding, and long enough that the tower
# is between the holding and the attacker rather than behind it.
TOWER_STANDOFF = 220.0
# How far from the plot marker a newly raised building may sit and still count as the thing
# built on it. Wider than PLOT_RADIUS on purpose: that one asks "is this plot taken", where a
# tight radius is right, and this one asks "did my order raise something", where a large
# structure's centre genuinely lands further out.
BUILD_RADIUS = 140.0
UPGRADE_ATTEMPTS = 2
# `KindOf` flags marking an object whose upgrades are not worth a policy's gold. A wall segment
# sells postern gates and turrets and carries a real `ProductionUpdate`, so nothing structural
# rules it out - but it was absorbing the entire research budget, at 300g a go, while the army
# fought unupgraded. Castle furniture is a luxury; armour is not.
NOT_WORTH_UPGRADING = ("WALL_UPGRADE", "WALK_ON_TOP_OF_WALL")

# Gold above which upgrades outbid unit production. Upgrades and units come out of one purse,
# so the two need an arbiter: a floor rather than a phase, because a phase that shops while
# the army waits is punished by anything that attacks, and a bot that upgrades only after
# massing has already fought its first fight with bare troops. Set above the dearest thing in
# a starting tech chain (Gondor's heavy armour tech is 1000) so the floor never blocks the
# chain it is meant to pace.
UPGRADE_FLOOR = 1500

# How many of each economy building are worth laying - the rung where its discount stops
# improving, and therefore where another copy buys nothing.
#
# **Read off the data rather than measured.** Edain's economy buildings each carry a
# `CostModifierUpgrade` with `StartsActive = Yes` and a ladder of six percentages - 0, -10, -15,
# -20, -25, -30 - indexed by how many of that building the player owns. `GondorWohnhaus` points
# its ladder at an `ObjectFilter` of the faction's elites plus `CPObject`; `GondorForge` points
# an identical ladder at `ApplyToTheseUpgrades`, the five per-object unit upgrades. So six is not
# a judgement about base size: it is the count at which the sixth rung is reached and a seventh
# copy is a plot spent for a discount that cannot improve.
#
# **A count rather than a balance**, which is the difference between this and `RESEARCH_FLOOR`.
# A research centre is bought to unlock techs, so it waits for the gold to buy them with; a
# building laid for its own output is worth having as soon as the base is past the stage where
# another house is the better use of the plot.
ECONOMY_CAP = 6

# Gold above which a plot is worth spending on a research centre rather than on more economy.
#
# **The same floor as `UPGRADE_FLOOR`, and deliberately the same number**, because the building
# and the upgrades it sells are one decision. Laying a `GondorMarketPlace` and a `GondorForge`
# and then not being able to afford `Upgrade_MarketplaceUpgradeIronOre` is the failure the
# earlier version of this file recorded: 1800g of buildings that sold nothing. A surplus large
# enough to justify the centre is by construction large enough to buy from it.
#
# 1500 rather than the 1000 of Gondor's dearest single tech, so the purchase that follows the
# building does not have to wait for the balance to climb a second time.
RESEARCH_FLOOR = 1500

# How far a counter advantage is allowed to move the army mix, as a floor and a ceiling on the
# per-unit weight. See `Bot.counter_score`: the raw numbers run 0.15 to 1.70 against a single
# opponent template, and multiplying a target share by 0.15 is not "prefer something else", it
# is "never build this again" - which turns a counter into the same one-unit army the counter
# exists to prevent. Clamped, a bad matchup halves a unit's share and a good one doubles it,
# and everything the faction's own definition asks for still gets built.
COUNTER_RANGE = (0.5, 2.0)

# How much of a basic unit's target share moves to the elite that succeeds it, once the
# building that sells it has levelled. See `Plan.succession`.
#
# **Most, deliberately not all.** The elite is twice the price in both of Gondor's pairs - 600g
# against 300g for the citadel guard over the pikeman and the ranger over the archer - so a
# clean swap buys half as many battalions out of the same income and thins the line exactly
# when the mid game is at its most dangerous. It also puts the whole of one role behind a
# single queue: lose the levelled barracks and there is no anti-cavalry unit orderable at all,
# where a mix still has the cheap one. Two thirds is a real shift - the elite becomes the
# majority of the role within a few cycles - while the basic keeps flowing.
SUCCESSION_SHARE = 0.65

# How many objects must sit inside a spell's own radius before it is worth firing at them.
#
# **The threshold exists because a cast is scarce, not because it is expensive.** A spellbook
# power costs nothing to fire and recharges in 180 to 940 seconds, so the question is never "can
# I afford this" - it is "will this be worth more than the same spell three minutes from now".
# Three is a battalion's worth of presence: fewer than that inside the radius and the spell is
# being spent on a scout.
CAST_MIN_TARGETS = 3

# How hurt a building has to be before a heal is worth spending on it.
#
# **`is_damaged` means `health < 1.0`, which makes a scratch a target.** That is the right
# definition for the observation API - a query asking for damaged objects wants all of them - and
# the wrong one for a spell that recharges in three minutes. Measured across two live runs, the
# heal went on buildings at 100%, 98%, 94% and 89% while a farm burned at 11% and the keep of a
# collapsing base sat at 0%; each of those cost the charge that the real casualty then had to
# wait for.
#
# Three quarters rather than something tighter, because a heal covers a radius and `aim` takes
# the densest cluster: the bar is what makes a building count toward that cluster at all, not
# what the spell is finally judged on. A building this side of it is taking fire.
CAST_HEAL_THRESHOLD = 0.75

# How hurt a building has to be to be worth the charge *straight away*, before the spell has
# spent `CAST_PATIENCE` finding nothing better.
#
# **Spending it early is how a repair arrives late.** `CAST_HEAL_THRESHOLD` alone fires at the
# first thing under three-quarters, which on any map is a farm taking a nibble - and then the
# building that is genuinely dying waits out the whole recharge. Measured: a cast on a
# `GondorWohnhaus03` at 70% at 120s, the same building at 52% at 297s, and a structure sitting
# under half health for twenty seconds in between with nothing available to save it.
#
# So the bar starts here and falls to `CAST_HEAL_THRESHOLD` once the spell has been ready and
# unused for `CAST_PATIENCE` - the same arithmetic `wanted_targets` applies to every other
# effect, and for the same reason: a charge held for ever is worth nothing either.
CAST_HEAL_URGENT = 0.6

# How long a ready power waits for a target worth `CAST_MIN_TARGETS` before it settles for less.
#
# **Both failure modes here are real and they pull opposite ways.** A bot that fires the moment
# anything is in range spends Army of the Dead on two orcs; a bot that holds out for the perfect
# target holds it for the whole match, and an uncast spell is worth exactly nothing - the same
# arithmetic that makes an unspent spellbook point worthless. So the bar drops rather than
# disappearing: after this long ready with nothing good, half the requirement will do.
#
# Two minutes is under the shortest recharge in Gondor's book (180s), so a power that keeps
# finding nothing still fires more often than it recharges.
CAST_PATIENCE = 120.0

# How much clear ground a spell-placed structure needs, and how far from the base to look.
#
# **A power that builds is the one aim with no target test, and that is what broke it.** The
# build effect returned `base_centre()` unconditionally - a point in the middle of the base,
# which is the first place a base runs out of room. Measured live: Gondor's Lone Tower landed
# once, was then refused three times, twice at byte-identical coordinates
# `(696.78, 2609.68, 150.0)`, and landed again only after the base had been partly destroyed and
# the ground cleared. Nothing about the power was wrong; it was being aimed at occupied ground.
#
# The clearance is a little over a Men castle's plot spacing (about 150), so a spot this far from
# everything standing has room for a building. The rings stop before `BASE_RADIUS`, because a
# tower placed beyond the base is a tower defending nothing.
CAST_BUILD_CLEARANCE = 160.0
CAST_BUILD_RINGS = (0.0, 200.0, 350.0, 500.0, 650.0)

# How much clear ground a summon needs, and how far from the fight to look for it.
#
# **A summon is not dropped on a point, it is unpacked over an area.** Measured by hand-casting
# both of Gondor's ground summons into open ground and watching what arrived: Army of the Dead
# put five spawn eggs about 100 units out in each direction from the aim point and hatched a host
# spanning roughly 160 by 105; the Grey Company covered x 1000-1153 by y 2061-2205 around a cast
# at `(1091, 2131)`. Aimed at the middle of twelve enemies there is nowhere for any of that to
# stand, and the engine discards the order - which is what `SpellBookArmyoftheDead` and
# `SpellBookDieGraueSchaar` each did, on the same cluster that `SpellBookAdler` landed on
# happily, eagles needing no ground at all.
#
# The rings stay tight, because a summon put down out of reach of the fight it was called for is
# a summon spent on walking.
CAST_SUMMON_CLEARANCE = 120.0
CAST_SUMMON_RINGS = (0.0, 150.0, 250.0, 350.0)

# How long a spot the engine refused is left alone before it is offered again.
#
# **A refusal does not prove the ground is bad.** Terrain is one reason the engine declines a
# placement; something standing in the way is another, and the two are indistinguishable from
# here. `open_ground` checks the spot is clear when it aims, but a battalion can walk into it
# during the confirmation window - so striking the spot off for the rest of the match would
# blacklist perfectly good ground on the strength of a passing unit.
#
# Timed out rather than permanent, the same way `_blocked_plots` handles a plot that refused a
# building. Longer than a battalion takes to cross its own clearance radius, so a spot that was
# merely occupied comes back; short enough that a base with genuinely little buildable ground
# still gets several attempts across a match.
CAST_GROUND_COOLDOWN = 120.0

# What to treat a power's radius as when the data gives none. `RadiusCursorRadius` is what the
# player sees as the spell's circle and most powers declare one, but a few carry the figure on
# their module instead in a form this cannot read - `HealRadius` is a macro. Used only to size a
# confirmation window, never to decide a target.
CAST_RADIUS_FLOOR = 100.0

# How much longer a power waits after the engine refuses it, when the engine's own ready-frame
# was not available to ask.
#
# **The ini's recharge is the wrong number and it is wrong in both directions.** Edain rescales
# `SpecialPower.ReloadTime` per player, so `Powers.ready`'s fallback clock is an estimate rather
# than a reading - and a measured run showed it estimating short. Rebuild's attempts landed at
# 179, 185, 183, 182, 184, 181 and 189 seconds against a declared 180, which is the bot firing
# on its own timer; three of those attempts were refused outright, at 182s and 178s, while 189s
# went through. So the real recharge sits just above the declared one and a fixed clock cannot
# find it.
#
# Multiplicative rather than a constant margin, because the error scales with the number: a
# power declaring 940 seconds is wrong by more than one declaring 180. Growth is kept slow so a
# refusal caused by something other than the recharge - a target that walked away, a placement
# the engine would not take - costs a little patience rather than benching the power.
CAST_BACKOFF = 1.15

# The ceiling on that growth, as a multiple of the declared recharge. Without one, a power the
# engine refuses for a reason that has nothing to do with its clock - Lone Tower aimed at ground
# already built on - would back off for ever and never be tried again once the ground cleared.
CAST_BACKOFF_CAP = 3.0

# How long a camera shot is held before another subject may take it.
#
# **The same lesson as the defence commitment window, in the one place it is purely cosmetic.**
# Every stage re-decides from scratch each cycle, so a camera that simply pointed at the current
# best subject would cut on every tie and every transient - at a two-second interval that is a
# slideshow of half-second shots, which is unwatchable and tells the viewer nothing. A shot is
# therefore held for this long unless something *strictly more important* happens, which is the
# only interruption a viewer reads as meaningful rather than as jitter.
SHOT_DWELL = 6.0

# The camera's zoom is deliberately **not** a knob here.
#
# An earlier version chose one per shot - closer for fights, wider for marches - and it looked
# wrong for a reason unrelated to the figures picked: the engine interpolates nothing, so every
# change was a snap, and a viewer reads a snap as a fault rather than as emphasis. `look_at` keeps
# whatever the view already had when it is not told otherwise, and it is never told otherwise.

# How far the subject has to move before the camera cuts instead of gliding.
#
# **Cut on a new subject, glide on a moving one.** `look_at` is a hard jump - the engine does no
# interpolation - so following a walking force by easing toward it each cycle reads as a pan,
# while easing across the whole map toward a *different* force reads as a drift through empty
# ground for several seconds. Past this distance the honest edit is a cut.
SHOT_CUT = 1200.0

# How much of the remaining distance the camera closes each cycle while gliding. Under one so the
# motion eases out rather than snapping; high enough that it keeps up with a force on the move.
SHOT_EASE = 0.45

# How many times a flag may be given up on before it stops counting as map left to take.
#
# **This exists to let a run end.** `raid_target`'s last resort - the enemy's victory-counting
# buildings - is gated on the map being finished, and the first version asked for zero free flags.
# Measured across two full runs that reached 94% and 88% map control with 19 and 24 battalions
# spare: `flags` bottomed out at 1 and 2, the gate never opened once, and both runs spent their
# endgame walking at settlements they had already failed to take. Every remaining flag in both was
# one the force had abandoned repeatedly - plot 202 four times in one run.
#
# Three, not one: a single abandonment is ordinary - a lair repopulated, a party arrived
# under-strength, the walk was interrupted by a raid - and treating it as permanent would write
# off half a map. Three says the force has been back with what it had and it did not work.
FLAG_GIVE_UP = 3

# The highest command-point ceiling the engine will honour.
#
# **The ceiling has its own ceiling, and nothing in the reading says so.** A seat starts at a flat
# base of 500 and each `CPObject` adds 200, but only five are ever counted - so 1500 is the end of
# it, and a sixth purchase is 500 gold and a keep queue slot spent on nothing. That matters more
# than an ordinary waste because of what triggers the purchase: `command_points_free` sitting at
# the floor is permanently true once the cap is reached and the army is against it, so without
# this the stage would buy one every cycle for the rest of the match.
#
# Compared against the cap the game reports rather than a count of purchases, because the objects
# die with the keep that holds them - the question is what ceiling is in force now.
CP_CAP_MAX = 1500

# The endgame: when the match stops being about taking ground and starts being about ending it.
#
# **The module docstring records two pushes that were removed, and the failure was the gate both
# times rather than the target.** A battalion count asked "am I strong enough", which nobody can
# answer from inside a match where the army is spent as fast as it is built. A stalemate timer
# turned a 600-cycle undefeated run into a 394-cycle defeat, "because committing did not create an
# army that could win, it only stopped the expansion that was paying for one". Both fired while
# there was still map to take, and paid for it.
#
# These two ask something both answerable and already true when they fire. Measured over run 4
# (1400 cycles, gap of rohan): map control reached 85% at cycle 619 and finished at 94%, and the
# command-point fill sat at 96-99% for the last four hundred cycles - 1440/1500 with eighteen
# battalions and 105,012 gold banked and nothing left to spend it on. Both gates were true for
# more than half the run, and the run ended undecided.
#
# So this is not a gamble on being strong enough. It is the observation that the army has stopped
# growing because it cannot, and the map has stopped growing because there is nothing left worth
# taking - at which point continuing to expand is not the thing paying for the army, it is the
# thing instead of using it.
# **Both lowered from 0.85 and 0.80 to 0.75.** Run 8 is what moved them: the push did fire, at
# 81% control and against its ceiling, and by the time it did the match had already been decided
# in every sense except the opponent still being alive. The bot then spent 250 cycles holding 88%
# of the map with **31,679 gold it could not spend**, command-point capped and unable to convert,
# while the army halved from 28 to 14 - the endgame arriving after the point where committing
# could still have been cheap.
#
# The two removed pushes failed by firing while there was still map to take. 75% is still well
# past that: three quarters of the flags held is not a bot with expansion left to do, it is a bot
# that has won the map and is waiting for permission to use it.
PUSH_CONTROL = 0.75
PUSH_ARMY = 0.75

# How far the army may be ground down before the push is called off and the match goes back to
# being played normally.
#
# **A latch with no release is the 394-cycle defeat again.** Committing must survive the losses
# a push takes, or the first casualties drop the fill back under `PUSH_ARMY` and the force turns
# round - which is worse than never having gone. But a force that has lost more than half its
# ceiling is not going to finish anything, and standing in their base being killed is exactly the
# "stopped the expansion that was paying for one" failure with extra steps. Below this, expansion
# and recruitment resume and the gates have to be met again from scratch.
PUSH_SPENT = 0.40

# How many battalions stay behind the push to go on taking and retaking the map.
#
# **The push used to take everything, and the map came apart behind it.** A measured run latched
# at 75% control and had bled to 56% five hundred cycles later, losing built settlements at one
# end while the whole force stood at the other - and nothing could answer, because latching
# dissolves the parties and `stage_expand` had none left to send. The release is on army strength
# alone, so control is never re-checked and the bot never comes back for it.
#
# Two, and horse for preference. It is small enough that the push is still the whole army in every
# sense that matters to the fight at the keep, and a settlement is taken by standing on it rather
# than by winning a battle there - so two battalions that nobody is contesting take exactly as much
# ground as twenty. Cavalry because the job is a circuit rather than a fight: what is left loose at
# this stage of a match is undefended flags and lone buildings, and the only thing that decides how
# many of them get visited is how fast the party rides between them.
PUSH_RAIDERS = 2

# How near a remembered enemy building the force must get before its absence is believed.
#
# The fogged view has no memory, so what has been seen is remembered here rather than re-read -
# see `Warfare.remember_keeps`. A remembered keep that is simply out of sight must not be
# forgotten, or the force turns round the moment it loses vision of where it is going; one the
# force is standing on top of and cannot see is genuinely gone.
PUSH_ARRIVED = 400.0

# How far a battalion may have drifted since last cycle and still count as **standing**.
#
# The whole formation decision turns on this number, because what a defensive formation costs is
# speed and speed is only worth something to a battalion that is going somewhere. A shield wall
# is +20% armour for -30% movement: free to a battalion holding a farm, and a real loss to one
# still walking into the fight.
#
# Measured against the *previous cycle's* position rather than against an order, deliberately.
# The bot issues orders from a dozen places and a battalion's intent is spread across all of
# them, but where it actually is can be compared to where it actually was - and that is the same
# question the engine is answering. A battalion crossing the map at 40-odd units a second covers
# several hundred between cycles; one standing in a melee jostles by a few tens.
FORMATION_STILL = 60.0

# How long a battalion must have been standing and fighting before the formation is worth
# changing, in cycles.
#
# **A formation change is not free and its cost is not the order.** The battalion re-forms its
# ranks to get into it, which is seconds of a fight spent shuffling rather than swinging, so a
# rule that flips on the first cycle of contact pays that price for every skirmish that is over
# in four seconds. Two cycles of standing still with something hostile in reach is a fight that
# has actually settled into one.
FORMATION_PATIENCE = 2

# The shortest time between two formation orders to the same battalion.
#
# Hysteresis, and the failure it prevents is the one every latch in this file exists for: contact
# and stillness both flicker, and a battalion that toggles on the flicker spends the fight
# re-forming in both directions and standing in neither. Long enough that a switch has to be
# worth committing to, short enough that a battalion which has genuinely been sent somewhere gets
# its speed back inside one march.
FORMATION_HOLD = 20.0

# Heroes are their own mission, and the reason is what they cost.
#
# **A hero is not a battalion with more hit points.** Beregond is 1300 gold and 30 command points
# against a battalion's 200 and 12, and unlike a battalion it does not come back when it dies -
# it goes to the tail of the revive list and has to be bought again. So the trade that makes a
# battalion worth fielding, that it will probably die somewhere useful, is exactly wrong here.
#
# What makes it worth the money is a kit that nothing else in the army has, and a kit is spent by
# firing it rather than by standing in a fight. `World.heroes` keeps them out of
# `expansion_parties` for the same reason `stage_cavalry` keeps the horse out: a unit whose value
# is a thing only it can do is worth nothing folded into a line of swordsmen.
HERO = "HERO"

# The health fraction at which a hero pulls out of a fight, and the one at which it goes back in.
#
# **Two numbers, and the gap between them is the whole design.** One threshold makes a hero
# oscillate across it: pull out at 40%, regenerate to 41% while walking, turn round, take one hit,
# turn round again. `stage_archers` is the cautionary case this bot already carries - it is
# written, it worked, and it is disabled in `Bot.decide` because its trigger fired on proximity
# and half its 202 firings were withdrawals from something that was not attacking. Health is the
# honest trigger for a hero, and hysteresis is what keeps it from being a twitch.
#
# 0.40 rather than something tighter because the cycle is the real constraint: at `--interval 2.0`
# the bot reads a hero's health every two seconds and a focused hero loses a great deal in two
# seconds, so the threshold has to be set where the *next* reading is still above zero rather than
# where the hero is nearly dead. Retreating early is cheap - heroes regenerate on their own - and
# retreating late is the whole loss.
#
# Unmeasured, both of them. They are the reading of what a hero costs against what a cycle can
# see, and the first live run is what should move them.
HERO_RETREAT = 0.40
HERO_RETURN = 0.75

# How long a hero's movement order is left alone before it is reissued.
#
# Shorter than the field force's `FIELD_REORDER`, for the same reason `CAVALRY_REORDER` is: a hero
# is one object rather than a party, what it is following moves, and a stale order costs more than
# a fresh one. Long enough that a retreat is not restarted from a standing start every cycle -
# which is `march`'s "3 battalions over 20 cycles, still 0 in range" failure applied to the one
# unit that cannot afford it.
HERO_REORDER = 8.0

# How near the force it is escorting a hero has to be before it is left where it is.
#
# **A hero's job is to be in the fight the army is having, not to have its own.** Sent at its own
# target it is one expensive object against whatever is there, which is how a 1300-gold purchase
# dies to four orcs; standing with a party it is a party that fights better and a hero the party
# is screening. So the mission is an escort, and this is what counts as escorting rather than as
# needing another order.
#
# Sized between `DEFEND_CONTACT` and `HOLDING_RADIUS`: near enough that the hero is in the same
# fight, far enough that it is not re-ordered every time the party shuffles.
HERO_ESCORT = 300.0

# How many enemies an area ability wants under it before it is worth firing.
#
# Lower than `CAST_MIN_TARGETS`, and the recharges are why: a hero ability runs from 30 to 360
# seconds where a spellbook power runs from 180 to 940, so the same "wait for a better target"
# arithmetic gives a different answer. Wizard Blast at 40 seconds is worth spending on two
# battalions; Army of the Dead at 830 is not.
HERO_CAST_TARGETS = 2

# The `KindOf` marking a hero that fades on a clock rather than one the player bought.
#
# **A summon's abilities are worth nothing the moment it fades**, and its lifetime is shorter than
# the abilities themselves: Gwaihir arrives from `SpellBookAdler` with `EAGLE_SUMMON_LIFETIME` to
# live and a screech that recharges in 180 seconds, so it fires it once or not at all. The patience
# `HERO_CAST_TARGETS` buys - hold out, a better crowd will come - is patience a summon does not
# have, which is the same arithmetic `CAST_PATIENCE` applies to a spellbook power that has been
# ready too long, arriving here as a fact about the caster instead of about the wait.
#
# The engine's own mark, so this needs no template list and reads the same on Theoden out of the
# Rohan banner as it does on the eagles and on the Grey Company.
SUMMONED = "SUMMONED"

# How hurt a unit has to be to count toward a hero's area heal, and how many of them it wants.
#
# **An area heal is paid for in bodies, not in the one worst casualty**, and that makes it the one
# hero ability whose bar has to go *up*. The twins' Healing Arts out of the Grey Company covers 200
# units around them and recharges in 90 seconds; the general heal aim takes the worst-hurt object
# anywhere within `HERO_ESCORT`, so a single battalion at 99% three hundred units away was reason
# enough to spend it - and the heal does not even land there, since it is cast on self and goes off
# where the twins are standing.
#
# The threshold matches `CAST_HEAL_THRESHOLD` because it answers the same question about the same
# kind of spell, and the count is four battalions: enough that the circle is worth drawing, few
# enough that an army in a real fight clears it within a cycle or two.
#
# Unmeasured. This is the reading of a 90-second recharge against a 200-unit circle, not a result.
HERO_HEAL_THRESHOLD = 0.75
HERO_HEAL_TARGETS = 4

# Gold above which the plan's hero is worth buying, and the reservation that holds it.
#
# **A hero is bought out of surplus, not out of the recruiting budget.** `stage_recruit` runs
# first and spends whatever it can see, so a hero priced against the plain balance is a hero that
# is never affordable - and one bought ahead of the army is a 1300-gold unit with nothing standing
# next to it, which is the same hero dying to four orcs by a different route. So the floor is what
# says the economy is already carrying production, and `HERO_PURPOSE` is what stops the rest of
# the loop spending the price while the queue is being reached.
#
# The same shape and the same number as `RESEARCH_FLOOR`, which answers the same question about a
# different purchase: what is this gold worth if the army is already being paid for.
HERO_FLOOR = 1500
HERO_PURPOSE = "hero"

# The `KindOf` that marks a pickup - a treasure chest, a salvage crate, a palantír shard, and
# the one the whole map stops for, `TheDroppedRing`. Read from the flag rather than from the
# fifteen names in `crate.ini`, because a mod that adds a sixteenth still marks it this way.
CRATE = "CRATE"

# How far a battalion will go out of its way for a crate.
#
# **Set by the crate's own clock, not by taste.** `SalvageCrate` carries a `DeletionUpdate` of
# `MinLifetime = 30000` / `MaxLifetime = 35000` - it is gone in about half a minute - and the
# engine advances at four to six logic frames a second under the bridge, so half a minute of
# game time is most of a wall-clock cycle's worth of walking. A battalion sent from across the
# map arrives at nothing, having stopped doing the thing it was sent out to do; one already
# nearby collects on the way past. This is the distance at which the second is still true.
CRATE_REACH = 600.0

# How long a crate order is left alone before the same battalion may be re-aimed. Every re-issue
# restarts the path, which is how a unit takes one step per cycle and never arrives - the failure
# `_sent_at` exists for. Shorter than the field force's because the crate expires.
CRATE_REORDER = 8.0

# How near a remembered *nest* something of ours must be before its absence is believed.
#
# **Deliberately much tighter than `PUSH_ARRIVED`, and the difference is a vision radius.**
# `remember_nests` first reused the 400 that `remember_keeps` uses, and it emptied the memory it
# had just been given: measured live across two runs, the `nests` column fell 2 -> 0 and 4 -> 1
# on maps where nothing had been destroyed. A battalion 350 away from a fogged lair cannot see
# it, so "I am near it and it is not in view" was not evidence of anything - it was the ordinary
# state of walking past something in the dark, and it deleted the lair.
#
# A keep survives that rule because it is enormous and the push walks onto it; a lair hole is a
# stump. At this distance the unit is standing on the spot rather than near it, which is the only
# reading that means the nest is genuinely gone. See `World.remember_nests`.
NEST_GONE = 120.0

# How close counts as standing on a crate rather than needing to walk to one.
#
# Pickup is a collision - `SalvageCrateCollide` - and the crate's own `GeometryMajorRadius` is
# 12, so a battalion this near has collected it or is one step from doing so. Ordering a move to
# where a unit already stands displaces nothing, and `Orders.manoeuvre` reads no displacement as
# an order the engine threw away: the first crate order sent live came back `REFUSED` with no way
# to tell that case from a real failure. Sized for a horde's own spread rather than for the box.
CRATE_ON = 40.0

# The engine's name for the seat that owns scenery, wildlife and map furniture.
#
# **A seat name rather than a template name, and that distinction is what makes it safe.** This
# file avoids matching template names because a mod renames them at will; the non-playing seats
# are engine fixtures and are spelled this way in every match observed. Nothing else separates
# them from the creeps - both report a `Civilian` faction and both answer False to `playing`.
#
# `PlyrCreeps` is deliberately *not* here. Lairs and the slaves they keep replacing are the
# creeps', and clearing them is how a flag is taken; the civilians own rocks, deer and pillars.
# See `World.civilian`, and `World.hostile` for what a match cost before the two were told apart.
CIVILIAN_SEAT = "PlyrCivilian"

# How near the spot a party razed a nest at a replacement counts as the same job.
#
# **A lair and the hole it leaves are one target, and only the object id says otherwise.**
# `RebuildHoleExposeDie` puts the stump where the building stood, so the hole is the same place
# with a new id - and a raid that re-decides from scratch treats it as a fresh target competing
# with every other nest on the map. Measured live, four battalions worked four nests for a
# hundred cycles and finished none of them, because `RebuildHoleBehavior` raises the lair again
# about two minutes after the stump appears and the party had wandered off by then.
#
# Sized for "the same building's footprint", not for a radius of influence - a lair is a few tens
# of units across and the hole lands inside it. See `Warfare.unfinished_nest`.
RAID_FINISH = 150.0

# How far from the push's own target a second front may be opened for a spare siege engine.
#
# **Bounded by the escort, not by the map.** `RECRUIT_NEVER` records why siege is barred outside
# a push at all - eight battering rams once walked to their targets alone and achieved nothing -
# and the push is the escort that lifts the ban. A structure beside the one being knocked down is
# inside the same fight and covered by the same battalions; one across the map is a ram on its
# own again, which is the failure this constant exists to keep bounded.
#
# Wider than `SCREEN_REACH` because it measures building-to-building rather than who is in
# contact, and far narrower than `RAID_STANDOFF`, which is about a different question entirely.
SIEGE_SPREAD = 700.0
