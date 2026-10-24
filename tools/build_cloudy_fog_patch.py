"""Build a separate CLOUDY fog test binary; never invoke the production patch installer."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from sage_patch.addresses.weather import WEATHER_FOG_HOOK  # noqa: E402
from sage_patch.patches.experimental.cloudy_hardware_fog import (  # noqa: E402
    SECTION_NAME,
    CloudyHardwareFogPatch,
    build_hooks,
)
from sage_patch.patches.experimental.foggy_weather import (  # noqa: E402
    NATIVE_SECTION_NAME,
    FoggyWeatherPatch,
    build_native_code,
)
from sage_patch.utils import find_section, read_bytes  # noqa: E402

__all__ = ["SOURCE_SHA256", "build", "digest"]

SOURCE_SHA256 = "5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26"


def digest(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def build(
    source: Path, output: Path, mode: str, patch: CloudyHardwareFogPatch | None = None
) -> dict[str, object]:
    """Verify every selected patch before writing a new test binary and hash manifest."""
    source, output = source.resolve(), output.resolve()
    manifest_path = output.with_name(output.name + ".json")
    protected = {
        source,
        (REPO / "tools/BFME-FILES/game.dat.backup").resolve(),
    }
    configured = (
        importlib.import_module("applymypatches")
        if (REPO / "applymypatches.py").is_file()
        else None
    )
    if configured is not None:
        protected.update(
            Path(getattr(configured, name)).resolve()
            for name in (
                "OUTPUT_PATH",
                "WORLDBUILDER_OUTPUT_PATH",
                "SAGEPATCH_OUTPUT_PATH",
                "EXE_OUTPUT_PATH",
                "DDL_OUTPUT_PATH",
            )
        )
    if output in protected or manifest_path in protected or output.name.endswith(".backup"):
        raise ValueError(
            "Output must be a separate test file, outside the configured install paths"
        )
    if mode not in {"standalone", "listed", "overlay"}:
        raise ValueError(f"Unknown mode: {mode}")
    if configured is None and mode != "standalone":
        raise ValueError("listed/overlay mode requires the local applymypatches.py")
    original = source.read_bytes()
    if mode != "overlay" and digest(original) != SOURCE_SHA256:
        raise ValueError("Standalone/listed builds require the verified game.dat.backup SHA256")

    if patch is None:
        patch = (
            next(
                (p for p in configured.patches if isinstance(p, CloudyHardwareFogPatch)),
                CloudyHardwareFogPatch(),
            )
            if configured is not None
            else CloudyHardwareFogPatch()
        )
    active = (
        []
        if configured is None
        else [p for p in configured.patches if not isinstance(p, CloudyHardwareFogPatch)]
    )
    if mode == "overlay":
        for existing in active:
            if problems := existing.verify(original):
                raise ValueError(f"Input does not verify {existing.name}: {problems}")

    data = bytearray(original)
    to_apply = [*active, patch] if mode == "listed" else [patch]
    for selected in to_apply:
        selected.apply(data)
    to_verify = [patch] if mode == "standalone" else [*active, patch]
    for selected in to_verify:
        if problems := selected.verify(data):
            raise ValueError(f"Output does not verify {selected.name}: {problems}")
    if source.read_bytes() != original:
        raise ValueError("Input changed during the build; no output written")
    section = find_section(data, SECTION_NAME)
    assert section is not None  # established by patch.verify above
    hooks = build_hooks(section[0])
    native_section = find_section(data, NATIVE_SECTION_NAME)
    if isinstance(patch, FoggyWeatherPatch):
        assert native_section is not None
        hooks.update(build_native_code(native_section[0])[1])

    manifest: dict[str, object] = {
        "schema": 1,
        "patch": patch.name,
        "author": patch.author,
        "experimental": patch.experimental,
        "version": 1 if isinstance(patch, FoggyWeatherPatch) else 3,
        "runtime_verified": patch.runtime_verified == "yes",
        "mode": mode,
        "input": str(source),
        "input_sha256": digest(original),
        "output": str(output),
        "output_sha256": digest(data),
        "output_bytes": len(data),
        "verified_patches": [p.name for p in to_verify],
        "hook_va": hex(WEATHER_FOG_HOOK),
        "hook_before": read_bytes(original, WEATHER_FOG_HOOK, 5).hex(),
        "hook_after": read_bytes(data, WEATHER_FOG_HOOK, 5).hex(),
        "cave": section,
        "native_weather_cave": native_section,
        "weather_id": patch._weather_id,
        "hooks": {
            hex(va): {
                "before": read_bytes(original, va, len(replacement)).hex(),
                "after": replacement.hex(),
            }
            for va, replacement in hooks.items()
        },
        "parameters": patch.options(),
        "time_source": "GameLogic.frame + GameEngine.alpha, gated by GameLogic.paused",
        "fog_rgb": patch.fog_rgb,
        "fog_start": patch.fog_start,
        "fog_end": patch.fog_end,
        "recovery": "Discard this test output; the input and configured installation are unchanged",
    }
    contents = [
        (output, bytes(data)),
        (manifest_path, (json.dumps(manifest, indent=2) + "\n").encode()),
    ]
    for path, content in contents:
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f"Output already exists with different content: {path}")
    for path, content in contents:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(content)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=REPO / "tools/BFME-FILES/game.dat.backup")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("standalone", "listed", "overlay"), default="listed")
    args = parser.parse_args()
    manifest = build(args.input, args.out, args.mode)
    print(f"Wrote test copy: {manifest['output']}")
    print(f"SHA256: {manifest['output_sha256']}")
    verified = manifest["verified_patches"]
    assert isinstance(verified, list)
    print(f"Verified {len(verified)} patches; see patch documentation for runtime evidence")


if __name__ == "__main__":
    main()
