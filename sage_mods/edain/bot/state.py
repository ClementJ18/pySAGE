"""What one run remembers, and nothing else.

The bottom of the class chain (see `sage_mods.edain.bot` for why there is one): every field the
stages read or write is created here and documented here, so "what state does this bot carry"
is one file rather than a search.
"""

from __future__ import annotations

from sage_live.api.camera import CameraPan
from sage_live.api.observation import GameObject, Observation, Vec3
from sage_live.api.session import Session
from sage_live.utils.statics import CastablePower, Formation, Statics
from sage_mods.edain.bot.factions import Plan
from sage_mods.edain.bot.ledger import Ledger
from sage_mods.edain.bot.recording import Recorder


class BotState:
    """Everything one run carries between cycles, created and documented in one place.

    The bot's memory is what makes its stages behave like commitments rather than like a fresh
    opinion every two seconds - a flag it is walking to, a plot it has given up on, an order it
    has already issued and should leave running. Each field below says which.
    """

    def __init__(
        self,
        session: Session,
        plan: Plan,
        statics: Statics,
        side: str,
        dry_run: bool = False,
        camera: bool = True,
        record: bool = False,
    ) -> None:
        self.session = session
        self.plan = plan
        self.statics = statics
        self.dry_run = dry_run
        # Whether to stage the camera at all. Off leaves the view entirely to whoever is at the
        # keyboard. It was once also a workaround - re-aiming went through `View::setLocation`,
        # which writes the zoom whether or not it was asked to and cannot write back the zoom it
        # reports, so every placement zoomed in and was snapped out again. `look_at` no longer
        # goes near it. The switch stays because the layer changes nothing about the match, so
        # filming is a preference and turning it off costs the run nothing.
        self.camera = camera
        # Films the run by pressing OBS's own start/stop hotkey, once at each end. Independent of
        # `camera`: what the recording is pointed at is the operator's business, and a run worth
        # filming with the view left alone is a perfectly ordinary thing to want.
        self.recorder = Recorder(record)
        self.ledger = Ledger()
        # Which faction this run is playing, as the engine's `Side` token. Passed in rather than
        # read from the observation so that `--faction` moves everything keyed on it together.
        self.side = side
        # The mix the shipped skirmish AI would build for this side, or None where the tree
        # defines no army for it.
        self.army_plan = statics.army_plan(side)
        # The faction's spellbook, twice over, because buying and casting are two different
        # command sets on two different things. `spell_store` is what the store sells - price in
        # points, and what unlocks it. `spell_book` is what the book can fire - how each power
        # casts, what it does, and how long it recharges. Both fixed for the match, read once.
        self.spell_store = statics.spell_store(side)
        self.spell_book = statics.spell_book(side)
        # When each power was last cast, by power name. **The fallback clock, not the primary
        # one**: `Powers.ready` prefers the ready-frame the engine keeps on the power's module,
        # and only counts from here for the powers that frame cannot be read for.
        self._cast_at: dict[str, float] = {}
        # How long that fallback waits, by power name - seeded from the ini's declared recharge
        # and grown by `CAST_BACKOFF` every time the engine refuses a cast made on it. The
        # declared figure is an estimate: Edain rescales it per player, and a measured run had it
        # estimating a few seconds short and refusing three casts because of it.
        self._cast_wait: dict[str, float] = {}
        # Places the engine has refused to build at, and when each may be tried again. An
        # observation carries objects but not terrain, so empty ground and buildable ground are
        # the same thing from here - and the scan that looks for it is deterministic, so a spot
        # that is water or cliff is picked again every cycle and in every match. Measured: Lone
        # Tower refused at `(4144.94, 1490.06, 150.0)` in two consecutive runs, identical to the
        # last decimal.
        #
        # **Held with an expiry, because a refusal does not say which reason it was.** Bad
        # terrain is permanent and something standing in the way is not, and nothing here can
        # tell them apart - so a spot is avoided rather than condemned. See
        # `CAST_GROUND_COOLDOWN` and `Powers.open_ground`.
        self._refused_ground: dict[tuple[float, float, float], float] = {}
        # The engine's ready-frame for each power as it stood when the bot last cast it.
        #
        # **A ready-frame that does not move is not a power that is ready.** A cast the engine
        # declines to accept starts no recharge, so its frame stays where it was and stays in the
        # past - and `ready` reading that as permission fires the same power every cycle for the
        # rest of the match. Measured live on `SpellBookRallyingCall_Gondor`: frozen at 10852
        # across five casts while the match ran on to frame 11360, reported as 14/14 successes
        # because a buff with no view marker leaves nothing to confirm against.
        self._cast_frame: dict[str, int] = {}
        # When each power first had everything it needs except a target worth spending it on.
        # `CAST_PATIENCE` reads this: a power that has been ready a long time lowers its bar.
        self._ready_since: dict[str, float] = {}
        # Science name -> order id, and the names the store mentions. Both are pure lookups over
        # data that cannot change mid-match, and the first costs an ini-table search per miss.
        self._science_ids: dict[str, int | None] = {}
        self._science_names: tuple[str, ...] | None = None
        # Whether any party expanded this cycle. Set every cycle by `stage_expand`,
        # which `decide` guarantees runs first - see `stage_raid` for why the raid is a fallback
        # job rather than a second front.
        self._expanding = False
        # **Gold already promised to something the bot has committed to**, keyed by what promised
        # it. Every stage prices its spends against the balance *minus* this, so a settlement the
        # force is three cycles' walk away from still has its price waiting when it arrives.
        #
        # Watching a match is what showed this was needed: battalions criss-crossing the map to
        # flags they then could not afford to build on, because recruiting had spent the balance
        # in the meantime and the whole walk was wasted. A reservation is a decision already
        # taken - it is not a budget or a floor, and the stage that made it is the only one that
        # can see the money. See `Orders.reserve`.
        self._reserved: dict[str, int] = {}
        # Latches for `finished`: whether each side has ever been seen holding something that
        # counts for victory. Before the map spawns, neither has, and nothing can be concluded.
        self._held = False
        self._opposed = False
        # **Which plots and flags had something standing on them last cycle, and the frame each
        # one lost it.** Together these are how the bot sees a rule the observation never states:
        # a plot is unbuildable for about twelve game seconds after whatever stood on it goes
        # away, and until `note_freed_plots` watched for the transition there was nothing to see
        # it happen - a razed building's plot simply reappeared as free and was ordered onto
        # again the next cycle, every cycle, until the cooldown happened to expire.
        #
        # By **frame** rather than by wall clock, unlike every other rest in this bot. Those are
        # heuristics about contested ground and are rightly measured in the operator's time; this
        # is the game's own rule and has to be measured in the game's own clock, which under the
        # bridge runs five or six times slower. See `PLOT_REBUILD_SECONDS`.
        self._plot_held: set[int] = set()
        self._plot_freed: dict[int, int] = {}
        # Plots and upgrades that refused an order, and when to try them again. **A failed
        # order is information, not noise**: retrying the same plot every cycle spent the whole
        # opening on one spot that was never going to take a building, at two 4s confirmation
        # windows a go, while gold climbed past 8000 unspent.
        self._blocked_plots: dict[int, float] = {}
        # Actions that keep failing. **An order that never works still costs a confirmation
        # window every cycle**: one match spent most of its time on `build Forge` 0/113,
        # `unpack` 0/120 and `cp` 5/382. Three strikes and it sits out.
        self._cooldowns: dict[str, float] = {}
        self._strikes: dict[str, int] = {}
        self._blocked_upgrades: dict[str, int] = {}
        # Flags given up on, how many cycles each has spent with the force making no progress,
        # and how many cycles the force has been committed to it at all. A capture that is not
        # progressing is a capture being lost, and the only way to see that is to count.
        self._blocked_flags: dict[int, float] = {}
        # How many times each flag has been given up on, which unlike `_blocked_flags` only ever
        # grows. **A cooldown answers "may I try again yet", and that is the wrong question for
        # deciding the map is finished.** `FLAG_COOLDOWN` expires, so a flag the force cannot take
        # returns as a candidate, is attempted, is abandoned and is blocked again - measured over
        # one run, plot 202 went round that loop four times and was still a live candidate at
        # cycle 400. Anything gated on "is it blocked right now" therefore flickers with the
        # cooldown; a count of failures does not. See `winnable_flags`.
        self._flag_failures: dict[int, int] = {}
        self._stalled: dict[int, int] = {}
        self._spent: dict[int, int] = {}
        # **Expansion parties, each taking its own flag.** The map is taken by several small
        # groups working in parallel rather than by one army walking as one body: `_parties` maps
        # a party id to its battalions, and `_party_flag` to the settlement it is committed to.
        #
        # The first party is the battalions the match starts with, and it goes out on cycle 1 at
        # whatever strength it has - recruits join it until it reaches `EXPAND_PARTY`, and only
        # then does `_forming` begin gathering the next one. So a battalion waits for its own
        # group to come together and never for the army as a whole, which is what left the
        # starting units idle for twenty cycles.
        self._parties: dict[int, tuple[int, ...]] = {}
        self._party_flag: dict[int, int] = {}
        self._forming: tuple[int, ...] = ()
        self._next_party = 0
        # Parties that found nothing to expand to this cycle, keyed the same way as `_parties`
        # - what `stage_raid` falls back on, one target each. Rebuilt every cycle by
        # `stage_expand`, so a party is only ever in one of the two jobs.
        self._idle_parties: dict[int, list] = {}
        # **Response groups, keyed by the holding they are defending** - `0` is the base, and
        # any other key is the object id of a building out on the map. Each is sized to the
        # enemies actually standing on that holding rather than to a constant, which is what lets
        # two orcs at a farm pull three battalions off the march instead of pulling the army home
        # or being ignored until the farm is gone.
        #
        # A dict rather than one `_guard` tuple because the map has more than one place worth
        # holding, and the army has to be able to be in more than one of them.
        self._groups: dict[int, tuple[int, ...]] = {}
        self._group_aim: dict[int, Vec3] = {}
        self._group_ordered: dict[int, float] = {}
        # Which raider each group was last sent at. **Position alone cannot say whether the
        # target changed**: two raiders standing together are the same point to within the
        # 200-unit test, so a group that switched from one to the other read as holding its
        # order - and one that had *not* switched was re-ordered anyway every `DEFEND_REORDER`,
        # which is what made a whole approach read as a string of failures. See `hold`.
        self._group_target: dict[int, int] = {}
        # Where each group was raised to defend, and when its reason for existing last ran out.
        #
        # **A group is released on losing contact, not on its holding going quiet, and that is a
        # fix for a self-cancelling rule.** A holding counts as threatened while enemies stand
        # near *it*, and the response to that is to walk out and meet them - which takes the fight
        # off the holding and so ends the threat by the only measure being applied. Measured live
        # at cycles 122-125 of one run: two battalions were pulled out of two parties, held for two
        # cycles, and snapped straight back to their previous march while the raider they were
        # sent at - an `IsengardUrukScoutHorde` - was still alive and simply standing somewhere
        # else. The battalions turned twice in four seconds and killed nothing.
        #
        # So `_group_quiet` records the first cycle a group had neither a threatened holding nor
        # anything in contact, and the group survives until `DEFEND_COMMITMENT` has passed since
        # then - which is what stops a raider stepping out of range for one cycle from dissolving
        # the group that was beating it. `_group_home` is where to go back to once it does run:
        # the group returns to the holding rather than chasing, because a defence that follows its
        # raider across the map is the strung-out army this shape exists to replace.
        self._group_home: dict[int, Vec3] = {}
        self._group_quiet: dict[int, float] = {}
        # What the camera is watching and since when. `_shot_label` is the subject's identity
        # rather than its caption - a party that has walked half the map is still the same shot -
        # and it is what makes the dwell timer answerable. Where the camera actually is belongs
        # to `pan`, which closes on the target between cycles rather than at them. See `director`.
        self._shot_label: str | None = None
        self._shot_since = 0.0
        self.pan = CameraPan(session)
        # **The hero mission, keyed by the hero's object id rather than by anything else.**
        #
        # By id and not by template, because a template is not an identity here: a hero that dies
        # and is revived is a new object, and two heroes of one faction can share an ability name
        # (`SpecialAbilityAragornBladeMaster` is Boromir's and Aragorn's, and every hero in the
        # game carries `SpecialAbilityCaptureBuilding`). A clock keyed by power name alone would
        # have one hero silencing the other's ability for a whole recharge - see `Powers.wait_for`,
        # which takes a key for exactly this.
        #
        # `_hero_aim` and `_hero_ordered` are the same re-order suppression every other force
        # here has: an order reissued every cycle restarts the path and the hero never arrives.
        self._hero_aim: dict[int, Vec3] = {}
        self._hero_ordered: dict[int, float] = {}
        # Which force each hero is escorting, by hero id, as `Heroes.hero_forces` keys it
        # (`party:3`, `group:118`, `push`). Held between cycles so a hero does not change which
        # force it is standing with every time two of them are equidistant - the same flicker
        # `Shot.label` exists to prevent one layer up. **A key rather than a position**, because a
        # positional index silently re-points the commitment at somebody else the moment a party
        # ahead of it dies.
        self._hero_escort: dict[int, str] = {}
        # **Heroes currently pulling out of a fight, latched.** A hero is added below
        # `HERO_RETREAT` and removed above `HERO_RETURN`, and the gap between the two is the whole
        # point: a single threshold makes a hero cross it, regenerate a percent while walking,
        # turn round into the same fight and cross it again. The same argument as `_pushing`,
        # which is latched for the same reason at the other end of the match.
        self._retreating: set[int] = set()
        # Each hero's abilities, by template - a pure `Statics` read over data that cannot change
        # mid-match, and one that walks a command set and every module on the object.
        self._hero_powers: dict[str, tuple[CastablePower, ...]] = {}
        # The cavalry mission and where it was last sent. Held apart from everything else because
        # its whole justification is going somewhere the rest of the army is not - see
        # `CAVALRY_MIN`.
        self._cav: tuple[int, ...] = ()
        self._cav_aim: Vec3 | None = None
        self._cav_ordered = 0.0
        # The horse split into small parties, keyed by the building each is riding down, for when
        # there is no siege or archer left to hunt. A building does not move, so a party needs no
        # remembered aim - only when it was last given an order. See `CAVALRY_PARTY`.
        self._cav_parties: dict[int, tuple[int, ...]] = {}
        self._cav_party_ordered: dict[int, float] = {}
        # What each mounted force is charging through and when it was sent, keyed the same way as
        # `_field_aim`. **A trample is two orders and the second must not overwrite the first**:
        # the ride-through is a move past the battalion and the fight is an attack on it, so a
        # stage that reissued its attack every cycle would cancel the charge on the frame after
        # ordering it and the horse would arrive at a walk. These two say a charge is already
        # running, and `TRAMPLE_SECONDS` says when it is over.
        #
        # Keyed by target as well as by force so that a *new* target gets its own charge while a
        # party that has already ridden through one stays in the fight it landed in - one trample
        # per commitment, not one per cycle.
        self._charge_target: dict[str, int] = {}
        self._charged: dict[str, float] = {}
        # Whether the endgame is on, and since when. Latched: see `Warfare.pushing` for why a
        # push that un-commits on its first casualties is worse than never having gone.
        self._pushing = False
        self._push_since = 0.0
        # The battalions held out of the push to go on taking the map - see `PUSH_RAIDERS`. Kept
        # by id rather than as a party, because they are the only thing `expansion_parties` may
        # draw on while the push is on and it has to be able to say so.
        self._raiders: tuple[int, ...] = ()
        # **The formation mechanic's three pieces of memory** - see `mechanics.formations`.
        #
        # `_formations` is a pure `Statics` cache keyed by *template*: which alternate formation
        # a battalion has and whether its control bar offers the button is a fact about the ini
        # tree, so it is answered once per template rather than once per battalion per cycle.
        #
        # The other two are keyed by object id and are the hysteresis. `_formation_seen` is where
        # each battalion stood last cycle, which is the whole of how "is it standing still"
        # is measured - the bot orders battalions from a dozen stages and only their positions
        # can be compared. `_formation_since` counts the cycles one has wanted a formation it is
        # not in, and `_formation_at` when it last changed, so a battalion cannot flip on the
        # flicker of a fight that has not settled.
        self._formations: dict[str, Formation | None] = {}
        self._formation_seen: dict[int, Vec3] = {}
        self._formation_since: dict[int, int] = {}
        self._formation_at: dict[int, float] = {}
        # **Where their victory buildings were seen, by object id - the bot's own scouting.**
        #
        # The fogged view has no memory of what it saw before, so at 85% map control the force
        # can be standing on the far side of the map with no idea where to walk. A player is not
        # in that position: they have crossed this map, they have seen the keep, and they still
        # know where it is. This is that, held honestly - a position is written here only on a
        # cycle where the building was genuinely visible, and dropped once the force is standing
        # where it was and it is not there any more. Nothing here reads the unfogged snapshot;
        # what has never been seen is not in it. See `Warfare.remember_keeps`.
        self._seen_keeps: dict[int, Vec3] = {}
        # Where the base was last read to be, which is what the next reading is taken around.
        # See `BASE_RADIUS`: without it the centre walks out across the map behind the
        # expansions and takes `DEFEND_RADIUS` and `free_plots` with it.
        self._home: Vec3 | None = None
        # Every claimable plot on the map by object id, censused once through the fog. See
        # `World.plot_ghosts` for why looking once is the honest reading rather than a cheat.
        self._ghosts: dict[int, GameObject] | None = None
        # Outlying holdings that have had a lone tower put up for them, by holding object id.
        #
        # **Held as a decision rather than read off the map**, which is the honest limitation to
        # state: the tower the Edain spell spawns is reached through an `OCL` rather than named
        # anywhere this bot can resolve, so "does this settlement already have one" cannot be
        # asked of the observation without matching a template name - which this codebase
        # deliberately does not do. The cost is that a tower destroyed is not replaced, which
        # matches "start with one per" and is the thing to revisit if towers start dying.
        self._towered: set[int] = set()
        # The nearest the force has got to each flag, which is what "is this working" is measured
        # against - a walk that is still shortening is working however far out it started.
        self._closest: dict[int, float] = {}
        # Where the field force was last sent and when. **Re-issuing a move every cycle is how a
        # force never arrives**: each order restarts the path, so units take one step, get a
        # fresh order, and take one more - they visibly move the whole time and close no
        # distance. Measured: 3 battalions, 20 cycles, still "0 in range".
        #
        # One pair for the whole force, because it is one force with one destination. Every other
        # group keeps its own, and that separation is not cosmetic: defence used to share the
        # push's pair, so an attack at home and an attack across the map each reset the other's
        # re-order window and both were reissued early.
        # Where each party's last attack or march was aimed, and when. **Keyed per party**,
        # because they work in parallel: one shared aim meant the second party's order looked
        # like a re-aim of the first's and was throttled away.
        self._field_aim: dict[str, Vec3] = {}
        self._field_ordered: dict[str, float] = {}
        session.observe()
        # Where the build phases are counted from. **The frame counter is not match time** - the
        # menu is a running game and its frames advance too, so the absolute number says nothing
        # about how old this match is. What it can honestly answer is how long *this bot* has
        # been playing, which is the same thing whenever the bot starts with the match and an
        # understatement whenever it attaches to one already running.
        self._start_frame = self.observation.frame
        self._fps = statics.frames_per_second()

    @property
    def observation(self) -> Observation:
        """The session's latest snapshot, never a copy this bot keeps.

        The confirmation helpers poll while they wait, so a bot holding its own reference is
        reading a world several frames old the moment it verifies anything - and then decides
        against it.
        """
        return self.session.latest or self.session.observe()

    def refresh(self) -> Observation:
        return self.session.observe()

    @property
    def gold(self) -> int:
        me = self.observation.me
        return 0 if me is None else me.resources
