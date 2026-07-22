"""Rules over on-disk asset files: that a referenced texture/model/map exists, and that a
WorldBuilder layout file is named the way the engine loads it.

Every field that holds an asset path is typed with an `_AssetFile` subclass carrying the
extension(s) the engine expects (`_TextureFile` -> `.tga`/`.dds`, `_ModelFile` -> `.w3d`,
`_MapFile` -> `.map`/`.bse`). The loader crawls the mod root alongside the ini files and records
the loose texture/model filenames in `game.assets` and the `.map`/`.bse` layout files in
`game.map_files` (see `sage_ini.parser.io`). The three missing-file rules (`MissingTextureFileRule`,
`MissingModelFileRule`, `MissingMapFileRule`) walk the typed fields and confirm each referenced
name resolves to one of those files - one code per kind, so a texture, model and map miss can be
selected, ignored and counted apart; `MapFolderNameRule` checks the `<name>/<name>.ext` convention
the reference resolution relies on.

The engine searches its asset roots by basename and treats a kind's extensions as
interchangeable (a `.tga` reference resolves to a `.dds` of the same name and vice versa), so
the membership check mirrors that - strip any directory and surrounding quotes, reduce the name
to its stem, and accept the file under any of the kind's expected extensions. Engine sentinels
(`NONE`, `<ANY>`, …) are left alone. When a kind was not crawled at all (a single file linted in
isolation, or assets shipped in archives), its index is empty and the rule stays silent rather
than flagging every reference.
"""

from collections.abc import Iterator

from sage_ini.model.game import Game
from sage_ini.model.types import (
    _AssetFile,
    _MapFile,
    _ModelFile,
    _TextureFile,
)
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.parser.location import Span
from sage_ini.walk import walk_asset_fields
from sage_lint.rules.base import Rule


def _normalize(raw: str) -> str:
    """The on-disk basename a reference resolves to: drop surrounding quotes and any directory
    prefix (the engine searches by basename), lower-cased for the case-insensitive match."""
    return raw.strip().strip('"').replace("\\", "/").rsplit("/", 1)[-1].strip().lower()


class _MissingAssetRule(Rule):
    """Shared base for the per-kind missing-file rules: a field naming a file the mod does not
    ship, so in game the engine finds no such asset and whatever the field drives silently fails
    to load. The name is matched the way the engine resolves it - by basename, appending the
    expected extension when the ini omits one. When the kind's index was not crawled at all the
    rule stays silent (the empty-index guard); engine sentinels (`NONE`, `<ANY>`, …) are left
    alone. Concrete subclasses below set the `_AssetFile` kind and its message nouns - one code
    each, so a texture, model and map miss are reported, selected and counted apart.

    (Audio/sound files are `_AssetFile`s too but get no rule: they routinely live in archives the
    loose-file crawl never indexes, so a miss there would be meaningless.)

    These rules are **opt-in** (`default = False`): a plain `lint` skips them, because without the
    base-game archives loaded every base asset reference would be reported missing - a flood, and
    a push to load large `.big` bases just to silence it. Enable with `--assets` (or `--select`)."""

    code = ""  # base does not register; each concrete subclass sets its own code
    default = False  # opt-in: skipped by a plain run, enabled by --assets/--select
    assets = True  # part of the asset group --assets turns on
    asset_class: type[_AssetFile]
    noun: str
    group: str  # which index the kind resolves against: "art" (textures/models) or "map"
    where: str  # a phrase naming where the file is expected, for the message

    def check(self, game: Game) -> Iterator[Diagnostic]:
        index = game.assets if self.group == "art" else {p.name.lower() for p in game.map_files}
        if not index:
            return  # that kind wasn't crawled: nothing to check against
        for obj, key, asset_cls, raw in walk_asset_fields(game):
            if asset_cls is not self.asset_class:
                continue
            name = _normalize(raw)
            if not name or name == "none" or name.startswith("<"):
                continue  # engine sentinels: NONE, <ANY>, <THIS_PLAYER>, ...
            extensions = asset_cls.extensions
            # The engine treats a kind's extensions as interchangeable - a `.tga` reference
            # resolves to a `.dds` of the same name (same texture, different compression), and
            # vice versa - so strip any extension the value already carries to the stem and try
            # them all, rather than demanding the exact one written.
            stem = name
            for ext in extensions:
                if name.endswith(ext):
                    stem = name[: -len(ext)]
                    break
            if any(stem + ext in index for ext in extensions):
                continue
            kinds = " or ".join(extensions)
            shown = raw.strip().strip('"')  # the source value, minus the quotes a spaced name needs
            yield Diagnostic(
                code=self.code,
                message=(
                    f"{type(obj).__name__}.{key} references {shown!r}, but no {self.noun} file "
                    f"({kinds}) by that name was found in {self.where}."
                ),
                span=obj._field_spans.get(key, obj.span),
                severity=Severity.WARNING,
                extra={
                    "name": shown,
                    "kind": self.noun,
                    "type": type(obj).__name__,
                    "key": key,
                },
            )


class MissingTextureFileRule(_MissingAssetRule):
    """A texture field naming a `.tga`/`.dds` the mod (and its base layers) do not ship."""

    code = "missing-texture-file"
    asset_class = _TextureFile
    noun = "texture"
    group = "art"
    where = "the mod's art folder"


class MissingModelFileRule(_MissingAssetRule):
    """A model field naming a `.w3d` the mod (and its base layers) do not ship."""

    code = "missing-model-file"
    asset_class = _ModelFile
    noun = "model"
    group = "art"
    where = "the mod's art folder"


class MissingMapFileRule(_MissingAssetRule):
    """A map field naming a `.map`/`.bse` layout the mod (and its base layers) do not ship."""

    code = "missing-map-file"
    asset_class = _MapFile
    noun = "map"
    group = "map"
    where = "the mod's maps, bases or libraries folders"


class MapFolderNameRule(Rule):
    """A WorldBuilder layout file whose name does not match its folder. The engine loads a map
    or base layout by folder name - `maps/my_map/my_map.map`, `bases/my_base/my_base.bse` - so a
    file like `maps/my_map/other.map` is never loaded, and a `MapFile` reference to the folder
    silently finds nothing. Flagged on the misnamed file itself."""

    code = "map-folder-name"

    def check(self, game: Game) -> Iterator[Diagnostic]:
        for path in game.map_files:
            folder = path.parent.name
            if path.stem.lower() == folder.lower():
                continue
            yield Diagnostic(
                code=self.code,
                message=(
                    f"Layout file {path.name!r} does not match its folder {folder!r}; the "
                    f"engine loads {folder}/{folder}{path.suffix} by folder name, so this file "
                    f"is never loaded."
                ),
                span=Span(str(path), 1, 1),
                severity=Severity.WARNING,
                extra={"file": path.name, "folder": folder},
            )
