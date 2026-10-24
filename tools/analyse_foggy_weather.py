"""Reproduce the direct weather-consumer inventory and save native disassembly evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from sage_patch.addresses.weather import THE_GLOBAL_WEATHER_SYSTEM  # noqa: E402
from sage_patch.utils import image_sections, read_bytes, read_cstring  # noqa: E402
from tools.build_cloudy_fog_patch import SOURCE_SHA256  # noqa: E402

_USES = {
    0x492E6E: "Rain manager: copy current ID to cached state; no WeatherData index",
    0x4940A3: "Rain manager: leave RAINY=2; compare only",
    0x4940F4: "Rain manager: enter RAINY=2; compare only",
    0x4944B9: "Forward to bounded HasLightning getter",
    0x494DFF: "CloudEffect output: bounded HasLightning getter",
    0x49524C: "Cloud renderer: singleton null gate",
    0x496F49: "Cloud renderer: CLOUDY texture choice; FOGGY local alias",
    0x497D2B: "CloudEffect state machine: CLOUDY comparison; FOGGY local alias",
    0x497D6B: "CloudEffect update: bounded HasLightning getter",
    0x62E8C0: "GameLogic dispatches WeatherSystem update through slot +28",
    0x63B37D: "Subsystem registration passes the address of the singleton",
    0x69406D: "Object binding: apply current weather modifiers, not a WeatherData index",
    0x6DFAE1: "CHUNK_WeatherSystem registers Snapshot subobject at +0C",
    0x719DD4: "WeatherData INI parser: independent five-name bounded search",
    0x897AED: "SpecialPower dispatch: reset existing weather modifiers",
    0x897B22: "SpecialPower dispatch: configure existing weather modifiers",
    0x897B3D: "SpecialPower dispatch: native setter, preserving sentinel 5",
    0x8C910B: "SpecialPower auxiliary effect compares current weather to RAINY=2",
    0x8C9323: "SpecialPower auxiliary effect compares current weather to CLOUDY=1",
}

_RANGES = {
    "cloud_factory": (0x44BEC3, 0x35),
    "cloud_constructor": (0x494C65, 0xDE),
    "cloud_update": (0x497D00, 0x17E),
    "cloud_settings_rgb": (0x614CED, 0x19),
    "cloud_output_entry": (0x494DBA, 0x5E),
    "cloud_output_tail": (0x49516B, 0xBD),
    "cloud_rgb_getter": (0x494D4A, 0x1D),
    "cloud_enabled_getter": (0x494794, 11),
    "client_factory_and_singleton": (0x647052, 0x35),
    "client_update_dispatch": (0x648594, 0xF),
    "client_frame_getter": (0x9F9F1A, 4),
    "scene_lighting_consumer": (0x4713C0, 0x5C),
    "terrain_lighting_consumer": (0x469108, 0x88),
    "prop_lighting_consumer": (0x4EDE98, 0x90),
    "drawable_lighting_consumer": (0x670A06, 0x4A),
    "cloud_texture_selection": (0x496F48, 0x18),
    "weather_lightning": (0x719BE4, 0x14),
    "weather_data_parser": (0x719D60, 0x8E),
    "weather_audio": (0x719DEE, 0x77),
    "weather_setter": (0x71A024, 0x2B),
    "weather_update": (0x71A09E, 0x38),
    "specialpower_parser": (0x8966F9, 0x4F),
    "specialpower_dispatch": (0x897B2C, 0x23),
    "weather_snapshot": (0x71A2E3, 0xD8),
    "snapshot_postload": (0x71A0D6, 8),
    "weather_enum_xfer": (0x70777F, 0x18),
    "generic_enum_xfer": (0xA1F8B5, 0x7E),
    "snapshot_registration": (0x6DFAE0, 0x24),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=REPO / "tools/BFME-FILES/game.dat.backup")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    # Optional analysis dependency; normal patch application does not need it.
    try:
        import capstone  # noqa: PLC0415 (optional evidence-only dependency)
    except ImportError as exc:
        raise SystemExit("Install capstone to run this evidence-only tool") from exc
    data = args.input.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA256:
        raise SystemExit("This inventory requires the verified original RotWK backup SHA256")
    refs = []
    needle = struct.pack("<I", THE_GLOBAL_WEATHER_SYSTEM)
    for section in image_sections(data):
        if section.name != ".text":
            continue
        pos = section.raw_offset
        end = pos + section.raw_size
        while (pos := data.find(needle, pos, end)) >= 0:
            refs.append(section.virtual_address + pos - section.raw_offset)
            pos += len(needle)
    if set(refs) != set(_USES):
        raise SystemExit(f"Direct weather references differ from the reviewed inventory: {refs}")
    args.out.mkdir(parents=True, exist_ok=True)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    for name, (va, size) in _RANGES.items():
        lines = [f"; Original RotWK backup SHA256 {digest}"]
        for insn in md.disasm(read_bytes(data, va, size), va):
            lines.append(
                f"{insn.address:08X} {insn.bytes.hex():24} {insn.mnemonic:8} {insn.op_str}"
            )
        (args.out / f"{name}.asm").write_text("\n".join(lines) + "\n")
    pointers = struct.unpack("<9I", read_bytes(data, 0xDB0074, 36))
    report = {
        "schema": 1,
        "source_sha256": digest,
        "runtime_verified": False,
        "evidence": "original disassembly plus reviewed direct-reference inventory",
        "scope_limit": (
            "Not a formal proof excluding every computed/aliased pointer in the executable"
        ),
        "direct_singleton_references": {hex(va): _USES[va] for va in refs},
        "old_specialpower_names": [read_cstring(data, p) if p else None for p in pointers],
        "reviewed_weatherdata_index_sites": {
            "0x719bf0": "HasLightning: signed 0..4 bounds, unchanged",
            "0x719ddd": "WeatherData parser: explicit five-entry search, unchanged",
            "0x719e12": (
                "Audio: unbounded original; patched locally to index 0 for values outside 0..4"
            ),
        },
        "root_cause": {
            "singleton": "0xDE3C24",
            "vtable": "0xBDE130",
            "update": "0x497D00",
            "client_frame_getter": "0x9F9F1A, GameClient+0x10 via vtable+0x7C",
            "factor": "CloudEffect.DarkeningFactor * (1 - counter/255)",
            "consumer": "lighting multiplied by 1 - output RGB; real virtual getter +0x48",
        },
        "snapshot": {
            "entry": "0x71A2E3",
            "this_adjustment": "+0x0C",
            "version": [1, 4],
            "weather": "+4 from Snapshot this, four-byte labelled GlobalWeatherType",
            "timers": "WeatherSystem+0x28/+0x2C from version 3",
            "postload": "0x71A0D6 -> 0x719DEE (bounded by the patch)",
            "limits": "Actual save-file, CRC and network/replay sessions remain untested",
        },
    }
    (args.out / "weather-consumers.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Reviewed {len(refs)} direct references; evidence written to {args.out}")


if __name__ == "__main__":
    main()
