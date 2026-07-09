"""Phase 3: cross-reference the ini-names a save carries against a loaded `sage_ini` `Game`.

A save file is full of names that resolve against ini definitions - deliberately, so that
ini edits (reordering, insertion) don't invalidate saves. `harvest_references` collects those
names and `check_references` resolves each through `Game.lookup` (exact match, then the
engine's case-insensitive fallback), reporting the danglers - the same dangling-reference
machinery `sage_lint` applies to maps, now applied to saves ("will this save still load under
this mod tree", and which definitions a rename would break).

Harvested today: the `CHUNK_GameLogic` object template table (every live object's ini `Object`
name - **non-fatal**: the engine skips an unknown object-template TOC entry at load, dropping
the object rather than failing); the `CHUNK_Players` **and** `CHUNK_GameLogic` object-body upgrade
masks and science vectors (**fatal**: a dangling upgrade/science is `XFER_UNKNOWN_STRING`, aborting
the load) - the object bodies add the per-object *applied* upgrades (veterancy, hero abilities,
structure/object levels) that the per-player faction masks omit; and the `CHUNK_Campaign` hero
carry-over roster - the persistent heroes' ini `Object` templates and the `Upgrade_*` names they
earned (**fatal**: the roster is restored by name on the next mission). The roster is the only
ini-name source in a between-missions save (no live objects, no `CHUNK_Players`). And the
`CHUNK_LivingWorldLogic` army rosters - the ini `Object` templates a War-of-the-Ring living-world
army fields (**non-fatal**, via the `02 01` roster-entry signature), the only object-name source in
a living-world save (no `CHUNK_GameLogic` objects).

**The fatal xref surface is now essentially complete.** The two classes the plan reserved for a
later pass turned out not to apply to BFME saves: **kind-of flags** are written by `xferKindOf` as
a bare ascii name but are **non-fatal** (an unknown name is silently ignored on load - GPL
`Xfer::xferKindOf`), and **command-button** names are **not serialized by name** anywhere in the
save (a scan of every chunk finds none - command sets are resolved from ini at runtime). So there
is no kind-of / command-button dangling-reference class to harvest.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from sage_save.chunks import (
    decode_campaign,
    decode_game_logic,
    decode_script_engine,
    living_world_object_templates,
)
from sage_save.players import harvest_name_lists
from sage_save.save import SaveFile


class SupportsLookup(Protocol):
    """The slice of `sage_ini.model.game.Game` this module needs: resolve `name` in table
    `key`, returning `(definition_or_None, canonical_name)`."""

    def lookup(self, key: str, name: str) -> tuple[object | None, object]: ...


# Maps a harvested reference kind to the `Game` table it resolves against.
TABLE_FOR_KIND = {
    "object_template": "objects",
    "upgrade": "upgrades",
    "science": "sciences",
}


@dataclass(frozen=True)
class Reference:
    """One ini-name a save carries, with how many times it occurs and whether a dangling
    occurrence fails the load (fatal) or is silently skipped (non-fatal)."""

    kind: str
    name: str
    count: int
    fatal: bool


@dataclass(frozen=True)
class Finding:
    """A reference that does not cleanly resolve: `status` is ``"missing"`` (no definition,
    the load-affecting case) or ``"case-mismatch"`` (resolves only by ignoring case, which the
    engine tolerates but is worth surfacing). `canonical` is the definition's real spelling on
    a case mismatch."""

    reference: Reference
    status: str
    canonical: str | None


def harvest_object_references(save: SaveFile) -> list[Reference]:
    """The `CHUNK_GameLogic` object template table (non-fatal), each carrying the count of live
    objects of that template (0 if the template is registered but has no live instance)."""
    logic = save.chunk("CHUNK_GameLogic")
    if logic is None:
        return []
    state = decode_game_logic(logic)
    counts = Counter(obj.template_name for obj in state.objects)
    return [
        Reference("object_template", name, counts.get(name, 0), fatal=False)
        for name in state.templates.values()
    ]


def harvest_player_references(save: SaveFile) -> list[Reference]:
    """The `CHUNK_Players` upgrade masks and science vectors (fatal), one reference per distinct
    name with the number of player lists that carry it."""
    players = save.chunk("CHUNK_Players")
    if players is None:
        return []
    counts: Counter[tuple[str, str]] = Counter()
    for name_list in harvest_name_lists(players):
        for name in name_list.names:
            counts[(name_list.kind, name)] += 1
    return [Reference(kind, name, count, fatal=True) for (kind, name), count in counts.items()]


def harvest_object_upgrade_references(save: SaveFile) -> list[Reference]:
    """The **applied upgrade masks** carried by live objects in `CHUNK_GameLogic` (fatal). A
    behavior module writes its `xferUpgradeMask` with the same `u8 version=1 + u16 count + ascii
    Upgrade_ names` signature as the player masks, so it is harvested the same way over the whole
    chunk payload - the `Upgrade_` prefix makes a false match in the ~2 MB of object bodies
    vanishingly unlikely. This is a *second, richer* fatal-upgrade source than `CHUNK_Players`:
    it catches the veterancy levels, hero-ability, structure/object-level and button-enable
    upgrades actually applied to units (e.g. `Upgrade_DainLeadership`, `Upgrade_StructureLevel2`),
    which the per-player faction masks don't list."""
    logic = save.chunk("CHUNK_GameLogic")
    if logic is None:
        return []
    counts: Counter[tuple[str, str]] = Counter()
    for name_list in harvest_name_lists(logic):
        for name in name_list.names:
            counts[(name_list.kind, name)] += 1
    return [Reference(kind, name, count, fatal=True) for (kind, name), count in counts.items()]


def harvest_campaign_references(save: SaveFile) -> list[Reference]:
    """The `CHUNK_Campaign` hero carry-over roster: each persistent hero's ini `Object` template
    and the `Upgrade_*` names it earned. Both are **fatal** - the roster is restored by name on
    the next mission load, so a dangling template or upgrade breaks the carry-over. Counts are the
    number of heroes carrying that template / upgrade."""
    campaign_chunk = save.chunk("CHUNK_Campaign")
    if campaign_chunk is None:
        return []
    heroes = decode_campaign(campaign_chunk).heroes
    counts: Counter[tuple[str, str]] = Counter()
    for hero in heroes:
        counts[("object_template", hero.name)] += 1
        for upgrade in hero.upgrades:
            counts[("upgrade", upgrade)] += 1
    return [Reference(kind, name, count, fatal=True) for (kind, name), count in counts.items()]


def harvest_script_engine_references(save: SaveFile) -> list[Reference]:
    """The `CHUNK_ScriptEngine` ini-names, now via the structured decode rather than a signature
    scan. The per-player acquired-science vectors are **fatal** - they are the same
    `xferScienceVec` restore-by-name machinery as `CHUNK_Players` (an unknown name is
    `XFER_UNKNOWN_STRING`) - and independently cross-check the `Players` harvest. The
    object-type lists and attack-priority overrides carry ini `Object` template names that are
    only stored (not resolved) at load time, so they are **non-fatal**."""
    script_chunk = save.chunk("CHUNK_ScriptEngine")
    if script_chunk is None:
        return []
    state = decode_script_engine(script_chunk)
    counts: Counter[tuple[str, str, bool]] = Counter()
    for sciences in state.player_sciences:
        for science in sciences:
            counts[("science", science, True)] += 1
    for type_list in state.object_type_lists:
        for template in type_list.templates:
            counts[("object_template", template, False)] += 1
    for priority in state.attack_priorities:
        for template, _value in priority.overrides:
            counts[("object_template", template, False)] += 1
    return [
        Reference(kind, name, count, fatal=fatal) for (kind, name, fatal), count in counts.items()
    ]


def harvest_living_world_references(save: SaveFile) -> list[Reference]:
    """The `CHUNK_LivingWorldLogic` army rosters: each ini `Object` template a saved
    War-of-the-Ring army fields (its units and heroes), identified by the `02 01` roster-entry
    signature so runtime instance names (`DurmarthPlayerArmy`, `Player_1`) are not mistaken for
    definitions. **Non-fatal** (kind `object_template`): as with the `CHUNK_GameLogic` template
    table, a dangling object name is conservatively treated as a dropped reference rather than a
    load-failure - whether the WotR
    strategic layer aborts or drops on an unknown army unit is not yet established, and over-stating
    fatality is worse than under-stating it. This is the only object-name source in a living-world
    save (no `CHUNK_GameLogic` objects). Count is presence (1) per distinct template - the
    per-army fielding count would need the record walk."""
    lwl = save.chunk("CHUNK_LivingWorldLogic")
    if lwl is None:
        return []
    return [
        Reference("object_template", name, 1, fatal=False)
        for name in living_world_object_templates(lwl.payload)
    ]


def _merge(references: list[Reference]) -> list[Reference]:
    """Combine references to the same `(kind, name)` into one - summing counts and treating the
    reference as fatal if any source is fatal - so a name a save carries in several chunks is
    reported once. Order follows first appearance."""
    merged: dict[tuple[str, str], Reference] = {}
    for ref in references:
        key = (ref.kind, ref.name)
        existing = merged.get(key)
        if existing is None:
            merged[key] = ref
        else:
            merged[key] = Reference(
                ref.kind, ref.name, existing.count + ref.count, existing.fatal or ref.fatal
            )
    return list(merged.values())


def harvest_references(save: SaveFile) -> list[Reference]:
    """Every ini-name a save references that this reader can currently harvest: object templates
    (non-fatal), the fatal upgrade/science name classes, and the campaign hero roster. Names that
    appear in more than one chunk are merged into a single reference."""
    return _merge(
        harvest_object_references(save)
        + harvest_player_references(save)
        + harvest_object_upgrade_references(save)
        + harvest_campaign_references(save)
        + harvest_script_engine_references(save)
        + harvest_living_world_references(save)
    )


def check_references(references: list[Reference], game: SupportsLookup) -> list[Finding]:
    """Resolve each reference against `game`, returning only the ones that don't match exactly
    (missing definitions and case-only matches), most-referenced first."""
    findings: list[Finding] = []
    for reference in references:
        table = TABLE_FOR_KIND.get(reference.kind)
        if table is None:
            continue
        definition, canonical = game.lookup(table, reference.name)
        if definition is None:
            findings.append(Finding(reference, "missing", None))
        elif canonical != reference.name:
            findings.append(Finding(reference, "case-mismatch", str(canonical)))
    # Missing before case; within missing, fatal (aborts the load) before non-fatal (dropped).
    findings.sort(
        key=lambda f: (
            f.status != "missing",
            not f.reference.fatal,
            -f.reference.count,
            f.reference.name,
        )
    )
    return findings


def check_save(save: SaveFile, game: SupportsLookup) -> list[Finding]:
    """Harvest a save's ini-names and report the ones that won't resolve against `game`."""
    return check_references(harvest_references(save), game)


def format_findings(findings: list[Finding]) -> list[str]:
    """Human-readable lines for `check_save` output."""
    lines: list[str] = []
    for finding in findings:
        ref = finding.reference
        if finding.status == "missing":
            effect = "load fails" if ref.fatal else f"{ref.count} object(s) dropped on load"
            lines.append(f"  MISSING  {ref.kind} {ref.name!r} - undefined ({effect})")
        else:
            lines.append(f"  CASE     {ref.kind} {ref.name!r} - defined as {finding.canonical!r}")
    return lines
