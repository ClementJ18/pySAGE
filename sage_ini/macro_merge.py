"""Set-aware resolution of `#define` list conflicts - the engine behind `macro-merge`.

SAGE/Edain data leans on long `#define NAME a b c ...` macros whose value is an
*unordered set* of object/upgrade references (e.g. `EVIL_INFANTRY_15`). Git line-merges
them as a single line, so any two branches that both touch such a macro collide on the
whole line, and resolving by hand means eyeballing 100+ names to guess what each side
added or removed. That guessing is where obsolete references get resurrected and new
ones silently dropped.

This resolves such a conflict the way the data actually means it: as a 3-way *set*
merge against the common ancestor (the diff3 `|||||||` section). A token present on a
side but absent from base was **added** there; a token in base but absent from a side
was **removed** there. The resolution keeps every addition and honours every removal:

    result = (base - removed_by_either) | added_by_ours | added_by_theirs

Because an added token is never in base and a removed token always is, the two sets are
disjoint and the merge is deterministic - there is no such thing as a token-level
"conflict" here. What still needs a human eye is a token *one* side deleted while the
other left it in place: the merge honours the deletion, and this module surfaces exactly
those tokens so the deletion can be confirmed rather than discovered later.

Only `#define` conflict hunks are touched; every other conflict is left byte-for-byte as
git wrote it, so the file can be finished the usual way afterwards.
"""

import re
from dataclasses import dataclass, field

__all__ = [
    "MacroMerge",
    "MacroResolveResult",
    "format_macro_report",
    "merge_macro_tokens",
    "resolve_macro_conflicts",
]

_DEFINE = re.compile(
    r"^(?P<indent>[ \t]*)#define[ \t]+(?P<name>\S+)(?:[ \t]+(?P<value>.*?))?[ \t]*$"
)


@dataclass(frozen=True, slots=True)
class MacroMerge:
    """The 3-way set analysis of one `#define` list conflict."""

    name: str
    merged: list[str]  # resolved token order (ours spine, theirs-only appended)
    added_ours: list[str]  # in ours, not in base
    added_theirs: list[str]  # in theirs, not in base
    removed_ours: list[str]  # in base, dropped by ours
    removed_theirs: list[str]  # in base, dropped by theirs
    duplicates: dict[str, list[str]]  # side name -> tokens that repeat on that side
    has_base: bool  # False for a 2-way (non-diff3) hunk: removals can't be detected

    @property
    def removed_one_side(self) -> list[tuple[str, str]]:
        """Base tokens exactly one side deleted (the other kept). The merge drops these;
        each is a deletion to confirm, not a safe automatic outcome. `(token, side)`."""
        only_ours = set(self.removed_ours) - set(self.removed_theirs)
        only_theirs = set(self.removed_theirs) - set(self.removed_ours)
        pairs = [(t, "ours") for t in only_ours] + [(t, "theirs") for t in only_theirs]
        return sorted(pairs)

    @property
    def removed_both(self) -> list[str]:
        return sorted(set(self.removed_ours) & set(self.removed_theirs))


@dataclass(slots=True)
class MacroResolveResult:
    text: str
    merges: list[MacroMerge] = field(default_factory=list)
    resolved: int = 0  # `#define` hunks collapsed to a single merged line
    remaining: int = 0  # conflict hunks left untouched (not `#define` lists)


def merge_macro_tokens(
    base: list[str] | None, ours: list[str], theirs: list[str]
) -> tuple[list[str], set[str], set[str]]:
    """Return the merged token list and the removal sets. Ours order is the spine and
    theirs-only additions are appended; a token removed by either side is dropped. With
    `base=None` (no ancestor) nothing can be classed as a removal, so the result is the
    order-preserving union - a safe superset."""
    base_set = set(base) if base is not None else None
    ours_set, theirs_set = set(ours), set(theirs)
    if base_set is None:
        removed_ours: set[str] = set()
        removed_theirs: set[str] = set()
    else:
        removed_ours = base_set - ours_set
        removed_theirs = base_set - theirs_set
    dropped = removed_ours | removed_theirs

    merged: list[str] = []
    seen: set[str] = set()
    for token in [*ours, *theirs]:
        if token in dropped or token in seen:
            continue
        seen.add(token)
        merged.append(token)
    return merged, removed_ours, removed_theirs


def _parse_define(line: str) -> tuple[str, str, str] | None:
    """(indent, name, value) for a `#define` line, else None."""
    match = _DEFINE.match(line)
    if match is None:
        return None
    return match["indent"], match["name"], match["value"] or ""


def _defines_by_name(lines: list[str]) -> dict[str, tuple[str, str, str]] | None:
    """Map name -> (indent, name, value) for a hunk side, or None if the side holds
    anything other than `#define` lines (blank lines are ignored) or repeats a name."""
    result: dict[str, tuple[str, str, str]] = {}
    for line in lines:
        if not line.strip():
            continue
        parsed = _parse_define(line)
        if parsed is None or parsed[1] in result:
            return None
        result[parsed[1]] = parsed
    return result


def _is_marker(line: str, ch: str, marker_size: int) -> bool:
    return line[:marker_size] == ch * marker_size and line[marker_size : marker_size + 1] != ch


def _resolve_hunk(
    ours: list[str], base: list[str] | None, theirs: list[str]
) -> tuple[list[str], list[MacroMerge]] | None:
    """Set-merge a conflict hunk whose every side is `#define` lines with the same names.
    Return (replacement lines, analyses), or None to leave the hunk untouched."""
    ours_defs = _defines_by_name(ours)
    theirs_defs = _defines_by_name(theirs)
    if ours_defs is None or theirs_defs is None or ours_defs.keys() != theirs_defs.keys():
        return None
    base_defs: dict[str, tuple[str, str, str]] | None = None
    if base is not None:
        base_defs = _defines_by_name(base)
        # A diff3 base that isn't the same macro set means this isn't a clean list edit.
        if base_defs is None or not set(base_defs).issubset(ours_defs):
            return None

    # Set-merging only makes sense for reference *lists*. A macro that is one token on
    # every side is a scalar (`#define MONEY 1000`); unioning two rival values would be
    # wrong, so if no macro in the hunk is ever multi-token, leave it as a real conflict.
    sides = [ours_defs, theirs_defs] + ([base_defs] if base_defs is not None else [])
    if all(len(defs[name][2].split()) <= 1 for defs in sides for name in defs):
        return None

    lines: list[str] = []
    merges: list[MacroMerge] = []
    for name, (indent, _, ours_value) in ours_defs.items():
        theirs_value = theirs_defs[name][2]
        base_value = base_defs[name][2] if base_defs is not None and name in base_defs else None
        ours_tokens = ours_value.split()
        theirs_tokens = theirs_value.split()
        base_tokens = base_value.split() if base_value is not None else None
        merged, removed_ours, removed_theirs = merge_macro_tokens(
            base_tokens, ours_tokens, theirs_tokens
        )
        base_set = set(base_tokens) if base_tokens is not None else set()
        merges.append(
            MacroMerge(
                name=name,
                merged=merged,
                added_ours=sorted(set(ours_tokens) - base_set) if base_tokens is not None else [],
                added_theirs=(
                    sorted(set(theirs_tokens) - base_set) if base_tokens is not None else []
                ),
                removed_ours=sorted(removed_ours),
                removed_theirs=sorted(removed_theirs),
                duplicates=_find_duplicates(ours_tokens, base_tokens, theirs_tokens),
                has_base=base_tokens is not None,
            )
        )
        lines.append(f"{indent}#define {name} {' '.join(merged)}".rstrip())
    return lines, merges


def _find_duplicates(
    ours: list[str], base: list[str] | None, theirs: list[str]
) -> dict[str, list[str]]:
    sides = {"ours": ours, "theirs": theirs}
    if base is not None:
        sides["base"] = base
    out: dict[str, list[str]] = {}
    for side, tokens in sides.items():
        dups = sorted({t for t in tokens if tokens.count(t) > 1})
        if dups:
            out[side] = dups
    return out


def resolve_macro_conflicts(text: str, *, marker_size: int = 7) -> MacroResolveResult:
    """Scan conflict-marked `text`, set-merge every `#define` list conflict, and leave all
    other conflicts exactly as they were. A confident add/remove split needs the diff3
    base (`merge.conflictStyle = diff3`/`zdiff3`); a hunk without one is unioned as a safe
    superset and flagged (`has_base=False`).

    Line endings are preserved: the file's own newline (CRLF or LF) and whether it ends in
    one are kept, so an unchanged region round-trips byte-for-byte."""
    out_lines: list[str] = []
    merges: list[MacroMerge] = []
    resolved = remaining = 0

    newline = "\r\n" if "\r\n" in text else "\r" if "\r" in text else "\n"
    trailing = newline if text.endswith(("\n", "\r")) else ""
    lines = text.splitlines()  # drops each line's terminator (\r\n, \n, or \r)
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_marker(line, "<", marker_size):
            out_lines.append(line)
            index += 1
            continue

        # Collect the hunk: ours .. (optional ||| base) .. === theirs .. >>>.
        ours: list[str] = []
        base: list[str] | None = None
        theirs: list[str] = []
        bucket = ours
        closed = False
        cursor = index + 1
        while cursor < len(lines):
            current = lines[cursor]
            if _is_marker(current, "|", marker_size):
                base = []
                bucket = base
            elif _is_marker(current, "=", marker_size):
                bucket = theirs
            elif _is_marker(current, ">", marker_size):
                closed = True
                cursor += 1
                break
            else:
                bucket.append(current)
            cursor += 1

        replacement = _resolve_hunk(ours, base, theirs) if closed else None
        if replacement is None:
            out_lines.extend(lines[index:cursor])  # leave the hunk verbatim
            remaining += 1 if closed else 0
        else:
            hunk_lines, hunk_merges = replacement
            out_lines.extend(hunk_lines)
            merges.extend(hunk_merges)
            resolved += 1
        index = cursor

    text_out = newline.join(out_lines) + trailing if out_lines else text
    return MacroResolveResult(text=text_out, merges=merges, resolved=resolved, remaining=remaining)


def _tokens(names: list[str], limit: int = 12) -> str:
    if not names:
        return "(none)"
    shown = ", ".join(names[:limit])
    return shown if len(names) <= limit else f"{shown}, +{len(names) - limit} more"


def format_macro_report(result: MacroResolveResult) -> str:
    """A human-readable per-macro add/remove report, ending with the deletions to verify."""
    out: list[str] = []
    verify: list[str] = []
    for merge in result.merges:
        if merge.has_base:
            head = f"#define {merge.name}  ({len(merge.merged)} refs after merge)"
        else:
            head = f"#define {merge.name}  ({len(merge.merged)} refs; NO base - union only)"
        out.append(head)
        out.append(f"  + added by ours   ({len(merge.added_ours)}): {_tokens(merge.added_ours)}")
        out.append(
            f"  + added by theirs ({len(merge.added_theirs)}): {_tokens(merge.added_theirs)}"
        )
        if merge.removed_both:
            out.append(
                f"  - removed by both ({len(merge.removed_both)}): {_tokens(merge.removed_both)}"
            )
        for token, side in merge.removed_one_side:
            out.append(f"  ! removed by {side} only (kept by the other, dropped): {token}")
            verify.append(f"{merge.name}: {token} (removed by {side})")
        for side, dups in merge.duplicates.items():
            out.append(f"  ! duplicate tokens in {side}: {_tokens(dups)}")
        out.append("")

    out.append(
        f"resolved {result.resolved} #define conflict(s); "
        f"{result.remaining} other conflict(s) left for manual merge."
    )
    if verify:
        out.append("")
        out.append("VERIFY these one-sided deletions are intentional (not obsolete re-adds):")
        out.extend(f"  - {item}" for item in verify)
    return "\n".join(out)
