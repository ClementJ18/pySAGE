"""Per-project lint config: the `lint` command reads `<root>/.sagelint` (committed, the
shared rules for a mod) overlaid with `<root>/.sagelint.local` (gitignored, machine paths
and personal overrides). Both are TOML. The local file overrides the shared one per key,
and explicit CLI flags override both - the CLI stays the final say.

Recognised keys (all optional): `level` ("ERROR" | "WARNING" | "INFO"), `root` (the folder
to lint, a single path resolved relative to the config file's own directory), `baseline` (a
path to a baseline file of accepted diagnostics, resolved the same way), `base_manifest` (a
path to a symbol manifest from `sage_lint manifest`, resolved the same way - stands in for the
base game when no `base` sources are configured, mirrors --base-manifest; a real `base` always
wins when both are set, since real data is strictly more complete), `suggest` (a bool
turning on "did you mean" hints), `assets` (a bool enabling the opt-in missing-texture/model/map
file rules, mirrors --assets), `maps` (a bool, default false, also linting the binary `.map`
layouts against the assembled game; mirrors --maps), `sentinels` (extra "intentionally nothing"
reference tokens - e.g. `NoSound` - never reported as dangling; `None`/empty are always treated
this way), `always_referenced` (definition kinds - block type names like `PlayerAIType` - the
unused-definition rule never flags, for kinds reached in ways the ini graph cannot see),
`ignore`, `select`, `exclude`, `base`,
`assets_base` (extra base sources loaded only when `assets` is on - the large texture/model
archives only those rules need; mirrors --assets-base), `maps_base` (extra base sources loaded
only when `maps` is on; mirrors --maps-base), and `asset_dat` (asset.dat files whose entries the
asset-dat-membership rules check model/texture references against - a path or list of paths
resolved relative to the config file, mirrors --asset-dat; setting it turns those two rules on
just as the flag does). The `format`
command reads two more: `align_equals` (a bool, mirrors --align-equals) and `align_exclude`
(block types to leave unaligned, mirrors --align-exclude). The `duplicates` command reads
`duplicate_min_lines` and `duplicate_min_occurrences` (integers, mirroring --min-lines and
--min-occurrences). `root`, `baseline`, `base_manifest`
and `level` are single strings, `suggest`/`align_equals` are bools, the duplicate thresholds
integers, the rest a string or a list
of strings, all mirroring the matching CLI flags. Unknown keys and bad values are reported as
warnings, never raised, so a typo in the config degrades to a message rather than a crash.
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from sage_ini.parser.io import iter_ini_files
from sage_ini.strings import string_files

CONFIG_NAME = ".sagelint"
LOCAL_CONFIG_NAME = ".sagelint.local"

_LEVELS = {"ERROR", "WARNING", "INFO"}
_LIST_KEYS = (
    "ignore",
    "select",
    "exclude",
    "base",
    "assets_base",
    "maps_base",
    "asset_dat",
    "align_exclude",
    "sentinels",
    "always_referenced",
)
_BOOL_KEYS = ("suggest", "align_equals", "assets", "maps")
# Integer keys with their smallest accepted value.
_INT_KEYS = {"duplicate_min_lines": 1, "duplicate_min_occurrences": 2}
_KNOWN_KEYS = {"level", "root", "baseline", "base_manifest", *_BOOL_KEYS, *_INT_KEYS, *_LIST_KEYS}


@dataclass
class Config:
    """Effective project config: the merge of `.sagelint` and `.sagelint.local`. Empty
    fields mean "unset" so the caller can let a CLI flag or the built-in default win."""

    level: str | None = None
    root: str | None = None
    baseline: str | None = None
    # A symbol manifest standing in for the base game when no `base` sources are configured; a
    # real `base` always wins (see `sage_lint.linter.build_cache`).
    base_manifest: str | None = None
    suggest: bool = False
    # Off by default: the missing-file rules need the base-game archives loaded via `base`,
    # else every base asset reads as missing.
    assets: bool = False
    # Off by default: parsing every map adds time, and the checks want base-game definitions.
    maps: bool = False
    align_equals: bool = False
    align_exclude: list[str] = field(default_factory=list)
    ignore: list[str] = field(default_factory=list)
    select: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    base: list[str] = field(default_factory=list)
    # Extra base sources merged only when `assets`/`maps` is on, so a plain run never pays to
    # load the large texture/model archives or base-game data those checks alone need.
    assets_base: list[str] = field(default_factory=list)
    maps_base: list[str] = field(default_factory=list)
    # asset.dat files whose file-entry names the asset-dat-membership rules check model/texture
    # references against; setting it (like passing --asset-dat) turns those two rules on.
    asset_dat: list[str] = field(default_factory=list)
    # Extra "intentionally nothing" reference tokens (e.g. NoSound) never flagged as dangling;
    # None/empty are always treated this way regardless. Definition kinds (block type names) the
    # unused-definition rule never flags, for kinds reached outside the ini reference graph.
    sentinels: list[str] = field(default_factory=list)
    always_referenced: list[str] = field(default_factory=list)
    # Thresholds for the `duplicates` command, in comment-stripped source lines / occurrence
    # count; None lets the CLI flag or the built-in default (10 / 2) win.
    duplicate_min_lines: int | None = None
    duplicate_min_occurrences: int | None = None
    # Human-readable problems found while loading (bad TOML, unknown keys, wrong types).
    warnings: list[str] = field(default_factory=list)


def _str_list(value: object, key: str, source: str, warnings: list[str]) -> list[str]:
    """Coerce a string-or-list-of-strings config value to a list, warning on anything else."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    warnings.append(f"{source}: '{key}' must be a string or a list of strings")
    return []


def _read_one(path: Path, warnings: list[str]) -> dict:
    """Parse one TOML config file. Missing is fine (returns {}); malformed is a warning."""
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except (tomllib.TOMLDecodeError, OSError) as exc:
        warnings.append(f"{path}: {exc}")
        return {}
    for key in sorted(set(data) - _KNOWN_KEYS):
        warnings.append(f"{path}: unknown key '{key}' (ignored)")
    return data


def load_config(directory: str | Path) -> Config:
    """Load `.sagelint` then overlay `.sagelint.local` from `directory`, returning the merge.
    The local file replaces the shared file's value for any key it sets."""
    directory = Path(directory)
    warnings: list[str] = []
    merged: dict = {}
    sources: dict[str, str] = {}
    for name in (CONFIG_NAME, LOCAL_CONFIG_NAME):
        path = directory / name
        data = _read_one(path, warnings)
        for key in data:
            sources[key] = str(path)
        merged.update(data)

    config = Config(warnings=warnings)
    if "level" in merged:
        level = merged["level"]
        if isinstance(level, str) and level.upper() in _LEVELS:
            config.level = level.upper()
        else:
            warnings.append(f"{sources['level']}: invalid level {level!r} (ignored)")
    if "root" in merged:
        root = merged["root"]
        if isinstance(root, str) and root:
            config.root = root
        else:
            warnings.append(f"{sources['root']}: 'root' must be a non-empty string (ignored)")
    if "baseline" in merged:
        baseline = merged["baseline"]
        if isinstance(baseline, str) and baseline:
            config.baseline = baseline
        else:
            warnings.append(
                f"{sources['baseline']}: 'baseline' must be a non-empty string (ignored)"
            )
    if "base_manifest" in merged:
        base_manifest = merged["base_manifest"]
        if isinstance(base_manifest, str) and base_manifest:
            config.base_manifest = base_manifest
        else:
            warnings.append(
                f"{sources['base_manifest']}: 'base_manifest' must be a non-empty string (ignored)"
            )
    for key in _BOOL_KEYS:
        if key in merged:
            value = merged[key]
            if isinstance(value, bool):
                setattr(config, key, value)
            else:
                warnings.append(f"{sources[key]}: '{key}' must be a bool (ignored)")
    for key, minimum in _INT_KEYS.items():
        if key in merged:
            value = merged[key]
            if isinstance(value, int) and not isinstance(value, bool) and value >= minimum:
                setattr(config, key, value)
            else:
                warnings.append(
                    f"{sources[key]}: '{key}' must be an integer >= {minimum} (ignored)"
                )
    for key in _LIST_KEYS:
        if key in merged:
            setattr(config, key, _str_list(merged[key], key, sources[key], warnings))
    return config


# The committed `.sagelint` written by `init`: the folder to lint plus suggestions on, the
# two settings a fresh project almost always wants. Comments point at the rest.
_DEFAULT_CONFIG_TEXT = """\
# sage_lint project config - committed; shared by everyone editing this mod.
# Run `sage_lint lint --list-codes` to see the codes `ignore`/`select` accept.

# Folder to lint, relative to this file. "." is this folder; includes and string
# tables (.str / Lotr.csv) are found recursively beneath it.
root = "."

# Show "Did you mean ...?" hints on unknown names, attributes and string labels.
suggest = true

# A symbol manifest (generated with `sage_lint manifest`) standing in for the base game when
# no `base` sources are configured, so references into it resolve with no base tree on disk.
# Unlike `base` (a machine-specific path, so it belongs in .sagelint.local), a manifest is a
# small committable file - share it here so everyone lints against the same base symbols. A
# real `base` (in .sagelint.local) always wins when both are set. Mods that #include base-game
# files still need a real `base` - a manifest carries symbols, not include text.
# base_manifest = "sage-base-manifest.json.gz"
"""

# The gitignored `.sagelint.local`: machine paths, written commented-out so a freshly
# scaffolded project has the placeholder ready to fill rather than a silent gap.
_LOCAL_CONFIG_TEXT = """\
# sage_lint local overrides - machine-specific paths; do NOT commit (add to .gitignore).
# Point `base` at your unmodified base-game data so references into it resolve instead of
# being reported as dangling. A folder or a .big archive; repeatable, highest priority first.
# base = ["C:/Program Files (x86)/Electronic Arts/.../BFME2"]

# `assets_base` is loaded only when asset checking is on (assets = true / --assets): the large
# texture/model .big archives the missing-file rules need, kept out of every other run.
# assets_base = ["C:/Program Files (x86)/Electronic Arts/.../BFME2/textures2.big"]

# `asset_dat` points the asset-dat-membership rules at the asset.dat(s) the engine actually reads,
# so a model/texture the mod references but that never made it into the cache is flagged (invisible
# in game even though the file is on disk). List the mod's own asset.dat and the base game's; a
# name present in any of them counts. Setting this turns those two rules on, like --asset-dat.
# asset_dat = ["asset.dat", "C:/Program Files (x86)/Electronic Arts/.../BFME2/asset.dat"]

# `maps_base` is loaded only when map linting is on (maps = true / --maps): the base-game data the
# map checks resolve object/upgrade references against (e.g. the .big holding data/ini/object).
# maps_base = ["C:/Program Files (x86)/Electronic Arts/.../BFME2/ini.big"]
"""


@dataclass
class InitResult:
    """What `init_project` found and did, for the CLI to report back. `written` are the files
    created, `skipped` ones left in place (already present, no `--force`)."""

    directory: Path
    ini_count: int
    string_files: list[Path]
    written: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)


def init_project(directory: str | Path, force: bool = False) -> InitResult:
    """Scaffold `.sagelint` (and a commented `.sagelint.local`) in `directory`, autodetecting
    what the linter will see: how many ini files and whether a string table is present (the
    string-label rule no-ops without one). Existing files are left untouched unless `force`."""
    directory = Path(directory)
    result = InitResult(
        directory=directory,
        ini_count=sum(1 for _ in iter_ini_files(directory)),
        string_files=string_files(directory),
    )
    targets = ((CONFIG_NAME, _DEFAULT_CONFIG_TEXT), (LOCAL_CONFIG_NAME, _LOCAL_CONFIG_TEXT))
    for name, text in targets:
        path = directory / name
        if path.exists() and not force:
            result.skipped.append(path)
            continue
        path.write_text(text, encoding="utf-8")
        result.written.append(path)
    return result
