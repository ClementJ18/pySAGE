"""Flag bit-field conversions for PlaceObject, Button, and ButtonAction flags."""


def _split_flags(flagstr: str) -> list[str]:
    return [f.strip().lower() for f in flagstr.split("|") if f.strip()]


# PlaceObject flags
_PO_BITS = {
    "move": 0x01,
    "hascharacter": 0x02,
    "hasmatrix": 0x04,
    "hascolortransform": 0x08,
    "hasratio": 0x10,
    "hasname": 0x20,
    "hasclipdepth": 0x40,
    "hasclipactions": 0x80,
}
_PO_NAMES = {v: k for k, v in _PO_BITS.items()}
_PO_DISPLAY = {
    "move": "Move",
    "hascharacter": "HasCharacter",
    "hasmatrix": "HasMatrix",
    "hascolortransform": "HasColorTransform",
    "hasratio": "HasRatio",
    "hasname": "HasName",
    "hasclipdepth": "HasClipDepth",
    "hasclipactions": "HasClipActions",
}
_PO_ORDER = [
    "HasCharacter",
    "HasClipActions",
    "HasClipDepth",
    "HasColorTransform",
    "HasMatrix",
    "HasName",
    "HasRatio",
    "Move",
]


def get_po_flags_str(flagint: int) -> str:
    parts = [name for name in _PO_ORDER if flagint & _PO_BITS[name.lower()]]
    return "|".join(parts)


def get_po_flags_int(flagstr: str) -> int:
    result = 0
    for part in _split_flags(flagstr):
        if part in _PO_BITS:
            result |= _PO_BITS[part]
        elif part:
            print(f"Unknown PlaceObjectFlag: {part}")
    return result


# Button record flags
_BUT_BITS = {
    "buttonstateup": 0x01,
    "buttonstateover": 0x02,
    "buttonstatedown": 0x04,
    "buttonstatehittest": 0x08,
}
_BUT_ORDER = ["ButtonStateDown", "ButtonStateHitTest", "ButtonStateOver", "ButtonStateUp"]


def get_but_flags_str(flagint: int) -> str:
    parts = [name for name in _BUT_ORDER if flagint & _BUT_BITS[name.lower()]]
    return "|".join(parts)


def get_but_flags_int(flagstr: str) -> int:
    result = 0
    for part in _split_flags(flagstr):
        if part in _BUT_BITS:
            result |= _BUT_BITS[part]
        elif part:
            print(f"Unknown ButtonFlag: {part}")
    return result


# ButtonAction flags
# Bit layout (uint32):
#   bit 0      : CondOverDownToIdle
#   bits 1-7   : KeyPress (7-bit)
#   bit 8      : CondIdleToOverUp
#   bit 9      : CondOverUpToIdle
#   bit 10     : CondOverUpToOverDown
#   bit 11     : CondOverDownToOverUp
#   bit 12     : CondOverDownToOutDown
#   bit 13     : CondOutDownToOverDown
#   bit 14     : CondOutDownToIdle
#   bit 15     : CondIdleToOverDown

_KEY_TO_CODE = {
    "none": 0,
    "left": 1,
    "right": 2,
    "home": 3,
    "end": 4,
    "insert": 5,
    "delete": 6,
    "backspace": 8,
    "unknown_9": 9,
    "enter": 13,
    "up": 14,
    "down": 15,
    "pgup": 16,
    "pgdown": 17,
    "tab": 18,
    "escape": 19,
}
_CODE_TO_KEY = {v: k for k, v in _KEY_TO_CODE.items()}

_BA_COND_BITS = {
    "condoverdowntoidle": 0x0001,
    "condidletooverup": 0x0100,
    "condoveruptoidle": 0x0200,
    "condoveruptooverdown": 0x0400,
    "condoverdowntooverup": 0x0800,
    "condoverdowntooutdown": 0x1000,
    "condoutdowntooverdown": 0x2000,
    "condoutdowntoidle": 0x4000,
    "condidletooverdown": 0x8000,
}
_BA_COND_ORDER = [
    "CondOverDownToIdle",
    "CondIdleToOverDown",
    "CondIdleToOverUp",
    "CondOutDownToIdle",
    "CondOutDownToOverDown",
    "CondOverDownToOutDown",
    "CondOverDownToOverUp",
    "CondOverUpToOverDown",
    "CondOverUpToIdle",
]


def get_but_action_flags_str(flagint: int) -> str:
    parts = []
    key_press = (flagint >> 1) & 0x7F
    if key_press:
        if key_press >= 32:
            parts.append(f"Key:{chr(key_press)}")
        else:
            parts.append(f"Key:{_CODE_TO_KEY.get(key_press, str(key_press))}")
    for name in _BA_COND_ORDER:
        if flagint & _BA_COND_BITS[name.lower()]:
            parts.append(name)
    result = "|".join(parts)
    if result.endswith("|"):
        result = result[:-1]
    return result


def get_but_action_flags_int(flagstr: str) -> int:
    result = 0
    for raw in flagstr.split("|"):
        raw = raw.strip()
        part = raw.lower()
        if part.startswith("key:"):
            key_part = raw[4:]  # case matters for printable keys ('A' != 'a')
            if len(key_part) == 1:
                key_val = ord(key_part)
            else:
                name = key_part.lower()
                key_val = _KEY_TO_CODE.get(name, int(name) if name.isdigit() else 0)
            result |= (key_val & 0x7F) << 1
        elif part in _BA_COND_BITS:
            result |= _BA_COND_BITS[part]
        elif part:
            print(f"Unknown ButtonActionFlag: {part}")
    return result
