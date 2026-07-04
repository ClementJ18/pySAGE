"""Unit tests for #include expansion.

#include is textual: included lines are spliced into the token stream at the
directive, so a block may open in one file and close in another. Spans always
point at the file that physically contains the line.
"""

from pathlib import Path

from sage_ini.parser.ast import Attribute, Block, Include
from sage_ini.parser.blockparser import parse_file


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestExpansion:
    def test_included_content_is_spliced_at_the_directive(self, tmp_path: Path):
        write(tmp_path / "part.inc", "Draw = X Tag\nEnd\n")
        root = write(
            tmp_path / "root.ini",
            'Object A\n#include "part.inc"\n    BuildCost = 1\nEnd\n',
        )

        result = parse_file(root, resolve_includes=True)

        assert not result.diagnostics
        (obj,) = result.document.children
        include, draw, cost = obj.children
        assert isinstance(include, Include)
        assert isinstance(draw, Block) and draw.name == "Draw"
        assert cost.key == "BuildCost"

    def test_block_may_span_the_include_boundary(self, tmp_path: Path):
        # the createahero.ini shape: Draw opens in the root, its End lives in
        # the included file
        write(tmp_path / "anims.inc", "Animation = A\nEnd\nEnd\n")
        root = write(
            tmp_path / "root.ini",
            'Object A\n    Draw = W3DScriptedModelDraw Tag\n#include "anims.inc"\nEnd\n',
        )

        result = parse_file(root, resolve_includes=True)

        assert not result.diagnostics
        (obj,) = result.document.children
        (draw,) = obj.children
        assert draw.name == "Draw"
        include, animation = draw.children
        assert isinstance(animation, Block) and animation.name == "Animation"

    def test_spans_point_at_the_physical_file(self, tmp_path: Path):
        write(tmp_path / "part.inc", "Speed = 30\n")
        root = write(tmp_path / "root.ini", 'Object A\n#include "part.inc"\nEnd\n')

        result = parse_file(root, resolve_includes=True)

        (obj,) = result.document.children
        _, speed = obj.children
        assert speed.span.file.endswith("part.inc")
        assert speed.span.line_start == 1
        assert obj.span.file.endswith("root.ini")

    def test_relative_paths_with_backslashes_and_dotdot(self, tmp_path: Path):
        (tmp_path / "common").mkdir()
        (tmp_path / "scenarios").mkdir()
        write(tmp_path / "common" / "shared.inc", "Speed = 30\n")
        root = write(
            tmp_path / "scenarios" / "s1.inc",
            '#include "..\\common\\shared.inc"\n',
        )

        result = parse_file(root, resolve_includes=True)

        assert not result.diagnostics
        include, speed = result.document.children
        assert speed == Attribute(key="Speed", value="30", span=speed.span)

    def test_leading_slash_resolves_relative_to_including_file(self, tmp_path: Path):
        # SAGE: a leading backslash does NOT mean ini-root relative; it is
        # stripped and resolved against the including file's own directory
        (tmp_path / "object" / "system" / "includes").mkdir(parents=True)
        write(tmp_path / "object" / "system" / "includes" / "evil.inc", "Speed = 30\n")
        root = write(
            tmp_path / "object" / "system" / "system.ini",
            '#include "\\includes\\evil.inc"\n',
        )

        result = parse_file(root, resolve_includes=True)

        assert not result.diagnostics
        include, speed = result.document.children
        assert speed == Attribute(key="Speed", value="30", span=speed.span)

    def test_leading_slash_same_directory(self, tmp_path: Path):
        write(tmp_path / "draws.inc", "Speed = 30\n")
        root = write(tmp_path / "unit.ini", '#include "\\draws.inc"\n')

        result = parse_file(root, resolve_includes=True)

        assert not result.diagnostics

    def test_nested_includes(self, tmp_path: Path):
        write(tmp_path / "inner.inc", "Speed = 30\n")
        write(tmp_path / "outer.inc", '#include "inner.inc"\n')
        root = write(tmp_path / "root.ini", '#include "outer.inc"\n')

        result = parse_file(root, resolve_includes=True)

        assert not result.diagnostics
        keys = [n.key for n in result.document.children if isinstance(n, Attribute)]
        assert keys == ["Speed"]


class TestExpansionRecovery:
    def test_missing_include_yields_diagnostic_and_continues(self, tmp_path: Path):
        root = write(tmp_path / "root.ini", '#include "nope.inc"\nObject A\nEnd\n')

        result = parse_file(root, resolve_includes=True)

        assert [d.code for d in result.diagnostics] == ["unresolved-include"]
        assert any(isinstance(n, Block) for n in result.document.children)

    def test_include_cycle_yields_diagnostic(self, tmp_path: Path):
        write(tmp_path / "a.inc", '#include "b.inc"\n')
        write(tmp_path / "b.inc", '#include "a.inc"\n')
        root = write(tmp_path / "root.ini", '#include "a.inc"\n')

        result = parse_file(root, resolve_includes=True)

        assert "include-cycle" in [d.code for d in result.diagnostics]

    def test_without_flag_includes_are_not_followed(self, tmp_path: Path):
        write(tmp_path / "part.inc", "Speed = 30\n")
        root = write(tmp_path / "root.ini", '#include "part.inc"\n')

        result = parse_file(root)

        assert not result.diagnostics
        (include,) = result.document.children
        assert isinstance(include, Include)
