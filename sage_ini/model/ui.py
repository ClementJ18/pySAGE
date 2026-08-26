"""UI sub-blocks. A `WindowTransition` scripts a sequence of `Window` fades; `InGameUI`
declares `RadiusCursorTemplate` ground cursors. Collected via `nested_attributes` on those
data blocks. Percentage and `R:G:B:A:` values are kept as raw strings (no converter yet)."""

import sage_ini.model.enums as e
import sage_ini.model.types as t
from sage_ini.model.objects import NestedAttribute


class Transition(NestedAttribute):
    """A `Transition = <type>` block inside a `Window`: the frames a fade spans and which
    views it affects, keyed by the transition type (`WINFADE`, `SOUNDFADE`, ...)."""

    keyed_by_label = True

    StartFrame: t.Int
    EndFrame: t.Int
    ViewsToFade: t.FlagList[e.ViewType]
    LeaveSilent: t.Bool

    # World-map transition variant fields (the same `Transition = <type>` keyword also drives
    # the living-world view fades): the animation played and the fade colour/image.
    AnimationName: t.List[t.Animation]
    AnimationMode: e.AnimationMode
    AnimationBlendTime: t.Int
    AnimationMustCompleteBlend: t.Bool
    AnimationSpeedFactorRange: t.List[t.Float]
    FadeColor: t.RGBA
    FadeImage: t.Opaque
    CrossFadeImage: t.Opaque
    FadeInUnfrozenSounds: t.Bool


class Window(NestedAttribute):
    """One window in a `WindowTransition`: which `.wnd` control fades and over how many
    frames; the fade itself is a nested `Transition` block."""

    nested_attributes = {"Transition": ["Transition"]}

    WinName: t.Opaque
    FrameDelay: t.Int


class RadiusCursorTemplate(NestedAttribute):
    """A `RadiusCursorTemplate = <name>` ground cursor in `InGameUI`: the decal texture,
    style, opacity envelope and colour shown for a radius-targeted ability."""

    keyed_by_label = True

    Texture: t.TextureFile
    Style: t.FlagList[e.ObjectShadowType]
    OpacityMin: t.Float
    OpacityMax: t.Float
    OpacityThrobTime: t.Int
    Color: t.RGBA
    OnlyVisibleToOwningPlayer: t.Bool
