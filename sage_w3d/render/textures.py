"""Texture decoding for the W3D viewport: turns raw image bytes (`.dds`, `.tga`, or anything
Pillow recognizes) into a flat RGBA buffer ready for `glTexImage2D`. Pillow is imported lazily
inside `decode_texture` (CONVENTIONS.md rule 3), so importing this module carries no extra
dependency - only calling the function does, and it names the `w3d-view` extra on failure."""

import io

__all__ = ["decode_texture"]


def decode_texture(data: bytes) -> tuple[int, int, bytes]:
    """Decode `data` to `(width, height, rgba_bytes)`, rows top-to-bottom as Pillow gives them;
    `viewport.py` flips it at upload time for OpenGL's bottom-to-top texture convention."""
    try:
        from PIL import Image  # noqa: PLC0415 - lazy: needs the `w3d-view` extra (pillow)
    except ImportError as exc:
        raise ImportError(
            "decode_texture needs Pillow - install the 'w3d-view' extra: "
            'pip install "pysage-tools[w3d-view]"'
        ) from exc

    image = Image.open(io.BytesIO(data)).convert("RGBA")
    return image.width, image.height, image.tobytes()
