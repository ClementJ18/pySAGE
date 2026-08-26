"""``sage-patch`` — apply, verify and list binary patches for the ROTWK SAGE engine (`game.dat`).

    sage-patch list
    sage-patch info   commandset-limit
    sage-patch apply  commandset-limit --count 64 --in game.dat.backup --out game.dat
    sage-patch verify commandset-limit --count 64 game.dat
    sage-patch sagepatch game.dat -o /path/to/mod/.sagepatch

``list`` names every registered patch in a table; ``info`` opens one of them up - its author,
its source and write-up, its parameters and the INI surface it adds - and reads a binary too
when given ``--file``, to say whether that `game.dat` carries it and with which parameters.

Each registered patch (see :mod:`sage_patch.registry`) supplies its own parameters; ``apply``
and ``verify`` grow a sub-command per patch. ``apply`` never modifies its input — it writes the
patched copy to ``--out`` (or overwrites ``--in`` when ``--out`` is omitted). ``verify`` exits
non-zero and prints the mismatches when a file does not carry the requested patch.

``sagepatch`` goes the other way: instead of naming a patch, it reads a binary and reports what
is *in* it, as the `.sagepatch` file `sage_ini` and `sage_lint` load so the mod's INI is checked
against the engine it actually runs on (see :mod:`sage_patch.sagepatch`).
"""

from __future__ import annotations

import argparse
import difflib
import inspect
import logging
import re
import sys
import textwrap
from collections.abc import Sequence
from pathlib import Path

from sage_ini.engine import Engine, dump_engine, load_engine
from sage_patch.patcher import EXPERIMENTAL_WARNING, Patch, apply_patches
from sage_patch.registry import PATCHES
from sage_patch.sagepatch import Generated, differences, generate, generate_from_patches


def _cmd_list(args: argparse.Namespace) -> int:
    """Every registered patch: what it is called, whether it is experimental, whose work it is,
    and what it does.

    **The author is a column rather than a footnote**, because this is the command somebody runs
    when they are writing their mod's credits. The alternative is reading it back out of an
    `apply` log, which only names the patches that particular build used - fine for a build, no
    use at all for "who do I need to thank". See the README's "Credit" section.

    `-` for a patch that names nobody, so the column stays readable and an unattributed patch is
    visible as a gap rather than as a blank that reads like alignment.

    **`exp` is a column too, and it is spelled out again underneath.** A three-letter marker is
    the only thing that fits between the name and the author, and on its own it is a riddle; a
    footer with no marker above it is a list nobody maps back onto the rows. The pair is what
    makes the warning land before somebody picks a patch, which is the one moment it is cheap to
    act on - `apply` warns too, but by then they have chosen.
    """
    width = max((len(name) for name in PATCHES), default=0)
    authors = max((len(cls.author) for cls in PATCHES.values()), default=0)
    experimental = [name for name, cls in PATCHES.items() if cls.experimental]
    for name, cls in PATCHES.items():
        mark = "exp" if cls.experimental else "   "
        print(f"{name:<{width}}  {mark}  {cls.author or '-':<{authors}}  {cls.description}")
    if experimental:
        print(f"\nexp = {EXPERIMENTAL_WARNING}")
        print(f"      {', '.join(experimental)}")
    return 0


#: A `docs/<name>.md` reference in a patch module's docstring - how a patch points at the reverse
#: engineering behind it. The write-up is named in prose rather than in an attribute, so `info`
#: reads the prose; a name that no longer exists on disk is dropped rather than printed as a
#: broken path.
_DOC_REFERENCE = re.compile(r"docs/([A-Za-z0-9._-]+\.md)")

#: A Sphinx cross-reference role in a docstring - ``:class:`~sage_patch.patcher.Patch```. The
#: docstrings are written for the API docs and this command prints them at a terminal, so a role
#: is reduced to the name it points at rather than shown as markup.
_ROLE = re.compile(r":[a-z]+:`~?([^`]+)`")

#: How wide the prose is wrapped, before the two-space indent every section body carries.
_WIDTH = 92

_PACKAGE = Path(__file__).resolve().parent
_ROOT = _PACKAGE.parent


def _relative(path: Path) -> str:
    """`path` as the repo-relative path it is written down as elsewhere, or as it stands when it
    lives outside the checkout (an installed package)."""
    try:
        return path.resolve().relative_to(_ROOT).as_posix()
    except ValueError:
        return str(path)


def _module_doc(cls: type[Patch]) -> str:
    return inspect.getdoc(sys.modules[cls.__module__]) or ""


def _prose(text: str) -> str:
    """A docstring paragraph as one line of plain text: no line breaks, no RST roles, no doubled
    backticks."""
    unrolled = _ROLE.sub(lambda match: match.group(1).rsplit(".", 1)[-1], " ".join(text.split()))
    return unrolled.replace("``", "`")


def _write_ups(cls: type[Patch]) -> list[str]:
    """The RE write-ups this patch's module names, in the order it names them, deduplicated."""
    found: list[str] = []
    for name in _DOC_REFERENCE.findall(_module_doc(cls)):
        doc = _PACKAGE / "docs" / name
        if doc.exists() and (relative := _relative(doc)) not in found:
            found.append(relative)
    return found


def _parameters(cls: type[Patch]) -> list[tuple[str, str]]:
    """This patch's CLI options as `(invocation, help)`, by asking it to register them on a
    throwaway parser - the same call `apply` and `verify` make, so the list cannot drift from
    what those two accept."""
    parser = argparse.ArgumentParser(add_help=False)
    cls.add_cli_arguments(parser)
    rows: list[tuple[str, str]] = []
    for action in parser._actions:  # noqa: SLF001 - argparse exposes its actions no other way
        # A tuple metavar (one name per value of a multi-value option) has no one-line spelling
        # here, so such an option is named by its dest, as argparse itself would without one.
        metavar = action.metavar if isinstance(action.metavar, str) else action.dest.upper()
        if action.option_strings:
            joined = ", ".join(action.option_strings)
            invocation = joined if action.nargs == 0 else f"{joined} {metavar}"
        else:
            invocation = metavar
        rows.append((invocation, action.help or ""))
    return rows


def _surface_lines(engine: Engine) -> list[str]:
    """One line per delta an engine description carries, kind first so a patch that adds a field
    and a token reads as two kinds rather than as one undifferentiated list.

    A patch that changes no INI says so rather than printing nothing: "does this need anything
    written into my INI" is the question this section is here to answer, and "no" is an answer."""
    lines: list[str] = []
    for block in engine.blocks:
        if block.removed:
            lines.append(f"block    {block.name} - no longer registered")
        else:
            base = f" (a {block.base})" if block.base else ""
            lines.append(f"block    {block.name}{base}")
    for field in engine.fields:
        default = "" if field.default is None else f" = {field.default}"
        lines.append(f"field    {field.block}.{field.name} : {field.type}{default}")
    for noop in engine.noops:
        reason = f" - {noop.reason}" if noop.reason else ""
        lines.append(f"retired  {noop.block}.{noop.name}{reason}")
    for member in engine.enum_members:
        value = "" if member.value is None else f" = {member.value}"
        lines.append(f"token    {member.enum}.{member.name}{value}")
    for limit in engine.limits:
        lines.append(f"limit    {limit.name} = {limit.value}")
    return lines or ["none - it adds no field, token or limit to the INI the engine accepts"]


def _section(title: str, lines: Sequence[str]) -> None:
    if not lines:
        return
    print(f"\n{title}")
    for line in lines:
        print(f"  {line}")


def _wrapped(text: str, indent: str = "") -> list[str]:
    """`text` wrapped to the section width, every line after the first indented by `indent` - so
    a two-column row keeps its second column when the right-hand side runs long."""
    return textwrap.wrap(text, width=_WIDTH, subsequent_indent=indent) or [""]


def _cmd_info(args: argparse.Namespace) -> int:
    """Everything this package knows about one patch, in one screen: what it does, whose work it
    is, where its assembly and its write-up live, what parameters it takes, and what it changes
    about the INI the engine accepts.

    `list` answers "which patches are there"; this answers "what am I about to apply", which is
    otherwise spread across `apply <name> --help` (the parameters), the module docstring (the
    reverse engineering) and a generated `.sagepatch` (the INI surface) - three places, two of
    which mean opening the source.

    With `--file` it reads a binary as well, so the same screen says whether *this* `game.dat`
    carries the patch and with which parameters, and describes the surface as applied rather
    than as defaulted."""
    cls = PATCHES.get(args.patch)
    if cls is None:
        print(f"unknown patch {args.patch!r}", file=sys.stderr)
        close = difflib.get_close_matches(args.patch, PATCHES, n=3)
        hint = f"did you mean {', '.join(close)}?  " if close else ""
        print(f"{hint}`sage-patch list` names them all", file=sys.stderr)
        return 2

    print(cls.name)
    for line in _wrapped(cls.description):
        print(f"  {line}")
    print(f"\nauthor     {cls.author or '-'}")
    print(f"source     {_relative(Path(inspect.getfile(cls)))}")
    for index, doc in enumerate(_write_ups(cls)):
        print(f"{'write-up  ' if index == 0 else '          '} {doc}")
    if cls.experimental:
        _section("EXPERIMENTAL", _wrapped(EXPERIMENTAL_WARNING))

    # The first paragraph of the module docstring: what the patch is, in the words of the person
    # who wrote the assembly. The rest of that docstring is the derivation, which is what the
    # write-up above is for.
    _section("about", _wrapped(_prose(_module_doc(cls).split("\n\n")[0])))

    parameters = _parameters(cls)
    if not parameters:
        _section("parameters", ["none"])
    else:
        width = max(len(invocation) for invocation, _ in parameters)
        rows: list[str] = []
        for invocation, help_ in parameters:
            column = f"{invocation:<{width}}  "
            rows.extend(_wrapped(f"{column}{help_}", indent=" " * len(column)))
        _section("parameters", rows)

    if args.file is None:
        _section("INI surface (default parameters)", _surface_lines(cls().ini_surface()))
        return 0

    data = Path(args.file).read_bytes()
    found = cls.detect(data)
    if found is None:
        _section(f"in {args.file}", ["not found - this binary does not carry the patch"])
        _section("INI surface (default parameters)", _surface_lines(cls().ini_surface()))
        return 0
    _section(f"in {args.file}", [f"applied, as {found}"])
    _section("INI surface (as applied)", _surface_lines(found.ini_surface()))
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    patch = PATCHES[args.patch].from_cli_args(args)
    out = apply_patches(args.src, [patch], output=args.out)
    print(f"wrote {out}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    patch = PATCHES[args.patch].from_cli_args(args)
    data = Path(args.file).read_bytes()
    problems = patch.verify(data)
    if problems:
        print(f"FAIL: {args.file} does not carry {patch}:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"OK: {args.file} carries {patch}")
    return 0


def _report(generated: Generated, stream) -> None:
    """The human half of `sagepatch`: what was recognised and anything worth knowing."""
    if generated.patches:
        print("patches found:", file=stream)
        for patch in generated.patches:
            print(f"  - {patch}", file=stream)
    else:
        print("no known patch found in this binary", file=stream)
    for note in generated.notes:
        print(f"note: {note}", file=stream)


def _cmd_sagepatch(args: argparse.Namespace) -> int:
    if not args.patch_name and args.file is None:
        print(
            "sagepatch needs a game.dat to read, or --patch NAME to describe patches by name",
            file=sys.stderr,
        )
        return 2
    if args.patch_name:
        generated, unknown = generate_from_patches(args.patch_name)
        for name in unknown:
            print(
                f"unknown patch {name!r} (ignored); `sage-patch list` names them", file=sys.stderr
            )
    else:
        data = Path(args.file).read_bytes()
        generated = generate(data, Path(args.file))

    if args.check:
        # Drift check: does the committed file still describe this binary? `[source]` is excluded
        # (a path and a hash differ per machine and per rebuild), so only the deltas are compared.
        committed = load_engine(args.check)
        for warning in committed.warnings:
            print(f"{args.check}: {warning}", file=sys.stderr)
        problems = differences(committed, generated.engine)
        if problems:
            print(f"FAIL: {args.check} no longer describes this engine:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print(f"OK: {args.check} matches this engine")
        return 0

    header = (
        "Written by `sage-patch sagepatch` - the INI surface this game.dat accepts.",
        "Commit it beside .sagelint; sage_lint and sage_ini read it (see sage_ini.engine).",
        "Regenerate it whenever the binary is repatched: `sage-patch sagepatch <game.dat>`.",
    )
    text = dump_engine(generated.engine, "\n".join(header))
    if args.out is None:
        print(text, end="")
        _report(generated, sys.stderr)
        return 0
    Path(args.out).write_text(text, encoding="utf-8")
    _report(generated, sys.stdout)
    print(f"wrote {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sage-patch",
        description="Binary patches for the ROTWK SAGE engine (game.dat).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list the registered patches").set_defaults(func=_cmd_list)

    info = sub.add_parser(
        "info",
        help="show what one patch is, takes and changes",
        description="Everything this package knows about one patch: what it does, whose work it "
        "is, where its source and its reverse-engineering write-up live, the parameters apply "
        "and verify take for it, and the INI surface it adds. With --file, whether a given "
        "game.dat carries it and with which parameters.",
    )
    info.add_argument("patch", metavar="PATCH", help="patch name, as `sage-patch list` prints it")
    info.add_argument(
        "--file",
        default=None,
        metavar="GAME_DAT",
        help="also read this binary and report whether it carries the patch, with the parameters "
        "recovered from it - so the INI surface shown is the one it was applied with",
    )
    info.set_defaults(func=_cmd_info)

    sagepatch = sub.add_parser(
        "sagepatch",
        help="write the .sagepatch describing the INI surface a patched game.dat accepts",
        description="Read a patched game.dat and write the .sagepatch that teaches sage_ini and "
        "sage_lint what INI it accepts: the fields, name-table tokens and raised limits its "
        "patches add. Commit the result beside .sagelint.",
    )
    sagepatch.add_argument(
        "file",
        nargs="?",
        metavar="GAME_DAT",
        help="the patched binary to read (omit only with --patch)",
    )
    sagepatch.add_argument(
        "-o",
        "--out",
        default=None,
        metavar="PATH",
        help="where to write it (default: stdout, so it can be piped or reviewed first)",
    )
    sagepatch.add_argument(
        "--patch",
        dest="patch_name",
        action="append",
        default=[],
        metavar="NAME",
        help="describe these patches with their DEFAULT parameters instead of reading a binary, "
        "for a project that knows what it builds with and would rather not wire a game.dat path "
        "into CI. A patch applied with any other parameter is described wrongly this way "
        "(repeatable)",
    )
    sagepatch.add_argument(
        "--check",
        default=None,
        metavar="SAGEPATCH",
        help="compare an existing .sagepatch against what this binary actually is, and exit "
        "non-zero on any difference - the drift check for a committed file",
    )
    sagepatch.set_defaults(func=_cmd_sagepatch)

    apply_p = sub.add_parser("apply", help="apply a patch to a copy of a game.dat")
    verify_p = sub.add_parser("verify", help="check a game.dat already carries a patch")
    apply_sub = apply_p.add_subparsers(dest="patch", required=True)
    verify_sub = verify_p.add_subparsers(dest="patch", required=True)

    for name, cls in PATCHES.items():
        # `help` is the one-liner in `sage-patch apply --help`'s subcommand list, `description` the
        # paragraph at the top of `sage-patch apply <name> --help`. An experimental patch says so in
        # both: the first is where somebody browsing picks one, the second is where somebody who
        # already typed the name goes to find out what its options are.
        #
        # A `help` string is %-formatted by argparse against its own parameter dict, so a
        # description naming a format specifier - `description-timers` says its keys take a
        # `%.1f`, `science-prereqs` quotes a message carrying `%s` - raises `TypeError` while
        # `apply --help` is being printed. Doubling the percents here keeps the escape out of the
        # descriptions themselves, which `list` and the paragraph below print verbatim.
        summary = f"EXPERIMENTAL - {cls.description}" if cls.experimental else cls.description
        summary = summary.replace("%", "%%")
        detail = f"{cls.description}.\n\nEXPERIMENTAL: {EXPERIMENTAL_WARNING}"
        ap = apply_sub.add_parser(
            name,
            help=summary,
            description=detail if cls.experimental else cls.description,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        ap.add_argument(
            "--in",
            dest="src",
            required=True,
            metavar="GAME_DAT",
            help="clean input binary (read, never modified)",
        )
        ap.add_argument(
            "--out",
            dest="out",
            default=None,
            metavar="OUT",
            help="where to write the patched binary (default: overwrite --in)",
        )
        cls.add_cli_arguments(ap)
        ap.set_defaults(func=_cmd_apply)

        vp = verify_sub.add_parser(name, help=summary)
        vp.add_argument("file", metavar="GAME_DAT", help="patched binary to check")
        cls.add_cli_arguments(vp)
        vp.set_defaults(func=_cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
