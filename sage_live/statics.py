"""Static per-template facts, joined to a live observation by `template_name`.

An `Observation` is deliberately small: it names each object's `ThingTemplate` and stops
there, because everything else about that template is already on disk. This is the join. It
turns a template name into the ini facts a policy needs and the engine does not re-send every
frame - starting with `KindOf`, which is how the game itself classifies objects.

`KindOf` answers two questions no live field does:

- **Where can I build?** A build plot carries `BASE_FOUNDATION` or `BASE_SITE`. Nothing in the
  live object identifies a plot otherwise: a plot has a `Body` (an `ImmortalBody` of 15,000),
  so "no body" does not find it, and its template name follows no reliable convention across
  factions or mods.
- **Who has lost?** `MP_COUNT_FOR_VICTORY` is the flag the engine's own multiplayer defeat
  check counts. A player owning nothing that carries it is beaten. That is a far better
  test than "owns no objects", which calls a player dead while their walls are still standing.

Like `resolve`, this imports `sage_ini` and is therefore **not** re-exported from the package
root - import it from here. The package root stays install-free.

**Inheritance is resolved, not ignored.** A `ChildObject` does not restate its parent's
`KindOf`, so reading the field directly reports nothing for a large share of real templates -
`GondorBuildingFoundation_Independant`, a plot, is one of them. `kind_of` walks the parent
chain. It also honours SAGE's delta form (`KindOf = +SUMMONED`), which adds to and subtracts
from the inherited set rather than replacing it; 472 definitions in RotWK+Edain use it, none
of them for the two plot flags, but a rule that is only right for today's data is not a rule.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from sage_ini import load_game
from sage_ini.model.game import Game
from sage_live.heroes import ReviveSlot

__all__ = [
    "BASE_SITE_KINDS",
    "MP_COUNT_FOR_VICTORY",
    "REVIVE",
    "Statics",
]

# The `CommandButton` command that recruits a hero. Every hero in the game is reached through
# one of these; see `sage_live.heroes` for the index space they are addressed by.
REVIVE = "REVIVE"

# The two flags that mark somewhere a structure can be placed. Both, not either: `BASE_SITE`
# is the settlement/outpost spot and `BASE_FOUNDATION` the castle plot, and a faction may use
# one, the other, or both on the same map.
BASE_SITE_KINDS = frozenset({"BASE_FOUNDATION", "BASE_SITE"})

# What the engine's multiplayer defeat check counts. Structures and plots carry it; ordinary
# units generally do not, which is why a player with an army but no buildings is still losing.
MP_COUNT_FOR_VICTORY = "MP_COUNT_FOR_VICTORY"

# A parent chain longer than this is a cycle in the data, not a deep hierarchy.
_MAX_DEPTH = 32


class Statics:
    """Template name to the static ini facts about it, for one loaded build.

    Case-insensitive throughout, because ini identifiers are and a live observation spells a
    template however the engine registered it.
    """

    def __init__(self, game: Game) -> None:
        self.game = game
        objects = game.tables.get("objects", {})
        # Keyed lowercase once, so every later lookup is a dict hit rather than a scan over
        # eleven thousand names.
        self._objects = {str(name).lower(): obj for name, obj in objects.items()}
        self._sets = {str(n).lower(): s for n, s in game.tables.get("commandsets", {}).items()}
        self._buttons = {
            str(n).lower(): b for n, b in game.tables.get("commandbuttons", {}).items()
        }
        # `PlayerTemplate` blocks live in the `factions` table, keyed `FactionMen` and so on.
        self._factions = {str(n).lower(): f for n, f in game.tables.get("factions", {}).items()}
        self._kinds: dict[str, frozenset[str]] = {}
        self._canonical: dict[str, str] | None = None
        self._members: frozenset[str] | None = None
        self._revives: dict[str, tuple[ReviveSlot, ...]] = {}

    @classmethod
    def from_root(cls, root: str | Path) -> Statics:
        """Load a game tree and index it.

        `root` must already be an ini tree - a live install keeps its data in `.big` archives,
        so mount it first with `sage_utils.gameroot.resolve_game_root`, which is also what
        makes the load cheap on a second run.
        """
        return cls(load_game(root).game)

    def known(self, template: str) -> bool:
        return template.lower() in self._objects

    def field(self, template: str, name: str) -> str | None:
        """One raw ini field, following the parent chain. None when nothing declares it."""
        current = self._objects.get(template.lower())
        for _ in range(_MAX_DEPTH):
            if current is None:
                return None
            value = current.fields.get(name)
            if value is not None:
                return str(value)
            parent = getattr(current, "parent_name", None)
            current = self._objects.get(str(parent).lower()) if parent else None
        return None

    def kind_of(self, template: str) -> frozenset[str]:
        """The template's resolved `KindOf` flags, inheritance and deltas applied.

        An unknown template answers the empty set rather than raising: a live game routinely
        carries templates a differently-modded tree has never heard of, and that is a reason
        to skip the object, not to stop the session.
        """
        key = template.lower()
        cached = self._kinds.get(key)
        if cached is None:
            cached = self._resolve_kinds(key)
            self._kinds[key] = cached
        return cached

    def _resolve_kinds(self, key: str) -> frozenset[str]:
        """Walk to the root of the parent chain, then apply each `KindOf` on the way back down.

        Order matters: a plain `KindOf` replaces whatever was inherited, while `+FLAG`/`-FLAG`
        edit it. Collecting the chain first and applying it root-first is what gets both right;
        reading only the nearest declaration would drop a parent's flags whenever a child used
        the delta form.
        """
        chain = []
        current = self._objects.get(key)
        for _ in range(_MAX_DEPTH):
            if current is None:
                break
            chain.append(current)
            parent = getattr(current, "parent_name", None)
            current = self._objects.get(str(parent).lower()) if parent else None

        flags: set[str] = set()
        for obj in reversed(chain):
            declared = obj.fields.get("KindOf")
            if declared is None:
                continue
            tokens = str(declared).split()
            if not any(t.startswith(("+", "-")) for t in tokens):
                flags = {t.upper() for t in tokens}
                continue
            for token in tokens:
                if token.startswith("+"):
                    flags.add(token[1:].upper())
                elif token.startswith("-"):
                    flags.discard(token[1:].upper())
                else:
                    flags.add(token.upper())
        return frozenset(flags)

    def has_kind(self, template: str, *flags: str) -> bool:
        """Whether the template carries **any** of `flags`."""
        kinds = self.kind_of(template)
        return any(flag.upper() in kinds for flag in flags)

    def is_build_site(self, template: str) -> bool:
        """Whether a structure can be placed here - a castle plot or a settlement spot."""
        return bool(self.kind_of(template) & BASE_SITE_KINDS)

    def counts_for_victory(self, template: str) -> bool:
        """Whether losing this counts toward the engine's own multiplayer defeat check."""
        return MP_COUNT_FOR_VICTORY in self.kind_of(template)

    def build_variations(self, template: str) -> tuple[str, ...]:
        """The templates the engine may actually place when asked to build `template`.

        `BuildVariations` is a list of visually different stand-ins - `GondorWohnhaus` declares
        `GondorWohnhaus01 GondorWohnhaus02 GondorWohnhaus03` - and the engine picks one at
        build time. **The ordered template is therefore never the one that appears**, which
        makes "did my building get built?" unanswerable by name, and makes a bot that counts
        `GondorWohnhaus` rebuild forever.
        """
        declared = self.field(template, "BuildVariations")
        return tuple(declared.split()) if declared else ()

    def canonical(self, template: str) -> str:
        """The template that was *ordered* to produce `template`, or `template` itself.

        The inverse of `build_variations`, so a live object can be traced back to the thing a
        build order names. Built once over the whole table and cached.
        """
        if self._canonical is None:
            mapping: dict[str, str] = {}
            for name, obj in self._objects.items():
                declared = obj.fields.get("BuildVariations")
                if declared:
                    for variation in str(declared).split():
                        mapping[variation.lower()] = name
            self._canonical = mapping
        key = template.lower()
        return self._canonical.get(key, template)

    def same_building(self, template: str) -> frozenset[str]:
        """`template` and every variation of it, lowercased - what "one of these" means.

        Counting by this is name-based and exact; counting by `KindOf` is broader and needs no
        variation table. Both are here because they answer different questions: "how many
        Wohnhaus" versus "how many economy buildings".
        """
        return frozenset({template.lower(), *(v.lower() for v in self.build_variations(template))})

    def horde_payload(self, template: str) -> str | None:
        """The member template a horde is filled with, or None if this is not a horde.

        Read off the `HordeContain` module's `InitialPayload`, whose first token is the member
        template and whose second is the count (`GondorFighter GOOD_MEN_GIANT_HORDE_SIZE`).
        """
        obj = self._objects.get(template.lower())
        if obj is None:
            return None
        for module in getattr(obj, "modules", ()):
            declared = getattr(module, "fields", {}).get("InitialPayload")
            if declared:
                tokens = str(declared).split()
                if tokens:
                    return tokens[0]
        return None

    def horde_members(self) -> frozenset[str]:
        """Every template that exists only as the contents of a horde, lowercased.

        **Orders address the horde, not its members.** A battalion appears in a live
        observation as its individual members *plus* the container, and selecting the members
        is not how the engine expects to be talked to - `HordeAIUpdate` on the container is
        what drives them. Selecting 30 `GondorFighter` and issuing a move produced an order
        that was recorded and then did nothing.

        This is the set to exclude when building a selection. Computed once over the whole
        table, since a horde names its payload and nothing names the reverse.
        """
        if self._members is None:
            members: set[str] = set()
            for name in self._objects:
                payload = self.horde_payload(name)
                if payload:
                    members.add(payload.lower())
            self._members = frozenset(members)
        return self._members

    def is_horde(self, template: str) -> bool:
        """Whether this template is a horde container - the thing an order should name."""
        return "HORDE" in self.kind_of(template)

    def is_horde_member(self, template: str) -> bool:
        """Whether this template only ever appears as the contents of a horde.

        A horde container is not a member of one, even where a template somehow appears in
        both roles - the container is always the correct thing to order.
        """
        return template.lower() in self.horde_members() and not self.is_horde(template)

    def command_set(self, template: str) -> str | None:
        """The template's `CommandSet` name, following the parent chain."""
        return self.field(template, "CommandSet")

    def command_buttons(self, command_set: str) -> tuple[tuple[int, str], ...]:
        """`(slot, button name)` for one `CommandSet`, in slot order.

        Slots are sparse and unordered in the file - a set may define 1-7 then jump to 12 -
        so they are read as the integer keys they are and sorted, never enumerated.
        """
        block = self._sets.get(command_set.lower())
        if block is None:
            return ()
        found = [
            (int(key.strip()), str(value).strip())
            for key, value in block.fields.items()
            if str(key).strip().isdigit()
        ]
        return tuple(sorted(found))

    def button_command(self, button: str) -> str:
        """A `CommandButton`'s `Command`, uppercased. Empty for a button this tree lacks."""
        block = self._buttons.get(button.lower())
        if block is None:
            return ""
        return str(block.fields.get("Command", "")).strip().upper()

    def revive_slots(self, template: str) -> tuple[ReviveSlot, ...]:
        """The producer's `Command = REVIVE` buttons, in slot order - its hero slots.

        Empty for anything that cannot recruit a hero, which is almost everything. A building
        with slots offers only the ones whose `NeededUpgrade` it can satisfy; the rest are
        present because heroes bind to these slots **by position**, so a building that recruits
        the fourth hero must carry the first three slots as well. See `sage_live.heroes` for
        why the position is offset by one, and for what the engine does and does not check.
        """
        key = template.lower()
        cached = self._revives.get(key)
        if cached is not None:
            return cached
        name = self.command_set(template)
        slots: list[ReviveSlot] = []
        if name:
            for command_slot, button in self.command_buttons(name):
                if self.button_command(button) != REVIVE:
                    continue
                block = self._buttons.get(button.lower())
                fields = block.fields if block is not None else {}
                needed = str(fields.get("NeededUpgrade", "")).split()
                options = str(fields.get("Options", "")).upper().split()
                slots.append(
                    ReviveSlot(
                        position=len(slots),
                        command_slot=command_slot,
                        button=button,
                        needed_upgrades=tuple(needed),
                        hide_while_disabled="HIDE_WHILE_DISABLED" in options,
                    )
                )
        result = tuple(slots)
        self._revives[key] = result
        return result

    def revive_slot_for(self, template: str, roster_index: int) -> ReviveSlot | None:
        """The producer's slot serving `roster_index`, or None if it carries no such slot."""
        for slot in self.revive_slots(template):
            if slot.roster_index == roster_index:
                return slot
        return None

    def hero_roster(self, faction: str) -> tuple[str, ...]:
        """A faction's `BuildableHeroesMP`, which is the revive list's starting order.

        `faction` is matched against the `PlayerTemplate` block name (`FactionMen`) *and*
        against its `Side` - a live observation reports the Side token, `Men`, and the two are
        not the same string. Where several templates share a Side, the playable one wins:
        `FactionTutorial` is also `Side = Men` and carries a different roster.

        **Map-scoped overrides are not applied.** A `map.ini` may redefine `BuildableHeroesMP`
        for the map being played, and several Edain maps do; this reads the base tree only.
        """
        key = faction.lower()
        block = self._factions.get(key) or self._factions.get(f"faction{key}")
        if block is None:
            playable = [
                f
                for f in self._factions.values()
                if str(f.fields.get("Side", "")).lower() == key
                and str(f.fields.get("PlayableSide", "")).lower() in ("yes", "true")
            ]
            if len(playable) != 1:
                return ()
            block = playable[0]
        return tuple(str(block.fields.get("BuildableHeroesMP", "")).split())

    def check_revive_slots(self, template: str, roster: Sequence[str]) -> tuple[str, ...]:
        """Whether this producer's slot block can be read against `roster` at all.

        An **enabled** slot serving an index outside the roster cannot be right: the positional
        rule has landed somewhere there is no hero, so this block does not line up and the
        heroes it appears to offer are fiction. Reported rather than resolved - a policy running
        without `godsight` should treat such a producer as unknown rather than trust it.

        Restricted to slots enabled with no upgrade held, because the permanently-gated
        `Command_FakeHeroReviveSlotN` fillers are not meant to line up with anything: they exist
        only to hold positions so the real buttons land in the right places.

        **Button names are deliberately not checked.** It is tempting - Edain appears to number
        these after the roster entry they serve - but `Command_GenericReviveSlot1` occurs at
        positions 0, 1, 3 and 4 in different sets, so its number identifies the button and not
        a hero. The names that *are* meaningful are the ones naming a hero outright
        (`Command_HaldirGenericReviveSlot`), and 220 of 231 of those land on their own roster
        entry - measured once, recorded in `sage_live.heroes`, not re-derived here by guessing
        at hero names.
        """
        problems: list[str] = []
        for slot in self.revive_slots(template):
            if not slot.enabled_for(frozenset()):
                continue
            if not 0 <= slot.roster_index < len(roster):
                problems.append(
                    f"{slot.button} sits at position {slot.position}, which serves roster "
                    f"index {slot.roster_index} - outside a roster of {len(roster)}"
                )
        return tuple(problems)

    def templates_with(self, *flags: str) -> frozenset[str]:
        """Every known template carrying any of `flags`, for surveying a build rather than
        asking about one object at a time."""
        wanted: Iterable[str] = [f.upper() for f in flags]
        return frozenset(
            name for name in self._objects if any(f in self.kind_of(name) for f in wanted)
        )
