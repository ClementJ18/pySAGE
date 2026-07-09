"""Command-button, command-set and button-image views: a button as a render-ready dict,
a set's slots in order, and the croppable `MappedImage`s behind portraits and icons."""

from sage_ini.model.data_blocks import MappedImage
from sage_ini.model.state import horde_member_object
from sage_utils.views.base import safe, upgrade_names
from sage_utils.views.text import display_name, localize


def _button_upgrade_view(game, button) -> dict | None:
    """The Upgrade an OBJECT_UPGRADE/PLAYER_UPGRADE button grants - its localized name,
    cost and time - or None when the button names no resolvable upgrade."""
    upgrade = safe(lambda: button.Upgrade)
    if upgrade is None:
        return None
    return {
        "name": display_name(game, upgrade) or upgrade.name,
        "cost": safe(lambda: upgrade.BuildCost),
        "time": safe(lambda: upgrade.BuildTime),
    }


def command_button_view(game, name, button) -> dict:
    """One CommandButton as a render-ready dict. Always carries the slot `name`, localized
    `text`/`tooltip` and the `command` action name (None when unloaded). The rest are
    filled only for the action the UI acts on, else None:

    - `upgrade` - {name, cost, time} for OBJECT_UPGRADE / PLAYER_UPGRADE.
    - `object` - the object a UNIT_BUILD button builds.
    - `special_power` - the SpecialPower of a SPECIAL_POWER* or SPELL_BOOK button.
    - `weapon_slot` - the SlotTypes name a FIRE_WEAPON button fires.
    - `toggle_flags` - the WeaponSet flags a TOGGLE_WEAPONSET button flips.
    - `button_image` - the button's `ButtonImage` as a croppable `MappedImage` list.
    """
    text = localize(game, safe(lambda: button.TextLabel)) if button else ""
    tooltip = localize(game, safe(lambda: button.DescriptLabel)) if button else ""
    command = getattr(safe(lambda: button.Command), "name", None) if button else None
    view = {
        "name": name,
        "text": text or name,
        "tooltip": tooltip,
        "command": command,
        "upgrade": None,
        "object": None,
        "special_power": None,
        "weapon_slot": None,
        "toggle_flags": [],
        "button_image": _mapped_images(safe(lambda: button.ButtonImage)) if button else [],
    }
    if button is None:
        return view
    if command in ("OBJECT_UPGRADE", "PLAYER_UPGRADE"):
        view["upgrade"] = _button_upgrade_view(game, button)
    elif command == "UNIT_BUILD":
        view["object"] = getattr(safe(lambda: button.Object), "name", None)
    elif command and (command.startswith("SPECIAL_POWER") or command == "SPELL_BOOK"):
        view["special_power"] = getattr(safe(lambda: button.SpecialPower), "name", None)
    elif command == "FIRE_WEAPON":
        view["weapon_slot"] = getattr(safe(lambda: button.WeaponSlot), "name", None)
    elif command == "TOGGLE_WEAPONSET":
        raw = button._fields.get("FlagsUsedForToggle")
        view["toggle_flags"] = [token.upper() for token in upgrade_names(raw)]
    return view


def _command_set_slots(command_set) -> list[tuple[int, str]]:
    """A CommandSet's `(slot index, button name)` pairs, in slot order. Only numbered
    fields are slots; one listing several values keeps the last (the engine's override)."""
    slots = []
    for slot, name in command_set.fields.items():
        if slot.isdigit():
            slots.append((int(slot), name[-1] if isinstance(name, list) else name))
    return sorted(slots)


def command_buttons_view(game, command_set) -> list[dict]:
    """Each filled slot of a CommandSet as a `command_button_view` dict, in slot order. A
    slot whose button isn't loaded falls back to the raw name so nothing is dropped."""
    table = game.commandbuttons
    return [
        command_button_view(game, name, table.get(name))
        for _slot, name in _command_set_slots(command_set)
    ]


def command_set_buttons(game, command_set) -> list[tuple[int, str, object]]:
    """`(slot, button_name, CommandButton)` for each *loaded* slot of a CommandSet, in slot
    order - the lean view that hands back the typed button so a caller can read its `Command`,
    `Object`, `Options`, … . Slots whose button isn't loaded are dropped (the hero-recruit
    index counts only resolvable buttons)."""
    table = game.commandbuttons
    return [
        (slot, name, table[name]) for slot, name in _command_set_slots(command_set) if name in table
    ]


def _mapped_images(value) -> list:
    """The croppable `MappedImage` definitions in a resolved `Image` field value, always
    as a list. Unresolved names (raw strings) and a missing field yield nothing."""
    values = value if isinstance(value, list) else [value]
    return [item for item in values if isinstance(item, MappedImage)]


def _image_names(value) -> list[str]:
    """The image names in a resolved `Image` field value, resolved or not: a loaded
    `MappedImage`'s `name`, else the raw token. Keeps the icon's real `ButtonImage` name
    even when its definition wasn't loaded. Always a list, mirroring `_mapped_images`."""
    values = value if isinstance(value, list) else [value]
    names = []
    for item in values:
        if isinstance(item, MappedImage):
            names.append(item.name)
        elif item:
            names.append(str(item).split()[0])
    return names


def select_portrait_image(obj) -> list:
    """The object's `SelectPortrait` as a list of croppable `MappedImage`s (empty when
    unset/unresolved), resolved like a button's `ButtonImage`."""
    return _mapped_images(safe(lambda: obj.SelectPortrait))


def object_button_image(obj) -> list:
    """The object's own `ButtonImage` (the icon shown for it, e.g. in a build menu) as a
    list of croppable `MappedImage`s; empty when unset/unresolved."""
    return _mapped_images(safe(lambda: obj.ButtonImage))


def portrait_mapped_images(obj) -> list:
    """The object's portrait `MappedImage`s, tried in order: its own `SelectPortrait`, a horde
    member's `SelectPortrait`, then either's `ButtonImage` (the next-best icon for
    structures/summons). A horde may carry the portrait on its shell or only on the contained
    unit - some define it on one, some on the other - so both are consulted. Empty when none
    resolves."""
    member = horde_member_object(obj)
    sources = [obj] if member is None else [obj, member]
    for resolve in (select_portrait_image, object_button_image):
        for source in sources:
            images = resolve(source)
            if images:
                return images
    return []


def command_button_images(game, command_set) -> list[dict]:
    """Each button of a CommandSet paired with its `ButtonImage`(s), in slot order, for
    the extract-image tool. Every slot yields `{name, text, image, image_names}`: `image`
    is the resolved `MappedImage` list (empty when unloaded/unresolved) and `image_names`
    the button's image name(s) resolved or not."""
    table = game.commandbuttons
    entries = []
    for _slot, name in _command_set_slots(command_set):
        button = table.get(name)
        image = safe(lambda b=button: b.ButtonImage) if button is not None else None
        text = localize(game, safe(lambda b=button: b.TextLabel)) if button is not None else ""
        entries.append(
            {
                "name": name,
                "text": text or name,
                "image": _mapped_images(image),
                "image_names": _image_names(image),
            }
        )
    return entries


def flatten_button_images(entries) -> list[dict]:
    """One selectable row per croppable image across button-image `entries`. A button's
    several layered images each become a row, the index suffixed onto `name`/`text` only
    when there is more than one. A button with no resolved image becomes a single row with
    `image` None, named after its `ButtonImage` if it has one, else the button itself. Each
    row keeps its originating `button` (the command button's name) so callers can look the
    button back up (e.g. to scaffold its ability template)."""
    rows: list[dict] = []
    for entry in entries:
        button = entry["name"]
        images = entry["image"]
        if not images:
            image_names = entry.get("image_names") or []
            name = image_names[0] if image_names else entry["name"]
            rows.append({"name": name, "text": entry["text"], "image": None, "button": button})
            continue
        multiple = len(images) > 1
        for index, image in enumerate(images, 1):
            rows.append(
                {
                    "name": f"{entry['name']}_{index}" if multiple else entry["name"],
                    "text": f"{entry['text']} ({index})" if multiple else entry["text"],
                    "image": image,
                    "button": button,
                }
            )
    return rows
