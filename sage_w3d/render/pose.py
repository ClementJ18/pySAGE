"""Animation playback for a resolved `Hierarchy`: `PoseEvaluator` normalizes every channel kind
`sage_w3d.animation`/`sage_w3d.compressed_animation` model (uncompressed, time-coded,
adaptive-delta, motion) into a uniform set of per-pivot tracks, then samples them at any frame
into a flat `Pose` of world matrices ready to re-skin a `Scene`'s meshes.

**Channel values are deltas, not absolute local transforms.** Measured across 102 real
skeleton/animation pairs (translation channels, types 0/1/2), 81 read as deltas from the rest
pose against 21 that could be read as absolute - decisively so on cases like `B_PELVIS` in
`chwz_yw_u_atnc.w3d`: its rest Z is +13.263, its channel's constant value -0.316; absolute would
put the pelvis at ankle height, delta keeps it at hip height. Quaternion channels (type 6),
measured across 127 idle-animation pivots with strongly rotated rests, compose on top of the
rest rotation 118 times against 9 that looked like outright replacement - frame-0 quats
overwhelmingly sit at identity, not at the rest quaternion. Both results feed the same
composition rule, taken from the released Renegade W3D engine source (`ww3d2/htree.cpp`):

    world(pivot, f) = world(parent, f) . T(rest_t) . R(rest_q) . T(anim_t(f)) . R(anim_q(f))

i.e. the rest local matrix (`pivot_local_matrix` - translation then rotation), with the
animation's translation delta and quaternion post-multiplied on top; see `_animated_local`'s own
docstring for the one alternative composition order worth knowing about if this one is ever
visually wrong. A pivot with no channel at all uses `anim_t = (0, 0, 0)`, `anim_q = (0, 0, 0, 1)`
- the identity element of this composition, so its world matrix is exactly the rest one.

Every channel kind normalizes into the same per-pivot shape: up to three scalar translation
tracks (one per axis), one quaternion rotation track, and one boolean visibility track, each a
sorted list of `(frame, value, step)` keys. Sampling clamps outside the first/last key, linearly
interpolates scalars between them, and normalized-lerps quaternions with a hemisphere check
(`_quat_nlerp`'s docstring explains why nlerp, not slerp, is enough here). A `step` key holds the
previous key's value right up until its own frame, then jumps - the semantics
`TimeCodedDatum.interpolated`'s raw bit encodes (`W3D_TIMECODED_BINARY_MOVEMENT` in the original
format: set means step into this key, not "this key is interpolated" despite the field's name).
Visibility comes in two on-disk forms, reduced to one boolean per pivot per frame: the bit
channels (a packed bit or sparse step keys - see `_VisibilityTrack`) and the BFME-era float
visibility channel (type 15), a scalar track like any translation axis - constant 1.0 on
always-visible bones, +-1.0 on/off switches, or a genuine 0..1 fade ramp - sampled with the
same lerp machinery and thresholded at `_VISIBILITY_THRESHOLD`, so a fade flips exactly where
it crosses the midpoint. Real exporters routinely write both forms for the same pivot (the bit
form is the float ramp thresholded; every measured real pair encodes the same timeline), so
the float form silently outranks the bit form rather than being diagnosed as a duplicate."""

import bisect
import math
from dataclasses import dataclass, field

from sage_w3d.animation import (
    Animation,
    AnimationBitChannel,
    AnimationChannel,
    AnimationHeader,
)
from sage_w3d.compressed_animation import (
    AdaptiveDeltaAnimationChannel,
    CompressedAnimation,
    CompressedAnimationHeader,
    MotionAdaptiveDeltaData,
    MotionChannel,
    MotionTimeCodedData,
    TimeCodedAnimationChannel,
    TimeCodedBitChannel,
)
from sage_w3d.hierarchy import Hierarchy, HierarchyPivot
from sage_w3d.render.math3d import Mat4, Vec3, multiply, pivot_local_matrix

__all__ = ["AnimationSource", "Pose", "PoseEvaluator"]

AnimationSource = Animation | CompressedAnimation

# Channel types this corpus actually carries: 0/1/2 = translation X/Y/Z, 6 = quaternion, and
# 15 = the BFME-era float visibility channel (a scalar per frame - constant 1.0 on
# always-visible bones, +-1.0 on/off switches on e.g. projectiles, and genuine 0..1 fade ramps;
# 45k instances across 2149 real files). 3/4/5 (Euler rotation) never occur in this corpus;
# a channel claiming one is diagnosed and skipped rather than guessed at.
_TRANSLATION_CHANNEL_TYPES = (0, 1, 2)
_ROTATION_CHANNEL_TYPE = 6
_VISIBILITY_CHANNEL_TYPE = 15
_UNSUPPORTED_CHANNEL_TYPES = (3, 4, 5)
_AXIS_NAMES = ("translation.x", "translation.y", "translation.z")

# A sampled float visibility at or above this renders the pivot visible - the same 0.5 midpoint
# `_ingest_animation_bit_channel` applies to a bit channel's byte default. The game engine
# alpha-blends fractional values instead of thresholding; a boolean visible/hidden is this
# viewer's honest reduction of that.
_VISIBILITY_THRESHOLD = 0.5

_Quat = tuple[float, float, float, float]
_ChannelValue = float | _Quat


@dataclass
class Pose:
    """One evaluated frame: `world_matrices[i]` and `pivot_visible[i]` are pivot `i`'s world
    matrix and visibility, index-aligned with `Hierarchy.pivots` (and so with `Scene.bones`).
    `pivot_visible` is `True` for every pivot the animation source carries no visibility
    channel (bit or float) for - "unanimated" means "always visible", not "hidden"."""

    world_matrices: list[Mat4]
    pivot_visible: list[bool]


def _animated_local(pivot: HierarchyPivot, translation: Vec3, rotation: _Quat) -> Mat4:
    """One pivot's local transform under animation: its rest local matrix (`pivot_local_matrix`,
    translation-then-rotation) with the animation's translation delta and quaternion
    post-multiplied on top - `T(rest_t) . R(rest_q) . T(anim_t) . R(anim_q)`, matching the
    released Renegade W3D engine's composition order (see this module's docstring for the
    corpus evidence behind it). OpenSAGE instead composes the translation delta in the parent
    frame, `T(rest_t + anim_t) . R(rest_q * anim_q)`; if visual verification ever disagrees with
    the choice made here, swapping to that alternative is a one-line change to this function."""
    rest = pivot_local_matrix(pivot.translation, pivot.rotation)
    anim = pivot_local_matrix(translation, rotation)
    return multiply(rest, anim)


def _quat_nlerp(a: _Quat, b: _Quat, t: float) -> _Quat:
    """Normalized linear interpolation from `a` to `b`, negating `b` first if it sits in the
    opposite quaternion hemisphere (`dot(a, b) < 0`) - the same rotation can be stored as `q` or
    `-q`, and a plain lerp between a hemisphere-mismatched pair swings the long way around
    instead of taking the short path. True spherical interpolation (slerp) is not needed: real
    animation keys are at most a frame apart, where nlerp is visually indistinguishable from
    slerp and considerably cheaper."""
    if a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3] < 0:
        b = (-b[0], -b[1], -b[2], -b[3])
    x = a[0] + (b[0] - a[0]) * t
    y = a[1] + (b[1] - a[1]) * t
    z = a[2] + (b[2] - a[2]) * t
    w = a[3] + (b[3] - a[3]) * t
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if length == 0.0:
        return (0.0, 0.0, 0.0, 1.0)
    return (x / length, y / length, z / length, w / length)


@dataclass
class _ScalarKey:
    frame: float
    value: float
    step: bool


@dataclass
class _QuatKey:
    frame: float
    value: _Quat
    step: bool


def _sample_scalar(keys: list[_ScalarKey], frame: float) -> float:
    """`0.0` (the identity translation delta) with no keys at all; otherwise clamps outside the
    first/last key and linearly interpolates (or, for a step key, holds the earlier key's value
    until the step key's own frame) between the bracketing pair."""
    if not keys:
        return 0.0
    if frame <= keys[0].frame:
        return keys[0].value
    if frame >= keys[-1].frame:
        return keys[-1].value
    idx = bisect.bisect_right(keys, frame, key=lambda k: k.frame)
    a, b = keys[idx - 1], keys[idx]
    if b.step:
        return a.value
    t = (frame - a.frame) / (b.frame - a.frame)
    return a.value + (b.value - a.value) * t


def _sample_quat(keys: list[_QuatKey], frame: float) -> _Quat:
    """`(0, 0, 0, 1)` (the identity rotation delta) with no keys at all; otherwise clamps outside
    the first/last key and nlerps (or, for a step key, holds) between the bracketing pair - see
    `_sample_scalar` for the shared clamp/step shape and `_quat_nlerp` for the blend itself."""
    if not keys:
        return (0.0, 0.0, 0.0, 1.0)
    if frame <= keys[0].frame:
        return keys[0].value
    if frame >= keys[-1].frame:
        return keys[-1].value
    idx = bisect.bisect_right(keys, frame, key=lambda k: k.frame)
    a, b = keys[idx - 1], keys[idx]
    if b.step:
        return a.value
    t = (frame - a.frame) / (b.frame - a.frame)
    return _quat_nlerp(a.value, b.value, t)


@dataclass
class _VisibilityTrack:
    """A pivot's bit-channel visibility: `frames`/`values` are parallel and sorted, one entry per
    recorded sample (every integer frame in `[first_frame, last_frame]` for a dense
    `AnimationBitChannel`; one per explicit time code for a sparse `TimeCodedBitChannel`).
    `default_before`/`default_after` are the value used strictly outside the recorded range -
    for `AnimationBitChannel` both equal `.default`, since the format defines an explicit
    out-of-range default on both sides; for `TimeCodedBitChannel` only `default_before` does
    (`bool(default_value)`, the state before the first explicit key), and `default_after` is
    just the last key's value, since a step function has nothing to revert to once it ends."""

    frames: list[int]
    values: list[bool]
    default_before: bool
    default_after: bool

    def sample(self, frame: float) -> bool:
        if not self.frames:
            return True
        f = round(frame)
        if f < self.frames[0]:
            return self.default_before
        if f > self.frames[-1]:
            return self.default_after
        idx = bisect.bisect_right(self.frames, f) - 1
        return self.values[idx]


@dataclass
class _PivotTracks:
    """`visibility` holds a bit channel's step samples; `visibility_scalar` holds a type-15
    float channel's keys, sampled like any scalar track (so a fade ramp flips exactly where it
    crosses `_VISIBILITY_THRESHOLD`, not at a key boundary) and thresholded at evaluate time.
    At most one of the two is ever populated: a float channel silently displaces (or
    preempts) a bit channel for the same pivot - see `_store_scalar` - so `visibility` only
    survives on pivots with no float channel at all."""

    translation: list[list[_ScalarKey]] = field(default_factory=lambda: [[], [], []])
    rotation: list[_QuatKey] = field(default_factory=list)
    visibility: _VisibilityTrack | None = None
    visibility_scalar: list[_ScalarKey] = field(default_factory=list)


def _as_float(value: _ChannelValue) -> float:
    assert isinstance(value, int | float)
    return float(value)


def _as_quat(value: _ChannelValue) -> _Quat:
    assert isinstance(value, tuple)
    return value


class PoseEvaluator:
    """Normalizes one `AnimationSource` (an uncompressed `Animation` or a `CompressedAnimation`
    of any flavor) against `hierarchy` into per-pivot tracks at construction time, then samples
    them into a `Pose` on every `evaluate(frame)` call - the per-frame cost is one left-to-right
    pass over the pivot list plus a key-bracket search per animated component, no re-parsing."""

    def __init__(self, hierarchy: Hierarchy, animation: AnimationSource) -> None:
        self._pivots = hierarchy.pivots
        self._parent_ids = [p.parent_id for p in self._pivots]
        self._tracks: list[_PivotTracks] = [_PivotTracks() for _ in self._pivots]
        self._seen: set[tuple[int, str]] = set()
        self.diagnostics: list[str] = []

        header = animation.header
        self._header: AnimationHeader | CompressedAnimationHeader | None = header
        if header is None:
            self.diagnostics.append("animation has no header chunk; name/frames/rate default")
        else:
            anim_name = header.hierarchy_name.value
            hierarchy_name = hierarchy.name
            if anim_name and hierarchy_name and anim_name.lower() != hierarchy_name.lower():
                self.diagnostics.append(
                    f"animation hierarchy name {anim_name!r} does not match "
                    f"skeleton name {hierarchy_name!r}"
                )

        if isinstance(animation, Animation):
            self._ingest_uncompressed(animation)
        else:
            self._ingest_compressed(animation)

    @property
    def name(self) -> str:
        return self._header.name.value if self._header is not None else ""

    @property
    def num_frames(self) -> int:
        return self._header.num_frames if self._header is not None else 0

    @property
    def frame_rate(self) -> float:
        return float(self._header.frame_rate) if self._header is not None else 0.0

    def evaluate(self, frame: float) -> Pose:
        """`Pose` at `frame` (fractional frames sample between keys): one left-to-right pass
        exactly like `scene._pivot_world_matrices`, except a pivot carrying a track composes its
        sampled translation/rotation on top of the rest local matrix (`_animated_local`) instead
        of using the rest local matrix outright - a pivot with no track at all takes the
        rest-matrix branch directly, so it is bit-identical to the static-pose renderer."""
        worlds: list[Mat4] = []
        visible: list[bool] = []
        for i, pivot in enumerate(self._pivots):
            tracks = self._tracks[i]
            if tracks.rotation or any(tracks.translation):
                t = (
                    _sample_scalar(tracks.translation[0], frame),
                    _sample_scalar(tracks.translation[1], frame),
                    _sample_scalar(tracks.translation[2], frame),
                )
                q = _sample_quat(tracks.rotation, frame)
                local = _animated_local(pivot, t, q)
            else:
                local = pivot_local_matrix(pivot.translation, pivot.rotation)
            parent = self._parent_ids[i]
            worlds.append(multiply(worlds[parent], local) if 0 <= parent < len(worlds) else local)
            if tracks.visibility_scalar:
                visible.append(
                    _sample_scalar(tracks.visibility_scalar, frame) >= _VISIBILITY_THRESHOLD
                )
            elif tracks.visibility is not None:
                visible.append(tracks.visibility.sample(frame))
            else:
                visible.append(True)
        return Pose(world_matrices=worlds, pivot_visible=visible)

    def _pivot_in_range(self, pivot: int, source: str) -> bool:
        if not (0 <= pivot < len(self._pivots)):
            self.diagnostics.append(
                f"{source}: pivot index {pivot} out of range (0..{len(self._pivots) - 1})"
            )
            return False
        return True

    def _claim(self, pivot: int, component: str, source: str) -> bool:
        """`True` the first time `(pivot, component)` is claimed by a channel; a later duplicate
        is diagnosed and its data ignored, so the first channel for a given pivot/component
        wins."""
        key = (pivot, component)
        if key in self._seen:
            self.diagnostics.append(f"{source}: duplicate {component} channel for pivot {pivot}")
            return False
        self._seen.add(key)
        return True

    def _unsupported_channel_type(self, pivot: int, channel_type: int, source: str) -> None:
        if channel_type in _UNSUPPORTED_CHANNEL_TYPES:
            self.diagnostics.append(
                f"{source}: pivot {pivot} uses an Euler rotation channel (type {channel_type}), "
                "not supported - skipped"
            )
        else:
            self.diagnostics.append(
                f"{source}: pivot {pivot} uses an unrecognized channel type {channel_type} - "
                "skipped"
            )

    def _store_scalar(
        self, pivot: int, channel_type: int, keys: list[_ScalarKey], source: str
    ) -> bool:
        """Stores an already-built scalar key list on the track `channel_type` names - a
        translation axis (0/1/2) or the float visibility channel (15). `False` when
        `channel_type` is neither (the caller diagnoses it) or the component is already
        claimed."""
        if channel_type in _TRANSLATION_CHANNEL_TYPES:
            if not self._claim(pivot, _AXIS_NAMES[channel_type], source):
                return True
            self._tracks[pivot].translation[channel_type] = keys
            return True
        if channel_type == _VISIBILITY_CHANNEL_TYPE:
            if not self._claim(pivot, "visibility.float", source):
                return True
            # A float channel outranks a bit channel for the same pivot, silently and in either
            # arrival order: real exporters write both (the bit form is the float ramp
            # thresholded - every measured pair encodes the same timeline), and the float form
            # carries the fade detail the bit form flattens.
            tracks = self._tracks[pivot]
            tracks.visibility = None
            tracks.visibility_scalar = keys
            return True
        return False

    def _store_dense(
        self, pivot: int, channel_type: int, values: list[_ChannelValue], source: str
    ) -> None:
        """Stores one channel's already-per-frame values (frames `0..len(values) - 1`, no
        stepping) - the shape a decoded adaptive-delta channel (plain or motion) produces."""
        if channel_type == _ROTATION_CHANNEL_TYPE:
            if not self._claim(pivot, "rotation", source):
                return
            self._tracks[pivot].rotation = [
                _QuatKey(float(i), _as_quat(v), step=False) for i, v in enumerate(values)
            ]
            return
        keys = [_ScalarKey(float(i), _as_float(v), step=False) for i, v in enumerate(values)]
        if not self._store_scalar(pivot, channel_type, keys, source):
            self._unsupported_channel_type(pivot, channel_type, source)

    # -- uncompressed ANIMATION -------------------------------------------------------------

    def _ingest_uncompressed(self, animation: Animation) -> None:
        for channel in animation.channels:
            self._ingest_animation_channel(channel)
        for bit_channel in animation.bit_channels:
            self._ingest_animation_bit_channel(bit_channel)

    def _ingest_animation_channel(self, channel: AnimationChannel) -> None:
        source = "ANIMATION_CHANNEL"
        pivot = channel.pivot
        if not self._pivot_in_range(pivot, source):
            return
        channel_type = channel.channel_type
        if channel_type == _ROTATION_CHANNEL_TYPE:
            if not self._claim(pivot, "rotation", source):
                return
            self._tracks[pivot].rotation = [
                _QuatKey(float(channel.first_frame + i), (v[0], v[1], v[2], v[3]), step=False)
                for i, v in enumerate(channel.values)
            ]
            return
        keys = [
            _ScalarKey(float(channel.first_frame + i), v[0], step=False)
            for i, v in enumerate(channel.values)
        ]
        if not self._store_scalar(pivot, channel_type, keys, source):
            self._unsupported_channel_type(pivot, channel_type, source)

    def _ingest_animation_bit_channel(self, channel: AnimationBitChannel) -> None:
        source = "ANIMATION_BIT_CHANNEL"
        pivot = channel.pivot
        if not self._pivot_in_range(pivot, source):
            return
        if (pivot, "visibility.float") in self._seen:
            return  # the pivot's float visibility channel outranks this - see `_store_scalar`
        if not self._claim(pivot, "visibility.bit", source):
            return
        default = channel.default >= 0.5
        self._tracks[pivot].visibility = _VisibilityTrack(
            frames=list(range(channel.first_frame, channel.last_frame + 1)),
            values=channel.values,
            default_before=default,
            default_after=default,
        )

    # -- COMPRESSED_ANIMATION ----------------------------------------------------------------

    def _ingest_compressed(self, animation: CompressedAnimation) -> None:
        for time_coded in animation.time_coded_channels:
            self._ingest_time_coded_channel(time_coded)
        for adaptive_delta_channel in animation.adaptive_delta_channels:
            self._ingest_adaptive_delta_channel(adaptive_delta_channel)
        for bit_channel in animation.bit_channels:
            self._ingest_time_coded_bit_channel(bit_channel)
        for motion in animation.motion_channels:
            self._ingest_motion_channel(motion)

    def _ingest_time_coded_channel(self, channel: TimeCodedAnimationChannel) -> None:
        # Bit 31 of a time-coded datum's raw time code (`.interpolated`) means "step into this
        # key" (`W3D_TIMECODED_BINARY_MOVEMENT`), not "this key is interpolated" - the dataclass
        # field name is kept as-is (public API) and just read with step semantics here.
        source = "COMPRESSED_ANIMATION_CHANNEL"
        pivot = channel.pivot
        if not self._pivot_in_range(pivot, source):
            return
        channel_type = channel.channel_type
        if channel_type == _ROTATION_CHANNEL_TYPE:
            if not self._claim(pivot, "rotation", source):
                return
            quat_keys = [
                _QuatKey(float(d.time_code), _as_quat(d.value), step=d.interpolated)
                for d in channel.data
            ]
            quat_keys.sort(key=lambda k: k.frame)
            self._tracks[pivot].rotation = quat_keys
            return
        keys = [
            _ScalarKey(float(d.time_code), _as_float(d.value), step=d.interpolated)
            for d in channel.data
        ]
        keys.sort(key=lambda k: k.frame)
        if not self._store_scalar(pivot, channel_type, keys, source):
            self._unsupported_channel_type(pivot, channel_type, source)

    def _ingest_adaptive_delta_channel(self, channel: AdaptiveDeltaAnimationChannel) -> None:
        source = "COMPRESSED_ANIMATION_CHANNEL(adaptive-delta)"
        pivot = channel.pivot
        if not self._pivot_in_range(pivot, source):
            return
        values = channel.data.decode(
            channel.channel_type, channel.vector_len, channel.num_time_codes, channel.scale
        )
        self._store_dense(pivot, channel.channel_type, values, source)

    def _ingest_time_coded_bit_channel(self, channel: TimeCodedBitChannel) -> None:
        source = "COMPRESSED_BIT_CHANNEL"
        pivot = channel.pivot
        if not self._pivot_in_range(pivot, source):
            return
        if (pivot, "visibility.float") in self._seen:
            return  # the pivot's float visibility channel outranks this - see `_store_scalar`
        if not self._claim(pivot, "visibility.bit", source):
            return
        ordered = sorted(channel.data, key=lambda d: d.time_code)
        frames = [d.time_code for d in ordered]
        values = [d.value for d in ordered]
        default_before = bool(channel.default_value)
        self._tracks[pivot].visibility = _VisibilityTrack(
            frames=frames,
            values=values,
            default_before=default_before,
            default_after=values[-1] if values else default_before,
        )

    def _ingest_motion_channel(self, channel: MotionChannel) -> None:
        source = "COMPRESSED_ANIMATION_MOTION_CHANNEL"
        pivot = channel.pivot
        if not self._pivot_in_range(pivot, source):
            return
        channel_type = channel.channel_type
        body = channel.body
        if isinstance(body, MotionTimeCodedData):
            if channel_type == _ROTATION_CHANNEL_TYPE:
                if not self._claim(pivot, "rotation", source):
                    return
                quat_keys = [
                    _QuatKey(float(d.time_code), _as_quat(d.value), step=False) for d in body.data
                ]
                quat_keys.sort(key=lambda k: k.frame)
                self._tracks[pivot].rotation = quat_keys
                return
            keys = [
                _ScalarKey(float(d.time_code), _as_float(d.value), step=False) for d in body.data
            ]
            keys.sort(key=lambda k: k.frame)
            if not self._store_scalar(pivot, channel_type, keys, source):
                self._unsupported_channel_type(pivot, channel_type, source)
        else:
            assert isinstance(body, MotionAdaptiveDeltaData)
            values = body.data.decode(
                channel_type,
                channel.vector_len,
                channel.num_time_codes,
                body.scale,
                bit_count=channel.delta_type * 4,
            )
            self._store_dense(pivot, channel_type, values, source)
