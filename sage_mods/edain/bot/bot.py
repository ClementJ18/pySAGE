"""The control loop itself: one cycle, the end of the match, and the run that repeats them."""

from __future__ import annotations

import time
from collections.abc import Callable

from sage_live.api.session import NoSelection
from sage_live.utils.naming import UnknownDefinition
from sage_mods.edain.bot.director import Director

__all__ = ["Bot"]


class Bot(Director):
    """The whole bot. `decide` is the seam an ML policy would replace."""

    def decide(self) -> str:
        """One cycle: every stage of the current phase gets a turn, in priority order.

        **The stages run in parallel, not as a chain.** Each returns after at most one order,
        so a cycle recruits *and* builds *and* expands rather than doing the first thing that
        applies and returning. That was the single biggest waste in the earlier version: a bot
        still laying its economy was not recruiting, so the barracks sat idle for the whole
        opening and the army arrived minutes late.

        **The build order is a phase gate, not a priority list.** Running every stage from
        frame one reads as harmless - a stage with nothing to do returns None - but it is not:
        `stage_build` would spend the opening's gold on economy before the barracks stood, and
        the command-point stage would buy ceiling for an army that does not exist. So the
        opening runs a deliberately short list:

        - **opening** (no production building): build it, and send the starting units out to
          claim external plots. Those are the only two things worth doing, and they do not
          compete - one spends gold, the other spends units standing idle.
        - **developed**: recruit and lay internal economy, keep expanding, and raise the
          command-point ceiling once there is an army near it.

        Within a phase the order is still priority: units first because they both defend and
        win, then the ceiling that caps them, then buildings, then defence, then expansion, then
        raiding, and research last because it spends only what the rest could not.

        **`stage_archers` is written and deliberately not in either list.** It pulls bowmen out
        of melee and back behind the line, and it worked - but a measured run fired it 202 times
        and roughly half were withdrawals from a banner carrier or a ram crew, armed support that
        was standing near the archers rather than hitting them. Proximity is the wrong trigger;
        damage taken is the right one, and until it reads that, the rule costs more shooting than
        it saves. `Warfare.stage_archers` and its tests stay so that re-enabling it is one line.

        **`stage_signal_fire` runs ahead of `stage_recruit`, and that ordering is the whole of
        its claim.** It spends no gold at all - its currency is the rider's charges - so it takes
        nothing from any stage here except the one thing it does compete for: command points. A
        summon puts *two* battalions on the map for no gold, where the recruit behind it puts one
        on for 200, so when the ceiling can only pay for one of them the free pair is the better
        buy. Below the opening list because the building it needs stands on a claimed settlement,
        which the opening has not taken yet. Inert on every faction but Men.

        **The two spellbook stages are in both lists and last in each, and neither placing is a
        priority judgement.** `stage_powers` spends spellbook points and `stage_cast` spends a
        recharge, and no other stage can touch either - so they take nothing from anything above
        them and there is nothing for the build order to protect them from. The opening runs both
        for the same reason the rest of the match does. Last because the order within a phase
        only decides who gets the *gold*, and neither of these is asking.

        **`stage_cast` after `stage_powers`, which is a real dependency rather than a
        preference**: a power bought this cycle is castable this cycle, and the buy is confirmed
        by the science appearing, so the cast stage reads a spellbook that is already up to date.

        **`stage_camera` is last in both lists and it is the one placing that carries no
        argument at all.** The camera is client state - no logic reads it, no order carries it,
        it costs no APM - so it takes nothing from any stage above it and cannot affect the
        match. Last because it wants to point at what this cycle decided, and because a stage
        that changes nothing has no claim on being asked earlier. See `director`.

        **The army is assigned to jobs, and the jobs are claimed in list order.** A response
        group per threatened holding, the cavalry on its own mission, and the field force with
        everything left over - and each stage skips the battalions the stages above it named this
        cycle. So the ordering in the list is a real dependency rather than a preference:
        `stage_defend` takes what the base and the farms need, `stage_cavalry` takes the horse
        that is still free, and `stage_expand` marches with the rest. It is also why
        `stage_raid` can tell it is a fallback - it only runs when the stage above found nothing.

        **One army walking as one body was the failure this shape replaces.** Watching a match
        makes it plain: the whole force crossing the map together while four orcs burn a
        settlement behind it that nobody will ever be sent to. A threat is now answered where it
        happens, by a group slightly stronger than it, and the march continues without it.

        **There is a push, and it is a third list rather than a stage in the second.** Two earlier
        versions had one and the module docstring records what both cost; what was wrong in each
        was the gate rather than the target, and a gate that fires while there is still map to
        take stops the expansion that pays for the army. `pushing` is two conditions that are
        both already true when they fire - the map is held and the army is against its own
        ceiling - so by the time this list is chosen there is no expansion left to stop. It drops
        the four stages that send battalions anywhere else and keeps everything that makes the
        force bigger: recruiting, the ceiling, upgrades and the spellbook all still run, because
        an endgame with 105,012 gold banked is an endgame that has already lost track of what the
        gold was for.

        **`stage_build` stays too**, which reads odd during an assault and is not: it lays
        economy on plots already held at home and never sends anyone across the map, so it
        competes with nothing the push is doing and keeps paying for the reinforcements.
        """
        self.refresh()
        self.remember_keeps()
        stages: tuple[Callable[[], str | None], ...]
        if self.opening():
            stages = (
                self.stage_repair,
                self.stage_build,
                self.stage_defend,
                self.stage_expand,
                self.stage_powers,
                self.stage_cast,
                self.stage_camera,
            )
        elif self.pushing():
            stages = (
                self.stage_repair,
                self.stage_command_points,
                self.stage_signal_fire,
                self.stage_recruit,
                self.stage_build,
                self.stage_defend,
                self.stage_push,
                self.stage_upgrade,
                self.stage_powers,
                self.stage_cast,
                self.stage_camera,
            )
        else:
            stages = (
                self.stage_repair,
                self.stage_sell,
                self.stage_command_points,
                self.stage_signal_fire,
                self.stage_recruit,
                self.stage_build,
                self.stage_defend,
                self.stage_cavalry,
                self.stage_expand,
                self.stage_raid,
                self.stage_upgrade,
                self.stage_powers,
                self.stage_cast,
                self.stage_camera,
            )
        done = []
        for stage in stages:
            try:
                said = stage()
            except (UnknownDefinition, NoSelection) as exc:
                # One stage failing is not the cycle failing: a missing name or an empty
                # selection is a fact about this frame, and the other stages are unaffected.
                said = f"{stage.__name__} refused: {exc}"
            if said:
                done.append(said)
        return " | ".join(done) or "nothing to do"

    def finished(self) -> str | None:
        """Why the match is over, or None while it continues.

        Derived from ownership rather than read from the engine. `TheVictorySystem` is *not*
        this - `victorysystem.ini` shows it is a per-cell battle-momentum bonus, not a win
        condition - and `TheVictoryConditions` has an address but has never been walked. So
        this infers, using the engine's own victory-counting flag, and says so.

        **The process is asked first.** A crashed game reads exactly as a finished one - no
        objects, no local player - so inferring from the observation alone would report a
        crash as a defeat, which is a result that looks real and means nothing.

        **You cannot lose what you never had.** `wait_for_match` returns the moment the local
        player becomes a faction, which is *before* the map has spawned anyone's base - so at
        frame 0 nobody owns anything that counts for victory and this test called every match
        an instant defeat, the winner's included. Both sides are therefore latched: a result is
        only read once that side has been seen holding something, which is a fact about the
        match having actually begun rather than a threshold anyone has to tune.

        **This one test reads through fog, deliberately.** An opponent's last buildings vanish
        from a fogged observation the moment nothing of ours is watching them, which is
        indistinguishable there from their having been destroyed - so asking the filtered
        snapshot gives an answer that is wrong in both directions, and an earlier version
        therefore refused to call a fogged match at all and waited for `in_match` to drop.

        That refusal was the wrong trade. **Whether the match is over is not a tactical read**:
        a human under full fog is still told who won, immediately and for free, so a bot that
        cannot tell is not being held to the human's information - it is being held below it.
        Nothing here feeds targeting or scouting; `self.observation`, which every stage that
        chooses an order reads, stays filtered, so the fog a policy trains against is intact.

        See `Session.latest_unfogged`, which is where that decision is written down.
        """
        if not self.session.alive:
            return "the game is gone (it exited or crashed) - this is not a result"
        if not self.observation.in_match:
            return "the match ended (the local player is no longer a faction)"

        # Both halves are read from the unfogged snapshot, which under `fog=False` is the same
        # object the rest of the bot uses. `owned_by` is exact either way, so this changes
        # nothing about a run without fog.
        whole = self.session.latest_unfogged or self.observation

        mine = bool(self._holdings(self.session.player_index, whole))
        self._held = self._held or mine
        if self._held and not mine:
            return "defeat: nothing left that counts for victory"

        theirs = any(self._holdings(p.index, whole) for p in whole.opponents)
        self._opposed = self._opposed or theirs
        if self._opposed and not theirs:
            return "victory: no opponent holds anything that counts for victory"
        return None

    @property
    def started(self) -> bool:
        """Whether the world has actually populated - both sides seen holding something.

        Both latches are set from the unfogged snapshot in `finished`, so this no longer has to
        weaken itself under fog to the half it could observe.
        """
        return self._held and self._opposed

    def run(self, cycles: int, interval: float) -> int:
        """Cycle until the match is decided or the budget runs out.

        The pan runs for the length of the run rather than being started per shot: it is a
        daemon thread that writes twelve bytes when the camera is not where the director asked
        for it and nothing at all when it is, so idling costs a comparison. Stopped in a
        `finally` so that killing a run does not leave a thread writing into the view of a game
        that is being closed.

        **The recording is bracketed here for the same reason and it matters more.** A pan
        thread left running dies with the process; a recording left running fills a disk. Both
        stops are in the one `finally`, so a victory, a defeat, an exhausted cycle budget, a
        crash mid-cycle and a Ctrl-C all end the same way.
        """
        if self.camera:
            self.pan.start()
        self.recorder.start()
        try:
            return self._cycle(cycles, interval)
        finally:
            self.pan.stop()
            self.recorder.stop()

    def _cycle(self, cycles: int, interval: float) -> int:
        started = time.monotonic()
        for cycle in range(1, cycles + 1):
            me = self.observation.me
            print(
                f"\n[{cycle:>3}] frame {self.observation.frame}  "
                f"gold {self.gold}"
                f"{f'-{self.reserved()}' if self.reserved() else ''}  "
                f"army {len(self.army())}  "
                # One count per member of the economy set rather than a total, because the whole
                # point of that set is that it is meant to stay even - and a total hides the one
                # failure mode worth watching for, which is all the plots going to one ladder.
                f"eco {'/'.join(str(len(self.owned_building(b))) for b in self.economy_set())}  "
                f"prod {len(self.production_buildings())}  "
                f"plots {len(self.free_plots())}  "
                f"flags {len(self.external_plots())}  "
                f"map {self.map_control():.0%}  "
                f"parties {[len(p) for p in self._parties.values()]} forming {len(self._forming)} "
                f"cav {len(self._cav)} groups {len(self._groups)}  "
                f"nests {len(self.nests())}  "
                f"phase {self.phase() + 1}  "
                f"{'PUSH ' if self._pushing else ''}"
                f"cp {me.command_points[0] if me else 0}/{me.command_points[1] if me else 0}  "
                f"sp {me.power_points if me else 0}  "
                f"{time.monotonic() - started:5.0f}s"
            )
            print(f"  {self.decide()}")
            over = self.finished()
            if over is not None:
                print(f"\n{over}")
                return 0
            time.sleep(interval)
        print(f"\nstopped after {cycles} cycles without a decision")
        return 0
