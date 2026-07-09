"""Diffing a page's infobox against the values computed from a game object.

The diff is infobox-driven: it pairs each parameter the infobox already has (and that
this tool can compute) with the object's value; parameters the infobox lacks are left
out. Different templates name the same stat differently (bare `damage` vs `damage_melee`,
`object_name` vs `object`), so `FIELD_ALIASES` maps a logical field to the params that
may carry it, preferred first, and the diff uses whichever the page actually has.
"""

from dataclasses import dataclass

from sage_wiki.infobox import Infobox
from sage_wiki.mapping import computed_fields

# Logical field -> infobox params that may hold it, preferred first. Heroes split combat
# stats by attack type (melee leads); the building infobox indexes by level, so `…1` (the
# base level) is the building alias. A field absent here is matched by its own name only.
FIELD_ALIASES: dict[str, list[str]] = {
    "object_name": ["object_name", "object"],
    "armor": ["armor", "armor_melee", "armor_ranged", "armor1"],
    "damage": ["damage", "damage_melee", "damage_ranged", "damage1"],
    "damage_type": ["damage_type", "damage_type_melee", "damage_type_ranged"],
    "attack_speed": ["attack_speed", "attack_speed_melee", "attack_speed_ranged", "attack_speed1"],
    "range": ["range", "range_melee", "range_ranged", "range1"],
    "speed": ["speed", "speed_melee", "speed_ranged"],
    "health": ["health", "health1"],
    "resources": ["resources", "resources1"],
    "interval": ["interval", "interval1"],
}


@dataclass(frozen=True)
class FieldChange:
    """One infobox parameter's current (`old`) value beside the computed (`new`) one."""

    param: str
    old: str
    new: str

    @property
    def changed(self) -> bool:
        return self.old != self.new


def resolved_param(infobox: Infobox, logical: str) -> str | None:
    """The infobox param carrying `logical` (the first of its `FIELD_ALIASES` the infobox
    defines), or None."""
    for candidate in FIELD_ALIASES.get(logical, [logical]):
        if infobox.has(candidate):
            return candidate
    return None


def _lookup_object(name: str, objects: dict):
    """The loaded object for a single id, or None. Matched case-insensitively (wiki ids
    are typed by hand and rarely reproduce SAGE's mixed case); the object carries its
    canonical name, so a diff rewrites the field to that casing."""
    name = name.strip()
    if not name:
        return None
    obj = objects.get(name)
    if obj is not None:
        return obj
    lowered = name.lower()
    return next((o for key, o in objects.items() if key.lower() == lowered), None)


def resolve_objects(infobox: Infobox, game) -> list:
    """The loaded objects a page names through its object-id field, in written order. That
    field may list several `/`-separated forms; each is resolved, unloaded parts dropped and
    duplicates collapsed. Empty when the field is absent or matches nothing."""
    param = resolved_param(infobox, "object_name")
    raw = infobox.get(param) if param else None
    if not raw:
        return []
    objects = game.objects
    resolved: list = []
    for part in raw.split("/"):
        obj = _lookup_object(part, objects)
        if obj is not None and obj not in resolved:
            resolved.append(obj)
    return resolved


def resolve_object(infobox: Infobox, game):
    """The single loaded object a page names (the first of a `/`-separated field), or None."""
    candidates = resolve_objects(infobox, game)
    return candidates[0] if candidates else None


def _merge_object_name(old: str, new: str) -> str:
    """Keep every form a page already lists in its object-id field: when the chosen object
    is one of the `/`-separated parts present, the original value is kept verbatim so loading
    one form never drops the others; otherwise the field rewrites to the computed name."""
    parts = [p.strip() for p in old.split("/") if p.strip()]
    if len(parts) > 1 and any(p.lower() == new.lower() for p in parts):
        return old
    return new


def diff_infobox(infobox: Infobox, obj) -> list[FieldChange]:
    """The per-field comparison for every parameter the infobox has and we can map, in the
    mapping's field order. Each change carries the page's real param name; unchanged fields
    are included too (with `changed` False) so the review shows the full picture."""
    computed = computed_fields(obj)
    changes: list[FieldChange] = []
    for logical, new in computed.items():
        param = resolved_param(infobox, logical)
        if param is None:
            continue  # only touch fields the infobox already defines
        old = infobox.get(param) or ""
        if logical == "object_name":
            new = _merge_object_name(old, new)
        changes.append(FieldChange(param, old=old, new=new))
    # The per-archetype summary now lives in the `damage` cell, so any `damage_targets`
    # the page still carries is redundant - clear it (and any stance variant).
    for param, value in infobox.fields().items():
        if param.startswith("damage_targets"):
            changes.append(FieldChange(param, old=value, new=""))
    return changes


def apply_changes(infobox: Infobox, changes: list[FieldChange]) -> str:
    """Write every changed field back into `infobox` and return the new wikitext (unchanged
    fields skipped, so the page differs only where a value moved)."""
    return apply_all([(infobox, changes)])


def apply_all(edited: list[tuple[Infobox, list[FieldChange]]]) -> str:
    """Write each infobox's changed fields back and return the full page wikitext, unchanged
    fields skipped. Every infobox parsed from one page shares its `Wikicode`, so a single
    render reflects all of their edits. Returns the empty string when `edited` is empty."""
    for infobox, changes in edited:
        for change in changes:
            if change.changed:
                infobox.set(change.param, change.new)
    return edited[0][0].render() if edited else ""
