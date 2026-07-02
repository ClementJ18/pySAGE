"""Structure-aware diff between two assembled games: given two mod ini folders (or two git
refs of one repo), report what definitions were added, removed, or changed, and for a changed
definition which fields and sub-modules moved. The intent is a human-readable changelog of game
data — "GondorFighter BuildCost 100 -> 150", "ActiveBody MaxHealth 300 -> 350" — rather than a
textual diff of the source.

Comparison runs on the loaded `Game` model, not the text: definitions are matched by table and
name, fields by key, and sub-modules (behaviors, draws, nuggets, nested states) recursively by
their slot and name. Raw field values are compared as read (no conversion), so a malformed value
diffs as plain text instead of aborting the run.
"""

import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from sage_ini.loader import load_game
from sage_ini.model.objects import IniObject

__all__ = [
    "FieldChange",
    "ChildChange",
    "ObjectDiff",
    "TableDiff",
    "DictDiff",
    "GameDiff",
    "diff_objects",
    "diff_games",
    "diff_folders",
    "diff_refs",
    "git_worktree",
    "format_game_diff",
]


@dataclass(frozen=True, slots=True)
class FieldChange:
    key: str
    old: str | None  # None when the field was added
    new: str | None  # None when the field was removed

    def to_dict(self) -> dict:
        return {"key": self.key, "old": self.old, "new": self.new}


@dataclass(frozen=True, slots=True)
class ChildChange:
    slot: str  # where the sub-object lives ("module", a nested group, a marker group)
    label: str  # the sub-object's descriptor (its name, which carries a module's tag)
    diff: "ObjectDiff"

    def to_dict(self) -> dict:
        return {"slot": self.slot, "label": self.label, "diff": self.diff.to_dict()}


@dataclass(slots=True)
class ObjectDiff:
    """What changed inside one definition: its own field edits plus added / removed / changed
    sub-modules (each change itself an `ObjectDiff`, so the structure nests arbitrarily deep)."""

    fields: list[FieldChange] = field(default_factory=list)
    added_children: list[tuple[str, str]] = field(default_factory=list)  # (slot, label)
    removed_children: list[tuple[str, str]] = field(default_factory=list)
    changed_children: list[ChildChange] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.fields or self.added_children or self.removed_children or self.changed_children
        )

    def to_dict(self) -> dict:
        return {
            "fields": [change.to_dict() for change in self.fields],
            "added_children": [{"slot": s, "label": n} for s, n in self.added_children],
            "removed_children": [{"slot": s, "label": n} for s, n in self.removed_children],
            "changed_children": [change.to_dict() for change in self.changed_children],
        }


@dataclass(frozen=True, slots=True)
class TableDiff:
    key: str  # the Game table (objects, weapons, upgrades, ...)
    added: list[str]  # names present only in the new game
    removed: list[str]  # names present only in the old game
    changed: list[tuple[str, ObjectDiff]]  # name -> what changed inside it

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": [{"name": name, "diff": diff.to_dict()} for name, diff in self.changed],
        }


@dataclass(frozen=True, slots=True)
class DictDiff:
    """Added / removed / changed entries of a flat name->value table (macros, strings)."""

    added: list[tuple[str, str]]
    removed: list[tuple[str, str]]
    changed: list[tuple[str, str, str]]  # name, old value, new value

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def to_dict(self) -> dict:
        return {
            "added": [{"name": n, "value": v} for n, v in self.added],
            "removed": [{"name": n, "value": v} for n, v in self.removed],
            "changed": [{"name": n, "old": o, "new": w} for n, o, w in self.changed],
        }


@dataclass(frozen=True, slots=True)
class GameDiff:
    tables: list[TableDiff]
    macros: DictDiff
    strings: DictDiff | None  # None unless string comparison was requested

    def to_dict(self) -> dict:
        """The whole diff as JSON-ready data. Tables with no changes are dropped, mirroring
        the text report; `strings` is None unless string comparison was requested."""
        return {
            "tables": [
                table.to_dict()
                for table in self.tables
                if table.added or table.removed or table.changed
            ],
            "macros": self.macros.to_dict(),
            "strings": self.strings.to_dict() if self.strings is not None else None,
        }


def _norm(value) -> tuple[str, ...] | str:
    """A comparable form of a raw field value: a repeated key (stored as a list) compares as the
    whole ordered tuple, a scalar as its string."""
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return str(value)


def _fmt(value) -> str:
    """A display form of a raw field value (a repeated key joined back into one line)."""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _diff_fields(old: IniObject, new: IniObject) -> list[FieldChange]:
    old_fields = old._fields
    new_fields = new._fields
    changes: list[FieldChange] = []
    for key in sorted(old_fields.keys() | new_fields.keys()):
        in_old = key in old_fields
        in_new = key in new_fields
        if in_old and not in_new:
            changes.append(FieldChange(key, _fmt(old_fields[key]), None))
        elif in_new and not in_old:
            changes.append(FieldChange(key, None, _fmt(new_fields[key])))
        elif _norm(old_fields[key]) != _norm(new_fields[key]):
            changes.append(FieldChange(key, _fmt(old_fields[key]), _fmt(new_fields[key])))
    return changes


def _child_objects(obj: IniObject) -> list[tuple[str, IniObject]]:
    """Every sub-object of `obj`, tagged with the slot it lives in: typed modules, the items of
    each nested group, and the typed items of each marker group. Raw (untyped) marker items have
    no fields to recurse into and are skipped."""
    children: list[tuple[str, IniObject]] = []
    for module in obj._modules:
        children.append(("module", module))
    for group, items in obj._nested_data.items():
        for item in items:
            children.append((group, item))
    for group, items in obj._marker_grouped.items():
        for item in items:
            if isinstance(item, IniObject):
                children.append((group, item))
    return children


def _child_key(slot: str, obj: IniObject) -> tuple[str, str, str]:
    """Match key for a sub-object across two versions: its slot, type, and name. A module's name
    carries its `ModuleTag_*`, so retagging shows as a remove + add rather than a false edit."""
    return (slot, type(obj).__name__, str(obj.name))


def diff_objects(old: IniObject, new: IniObject) -> ObjectDiff:
    """Recursively diff two same-named definitions: their scalar fields and their sub-modules."""
    result = ObjectDiff(fields=_diff_fields(old, new))

    old_buckets: dict[tuple[str, str, str], list[IniObject]] = defaultdict(list)
    new_buckets: dict[tuple[str, str, str], list[IniObject]] = defaultdict(list)
    for slot, child in _child_objects(old):
        old_buckets[_child_key(slot, child)].append(child)
    for slot, child in _child_objects(new):
        new_buckets[_child_key(slot, child)].append(child)

    for key in sorted(old_buckets.keys() | new_buckets.keys()):
        slot, _, label = key
        old_list = old_buckets.get(key, [])
        new_list = new_buckets.get(key, [])
        # Same-keyed siblings (rare) pair off in source order; the surplus is added or removed.
        for old_child, new_child in zip(old_list, new_list, strict=False):
            child_diff = diff_objects(old_child, new_child)
            if not child_diff.is_empty():
                result.changed_children.append(ChildChange(slot, label, child_diff))
        for _ in old_list[len(new_list) :]:
            result.removed_children.append((slot, label))
        for _ in new_list[len(old_list) :]:
            result.added_children.append((slot, label))
    return result


def _dict_diff(old: dict[str, str], new: dict[str, str]) -> DictDiff:
    added = [(k, new[k]) for k in sorted(new.keys() - old.keys())]
    removed = [(k, old[k]) for k in sorted(old.keys() - new.keys())]
    changed = [(k, old[k], new[k]) for k in sorted(old.keys() & new.keys()) if old[k] != new[k]]
    return DictDiff(added, removed, changed)


def diff_games(old, new, *, strings: bool = False) -> GameDiff:
    """Diff two assembled `Game`s table by table (plus macros, and strings on request)."""
    tables: list[TableDiff] = []
    for key in sorted(old.tables.keys() | new.tables.keys()):
        old_table = old.tables.get(key, {})
        new_table = new.tables.get(key, {})
        added = sorted(str(n) for n in new_table.keys() - old_table.keys())
        removed = sorted(str(n) for n in old_table.keys() - new_table.keys())
        changed: list[tuple[str, ObjectDiff]] = []
        for name in sorted(old_table.keys() & new_table.keys(), key=str):
            obj_diff = diff_objects(old_table[name], new_table[name])
            if not obj_diff.is_empty():
                changed.append((str(name), obj_diff))
        if added or removed or changed:
            tables.append(TableDiff(key, added, removed, changed))

    macros = _dict_diff(old.macros, new.macros)
    string_diff = _dict_diff(old.strings, new.strings) if strings else None
    return GameDiff(tables, macros, string_diff)


def diff_folders(
    old_dir: str | Path,
    new_dir: str | Path,
    *,
    strings: bool = False,
    overlays: tuple[str | Path, ...] = (),
    bases: tuple[str | Path, ...] = (),
) -> GameDiff:
    """Assemble each folder into a `Game` and diff them."""
    old = load_game(old_dir, overlays=overlays, bases=bases).game
    new = load_game(new_dir, overlays=overlays, bases=bases).game
    return diff_games(old, new, strings=strings)


def _clean_git_env() -> dict[str, str]:
    """The environment for a nested git call, with the repo-location variables git exports into a
    hook (GIT_DIR, GIT_INDEX_FILE, GIT_WORK_TREE, ...) stripped out. Without this, running the
    diff from inside a pre-commit hook makes `git worktree add` resolve its index against the
    committing repo instead of the new worktree, failing with a bogus `index.lock` path."""
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("GIT_") and key not in ("GIT_SSH", "GIT_SSH_COMMAND"):
            del env[key]
    return env


@contextmanager
def git_worktree(repo: str | Path, ref: str):
    """Check `ref` out into a throwaway detached worktree of `repo`, yield its path, then remove
    it — so two commits can be diffed without disturbing the working tree. The worktree is a real
    checkout of the whole repo; point at the ini subfolder within it."""
    repo = str(repo)
    env = _clean_git_env()
    holder = Path(tempfile.mkdtemp(prefix="sage-diff-"))
    tree = holder / "tree"
    try:
        subprocess.run(
            ["git", "-C", repo, "worktree", "add", "--detach", str(tree), ref],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        yield tree
    finally:
        subprocess.run(
            ["git", "-C", repo, "worktree", "remove", "--force", str(tree)],
            capture_output=True,
            text=True,
            env=env,
        )
        shutil.rmtree(holder, ignore_errors=True)


def diff_refs(
    repo: str | Path,
    old_ref: str,
    new_ref: str,
    subpath: str | Path = ".",
    *,
    strings: bool = False,
    overlays: tuple[str | Path, ...] = (),
    bases: tuple[str | Path, ...] = (),
) -> GameDiff:
    """Diff the ini folder `subpath` between two git refs of `repo`, materialising each ref in a
    temporary worktree."""
    with git_worktree(repo, old_ref) as old_tree, git_worktree(repo, new_ref) as new_tree:
        return diff_folders(
            old_tree / subpath,
            new_tree / subpath,
            strings=strings,
            overlays=overlays,
            bases=bases,
        )


def _render_object_diff(diff: ObjectDiff, indent: str, lines: list[str]) -> None:
    for change in diff.fields:
        if change.old is None:
            lines.append(f"{indent}+ {change.key} = {change.new}")
        elif change.new is None:
            lines.append(f"{indent}- {change.key} = {change.old}")
        else:
            lines.append(f"{indent}{change.key}: {change.old} -> {change.new}")
    for slot, label in diff.added_children:
        lines.append(f"{indent}+ {slot}: {label}")
    for slot, label in diff.removed_children:
        lines.append(f"{indent}- {slot}: {label}")
    for child in diff.changed_children:
        lines.append(f"{indent}{child.slot}: {child.label}")
        _render_object_diff(child.diff, indent + "    ", lines)


def _render_dict_diff(title: str, diff: DictDiff, lines: list[str]) -> None:
    total = len(diff.added) + len(diff.removed) + len(diff.changed)
    lines.append(f"## {title} ({total})")
    for name, value in diff.added:
        lines.append(f"+ {name} = {value}")
    for name, value in diff.removed:
        lines.append(f"- {name} = {value}")
    for name, old, new in diff.changed:
        lines.append(f"{name}: {old} -> {new}")
    lines.append("")


def format_game_diff(diff: GameDiff, old_label: str, new_label: str) -> str:
    """Render a `GameDiff` as a human-readable changelog grouped by table then definition."""
    added = sum(len(t.added) for t in diff.tables)
    removed = sum(len(t.removed) for t in diff.tables)
    changed = sum(len(t.changed) for t in diff.tables)
    lines = [
        f"# ini diff: {old_label} -> {new_label}",
        f"{added} added, {removed} removed, {changed} changed definition(s) "
        f"across {len(diff.tables)} table(s)",
        "",
    ]

    for table in diff.tables:
        lines.append(f"## {table.key}")
        for name in table.added:
            lines.append(f"+ {name}")
        for name in table.removed:
            lines.append(f"- {name}")
        for name, obj_diff in table.changed:
            lines.append(f"~ {name}")
            _render_object_diff(obj_diff, "    ", lines)
        lines.append("")

    if not diff.macros.is_empty():
        _render_dict_diff("macros", diff.macros, lines)
    if diff.strings is not None and not diff.strings.is_empty():
        _render_dict_diff("strings", diff.strings, lines)

    if len(lines) <= 3:
        lines.append("(no differences)")
    return "\n".join(lines).rstrip() + "\n"
