"""Copy a character - a sprite and everything it draws - from one `.apt` movie into another.

A movie's characters are an **array**, and everything that names one names it by index: a
`placeobject`'s `character`, a button record's `character`, an `edittext`'s `font`, a `morph`'s two
endpoints. A `shape` reaches further still - it names a `<Movie>_geometry/<id>.ru` mesh, and the
mesh's textured fills name `image` characters back in the array. So a character cannot be moved
between movies by copying its XML: every index in it means something different on the other side,
and one whole class of edge is not in the XML at all.

:func:`merge_character` does the renumbering. Give it the source's geometry and it walks the
transitive closure of one character *through* the meshes, appends the whole subtree to the
destination's array, and rewrites every index in the copied elements - characters, geometry ids and
texture ids alike - returning the maps so the caller can move the `.ru` and `.tga` files those last
two name. :func:`rewrite_geometry` renumbers a copied mesh to match.

Characters the subtree only *imports* are not copied. They are matched against the destination's
own imports by (movie, name), and only the ones it does not already have are added - which is why
merging a BFME1 menu sprite into a ROTWK one usually adds no imports at all: both movies already
import `buttonGlow` and friends from `MenuExport`.

The constant pool needs no attention. `sage_apt` rebuilds the `.const` from the XML on every
compile - a `pushdata`'s `data id` and a `constantpool`'s `constant id` are re-indexed from their
values - so action bytecode moves between movies unchanged.

What this does **not** do is lay anything out. The copied character arrives with no `placeobject`
naming it; putting it on a frame is the caller's business, and so is the ActionScript that drives
it.
"""

from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = [
    "CHARACTER_TAGS",
    "POOL_INDEXED",
    "POOL_LIMIT",
    "MergePlan",
    "character_index",
    "closure",
    "constant_index",
    "copy_functions",
    "geometry_images",
    "merge_character",
    "rewrite_geometry",
]

#: The action opcodes whose `val` is an index into the enclosing block's constant pool rather than
#: a literal. `pushbyte`, `pushshort`, `pushregister` and the rest carry values and are left alone.
POOL_INDEXED = frozenset(
    {
        "callnamedfunc",
        "callnamedfuncpop",
        "callnamedmethod",
        "callnamedmethodpop",
        "getnamedmember",
        "pushconstant",
        "pushvalue",
    }
)

#: How far those opcodes can reach. Their operand is one byte, and only `pushconstant` has a word
#: form (`pushwordconstant`) to fall back on - so a pool that grows past this cannot be addressed
#: by `getnamedmember` or the call opcodes at all, and :func:`copy_functions` refuses rather than
#: emitting an index that silently wraps.
POOL_LIMIT = 256

#: Every tag that occupies a slot in the character array, in the order the compiler reads them.
#: `empty` is in the list because a gap is a slot too - an unused index, or one an `import` claims.
CHARACTER_TAGS = (
    "shape",
    "edittext",
    "font",
    "button",
    "sprite",
    "image",
    "morph",
    "text",
    "empty",
)

#: Where a character index can appear inside a character: `tag -> attributes`.
_CHARACTER_REFS = {
    "placeobject": ("character",),
    "buttonrecord": ("character",),
    "edittext": ("font",),
    "textrecord": ("font",),
    "morph": ("start", "end"),
}

#: A textured fill in a `.ru` mesh: `s tc:<r>:<g>:<b>:<a>:<image>:<six floats>`. The sixth field is
#: the `image` character the fill samples, and is the only reference a mesh carries.
_FILL = re.compile(r"^(\s*s\s+tc:(?:[^:\s]+:){4})(\d+)(:)", re.MULTILINE)


@dataclass
class MergePlan:
    """What :func:`merge_character` did, as the renumberings it performed.

    `character` is the copied subtree's root in its new home - the id a `placeobject` has to name
    to put it on a frame. The maps are `source id -> destination id`; `geometry` says which `.ru`
    files to copy and what to rename them to, and `textures` does the same for `apt_<Movie>_<id>`.
    """

    character: int
    characters: dict[int, int] = field(default_factory=dict)
    geometry: dict[int, int] = field(default_factory=dict)
    textures: dict[int, int] = field(default_factory=dict)
    #: Imports added to the destination, as `(movie, name, destination character)`. An import the
    #: destination already had is reused and does not appear here.
    imports: list[tuple[str, str, int]] = field(default_factory=list)


def character_index(root: ET.Element) -> list[ET.Element]:
    """The movie's character array, by position.

    Position is what the format stores and what the compiler re-derives, so this counts elements
    rather than trusting the `id` attribute the decompiler writes beside them. Index 0 is the movie
    itself, which the decompiler emits as `<empty id="0"/>`.
    """
    return [child for child in root if child.tag in CHARACTER_TAGS]


def geometry_images(text: str) -> set[int]:
    """The `image` characters a `.ru` mesh's textured fills sample."""
    return {int(match.group(2)) for match in _FILL.finditer(text)}


def rewrite_geometry(text: str, plan: MergePlan) -> str:
    """A copied mesh with its fills' `image` characters renumbered for their new movie."""
    return _FILL.sub(
        lambda m: (
            m.group(1) + str(plan.characters.get(int(m.group(2)), int(m.group(2)))) + m.group(3)
        ),
        text,
    )


def _imports_of(root: ET.Element) -> dict[int, tuple[str, str]]:
    """`character slot -> (movie, name)` for the movie's imports."""
    movieclip = root.find("movieclip")
    imports = None if movieclip is None else movieclip.find("imports")
    if imports is None:
        return {}
    return {
        int(imp.get("character", "0")): (imp.get("movie", ""), imp.get("name", ""))
        for imp in imports
    }


def _refs(element: ET.Element, geometry: Mapping[int, str] | None) -> set[int]:
    """Every character index the element names, directly or through its mesh."""
    found: set[int] = set()
    for node in element.iter():
        for attribute in _CHARACTER_REFS.get(node.tag, ()):
            value = node.get(attribute)
            if value is not None and int(value) >= 0:
                found.add(int(value))
    if geometry is not None and element.tag == "shape":
        mesh = geometry.get(int(element.get("geometry", "-1")))
        if mesh is not None:
            found |= geometry_images(mesh)
    return found


def closure(root: ET.Element, start: int, geometry: Mapping[int, str] | None = None) -> set[int]:
    """Every character index reachable from ``start``, including itself.

    Breadth-first over the reference attributes, and - when ``geometry`` maps geometry ids to their
    `.ru` text - over each shape's textured fills as well. Without it the `image` characters the
    meshes sample are invisible, and a merge built on that closure would carry shapes that sample
    textures their new movie does not have.

    An index with no character behind it is kept and has no children, which is what makes an import
    - a slot holding an `<empty>` - come out as a leaf.
    """
    characters = character_index(root)
    seen: set[int] = set()
    queue = deque([start])
    while queue:
        index = queue.popleft()
        if index in seen:
            continue
        seen.add(index)
        if 0 <= index < len(characters):
            queue.extend(ref for ref in _refs(characters[index], geometry) if ref not in seen)
    return seen


def _highest(root: ET.Element, tag: str, attribute: str) -> int:
    """The largest value of ``attribute`` across every ``tag`` element, or -1 for none."""
    return max((int(el.get(attribute, "-1")) for el in root.iter(tag)), default=-1)


def merge_character(
    destination: ET.Element,
    source: ET.Element,
    start: int,
    geometry: Mapping[int, str] | None = None,
) -> MergePlan:
    """Copy character ``start`` and everything it draws from ``source`` into ``destination``.

    Both arguments are `<aptdata>` roots, as :func:`sage_apt.apt_to_xml` writes them.
    ``destination`` is modified in place; ``source`` is not touched. ``geometry`` maps the source's
    geometry ids to their `.ru` text - pass it whenever the subtree contains shapes, or the images
    they sample will be left behind.

    Raises `ValueError` if ``start`` names no character, if the subtree reaches a slot the source
    neither defines nor imports, or if an `image` character's texture id differs from its own
    character id. That last one holds across every movie ROTWK and BFME1 ship, and the renumbering
    preserves it rather than tracking two numbers that are always equal; a movie that broke it
    would be renumbered wrongly and silently, so it is refused instead.
    """
    source_characters = character_index(source)
    if not 0 <= start < len(source_characters) or source_characters[start].tag == "empty":
        raise ValueError(f"character {start} is not a character in the source movie")

    source_imports = _imports_of(source)
    wanted = sorted(closure(source, start, geometry))

    unknown = [
        index
        for index in wanted
        if index >= len(source_characters)
        or (source_characters[index].tag == "empty" and index not in source_imports)
    ]
    if unknown:
        raise ValueError(
            f"character {start} reaches {unknown}, which the source movie neither defines nor "
            "imports"
        )
    mismatched = [
        index
        for index in wanted
        if source_characters[index].tag == "image"
        and int(source_characters[index].get("image", "-1")) != index
    ]
    if mismatched:
        raise ValueError(
            f"image characters {mismatched} name a texture other than themselves, which this "
            "renumbering does not model"
        )

    destination_characters = character_index(destination)
    next_character = len(destination_characters)

    # Imports first: one the destination already has costs no slot, so resolving them before the
    # copied characters keeps the new indices contiguous.
    have = {pair: slot for slot, pair in _imports_of(destination).items()}
    plan = MergePlan(character=-1)
    added_imports: list[tuple[str, str, int]] = []
    for index in wanted:
        if index not in source_imports:
            continue
        pair = source_imports[index]
        if pair in have:
            plan.characters[index] = have[pair]
            continue
        plan.characters[index] = next_character
        added_imports.append((*pair, next_character))
        next_character += 1

    for index in wanted:
        if index not in plan.characters:
            plan.characters[index] = next_character
            next_character += 1

    # Geometry ids live in their own namespace; renumber them above whatever the destination
    # already uses so no existing mesh is displaced. Texture ids follow the character ids, which is
    # the invariant checked above.
    next_geometry = _highest(destination, "shape", "geometry") + 1
    for index in wanted:
        if index in source_imports:
            continue
        element = source_characters[index]
        if element.tag == "shape":
            old = int(element.get("geometry", "-1"))
            if old >= 0 and old not in plan.geometry:
                plan.geometry[old] = next_geometry
                next_geometry += 1
        elif element.tag == "image":
            plan.textures[index] = plan.characters[index]

    # Copy, renumber, append. Slots are appended in ascending destination index, and an import's
    # slot is an `<empty>`, so the array stays dense and in step with the imports list.
    by_new = {new: old for old, new in plan.characters.items()}
    import_slots = {slot for _, _, slot in added_imports}
    for new_index in range(len(destination_characters), next_character):
        if new_index in import_slots:
            destination.append(ET.Element("empty", {"id": str(new_index)}))
            continue
        element = copy.deepcopy(source_characters[by_new[new_index]])
        element.set("id", str(new_index))
        _renumber(element, plan)
        destination.append(element)

    movieclip = destination.find("movieclip")
    if movieclip is None:  # pragma: no cover - a movie without one cannot be compiled either
        raise ValueError("the destination has no <movieclip>")
    imports_elem = movieclip.find("imports")
    if imports_elem is None:
        imports_elem = ET.Element("imports")
        movieclip.insert(0, imports_elem)
    for movie, name, slot in added_imports:
        ET.SubElement(
            imports_elem, "import", {"name": name, "movie": movie, "character": str(slot)}
        )
    plan.imports = added_imports
    plan.character = plan.characters[start]
    return plan


def constant_index(action: ET.Element, value: str) -> int:
    """The index of the string ``value`` in ``action``'s constant pool, appending it if absent.

    The pool is positional - `sage_apt` re-indexes it on compile from the order of the
    `<constant>` elements, ignoring their `id` attribute - so appending is safe and the new index
    is simply the old length. The `id` is still written, because that is what the decompiler emits
    and a reader comparing the two forms should see the same thing.
    """
    pool = action.find("constantpool")
    if pool is None:
        pool = ET.Element("constantpool")
        action.insert(0, pool)
    for index, constant in enumerate(pool):
        if constant.get("string") == value:
            return index
    index = len(pool)
    ET.SubElement(pool, "constant", {"id": str(index), "string": value})
    return index


def _anchors(element: ET.Element) -> set[str]:
    return {node.get("anchor") for node in element.iter() if node.get("anchor")}  # type: ignore[misc]


def _targets(element: ET.Element) -> set[str]:
    return {node.get("target") for node in element.iter() if node.get("target")}  # type: ignore[misc]


def copy_functions(
    destination: ET.Element, source: ET.Element, names: list[str] | tuple[str, ...]
) -> dict[str, int]:
    """Copy named `definefunction` blocks from one `<action>` element into another.

    Both arguments are `<action>` elements - the thing a frame carries its ActionScript in. Each
    named function is deep-copied, its constant-pool operands are rewritten to the destination
    pool's indices (appending the strings it needs), and it is inserted before the destination
    block's trailing `<end/>`.

    Returns `name -> destination pool index of that name`, because a function is only reachable
    once something calls it and the caller needs the index.

    Raises `ValueError` when a requested function is absent, when a copied body branches to an
    anchor outside itself (the branch would land somewhere else in its new block), or when the
    destination pool would grow past what a one-byte operand can address.
    """
    source_pool = source.find("constantpool")
    strings = (
        [constant.get("string", "") for constant in source_pool] if source_pool is not None else []
    )
    available = {
        node.get("name"): node
        for node in source
        if node.tag in ("definefunction", "definefunction2")
    }
    missing = [name for name in names if name not in available]
    if missing:
        raise ValueError(f"the source action defines no {missing}")

    indices: dict[str, int] = {}
    for name in names:
        copied = copy.deepcopy(available[name])
        copied.attrib.pop("anchor", None)  # its callers are not coming with it
        stray = _targets(copied) - _anchors(copied)
        if stray:
            raise ValueError(f"{name} branches to {sorted(stray)}, which is outside the function")
        for node in copied.iter():
            if node.tag not in POOL_INDEXED:
                continue
            old = int(node.get("val", "0"))
            if not 0 <= old < len(strings):
                raise ValueError(
                    f"{name} names constant {old}, which the source pool does not have"
                )
            new = constant_index(destination, strings[old])
            if new >= POOL_LIMIT:
                raise ValueError(
                    f"copying {name} would need constant {new}, past the {POOL_LIMIT}-entry reach "
                    "of a one-byte operand"
                )
            node.set("val", str(new))
        indices[name] = constant_index(destination, name)
        if indices[name] >= POOL_LIMIT:
            raise ValueError(
                f"naming {name} would need constant {indices[name]}, past the {POOL_LIMIT}-entry "
                "reach of a one-byte operand"
            )
        end = destination.find("end")
        if end is None:
            destination.append(copied)
        else:
            destination.insert(list(destination).index(end), copied)
    return indices


def _renumber(element: ET.Element, plan: MergePlan) -> None:
    """Rewrite every index inside one copied character to its destination value."""
    for node in element.iter():
        for attribute in _CHARACTER_REFS.get(node.tag, ()):
            value = node.get(attribute)
            if value is not None and int(value) in plan.characters:
                node.set(attribute, str(plan.characters[int(value)]))
        if node.tag == "shape":
            old = int(node.get("geometry", "-1"))
            if old in plan.geometry:
                node.set("geometry", str(plan.geometry[old]))
        elif node.tag == "image":
            old = int(node.get("image", "-1"))
            if old in plan.textures:
                node.set("image", str(plan.textures[old]))
