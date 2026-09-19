"""The game's art as the 3D view needs it: textures as pixels, and a model's FX shader material.

Both are read through an art index (`models.ArtIndex`: `find_texture`, `find_model`) the first
time they are asked for and kept, because a view asks for the same water, road or model texture
every frame. Anything missing or unreadable answers None, so a view without game data, or with a
texture it cannot decode, still draws.
"""

from __future__ import annotations

import numpy as np

from sage_w3d.render.textures import decode_texture

__all__ = ["ArtTextures", "fx_material"]


def fx_material(model: object) -> dict[str, object] | None:
    """The properties of the first FX shader material in a W3D model's meshes, by lower-case name,
    or None when it has none."""
    for mesh in getattr(model, "meshes", None) or []:
        materials = getattr(mesh, "shader_materials", None)
        for material in getattr(materials, "chunks", None) or []:
            properties = getattr(material, "properties", None)
            if properties:
                return {prop.name.lower(): prop.value for prop in properties}
    return None


class ArtTextures:
    """Textures and FX materials read through an art index and kept. A texture is RGBA pixels,
    bottom row first as OpenGL takes them; None where missing or unreadable."""

    def __init__(self, art: object) -> None:
        self.art = art
        self._textures: dict[str, np.ndarray | None] = {}
        self._materials: dict[str, dict[str, object] | None] = {}

    def texture(self, name: str) -> np.ndarray | None:
        key = name.lower()
        if key not in self._textures:
            self._textures[key] = self._read_texture(name)
        return self._textures[key]

    def material(self, name: str) -> dict[str, object] | None:
        key = name.lower()
        if key not in self._materials:
            try:
                model = self.art.find_model(name) if name else None  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - an unreadable model draws without its material
                model = None
            self._materials[key] = fx_material(model) if model is not None else None
        return self._materials[key]

    def _read_texture(self, name: str) -> np.ndarray | None:
        data = self.art.find_texture(name)  # type: ignore[attr-defined]
        if data is None:
            return None
        try:
            width, height, rgba = decode_texture(data)
        except (ImportError, OSError, ValueError):
            return None
        if not (width and height):
            return None
        pixels = np.frombuffer(rgba, dtype=np.uint8).reshape(height, width, 4)
        return np.ascontiguousarray(pixels[::-1])
