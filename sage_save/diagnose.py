"""Explain why a save might fail to load: run every check we have and rank the suspects.

A BFME save refuses to load for a small number of reasons, and this module tests for each:

- **A dangling *fatal* name reference** — an `Upgrade_*`, `SCIENCE_*`, object template or
  carried-over campaign hero the save names but the loaded ini/mod tree no longer defines. The
  engine hits `XFER_UNKNOWN_STRING` and aborts. This is the single most common cause; it is only
  checkable with a `--game` tree to resolve names against (`sage_save.xref.check_save`).
- **A truncated or corrupt chunk** — a chunk whose bytes don't match its format. The container
  parse catches gross damage; the per-chunk decode of the 18 modelled chunks catches subtler
  drift (a decode that raises is a prime suspect for a save known to fail).
- **A chunk-version bump** — a subsystem serialized at a version the target engine doesn't
  support (e.g. a mod or a different title). Every chunk carries a `u8` version; we compare it
  to the vanilla-BFME2 baseline.
- **An unknown / unexpected chunk** — a chunk name outside the known set (a mod-added subsystem,
  or a different title's layout).

`diagnose_save` returns a ranked `list[Diagnostic]` (fatal → warning → info). It never raises on
a decodable container: a chunk that fails to decode becomes a diagnostic, not an exception, so a
broken save still produces a report. The container parse itself is the caller's responsibility
(`parse_save` raises `ValueError` on a damaged container — the CLI turns that into a fatal
diagnostic of its own).

**Honest framing**: a chunk failing to decode here is a *suspect*, not a proof — it can equally
mean the save is from an engine/mod whose layout we don't model. The value is triage: for a save
you already know won't load, this narrows "it won't load" to a short, concrete list.
"""

from dataclasses import dataclass

from sage_save.chunks import CHUNK_CODECS
from sage_save.save import SaveFile
from sage_save.xref import SupportsLookup, check_save

# The chunk versions every vanilla-BFME2 save writes (derived from the whole fixture corpus;
# each chunk appears at exactly one version). A version other than this is not necessarily a
# failure — a mod or another title legitimately differs — but it is worth surfacing.
KNOWN_CHUNK_VERSIONS: dict[str, int] = {
    "CHUNK_AiOrdersManager": 1,
    "CHUNK_Audio": 4,
    "CHUNK_Campaign": 1,
    "CHUNK_Collision": 1,
    "CHUNK_FireLogicSystem": 2,
    "CHUNK_GameClient": 4,
    "CHUNK_GameLogic": 8,
    "CHUNK_GameState": 1,
    "CHUNK_GameStateMap": 2,
    "CHUNK_GhostObject": 1,
    "CHUNK_InGameUI": 2,
    "CHUNK_LivingWorldLogic": 6,
    "CHUNK_MineshaftPortalNetworkManager": 1,
    "CHUNK_MissionObjectives": 1,
    "CHUNK_ObjectivesMenu": 1,
    "CHUNK_Palantir": 4,
    "CHUNK_ParticleSystem": 2,
    "CHUNK_Partition": 1,
    "CHUNK_Players": 1,
    "CHUNK_Radar": 3,
    "CHUNK_ScriptEngine": 5,
    "CHUNK_Shroud": 1,
    "CHUNK_SidesList": 1,
    "CHUNK_SkirmishAISystem": 2,
    "CHUNK_SpellStore": 1,
    "CHUNK_TacticalView": 3,
    "CHUNK_TaintManager": 1,
    "CHUNK_TeamFactory": 3,
    "CHUNK_TerrainLogic": 1,
    "CHUNK_TerrainVisual": 1,
    "CHUNK_VictorySystem": 1,
    "CHUNK_WeatherSystem": 4,
}

# Severity order for ranking (lower sorts first).
_SEVERITY_RANK = {"fatal": 0, "warning": 1, "info": 2}


@dataclass(frozen=True)
class Diagnostic:
    """One finding about a save. `severity` is `fatal` (will prevent the load — a dangling fatal
    reference or an unparseable container), `warning` (a plausible cause worth investigating — a
    chunk that won't decode, a version bump, an unknown chunk), or `info` (notable but benign — a
    non-fatal dropped-object reference, a case-only mismatch). `chunk` is the chunk it concerns
    (None for whole-save findings)."""

    severity: str
    # "container" | "chunk-decode" | "chunk-version" | "chunk-inventory" | "reference"
    category: str
    message: str
    chunk: str | None = None


def _check_chunk_inventory(save: SaveFile) -> list[Diagnostic]:
    """Chunks whose name is outside the known BFME2 set, and any duplicated chunk name."""
    found: list[Diagnostic] = []
    seen: dict[str, int] = {}
    for chunk in save.chunks:
        seen[chunk.name] = seen.get(chunk.name, 0) + 1
        if chunk.name not in KNOWN_CHUNK_VERSIONS:
            found.append(
                Diagnostic(
                    "warning",
                    "chunk-inventory",
                    "unknown chunk (not written by vanilla BFME2 — a mod-added subsystem or a "
                    "different title/engine)",
                    chunk.name,
                )
            )
    for name, count in seen.items():
        if count > 1:
            found.append(
                Diagnostic(
                    "warning",
                    "chunk-inventory",
                    f"appears {count} times — a duplicated chunk usually means a corrupt stream",
                    name,
                )
            )
    return found


def _check_chunk_versions(save: SaveFile) -> list[Diagnostic]:
    """Chunks whose version differs from the vanilla-BFME2 baseline."""
    found: list[Diagnostic] = []
    for chunk in save.chunks:
        expected = KNOWN_CHUNK_VERSIONS.get(chunk.name)
        if expected is not None and chunk.version != expected:
            found.append(
                Diagnostic(
                    "warning",
                    "chunk-version",
                    f"version {chunk.version} — vanilla BFME2 writes version {expected}; a "
                    "different version can be rejected by an engine that doesn't support it "
                    "(normal if this save is from a mod or another title)",
                    chunk.name,
                )
            )
    return found


def _check_chunk_decodes(save: SaveFile) -> list[Diagnostic]:
    """Attempt to decode every modelled chunk; a decode that raises is a suspect for corruption
    or format drift. Only chunks in `CHUNK_CODECS` are checked (the opaque ones have no model to
    validate against)."""
    found: list[Diagnostic] = []
    for chunk in save.chunks:
        codec = CHUNK_CODECS.get(chunk.name)
        if codec is None:
            continue
        try:
            codec.decode(chunk)
        except Exception as exc:  # noqa: BLE001 — any decode error is a reportable suspect
            found.append(
                Diagnostic(
                    "warning",
                    "chunk-decode",
                    f"did not decode with the BFME2 model ({type(exc).__name__}: {exc}) — the "
                    "bytes may be truncated/corrupt, or from an engine layout we don't model",
                    chunk.name,
                )
            )
    return found


def _check_references(save: SaveFile, game: SupportsLookup) -> list[Diagnostic]:
    """Resolve the save's ini-names against `game`; a missing *fatal* name aborts the load, a
    missing non-fatal one drops an object, a case-only mismatch is tolerated. Guarded so a
    decode failure inside the harvest degrades to one diagnostic rather than crashing."""
    try:
        findings = check_save(save, game)
    except Exception as exc:  # noqa: BLE001
        return [
            Diagnostic(
                "warning",
                "reference",
                f"could not harvest references ({type(exc).__name__}: {exc}) — a decode failure "
                "above likely blocked the name scan",
            )
        ]
    out: list[Diagnostic] = []
    for finding in findings:
        ref = finding.reference
        if finding.status == "missing" and ref.fatal:
            out.append(
                Diagnostic(
                    "fatal",
                    "reference",
                    f"{ref.kind} {ref.name!r} is undefined in the game — a dangling fatal "
                    f"reference aborts the load ({ref.count} occurrence(s))",
                )
            )
        elif finding.status == "missing":
            out.append(
                Diagnostic(
                    "info",
                    "reference",
                    f"{ref.kind} {ref.name!r} is undefined — non-fatal, drops "
                    f"{ref.count} object(s) on load",
                )
            )
        else:  # case-mismatch
            out.append(
                Diagnostic(
                    "info",
                    "reference",
                    f"{ref.kind} {ref.name!r} resolves only by ignoring case "
                    f"(defined as {finding.canonical!r})",
                )
            )
    return out


def diagnose_save(save: SaveFile, game: SupportsLookup | None = None) -> list[Diagnostic]:
    """Every check we can run on a parsed save, ranked fatal → warning → info. Pass `game` (a
    loaded `sage_ini` `Game`) to include the dangling-reference check — the most common and most
    definitive load-failure cause. Without it, only the structural checks run (still useful:
    corruption, version drift, unknown chunks)."""
    diagnostics: list[Diagnostic] = []
    diagnostics += _check_chunk_inventory(save)
    diagnostics += _check_chunk_versions(save)
    diagnostics += _check_chunk_decodes(save)
    if game is not None:
        diagnostics += _check_references(save, game)
    diagnostics.sort(key=lambda d: (_SEVERITY_RANK.get(d.severity, 9), d.category, d.chunk or ""))
    return diagnostics


def format_diagnosis(diagnostics: list[Diagnostic], *, checked_references: bool) -> list[str]:
    """Human-readable report lines for `diagnose_save`."""
    counts = {sev: sum(1 for d in diagnostics if d.severity == sev) for sev in _SEVERITY_RANK}
    lines: list[str] = []
    if not diagnostics:
        lines.append(
            "No anomalies found — the container parses, every modelled chunk decodes, "
            "and all chunk versions match the BFME2 baseline."
        )
        if not checked_references:
            lines.append(
                "(reference check skipped — pass --game <root> to test for dangling "
                "upgrade/science/template names, the most common load-failure cause.)"
            )
        return lines

    verdict = f"{counts['fatal']} fatal, {counts['warning']} warning, {counts['info']} info"
    lines.append(f"Diagnosis: {verdict}")
    if counts["fatal"]:
        lines.append("This save carries a fatal problem and would not load under the given game.")
    elif not checked_references:
        lines.append(
            "(no --game given: the dangling-reference check — the most common load "
            "cause — was not run. Re-run with --game <root> to include it.)"
        )
    lines.append("")
    label = {"fatal": "FATAL  ", "warning": "WARNING", "info": "INFO   "}
    for diag in diagnostics:
        where = f" [{diag.chunk.removeprefix('CHUNK_')}]" if diag.chunk else ""
        lines.append(f"  {label[diag.severity]}{where} {diag.message}")
    return lines
