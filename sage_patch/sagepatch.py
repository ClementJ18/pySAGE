"""Read a patched `game.dat` and write down the INI surface it accepts - the `.sagepatch` that
`sage_ini` and `sage_lint` load (see :mod:`sage_ini.engine`).

The file is derived from **the binary**, not from a list of patch names someone types, and that
is the point: a mod's `game.dat` is whatever its author actually built, and the questions that
matter - which patches are in it, at what count, under which keyword, with which tokens on which
bits - are all answerable from the image itself.

Two passes produce it, and they cover for each other:

* **Detection.** Every registered patch is offered the image through
  :meth:`~sage_patch.patcher.Patch.detect`, which recovers its parameters where it has any. A
  detected patch contributes :meth:`~sage_patch.patcher.Patch.ini_surface` - the fields it adds,
  the ceilings it raises, the tokens it names - and its name as the provenance on each delta.

* **Name tables.** The engine's three name tables plus the weather list are read live and
  compared with their stock lengths, so **every** token past the stock ones is written down with
  the index it actually landed on. This is what catches a patch applied with a non-default name
  (detection misses it, the table does not), a hand-rolled patch this package never heard of, and
  two patches that each added a token.

The two are then fused per token: the table pass supplies the index, the detection pass supplies
the patch that put it there, and a token only one pass knows about is kept regardless.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from importlib.metadata import PackageNotFoundError, version

from sage_ini.engine import AppliedPatch, Engine, EnumDelta, Source

from .addresses import BUILD
from .patcher import Patch
from .patches import desert_weather
from .patches.utils import locomotor_sets, model_conditions, modifier_types, weapon_set_flags
from .patches.utils.name_tables import read_cstring, read_terminated, resolve_base
from .registry import PATCHES

__all__ = [
    "Generated",
    "detect_patches",
    "differences",
    "generate",
    "generate_from_patches",
    "manifest",
    "name_table_members",
    "patch_differences",
    "rebuild",
]

#: Each engine name table, as `(model enum, how many entries the stock build names, reader)`. The
#: reader answers the live table's name pointers - wherever the table now lives and however long
#: it now is - so a relocated, rebuilt table reads back exactly like a stock one.
_NAME_TABLES: tuple[tuple[str, int, object], ...] = (
    ("ModelCondition", model_conditions.STOCK_BIT_COUNT, model_conditions.read),
    ("WeaponSetConditions", weapon_set_flags.STOCK_FLAG_COUNT, weapon_set_flags.read),
    ("LocomotorSetType", locomotor_sets.STOCK_SET_COUNT, locomotor_sets.read),
    ("ModifierType", modifier_types.STOCK_TYPE_COUNT, modifier_types.read),
)

# What to write as the `[source] generator`: the distribution version, since the packages here
# are versioned together. Running from a checkout that was never installed has no version to
# report, which is a fine thing for a provenance line to say.
try:
    _GENERATOR = f"sage_patch {version('pysage-tools')}"
except PackageNotFoundError:  # pragma: no cover - only on an uninstalled checkout
    _GENERATOR = "sage_patch"

#: The build every address in this package was derived against. A file that is not this build is
#: still read - the tables are found through their references, not their stock addresses - but
#: the mismatch is worth saying out loud.
_EXPECTED_SIZE = 11_346_944


@dataclass(frozen=True, slots=True)
class Generated:
    """The outcome of reading one `game.dat`: the engine description, the patches recognised in
    it, and anything worth telling the user about how it was read."""

    engine: Engine
    patches: tuple[Patch, ...]
    notes: tuple[str, ...] = ()


def _weather_names(data: bytes | bytearray) -> list[str]:
    """The live global-weather list. It is a plain NULL-terminated table like the other three,
    but it belongs to no single patch module, so it is read here from the references the
    desert-weather patch repoints."""
    base_va = resolve_base(data, desert_weather.WEATHER_TABLE_REF_VAS, "weather name table")
    pointers = read_terminated(data, base_va, "weather name table")
    return [read_cstring(data, pointer) or "" for pointer in pointers]


def name_table_members(data: bytes | bytearray) -> tuple[tuple[EnumDelta, ...], tuple[str, ...]]:
    """Every token the image names past the stock ones, with the index it sits at, plus notes on
    any table that could not be read.

    A table that fails to read is reported and skipped rather than raising: on a stock binary,
    a differently-built one, or one a foreign patch has restructured, the right answer is "this
    is what I could tell you", not a traceback."""
    members: list[EnumDelta] = []
    notes: list[str] = []
    readers: list[tuple[str, int, object]] = [
        *_NAME_TABLES,
        ("MapWeatherType", len(desert_weather.STOCK_WEATHER_NAMES), None),
    ]
    for enum_name, stock_count, reader in readers:
        try:
            if reader is None:
                names = _weather_names(data)
            else:
                table = reader(data)  # type: ignore[operator]
                names = [read_cstring(data, pointer) or "" for pointer in table.pointers]
        except (ValueError, struct.error) as exc:
            notes.append(f"{enum_name}: could not read the name table ({exc})")
            continue
        for index in range(stock_count, len(names)):
            if names[index]:
                members.append(EnumDelta(enum=enum_name, name=names[index], value=index))
    return tuple(members), tuple(notes)


def detect_patches(data: bytes | bytearray) -> tuple[Patch, ...]:
    """Every registered patch the image carries, each built with the parameters recovered from
    it. Registration order, which is stable and therefore keeps a generated file diffable."""
    found = [patch for cls in PATCHES.values() if (patch := cls.detect(data)) is not None]
    return tuple(found)


def _fuse(surfaced: Sequence[EnumDelta], observed: Sequence[EnumDelta]) -> tuple[EnumDelta, ...]:
    """Merge the tokens the detected patches claim with the tokens the tables actually hold.

    Neither side is complete on its own: a patch knows its own name but usually not which bit it
    landed on, and a table knows the bit but not who wrote it. Keyed by `(enum, token)`, the
    index comes from the table and the provenance from the patch, and a token only one side knows
    about is kept as it stands."""
    fused: dict[tuple[str, str], EnumDelta] = {}
    for delta in observed:
        fused[(delta.enum, delta.name)] = delta
    for delta in surfaced:
        key = (delta.enum, delta.name)
        seen = fused.get(key)
        if seen is None:
            fused[key] = delta
        else:
            fused[key] = EnumDelta(
                enum=delta.enum,
                name=delta.name,
                value=seen.value if seen.value is not None else delta.value,
                patch=delta.patch or seen.patch,
            )
    return tuple(fused.values())


def _writable(value: object) -> bool:
    """Whether a patch option is something the `.sagepatch` can hold and a constructor can take
    back: a scalar, or a list of them."""
    if isinstance(value, bool | int | float | str):
        return True
    return isinstance(value, tuple | list) and all(
        isinstance(item, bool | int | float | str) for item in value
    )


def manifest(patches: Iterable[Patch]) -> tuple[tuple[AppliedPatch, ...], list[str]]:
    """`patches` as the `[[patches]]` manifest plus anything that could not be written down.

    Every patch is listed, whether or not it changes the INI: a build is made mostly of patches
    that add no field and no token, and the list is what lets the committed file say what the
    binary is and `rebuild` put it back together. Each entry carries the parameters the instance
    holds - recovered from the image by `detect`, so a manifest describes the build rather than
    this version's defaults - plus the author and the one-line description, so the file reads as
    a reference where nothing else is installed."""
    records: list[AppliedPatch] = []
    notes: list[str] = []
    for patch in patches:
        options: list[tuple[str, object]] = []
        for key, value in sorted(patch.options().items()):
            if not _writable(value):
                notes.append(
                    f"{patch.name}: parameter {key!r} is a {type(value).__name__}, which a "
                    "manifest entry cannot hold - it is listed without it, and a rebuild from "
                    "this file would use the default"
                )
                continue
            options.append((key, value))
        cls = type(patch)
        records.append(
            AppliedPatch(
                name=patch.name,
                options=tuple(options),
                experimental=cls.experimental,
                author=cls.author,
                description=cls.description,
            )
        )
    return tuple(records), notes


def _source(data: bytes | bytearray) -> Source:
    """Provenance for the generated file. Deliberately **not** the path it was read from: see
    :class:`~sage_ini.engine.Source`."""
    return Source(
        build=BUILD,
        sha256=hashlib.sha256(bytes(data)).hexdigest(),
        generator=_GENERATOR,
        generated=date.today().isoformat(),
    )


def _combine(
    patches: Sequence[Patch], observed: Sequence[EnumDelta], source: Source
) -> tuple[Engine, list[str]]:
    """One engine from the detected patches - their manifest entries and their surfaces - plus
    the observed tokens, and whatever could not be written down."""
    surface = Engine()
    for patch in patches:
        surface = surface.merge(patch.ini_surface())
    records, notes = manifest(patches)
    return Engine(
        patches=records,
        blocks=surface.blocks,
        nested=surface.nested,
        fields=surface.fields,
        noops=surface.noops,
        enum_members=_fuse(surface.enum_members, observed),
        limits=surface.limits,
        source=source,
    ), notes


def generate(data: bytes | bytearray) -> Generated:
    """Read `data` (a `game.dat` image) and describe the INI surface it accepts."""
    notes: list[str] = []
    if len(data) < _EXPECTED_SIZE:
        notes.append(
            f"this image is {len(data)} bytes; the build these addresses were derived against is "
            f"{_EXPECTED_SIZE} before any patch appends to it - the result may be incomplete"
        )
    patches = detect_patches(data)
    observed, table_notes = name_table_members(data)
    notes.extend(table_notes)
    engine, manifest_notes = _combine(patches, observed, _source(data))
    notes.extend(manifest_notes)
    unattributed = sorted(
        f"{delta.enum}.{delta.name}" for delta in engine.enum_members if not delta.patch
    )
    if unattributed:
        notes.append(
            "named by no patch this build recognises (kept, with no provenance): "
            + ", ".join(unattributed)
        )
    return Generated(engine=engine, patches=patches, notes=tuple(notes))


def generate_from_patches(names: Sequence[str]) -> tuple[Generated, list[str]]:
    """Describe the surface `names` would add, with each patch's **default** parameters, without
    reading a binary - for a project that knows which patches it builds with and would rather not
    wire a `game.dat` path into CI. Returns the description and the names that are not patches.

    Defaults are the limitation: a patch applied with any other parameter (another keyword, a
    different limit, a custom token) is described wrongly here and correctly by `generate`."""
    unknown = [name for name in names if name not in PATCHES]
    patches = [PATCHES[name]() for name in names if name in PATCHES]
    engine, manifest_notes = _combine(patches, (), Source(generator=_GENERATOR))
    notes = [
        "written from patch names, not from a binary: every patch is described with its default "
        "parameters",
        *manifest_notes,
    ]
    return Generated(engine=engine, patches=tuple(patches), notes=tuple(notes)), unknown


def rebuild(engine: Engine) -> tuple[list[Patch], list[str]]:
    """The patches an engine description's `[[patches]]` manifest names, rebuilt with the
    parameters it records, plus the entries that could not be rebuilt.

    This is the manifest's payoff: applying the result to a clean `game.dat` reproduces the build
    the file describes, at the counts and keywords it was built with rather than at this version's
    defaults. Order is the file's, which is the registration order `generate` writes; since the
    bundled patches are order-independent (see the composition contract on
    :class:`~sage_patch.patcher.Patch`), any order that lists them all yields the same *engine* -
    the same patches at the same parameters, verifiable with `sagepatch --check`. It does not
    promise the same *bytes* as some other build of the same list: each cave is appended past the
    sections already present, so a different application order lands them at different addresses.

    A name this build does not know, or a parameter it no longer takes, is reported rather than
    raised: an older mod's file against a newer package should say which entries went stale, not
    stop at the first one."""
    patches: list[Patch] = []
    problems: list[str] = []
    for record in engine.patches:
        cls = PATCHES.get(record.name)
        if cls is None:
            problems.append(
                f"{record.name}: no patch of that name in this build - `sage-patch list` names them"
            )
            continue
        try:
            patches.append(cls(**record.settings))  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            problems.append(f"{record.name}: {exc}")
    return patches, problems


def _spelt(record: AppliedPatch) -> str:
    """A manifest entry as `name (key=value, ...)` - what it was applied with, for a drift
    report that has to say more than which names differ."""
    options = ", ".join(f"{key}={value!r}" for key, value in record.options)
    return f"{record.name} ({options})" if options else record.name


def patch_differences(committed: Engine, generated: Engine) -> list[str]:
    """How the two manifests disagree, by patch name.

    Compared apart from the deltas, and on name plus parameters only: `author` and `description`
    are the generator's prose about a patch rather than a fact about the binary, and a reworded
    description must not fail a drift check."""
    problems: list[str] = []
    theirs = {record.name: record for record in committed.patches}
    ours = {record.name: record for record in generated.patches}
    for name, record in ours.items():
        seen = theirs.get(name)
        if seen is None:
            problems.append(f"patch in the binary but not in the file: {_spelt(record)}")
        elif seen.options != record.options:
            problems.append(
                f"patch {name} was applied as {_spelt(record)}, the file says {_spelt(seen)}"
            )
    for name, record in theirs.items():
        if name not in ours:
            problems.append(f"patch in the file but not in the binary: {_spelt(record)}")
    return problems


def differences(committed: Engine, generated: Engine) -> list[str]:
    """How `committed` disagrees with `generated`, ignoring `[source]` (a path and a hash, which
    differ per machine and per rebuild by design). An empty list means the committed file still
    describes the binary.

    Both halves are checked: the `[[patches]]` manifest, so a repatched binary fails the drift
    check even when the patch added no INI, and the surface deltas."""
    problems: list[str] = patch_differences(committed, generated)
    sections = (
        ("block", committed.blocks, generated.blocks),
        ("nested block", committed.nested, generated.nested),
        ("field", committed.fields, generated.fields),
        ("retired field", committed.noops, generated.noops),
        ("token", committed.enum_members, generated.enum_members),
        ("limit", committed.limits, generated.limits),
    )
    for label, theirs, ours in sections:
        for delta in ours:
            if delta not in theirs:
                problems.append(f"{label} in the binary but not in the file: {delta}")
        for delta in theirs:
            if delta not in ours:
                problems.append(f"{label} in the file but not in the binary: {delta}")
    return problems
