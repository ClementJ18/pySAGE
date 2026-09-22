"""View > Set LOD: which detail tier `GameLODManager` reports as the current model LOD, and
the fallback and comparison that flow from it into which draw modules the 3D view shows.

WorldBuilder's five Set LOD menu entries (`worldbuilder.exe` 0x00664B80-0x00664C00, WorldBuilder
command ids 33419-33423) each call one setter (0x00664D60) with a static LOD level (an engine
name array at 0x0222EEA4: VeryLow=0, Low=1, Medium=2, High=3, UltraHigh=4). The setter calls
`GameLODManager::setStaticLODLevel` (0x00B30020) -> `applyStaticLODLevel` (0x00B30070), which
indexes an array of `StaticGameLOD` buckets by that level and copies bucket offset 0x00,
`ModelLOD`, into `GameLODManager::m_currentModelLOD` (+0x1774). `sage_ini`'s
`StaticGameLOD.ModelLOD` is that same field, keyed by level name (`gamelod.ini`'s
`StaticGameLOD = VeryLow` / `Low` / `Medium` / `High` / `UltraHigh` blocks) - which is why
`current_model_lod` reads it out of the game data rather than assuming the level names its own
`ModelLOD` (the `VeryLow` bucket's `ModelLOD` is `Low` in the shipped data).

A drawable's construction (0x00CB925E) then skips a draw module whose `MinLODRequired` outranks
`m_currentModelLOD`, so this is the whole visible effect of the menu: the object is unchanged,
one or more of its `Draw` modules is just never built. `ModelLOD` and `MinLODRequired` share a
name array, at 0x0222EEBC, that does *not* run in `LodLevel`'s own member order:
`Low=0, Medium=1, High=2, UltraHigh=3, VeryLow=4` - VeryLow sorts last. `_RANK` reproduces that
array verbatim rather than the enum's ordinal, since it is what the engine's `>` comparison
actually runs on: parity here is by the numbers, not by eye.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sage_ini.model.enums import LodLevel

if TYPE_CHECKING:
    from sage_ini.model.game import Game

__all__ = ["DEFAULT_LOD_LEVEL", "current_model_lod", "draw_is_visible"]

# View > Set LOD's own default, and current_model_lod's fallback with no game data, no
# StaticGameLOD bucket for the level, or a bucket that names no ModelLOD: today's behaviour,
# where every draw module is built.
DEFAULT_LOD_LEVEL = LodLevel.UltraHigh

# 0x0222EEBC: the name array both ModelLOD and MinLODRequired are parsed through.
_RANK = {
    LodLevel.Low: 0,
    LodLevel.Medium: 1,
    LodLevel.High: 2,
    LodLevel.UltraHigh: 3,
    LodLevel.VeryLow: 4,
}


def current_model_lod(game: Game | None, level: LodLevel) -> LodLevel:
    """The `ModelLOD` the `StaticGameLOD` bucket named after `level` gives, or `DEFAULT_LOD_LEVEL`
    with no game, no bucket of that name, or a bucket whose `ModelLOD` the engine's own order has
    no rank for (including no `ModelLOD` at all). `getattr` throughout
    so a minimal test double standing in for `Game` (no `tables`) falls back the same way."""
    tables = getattr(game, "tables", None)
    bucket = tables.get("staticgamelods", {}).get(level.name) if tables is not None else None
    lod = getattr(bucket, "ModelLOD", None)
    # A member the engine's own array has no place for - `Off`, which only the shadow and decal
    # buckets take - has nothing to compare against, so it falls back rather than ranking below
    # every draw and emptying the view.
    return lod if isinstance(lod, LodLevel) and lod in _RANK else DEFAULT_LOD_LEVEL


def draw_is_visible(min_lod_required: object, model_lod: LodLevel) -> bool:
    """Whether a draw module whose `MinLODRequired` is `min_lod_required` is built at
    `model_lod` (`0x00CB925E`): always, when the field is unset (or not a `LodLevel` at all),
    else only when it does not outrank `model_lod` in the engine's own order (`_RANK`)."""
    if not isinstance(min_lod_required, LodLevel):
        return True
    return _RANK.get(min_lod_required, -1) <= _RANK.get(model_lod, -1)
