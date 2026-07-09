"""Corpus scan that bootstraps/validates sage_ini.parser.keywords.

Parses every corpus file and reports diagnostics with source context, so a
missing block-opening keyword (which surfaces as stray-end / unclosed-block)
can be identified and added to BLOCK_OPENING_KEYWORDS.

Usage: python tools/scan_block_keywords.py <root> [<root> ...] [--context N] [--max M]
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sage_ini.parser.blockparser import parse_file  # noqa: E402,PLC0415
from sage_ini.parser.io import iter_ini_files, read_text  # noqa: E402,PLC0415


def suggest_opener(text_lines: list[str], end_line: int) -> str | None:
    """For a stray End at 1-based `end_line`, guess the missed opener key.

    Walks backward to the nearest `key = value` line that directly follows a
    blank/comment/End/file-start boundary - the usual shape of a missed
    block-opening attribute.
    """
    from sage_ini.parser.lexer import split_comment  # noqa: PLC0415

    for number in range(end_line - 1, 0, -1):
        content, _ = split_comment(text_lines[number - 1])
        if not content:
            continue
        if content.lower() == "end":
            return None
        if "=" not in content:
            continue
        prev_content = ""
        for prev in range(number - 1, 0, -1):
            prev_content, _ = split_comment(text_lines[prev - 1])
            if prev_content:
                break
        if not prev_content or prev_content.lower() == "end":
            return content.partition("=")[0].strip()
    return None


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("roots", nargs="+", type=Path)
    cli.add_argument("--context", type=int, default=3)
    cli.add_argument("--max", type=int, default=20, help="max files to detail")
    cli.add_argument("--suggest", action="store_true", help="aggregate suspected opener keys")
    cli.add_argument("--list", action="store_true", help="one line per failing file")
    args = cli.parse_args()

    bad_files = 0
    total = 0
    codes = Counter()
    suggestions = Counter()
    suggestion_files = {}
    detailed = 0

    for root in args.roots:
        for path in iter_ini_files(root):
            total += 1
            result = parse_file(path)
            if not result.diagnostics:
                continue

            bad_files += 1
            codes.update(d.code for d in result.diagnostics)
            text_lines = read_text(path).splitlines()

            if args.list:
                local = Counter(d.code for d in result.diagnostics)
                first = next(iter(result.diagnostics))
                print(
                    f"{str(path.relative_to(root)):70} {dict(local)}  first@{first.span.line_start}"
                )

            if args.suggest:
                for diag in result.diagnostics:
                    if diag.code == "unclosed-block":
                        name = diag.message.rpartition("'")[0].rpartition("'")[2]
                        suggestions[f"[bare] {name}"] += 1
                        suggestion_files.setdefault(f"[bare] {name}", path.name)
                        continue
                    if diag.code != "stray-end":
                        continue
                    key = suggest_opener(text_lines, diag.span.line_start)
                    if key:
                        suggestions[key] += 1
                        suggestion_files.setdefault(key, path.name)

            if detailed >= args.max:
                continue
            detailed += 1

            print(f"\n=== {path.relative_to(root)} ({len(result.diagnostics)} diagnostics)")
            for diag in list(result.diagnostics)[:3]:
                print(f"  {diag}")
                start = max(0, diag.span.line_start - 1 - args.context)
                stop = min(len(text_lines), diag.span.line_start + args.context)
                for number in range(start, stop):
                    marker = ">>" if number == diag.span.line_start - 1 else "  "
                    print(f"  {marker} {number + 1:5} {text_lines[number].rstrip()}")

    print(f"\nfiles: {total}, with diagnostics: {bad_files}")
    print(f"diagnostic codes: {dict(codes)}")
    if suggestions:
        print("\nsuspected missing opener keys:")
        for key, count in suggestions.most_common(40):
            print(f"{count:7}  {key:35} e.g. {suggestion_files[key]}")
    return 0 if bad_files == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
