"""Build FOGGY=6 into a separate test binary, replacing the CLOUDY fog test selection."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from sage_patch.patches.experimental.cloudy_hardware_fog import CloudyHardwareFogPatch  # noqa: E402
from sage_patch.patches.experimental.foggy_weather import (  # noqa: E402
    FoggyWeatherPatch,
    FoggyWeatherWorldbuilderPatch,
)
from tools.build_cloudy_fog_patch import build, digest  # noqa: E402

__all__ = ["build_worldbuilder"]

_WB_SHA256 = "005971beb68d0485846ff5f62d6f043e9c9b89d6576525ee25b56e9d305ec65d"


def build_worldbuilder(source: Path, output: Path) -> dict[str, object]:
    """Build and verify all configured editor patches into a separate, guarded test copy."""
    source, output = source.resolve(), output.resolve()
    configured = importlib.import_module("applymypatches")
    protected = {
        source,
        (REPO / "tools/BFME-FILES/Worldbuilder.exe.backup").resolve(),
        (REPO / "tools/BFME-FILES/game.dat.backup").resolve(),
        *(
            Path(getattr(configured, name)).resolve()
            for name in (
                "OUTPUT_PATH",
                "WORLDBUILDER_OUTPUT_PATH",
                "SAGEPATCH_OUTPUT_PATH",
                "EXE_OUTPUT_PATH",
                "DDL_OUTPUT_PATH",
            )
        ),
    }
    audit_path = output.with_name(output.name + ".json")
    if output in protected or audit_path in protected or output.name.endswith(".backup"):
        raise ValueError("Worldbuilder output must be a separate test copy")
    original = source.read_bytes()
    if digest(original) != _WB_SHA256:
        raise ValueError("Worldbuilder build requires the verified original backup SHA256")
    patch = FoggyWeatherWorldbuilderPatch()
    selected = [p for p in configured.worldbuilder_patches if p.name != patch.name] + [patch]
    data = bytearray(original)
    for p in selected:
        p.apply(data)
    for p in selected:
        if problems := p.verify(data):
            raise ValueError(f"Worldbuilder output does not verify {p.name}: {problems}")
    audit: dict[str, object] = {
        "patch": patch.name,
        "author": patch.author,
        "experimental": patch.experimental,
        "runtime_verified": patch.runtime_verified == "yes",
        "input": str(source),
        "input_sha256": digest(original),
        "output": str(output),
        "output_sha256": digest(data),
        "output_bytes": len(data),
        "verified_patches": [p.name for p in selected],
    }
    contents = [(output, bytes(data)), (audit_path, (json.dumps(audit, indent=2) + "\n").encode())]
    if source.read_bytes() != original:
        raise ValueError("Worldbuilder source changed during build; no output written")
    for path, content in contents:
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f"Output already exists with different content: {path}")
    for path, content in contents:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(content)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--target", choices=("game", "worldbuilder"), default="game")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("standalone", "listed", "overlay"), default="listed")
    FoggyWeatherPatch.add_cli_arguments(parser)
    profile_names = ("blend_in_ms", "blend_out_ms", "fog_rgb", "fog_start", "fog_end")
    # Omitted options retain the user's selected profile rather than constructor defaults.
    parser.set_defaults(**dict.fromkeys(profile_names))
    for action in parser._actions:  # noqa: SLF001 - argparse exposes option help through actions.
        if action.dest in profile_names and action.help:
            action.help = action.help.partition(" (default:")[0] + " (default: configured profile)"
    args = parser.parse_args()
    if args.target == "worldbuilder":
        if any(getattr(args, name) is not None for name in profile_names):
            parser.error("Fog profile options apply to --target game only")
        if args.mode != "listed":
            parser.error("Worldbuilder supports --mode listed only")
        manifest = build_worldbuilder(
            args.input or REPO / "tools/BFME-FILES/Worldbuilder.exe.backup", args.out
        )
        print(f"Wrote Worldbuilder test copy: {manifest['output']}")
        print(f"SHA256: {manifest['output_sha256']}")
        return
    configured = (
        importlib.import_module("applymypatches")
        if (REPO / "applymypatches.py").is_file()
        else None
    )
    current = (
        next((p for p in configured.patches if isinstance(p, CloudyHardwareFogPatch)), None)
        if configured is not None
        else None
    )
    patch = (
        FoggyWeatherPatch(
            current.blend_in_ms,
            current.blend_out_ms,
            current.fog_start,
            current.fog_end,
            current.fog_rgb,
        )
        if current is not None
        else FoggyWeatherPatch()
    )
    settings = patch.options()
    settings.update(
        (name, value) for name in profile_names if (value := getattr(args, name)) is not None
    )
    patch = FoggyWeatherPatch(**settings)  # type: ignore[arg-type]
    manifest = build(
        args.input or REPO / "tools/BFME-FILES/game.dat.backup", args.out, args.mode, patch
    )
    print(f"Wrote FOGGY test copy: {manifest['output']}")
    print(f"SHA256: {manifest['output_sha256']}")
    verified = manifest["verified_patches"]
    assert isinstance(verified, list)
    print(f"Verified {len(verified)} patches; runtime report is documented in foggy-weather.md")


if __name__ == "__main__":
    main()
