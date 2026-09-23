"""Every `.md` file the source and docs point at is one a reader of the repository can open.

Checked against `git ls-files` rather than the disk: a gitignored working note exists on the
machine that wrote it and nowhere else, so a link to it passes locally and dangles for everyone
else. Outside a git checkout (an sdist, a wheel) there is nothing to compare against and the test
skips.
"""

import re
import subprocess
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files that mention `.md` names which are not links: one-off RE scripts, the tests themselves, and
# the review plan that lists the dead links it set out to remove.
_SKIPPED_PREFIXES = ("sage_patch/scripts/", "tests/", "docs/code-review-plan.md")
# Written by a tool into its output folder, never committed.
_GENERATED = {"battle-school.md"}

_MENTION = re.compile(r"(?<![\w.…/-])([\w-][\w./-]*\.md)\b")
_LINK = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")


def _tracked_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return out.splitlines()


def _dangling() -> list[str]:
    tracked = _tracked_files()
    tracked_set = set(tracked)
    names = {PurePosixPath(p).name.lower() for p in tracked if p.endswith(".md")} | _GENERATED
    problems = []
    for rel in tracked:
        if not rel.endswith((".py", ".md")) or rel.startswith(_SKIPPED_PREFIXES):
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for target in _LINK.findall(line):
                if "://" in target:
                    continue
                resolved = PurePosixPath(rel).parent / target
                parts: list[str] = []
                for part in resolved.parts:
                    if part == "..":
                        if parts:
                            parts.pop()
                    elif part != ".":
                        parts.append(part)
                if "/".join(parts) not in tracked_set:
                    problems.append(f"{rel}:{lineno}: link to {target}")
            for mention in _MENTION.findall(line):
                if PurePosixPath(mention).name.lower() not in names:
                    problems.append(f"{rel}:{lineno}: mentions {mention}")
    return problems


def test_markdown_references_resolve_to_tracked_files():
    problems = _dangling()
    assert not problems, "references to .md files that are not in the repository:\n" + "\n".join(
        problems
    )
