"""The incremental re-lint path (`lint_file_cached`) and the `serve` daemon that drives it:
a file is re-linted against an already-built game so cross-file references resolve, without
rebuilding the whole folder."""

import json
import subprocess
import sys
from pathlib import Path

from sage_ini.loader import load_game
from sage_ini.stats import ini_root
from sage_lint.commands.serve import _defs_changed
from sage_lint.linter import lint_file, lint_file_cached, lint_file_cached_game

# A locomotor and an object that references it from a *separate* file — the case a single-file
# lint cannot resolve, but a cache-backed re-lint can.
_LOCO = "Locomotor MyLoco\n    Surfaces = GROUND\nEnd\n"
_HERO = (
    "Object Hero\n    LocomotorSet\n        Locomotor = MyLoco\n"
    "        Condition = SET_NORMAL\n        Speed = 10\n    End\nEnd\n"
)


def _mod(tmp_path: Path) -> Path:
    (tmp_path / "locomotor.ini").write_text(_LOCO, encoding="utf-8")
    (tmp_path / "hero.ini").write_text(_HERO, encoding="utf-8")
    return tmp_path


class TestLintFileCached:
    def test_resolves_a_cross_file_reference_against_the_cache(self, tmp_path):
        root = _mod(tmp_path)
        cache = load_game(root).game

        # Isolated: the sibling-defined locomotor dangles.
        isolated = [d for d in lint_file(root / "hero.ini", include_root=root)]
        assert any("MyLoco" in d.message for d in isolated if d.code == "conversion-error")

        # Cached: it resolves, so no conversion error remains.
        cached = lint_file_cached(cache, root / "hero.ini", include_root=root)
        assert not [d for d in cached if d.code == "conversion-error"]

    def test_still_reports_an_in_file_error(self, tmp_path):
        root = _mod(tmp_path)
        (root / "hero.ini").write_text(
            "Object Hero\n    BuildCost = NotANumber\nEnd\n", encoding="utf-8"
        )
        cache = load_game(root).game
        cached = lint_file_cached(cache, root / "hero.ini", include_root=root)
        assert any("BuildCost" in d.message for d in cached if d.code == "conversion-error")

    def test_does_not_mutate_the_cache(self, tmp_path):
        root = _mod(tmp_path)
        cache = load_game(root).game
        before = len(cache.tables["objects"])
        lint_file_cached(cache, root / "hero.ini", include_root=root)
        assert len(cache.tables["objects"]) == before

    def test_does_not_flag_an_override_of_a_cached_definition_as_unused(self, tmp_path):
        # A map.ini that re-tunes a Science already built in the main mod overrides what the
        # engine reaches by that name; the original is what's referenced, so the override is
        # not "unused" even though nothing local names it.
        root = _mod(tmp_path)
        (root / "science.ini").write_text("Science SCIENCE_Gandalf\nEnd\n", encoding="utf-8")
        cache = load_game(root).game
        override = root / "map.ini"
        override.write_text(
            "Science SCIENCE_Gandalf\n    SciencePurchasePointCost = 1\nEnd\n", encoding="utf-8"
        )
        cached = lint_file_cached(cache, override, include_root=root)
        assert not [d for d in cached if d.code == "unused-definition"]


class TestDefsChanged:
    """The saved-definition diff behind the daemon's `defs_changed` flag: a save that adds or
    removes names sibling files may reference tells the editor a folder rebuild is due."""

    @staticmethod
    def _built(cache, path, root):
        _diags, built = lint_file_cached_game(cache, path, include_root=root)
        assert built is not None
        return built

    def test_an_unchanged_save_does_not_flag(self, tmp_path):
        root = _mod(tmp_path)
        cache = load_game(root).game
        built = self._built(cache, root / "locomotor.ini", root)
        assert not _defs_changed(cache, built, str(root / "locomotor.ini"))

    def test_a_new_definition_flags(self, tmp_path):
        root = _mod(tmp_path)
        cache = load_game(root).game
        (root / "locomotor.ini").write_text(
            _LOCO + "Locomotor OtherLoco\n    Surfaces = GROUND\nEnd\n", encoding="utf-8"
        )
        built = self._built(cache, root / "locomotor.ini", root)
        assert _defs_changed(cache, built, str(root / "locomotor.ini"))

    def test_a_removed_definition_flags(self, tmp_path):
        root = _mod(tmp_path)
        cache = load_game(root).game
        (root / "locomotor.ini").write_text("; emptied\n", encoding="utf-8")
        built = self._built(cache, root / "locomotor.ini", root)
        assert _defs_changed(cache, built, str(root / "locomotor.ini"))

    def test_a_cross_file_redefinition_does_not_flag(self, tmp_path):
        # hero.ini gains its own `Locomotor MyLoco`: the name already resolves in the cache
        # (attributed to locomotor.ini), so the reachable name set — what sibling files can
        # reference — is unchanged, and saving hero.ini must not rebuild on every save.
        root = _mod(tmp_path)
        cache = load_game(root).game
        (root / "hero.ini").write_text(_HERO + _LOCO, encoding="utf-8")
        built = self._built(cache, root / "hero.ini", root)
        assert not _defs_changed(cache, built, str(root / "hero.ini"))

    def test_a_macro_value_change_flags(self, tmp_path):
        # A `#define`'s value expands in sibling files at parse time, so revaluing it has the
        # same blast radius as renaming it.
        root = _mod(tmp_path)
        (root / "macros.ini").write_text("#define MY_COST 50\n", encoding="utf-8")
        cache = load_game(root).game
        (root / "macros.ini").write_text("#define MY_COST 60\n", encoding="utf-8")
        built = self._built(cache, root / "macros.ini", root)
        assert _defs_changed(cache, built, str(root / "macros.ini"))


class TestBaseGameInclude:
    """A mod file `#include`ing a file that lives only in the base game (the ROTWK ini.big,
    merged into a base layer) must resolve on a single-file re-lint, not just the full build."""

    def _mod_including_base(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        base = tmp_path / "base"
        (base / "object" / "includes").mkdir(parents=True)
        (base / "object" / "includes" / "thing.inc").write_text(
            "; base-game eva events\n", encoding="utf-8"
        )
        mod = tmp_path / "mod"
        deep = mod / "object" / "sub"
        deep.mkdir(parents=True)
        hero = deep / "hero.ini"
        # The `..\includes\thing.inc` form the real corpus uses: resolved relative to the
        # including file's own folder, it climbs to object/includes/, present only in the base.
        hero.write_text(
            'Object Hero\n    #include "..\\includes\\thing.inc"\nEnd\n', encoding="utf-8"
        )
        return mod, base, hero

    def test_unresolved_without_the_base_layer(self, tmp_path):
        mod, _base, hero = self._mod_including_base(tmp_path)
        cache = load_game(mod).game
        cached = lint_file_cached(cache, hero, include_root=mod)
        assert any(d.code == "unresolved-include" for d in cached)

    def test_resolves_with_the_base_layer(self, tmp_path):
        mod, base, hero = self._mod_including_base(tmp_path)
        cache = load_game(mod).game
        cached = lint_file_cached(cache, hero, include_root=mod, include_bases=(ini_root(base),))
        assert not any(d.code == "unresolved-include" for d in cached)


class TestServeProtocol:
    def _serve(self, root: Path, *extra: str) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, "-m", "sage_lint", "serve", str(root), *extra],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    @staticmethod
    def _read(proc: subprocess.Popen) -> dict:
        """The next non-`building` message from the daemon."""
        for line in proc.stdout:
            message = json.loads(line)
            if message.get("type") != "building":
                return message
        raise AssertionError("daemon closed without a message")

    def test_emits_a_folder_report_then_resolves_a_file_request(self, tmp_path):
        root = _mod(tmp_path)
        proc = self._serve(root)
        try:
            folder = self._read(proc)
            assert folder["type"] == "folder"
            assert folder["summary"]["errors"] == 0

            proc.stdin.write(
                json.dumps({"cmd": "lint_file", "id": 7, "path": str(root / "hero.ini")}) + "\n"
            )
            proc.stdin.flush()
            result = self._read(proc)

            assert result["type"] == "file" and result["id"] == 7
            assert not [d for d in result["diagnostics"] if d["severity"] == "error"]
        finally:
            proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        assert proc.returncode == 0

    def test_flags_a_saved_definition_change_but_not_a_buffer_one(self, tmp_path):
        root = _mod(tmp_path)
        added = _LOCO + "Locomotor OtherLoco\n    Surfaces = GROUND\nEnd\n"
        proc = self._serve(root)
        try:
            assert self._read(proc)["type"] == "folder"

            # A buffer lint (unsaved content) never asks for a rebuild, however it changed.
            proc.stdin.write(
                json.dumps(
                    {"cmd": "lint_file", "path": str(root / "locomotor.ini"), "content": added}
                )
                + "\n"
            )
            proc.stdin.flush()
            assert "defs_changed" not in self._read(proc)

            # The same change saved to disk does: sibling files may now reference OtherLoco.
            (root / "locomotor.ini").write_text(added, encoding="utf-8")
            proc.stdin.write(
                json.dumps({"cmd": "lint_file", "path": str(root / "locomotor.ini")}) + "\n"
            )
            proc.stdin.flush()
            assert self._read(proc)["defs_changed"] is True
        finally:
            proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        assert proc.returncode == 0

    def test_index_reports_definitions_macros_and_block_schemas(self, tmp_path):
        root = _mod(tmp_path)
        (root / "macros.ini").write_text("#define MY_COST 50\n", encoding="utf-8")
        (root / "lotr.str").write_text('OBJECT:Hero\n"The Hero"\nEND\n', encoding="utf-8")
        proc = self._serve(root)
        try:
            assert self._read(proc)["type"] == "folder"
            proc.stdin.write(json.dumps({"cmd": "index", "id": 3}) + "\n")
            proc.stdin.flush()
            index = self._read(proc)

            assert index["type"] == "index" and index["id"] == 3
            names = {d["name"]: d for d in index["definitions"]}
            assert "MyLoco" in names and "Hero" in names
            assert names["MyLoco"]["kind"] == "Locomotor"
            assert names["MyLoco"]["file"].endswith("locomotor.ini")
            assert names["MyLoco"]["line"] >= 1
            # Each definition carries its game-table key so a reference field can offer it.
            assert names["MyLoco"]["table"] == "locomotors"
            assert names["Hero"]["table"] == "objects"

            assert index["macros"]["MY_COST"]["value"] == "50"
            assert index["macros"]["MY_COST"]["file"].endswith("macros.ini")

            # A mod-defined string label carries its `.str` location for go-to.
            assert index["strings"]["OBJECT:Hero"]["value"] == "The Hero"
            assert index["strings"]["OBJECT:Hero"]["file"].endswith("lotr.str")
            assert index["strings"]["OBJECT:Hero"]["line"] == 1

            # Block schemas are read from the typed model, not a hand-kept table: a module slot
            # and a top-level block alike, each field carrying its value kind (enum/ref).
            blocks = index["blocks"]
            assert "TriggeredBy" in blocks["AutoHealBehavior"]
            assert "FORCE" in blocks["Weapon"]["DamageType"]["enum"]
            assert blocks["Object"]["CommandSet"]["ref"] == "commandsets"
            # Module slot classes are listed for `Behavior =`/`Body =` value completion.
            assert "AutoHealBehavior" in index["module_slots"]
            # Keyed-by-label blocks (`ModelConditionState = DAMAGED`) are listed so the editor
            # tells such a header from a plain `Field = value` and offers the block's fields.
            assert "ModelConditionState" in index["keyed_by_label"]
            assert "Model" in blocks["ModelConditionState"]

            # The mod's ini root is exposed so the editor resolves includes as the linter does.
            assert [Path(p) for p in index["include_roots"]] == [ini_root(root)]
        finally:
            proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        assert proc.returncode == 0

    def test_index_include_roots_carry_the_merged_base_game(self, tmp_path):
        # With a base game configured, its merged ini root follows the mod's in the index, so a
        # base-game-only `#include` resolves in the editor's go-to/hover, not just the linter.
        base = tmp_path / "base"
        (base / "object" / "includes").mkdir(parents=True)
        (base / "object" / "includes" / "thing.inc").write_text("; eva\n", encoding="utf-8")
        mod = tmp_path / "mod"
        mod.mkdir()
        root = _mod(mod)
        proc = self._serve(root, "--base", str(base))
        try:
            assert self._read(proc)["type"] == "folder"
            proc.stdin.write(json.dumps({"cmd": "index", "id": 1}) + "\n")
            proc.stdin.flush()
            index = self._read(proc)
            roots = index["include_roots"]
            assert Path(roots[0]) == ini_root(root)
            # The base root is a merged temp tree (not `base` itself), but must resolve thing.inc.
            assert len(roots) == 2
            assert (Path(roots[1]) / "object" / "includes" / "thing.inc").is_file()
        finally:
            proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=10)
        assert proc.returncode == 0
