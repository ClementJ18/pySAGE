"""Rules that a referenced model/texture is listed in a provided `asset.dat`.

The SAGE engine never opens art off disk directly: it looks a model or texture up by name in
`asset.dat`, the binary cache index the asset cache builder generates from the source art tree
(see `sage_asset`). A file that sits in the mod's art folder but never made it into the mod's
asset.dat - a cache builder that was not rerun after adding it, an entry dropped by a bad
combine - is invisible in game: the engine's lookup finds no such name and whatever field named
it silently fails to load, even though the file is genuinely there on disk. The on-disk
missing-file rules in `sage_lint.rules.assets` cannot catch this, since the file *does* exist;
these rules check the other half of the pipeline, membership in the cache the engine actually
reads.

`AssetDatMissingModelRule` (`asset-dat-missing-model`) and `AssetDatMissingTextureRule`
(`asset-dat-missing-texture`) walk the same typed model/texture fields as the on-disk rules -
`sage_ini.walk.walk_asset_fields`, plus `_normalize` from `sage_lint.rules.assets` - and check each
referenced name's stem against `game.asset_dat_names`, the lower-cased file-entry basenames read
out of every `asset.dat` given to the linter (see `sage_lint.commands.lint`, `--asset-dat`). A
normally-built asset.dat always names a texture entry `stem.tga`, even when the source was a
`.dds`, but a hand-built or hand-edited one may index the `.dds` name directly, so both
extensions are accepted, mirroring the on-disk rule's tolerance. Maps are deliberately not
covered here: a `.map`/`.bse` layout is loaded by folder name straight off disk and is never
indexed in asset.dat.

Both rules are **opt-in** (`default = False`), part of the asset group `--assets` turns on
(`assets = True`), and stay silent when `game.asset_dat_names` is empty - no `--asset-dat` was
given, so there is nothing to check membership against and flagging every reference would only
be noise."""

from collections.abc import Iterator

from sage_ini.model.game import Game
from sage_ini.model.types import _AssetFile, _ModelFile, _TextureFile
from sage_ini.parser.diagnostics import Diagnostic, Severity
from sage_ini.walk import walk_asset_fields
from sage_lint.rules.assets import _normalize
from sage_lint.rules.base import Rule


class _AssetDatMissingRule(Rule):
    """Shared base for the two asset.dat-membership rules: a field naming a model or texture
    that no provided asset.dat lists, so the engine's lookup finds nothing and whatever the
    field drives silently fails to load in game - regardless of whether the file exists on
    disk. Silent when `game.asset_dat_names` is empty (no `--asset-dat` given); concrete
    subclasses set the `_AssetFile` kind and its message noun."""

    code = ""  # base does not register; each concrete subclass sets its own code
    default = False  # opt-in: skipped by a plain run, enabled by --assets/--select
    assets = True  # part of the asset group --assets turns on
    asset_class: type[_AssetFile]
    noun: str

    def check(self, game: Game) -> Iterator[Diagnostic]:
        if not game.asset_dat_names:
            return  # no --asset-dat given: nothing to check membership against
        for obj, key, asset_cls, raw in walk_asset_fields(game):
            if asset_cls is not self.asset_class:
                continue
            name = _normalize(raw)
            if not name or name == "none" or name.startswith("<"):
                continue  # engine sentinels: NONE, <ANY>, <THIS_PLAYER>, ...
            extensions = asset_cls.extensions
            # Same interchangeable-extension resolution as the on-disk rule: strip whichever
            # expected extension the value already carries down to the stem, then accept a
            # file entry under any of the kind's extensions rather than the exact one written.
            stem = name
            for ext in extensions:
                if name.endswith(ext):
                    stem = name[: -len(ext)]
                    break
            if any(stem + ext in game.asset_dat_names for ext in extensions):
                continue
            kinds = " or ".join(extensions)
            shown = raw.strip().strip('"')  # the source value, minus the quotes a spaced name needs
            yield Diagnostic(
                code=self.code,
                message=(
                    f"{type(obj).__name__}.{key} references {shown!r}, but no {self.noun} "
                    f"({kinds}) by that name is listed in any provided asset.dat; the mod's "
                    f"asset.dat may need rebuilding to include it."
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


class AssetDatMissingModelRule(_AssetDatMissingRule):
    """A model field naming a `.w3d` no provided asset.dat lists."""

    code = "asset-dat-missing-model"
    asset_class = _ModelFile
    noun = "model"


class AssetDatMissingTextureRule(_AssetDatMissingRule):
    """A texture field naming a `.tga`/`.dds` no provided asset.dat lists."""

    code = "asset-dat-missing-texture"
    asset_class = _TextureFile
    noun = "texture"
