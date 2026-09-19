"""Extract WorldBuilder's icons, cursors, bitmaps and toolbar buttons from `worldbuilder.exe` into
`sage_worldbuilder/assets/worldbuilder_icons/`.

- `icons/`: each icon group as its original `.ico`, and a `.png` of its largest image that has
  anything drawn in it (some groups carry an empty 32x32 beside a real 16x16).
- `cursors/`: each cursor group as its original `.cur`, and a `.png` with the transparency the
  cursor's mask gives it.
- `bitmaps/`: every bitmap resource as `.png` (the toolbar strips among them).
- `toolbar_buttons/`: the toolbars' strips cut into one `.png` per button, named
  `<toolbar>_<slot>_<command>_<tooltip>.png`, on WorldBuilder's grey button background.
- `toolbars.txt`: each toolbar's slots in order, with the command and tooltip behind each.

    python tools/extract_worldbuilder_icons.py [path/to/worldbuilder.exe] [--out DIR]
"""

from __future__ import annotations

import argparse
import io
import re
import shutil
import struct
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pefile
from extract_worldbuilder_keymap import _string_table
from PIL import Image

__all__ = ["extract_icons"]

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXE = REPO_ROOT / "worldbuilder.exe"
DEFAULT_OUT = REPO_ROOT / "sage_worldbuilder" / "assets" / "worldbuilder_icons"

RT_CURSOR, RT_BITMAP, RT_ICON, RT_GROUP_CURSOR, RT_GROUP_ICON, RT_TOOLBAR = 1, 2, 3, 12, 14, 241
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# A pixel an icon's mask makes screen-inverting has no colour of its own; show it grey.
_INVERTING = (128, 128, 128, 255)


def _resources(pe: pefile.PE, type_id: int) -> Iterator[tuple[int | str, bytes]]:
    """(resource id or name, bytes) for every resource of a type, first language."""
    for resource_type in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if resource_type.id != type_id:
            continue
        for entry in resource_type.directory.entries:
            key = entry.id if entry.id is not None else str(entry.name)
            data = entry.directory.entries[0].data.struct
            yield key, pe.get_data(data.OffsetToData, data.Size)


def _safe(text: object) -> str:
    return re.sub(r"[^\w.-]+", "_", str(text)).strip("_") or "unnamed"


def _group_file(group: bytes, images: dict[int | str, bytes], cursor: bool) -> bytes:
    """An `.ico` / `.cur` file from a group directory resource and the images it names."""
    _reserved, _kind, count = struct.unpack_from("<HHH", group, 0)
    entries, blobs = [], []
    offset = 6 + 16 * count
    for index in range(count):
        base = 6 + index * 14
        if cursor:
            width, height, _planes, _bits, _size, image_id = struct.unpack_from(
                "<HHHHIH", group, base
            )
            blob = images.get(image_id, b"")
            # A cursor resource starts with its hotspot, which the file keeps in its directory.
            hot_x, hot_y = struct.unpack_from("<HH", blob, 0) if len(blob) >= 4 else (0, 0)
            blob = blob[4:]
            entry = struct.pack(
                "<BBBBHHII",
                width & 0xFF,
                (height // 2) & 0xFF,
                0,
                0,
                hot_x,
                hot_y,
                len(blob),
                offset,
            )
        else:
            width, height, colors, _r, planes, bits, _size, image_id = struct.unpack_from(
                "<BBBBHHIH", group, base
            )
            blob = images.get(image_id, b"")
            entry = struct.pack(
                "<BBBBHHII", width, height, colors, 0, planes, bits, len(blob), offset
            )
        entries.append(entry)
        blobs.append(blob)
        offset += len(blob)
    return struct.pack("<HHH", 0, 2 if cursor else 1, count) + b"".join(entries) + b"".join(blobs)


def _file_images(data: bytes) -> Iterator[tuple[tuple[int, int, int], bytes]]:
    """((width, height, bits), image bytes) for each image in an `.ico` / `.cur` file."""
    _reserved, _kind, count = struct.unpack_from("<HHH", data, 0)
    for index in range(count):
        width, height, _c, _r, _a, bits, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * index
        )
        yield (width or 256, height or 256, bits), data[offset : offset + length]


def _decode_dib(dib: bytes) -> Image.Image:
    """An icon or cursor image (a colour bitmap over an AND mask) as RGBA."""
    if dib[:8] == _PNG_SIGNATURE:
        return Image.open(io.BytesIO(dib)).convert("RGBA")
    header_size, width, double_height, _planes, bits = struct.unpack_from("<IiiHH", dib, 0)
    height = abs(double_height) // 2
    colors = struct.unpack_from("<I", dib, 32)[0] or (1 << bits if bits <= 8 else 0)
    palette = [struct.unpack_from("<BBBB", dib, header_size + 4 * i) for i in range(colors)]
    start = header_size + 4 * colors
    row_bytes = ((width * bits + 31) // 32) * 4
    mask_bytes = ((width + 31) // 32) * 4
    pixels = dib[start : start + row_bytes * height]
    mask = dib[start + row_bytes * height : start + row_bytes * height + mask_bytes * height]
    image = Image.new("RGBA", (width, height))
    for y in range(height):
        row = pixels[(height - 1 - y) * row_bytes : (height - y) * row_bytes]
        mask_row = mask[(height - 1 - y) * mask_bytes : (height - y) * mask_bytes]
        for x in range(width):
            if bits == 1:
                blue, green, red, _ = palette[(row[x // 8] >> (7 - x % 8)) & 1]
            elif bits == 4:
                blue, green, red, _ = palette[(row[x // 2] >> (4 if x % 2 == 0 else 0)) & 0xF]
            elif bits == 8:
                blue, green, red, _ = palette[row[x]]
            else:
                step = bits // 8
                blue, green, red = row[x * step : x * step + 3]
            masked = bool(mask_row) and (mask_row[x // 8] >> (7 - x % 8)) & 1
            if bits == 32 and not any(mask):
                pixel = (red, green, blue, row[x * 4 + 3])
            elif masked and (red, green, blue) == (0, 0, 0):
                pixel = (0, 0, 0, 0)
            elif masked:
                pixel = _INVERTING
            else:
                pixel = (red, green, blue, 255)
            image.putpixel((x, y), pixel)
    return image


def _preview(data: bytes) -> Image.Image:
    """The largest image of an icon or cursor file that has anything drawn in it."""
    decoded = [(size, _decode_dib(blob)) for size, blob in _file_images(data) if blob]
    drawn = [(size, image) for size, image in decoded if image.getbbox() is not None]
    candidates = drawn or decoded
    return max(candidates, key=lambda item: (item[0][0] * item[0][1], item[0][2]))[1]


def _dib_file(dib: bytes) -> bytes:
    """A bitmap resource (a DIB without its file header) as a `.bmp` file."""
    header_size = struct.unpack_from("<I", dib, 0)[0]
    bits = struct.unpack_from("<H", dib, 14)[0]
    compression = struct.unpack_from("<I", dib, 16)[0] if header_size >= 40 else 0
    colors = struct.unpack_from("<I", dib, 32)[0] if header_size >= 40 else 0
    if bits <= 8:
        palette = (colors or (1 << bits)) * 4
    elif compression == 3 and header_size == 40:
        palette = 12
    else:
        palette = 0
    pixel_offset = 14 + header_size + palette
    return struct.pack("<2sIHHI", b"BM", 14 + len(dib), 0, 0, pixel_offset) + dib


def extract_icons(exe: Path, out: Path) -> Counter[str]:
    pe = pefile.PE(str(exe), fast_load=True)
    pe.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
    )
    strings = _string_table(pe)
    if out.exists():
        shutil.rmtree(out)
    counts: Counter[str] = Counter()
    for folder in ("icons", "cursors", "bitmaps", "toolbar_buttons"):
        (out / folder).mkdir(parents=True, exist_ok=True)

    for group_type, image_type, folder, suffix, cursor in (
        (RT_GROUP_ICON, RT_ICON, "icons", ".ico", False),
        (RT_GROUP_CURSOR, RT_CURSOR, "cursors", ".cur", True),
    ):
        images = dict(_resources(pe, image_type))
        for key, group in _resources(pe, group_type):
            data = _group_file(group, images, cursor)
            path = out / folder / f"{_safe(key)}{suffix}"
            path.write_bytes(data)
            _preview(data).save(path.with_suffix(".png"))
            counts[folder] += 1

    bitmaps: dict[int | str, Image.Image] = {}
    for key, dib in _resources(pe, RT_BITMAP):
        with Image.open(io.BytesIO(_dib_file(dib))) as image:
            bitmap = image.convert("RGBA")
        bitmaps[key] = bitmap
        bitmap.save(out / "bitmaps" / f"{_safe(key)}.png")
        counts["bitmaps"] += 1

    lines = []
    for key, data in _resources(pe, RT_TOOLBAR):
        _version, width, height, count = struct.unpack_from("<HHHH", data, 0)
        commands = struct.unpack_from(f"<{count}H", data, 8)
        strip = bitmaps.get(key)
        lines.append(f"toolbar {key}: {width}x{height} buttons, bitmap {key}")
        slot = 0
        for command in commands:
            if command == 0:
                lines.append("  (separator)")
                continue
            description, _, tooltip = strings.get(command, "").partition("\n")
            label = re.sub(r"\s*\([^()]*\)$", "", tooltip or description).strip()
            lines.append(f"  slot {slot}: command {command} {label or '(no tooltip)'}")
            if strip is not None and (slot + 1) * width <= strip.width:
                button = strip.crop((slot * width, 0, (slot + 1) * width, height))
                name = f"{key}_{slot:02d}_{command}_{_safe(label or 'command')}.png"
                button.save(out / "toolbar_buttons" / name)
                counts["toolbar_buttons"] += 1
            slot += 1
    (out / "toolbars.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("exe", nargs="?", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    counts = extract_icons(args.exe, args.out)
    print(f"wrote {args.out}: " + ", ".join(f"{count} {kind}" for kind, count in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
