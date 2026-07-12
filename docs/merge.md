# Merging SAGE ini in git

Git merges ini files line by line, but SAGE data does not read that way. A single
`Object` definition is dozens of lines long and sits directly against its neighbours, and
a `#define NAME a b c …` macro is really an unordered *set* of references written on one
line. So two branches that touch nearby-but-different definitions, or that both add a
reference to the same macro, collide on adjacency alone — and resolving by hand means
eyeballing definitions (or 100+ names) to guess what each side actually changed. That
guessing is where obsolete references get resurrected and new ones silently dropped.

`sage_ini` ships two helpers that merge ini the way it actually means:

| Tool | Merges by | Use it for |
| --- | --- | --- |
| `sage-ini merge` | **definition identity** — match top-level defs by name, merge field by field | any ini/inc conflict; installs as a git merge driver so this happens automatically |
| `sage-ini macro-merge` | **set membership** — a `#define` list is a set of references | the one thing the structural merge leaves alone: rival edits to a long `#define` reference list |

Both are also usable one-off on a file that already carries conflict markers, so you can
adopt them without touching git config first.

> The examples use the installed `sage-ini` console script. `python -m sage_ini …` is
> equivalent everywhere; the git merge driver specifically calls `sage-ini`, so it must be
> on `PATH` (any `pip install` of this package puts it there).

## Contents

- [Recommended one-time git setup](#recommended-one-time-git-setup)
- [Install the structure-aware merge driver](#install-the-structure-aware-merge-driver)
- [Everyday use](#everyday-use)
- [Resolve a file that already has conflict markers](#resolve-a-file-that-already-has-conflict-markers)
- [Merge three files by hand](#merge-three-files-by-hand)
- [macro-merge: `#define` reference-list conflicts](#macro-merge-define-reference-list-conflicts)
- [How it decides (and when it still conflicts)](#how-it-decides-and-when-it-still-conflicts)
- [Troubleshooting](#troubleshooting)

## Recommended one-time git setup

Turn on diff3 conflict markers. Both tools do their best work with the common ancestor
(the `|||||||` section of a conflict): it lets them tell an **add** from a **remove**
instead of unioning blindly. Without it they still work, but fall back to a 2-way merge
(only identical edits merge silently; a `#define` list becomes a safe superset).

```sh
git config --global merge.conflictStyle zdiff3
```

`zdiff3` is the modern default; plain `diff3` works too. This is a general quality-of-life
setting for any merge — it is not specific to these tools.

## Install the structure-aware merge driver

A git *merge driver* is a program git hands the three versions of a file (base, ours,
theirs) and lets decide the result. Registering `sage-ini` as one makes every `git
merge` / `git rebase` / `git cherry-pick` / `git stash pop` route ini files through the
structural merge automatically.

Two steps: register the driver in git config, then tell git which files it applies to.

```sh
# 1. register the 'sage-ini' driver (this repo only)
sage-ini merge --install

# 2. route ini/inc files through it
printf '*.ini merge=sage-ini\n*.inc merge=sage-ini\n' >> .gitattributes
```

`merge --install` writes two keys into `.git/config`:

```ini
[merge "sage-ini"]
    name = SAGE ini structure-aware merge
    driver = sage-ini merge %O %A %B -L %L -P %P
```

and prints the `.gitattributes` lines to add. (`%O %A %B` are the base/ours/theirs temp
files git passes; `%L` is the conflict-marker length; `%P` is the real path, for
messages.)

**Per-repo vs. global.** `.git/config` is not shared through the repo, so each clone runs
`merge --install` once. To register the driver for *every* repository on your machine
instead, add `--global`:

```sh
sage-ini merge --install --global
```

`.gitattributes`, by contrast, **is** committed — commit it once and every collaborator's
ini files route through the driver as soon as they have run `merge --install` (or
`--global`). A collaborator who has not installed the driver is not broken: git silently
falls back to its built-in text merge for them.

## Everyday use

Once installed, there is nothing to run. `git merge`, `git rebase`, and friends apply the
structural merge to ini/inc files on their own: independent definitions merge silently,
and git only reports a conflict around the fields both sides changed differently. The
result you get is smaller and truer than git's line merge, and any conflict it *does*
leave is an ordinary git conflict you finish the usual way.

## Resolve a file that already has conflict markers

For a file that git (or someone else) already filled with `<<<<<<<` / `=======` /
`>>>>>>>` markers — e.g. you merged before installing the driver — re-merge it
structurally in place:

```sh
sage-ini merge --resolve path/to/file.ini
```

This reconstructs the three sides from the markers, runs the structural merge, and writes
the file back with far fewer (often zero) conflicts — collapsing everything git only
flagged because independent definitions sat next to each other. It is richest when the
markers are diff3-style (`|||||||` base present); with plain markers it does a 2-way
merge. Write elsewhere with `-o out.ini`. Exit status is non-zero while any real conflict
remains, so it fits a script.

## Merge three files by hand

You can also drive the merge directly, outside git — useful in scripts or to preview a
result:

```sh
sage-ini merge base.ini ours.ini theirs.ini -o merged.ini
```

With `base` omitted the merge is 2-way (no common ancestor: only identical edits merge
silently, everything else conflicts). `-L N` sets the conflict-marker length and
`--ours-label` / `--theirs-label` rename the sides written next to the markers.

## macro-merge: `#define` reference-list conflicts

The structural merge deliberately leaves `#define` lists alone — unioning two rival macro
values would be wrong for a *scalar* like `#define MONEY 1000`. `macro-merge` handles the
*list* case: it reads such a conflict as a 3-way set diff against the diff3 base. A token
present on a side but not in base was **added** there; a token in base but absent from a
side was **removed** there. It keeps every addition and honours every removal:

```
result = (base − removed by either) ∪ added by ours ∪ added by theirs
```

Run it on a conflict-marked file. It **reports by default and changes nothing** — pass
`--write` to apply:

```sh
sage-ini macro-merge path/to/file.inc          # dry run: print the per-macro report
sage-ini macro-merge path/to/file.inc --write  # apply the set-merge in place
```

The report lists, per macro, what each side added and removed, and ends with a **VERIFY**
section — the one thing that genuinely needs a human eye:

```
#define EVIL_INFANTRY_HORDES  (37 refs after merge)
  + added by ours   (2): MordorOrcHorde, MordorHaradrimHorde
  + added by theirs (1): IsengardUrukHorde
  - removed by both (1): MordorObsoleteHorde
  ! removed by ours only (kept by the other, dropped): MordorFighterHorde

resolved 1 #define conflict(s); 0 other conflict(s) left for manual merge.

VERIFY these one-sided deletions are intentional (not obsolete re-adds):
  - EVIL_INFANTRY_HORDES: MordorFighterHorde (removed by ours)
```

A **one-sided deletion** — a token one branch dropped while the other left it in place —
is the merge's only judgement call: it honours the deletion, and lists it under VERIFY so
you confirm a deliberate removal rather than discover a resurrected reference later.

Notes:

- It touches **only** `#define` list hunks. A scalar `#define` and every non-macro
  conflict are left byte-for-byte as git wrote them, so you finish the file normally
  afterward.
- It needs **diff3 markers** for a confident add/remove split (set
  `merge.conflictStyle = zdiff3`, above). A hunk with no base is unioned as a safe
  superset and flagged `NO base — union only` in the report.
- `--json` emits the same analysis for tooling; `-o out.inc` writes elsewhere; `-L N`
  matches a non-default marker length. Exit status is non-zero while other (non-macro)
  conflicts remain.

You can wire `macro-merge --write` into a git driver the same way as `merge` if a repo's
`#define` lists churn constantly, but the common workflow is to run the structural driver
automatically and reach for `macro-merge` by hand on the occasional macro collision.

## How it decides (and when it still conflicts)

**Structural merge.** Each side is parsed to the comment-preserving AST (node equality
ignores whitespace and spans, so reflowed or moved blocks read as unchanged), top-level
definitions are matched by name, and a definition only counts as edited if it changed. Of
two edits to the same definition:

- only one side changed it → that side wins, silently;
- both changed it the same way → merges silently;
- both changed it differently → recurse into the block's fields and raise a git conflict
  **only** around the fields that actually overlap.

A block with repeated child keys (a multi-slot `WeaponSet`, repeated bare-value lines)
is not safely addressable by key, so it falls back to a textual diff3 of just that block's
body — still confining the conflict to the one block. A modify/delete (one side edits a
definition the other removed) is always surfaced as a conflict, never silently dropped.

**macro-merge.** Because an added token is never in base and a removed token always is,
additions and removals are disjoint and the set-merge is deterministic — there is no
token-level "conflict." The only thing it surfaces for review is the one-sided deletion
described above.

Both tools preserve the source file's encoding (SAGE data mixes utf-8, windows-1252 and
latin-1) and its newline style, so unchanged regions round-trip byte-for-byte.

## Troubleshooting

- **`git not found on PATH`** from `merge --install` — git is not callable from this
  shell; the command only shells out to `git config`.
- **The driver does nothing on merge.** Check both halves are in place: `git config --get
  merge.sage-ini.driver` should print the driver line, and `.gitattributes` must route the
  file (`git check-attr merge -- some/file.ini` should say `merge: sage-ini`). Remember
  `.git/config` is per-clone — a fresh clone needs `merge --install` again (or install
  `--global`).
- **macro-merge reports `NO base — union only`.** The conflict has no diff3 base, so
  removals can't be detected and the result is a superset. Set
  `merge.conflictStyle = zdiff3` and re-create the conflict to get add/remove precision.
- **A `#define` scalar is still conflicted.** That is intentional — `macro-merge` only
  set-merges reference *lists*, never single-value macros. Resolve it as a normal
  conflict.
- **A collaborator merged without the driver.** Nothing breaks; git used its text merge.
  Run `sage-ini merge --resolve <file>` afterward to collapse the spurious conflicts
  structurally.
