"""Resolve a unit's portrait from texture sources and wire it into the infobox.

Crops the object's portrait `MappedImage` (its `SelectPortrait`, else `ButtonImage`; a
horde's comes from its contained unit) to a PNG and works out how the page's `image`
parameter should point at the uploaded file -
the headless, Qt-/network-free half of the upload tool (the upload itself is the wiki
client's job). Files are named after the object's internal id, stable across display-name
changes.
"""

import io

from PIL import Image

from sage_ini.model.state import select_command_set
from sage_utils.textures import (
    TextureSource,
    crop_mapped_image,
    frame_icon,
    render_portrait,
)
from sage_utils.views import (
    command_button_images,
    flatten_button_images,
)
from sage_wiki.names import split_file_namespace

# The infobox parameter that names the portrait file. Shared by the unit, hero and
# building infoboxes (all use a bare `image` param), so no aliasing is needed.
IMAGE_PARAM = "image"


def portrait_filename(obj) -> str:
    """The wiki filename for the object's portrait - its internal id plus ``.png``."""
    return f"{obj.name}.png"


def _png_bytes(picture) -> bytes:
    """A Pillow image encoded as PNG bytes."""
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    return buffer.getvalue()


def render_portrait_png(
    source: TextureSource, obj, background: Image.Image | None = None
) -> bytes | None:
    """The object's cropped portrait as PNG bytes, composited onto `background` if given,
    or None when the object defines no portrait or its texture isn't in `source`."""
    picture = render_portrait(source, obj, background)
    return _png_bytes(picture) if picture is not None else None


def render_icon_png(
    source: TextureSource, image, overlay: Image.Image | None = None
) -> bytes | None:
    """A single `MappedImage` cropped to PNG bytes, or None when `image` is None or its
    texture isn't present in `source`. When `overlay` is given (an ability frame), the icon
    is scaled and centered under it (see `frame_icon`)."""
    if image is None:
        return None
    picture = crop_mapped_image(source, image)
    if picture is None:
        return None
    if overlay is not None:
        picture = frame_icon(picture, overlay)
    return _png_bytes(picture)


def icon_filename(name: str) -> str:
    """The wiki filename for a button icon - the command button's name plus ``.png``."""
    return f"{name}.png"


def object_command_icon_rows(
    game, obj, active_upgrades=frozenset()
) -> tuple[str | None, list[dict]]:
    """The object's active command set name and its icon rows (see `command_set_icon_rows`),
    or `(None, [])`. Resolves the set the engine shows for `obj` under `active_upgrades`."""
    command_set = select_command_set(obj, set(active_upgrades))
    if command_set is None:
        return None, []
    return command_set.name, command_set_icon_rows(game, command_set)


def command_icon_rows(game, obj, active_upgrades=frozenset()) -> list[dict]:
    """The object's command-set button icons as one `{name, text, image}` row per image
    (`image` None for a button with no icon). `name` is the `MappedImage`'s own name (so
    the uploaded file matches the shared image definition), falling back to the raw
    `ButtonImage` token, then the button name. Empty when the object displays no command set."""
    return object_command_icon_rows(game, obj, active_upgrades)[1]


def command_set_icon_rows(game, command_set) -> list[dict]:
    """The `{name, text, image}` icon rows for an explicit `command_set` (like
    `command_icon_rows`, but for a set chosen directly rather than resolved from an object)."""
    rows = flatten_button_images(command_button_images(game, command_set))
    for row in rows:
        image = row["image"]
        image_name = getattr(image, "name", None) if image is not None else None
        if image_name:
            row["name"] = image_name
    return rows


def command_icon_names(game, command_set) -> dict[str, str]:
    """Map each button name in `command_set` to the wiki filename its icon uploads as - the
    button's `ButtonImage` name (the loaded `MappedImage`'s, else the raw token) plus `.png`.
    Buttons with no `ButtonImage` are left out."""
    names: dict[str, str] = {}
    for entry in command_button_images(game, command_set):
        image_names = entry["image_names"]
        if image_names:
            names[entry["name"]] = icon_filename(image_names[0])
    return names


def _first_gallery_entry(text: str) -> str | None:
    """The first `Filename|caption` line inside a `<gallery>…</gallery>` (the portrait), or
    None when `text` is not a gallery. The opening tag may carry attributes; the close is
    optional."""
    lower = text.lower()
    start = lower.find("<gallery")
    if start == -1:
        return None
    open_end = text.find(">", start)
    if open_end == -1:
        return None
    close = lower.find("</gallery>", open_end)
    inner = text[open_end + 1 : close if close != -1 else len(text)]
    for line in inner.splitlines():
        if line.strip():
            return line.strip()
    return None


def filename_from_value(raw: str | None) -> str | None:
    """The bare file name in an infobox image value, or None. Handles a bare `Foo.png`, a
    `File:`/`Image:` prefix, a `[[File:…|options]]` link, and a `<gallery>` (its first
    entry); options after the first `|` are dropped."""
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    gallery_entry = _first_gallery_entry(text)
    if gallery_entry is not None:
        text = gallery_entry
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2].strip()
    head = text.split("|", 1)[0].strip()  # drop any [[File:X|options]] or gallery caption
    _, head = split_file_namespace(head)
    return head or None


def rewrite_image_value(old_raw: str | None, new_filename: str) -> str:
    """The new infobox image value pointing at `new_filename`, keeping the old style (bare,
    a `File:` prefix, or a `[[File:…|options]]` link with its options). Bare when there was
    no previous value."""
    if not old_raw or not old_raw.strip():
        return new_filename
    text = old_raw.strip()
    bracketed = text.startswith("[[") and text.endswith("]]")
    inner = text[2:-2].strip() if bracketed else text
    head, separator, options = inner.partition("|")
    namespace, _ = split_file_namespace(head)
    rebuilt = f"{namespace}{new_filename}{separator}{options}"
    return f"[[{rebuilt}]]" if bracketed else rebuilt
