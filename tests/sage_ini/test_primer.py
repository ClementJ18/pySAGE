"""Tests for the compact model digest (`sage_ini.primer`) and its `primer` CLI command."""

from sage_ini.__main__ import main
from sage_ini.model.objects import REGISTRY
from sage_ini.primer import (
    _INFRA_FIELDS,
    _Decoder,
    build_digest,
    build_index,
    dump_enum,
    expand_kind,
    table_catalog,
)


class TestDecoder:
    def _code(self, kind: str, field: str) -> str:
        decoder = _Decoder()
        return decoder.decode(REGISTRY[kind]._fieldspec[field])

    def test_reference_field_carries_its_target_table(self):
        # The whole "where to look" premise: a reference decodes to R:<table>.
        assert self._code("CommandButton", "CommandTrigger") == "R:commandbuttons"
        assert self._code("CommandButton", "CursorName") == "R:cursors"

    def test_list_and_nullable_wrappers_nest(self):
        assert self._code("CommandButton", "ButtonImage") == "L[R:mappedimages]"
        assert self._code("CommandButton", "Object") == "?R:objects"
        assert self._code("CommandButton", "NeededUpgrade") == "L[?R:upgrades]"

    def test_enum_field_is_collected(self):
        decoder = _Decoder()
        code = decoder.decode(REGISTRY["CommandButton"]._fieldspec["WeaponSlot"])
        assert code == "E:SlotTypes"
        assert any(e.__name__ == "SlotTypes" for e in decoder.enums)

    def test_every_field_of_every_kind_decodes_without_error(self):
        decoder = _Decoder()
        for cls in REGISTRY.values():
            for name, annotation in cls._fieldspec.items():
                if name in _INFRA_FIELDS or name.startswith("_"):
                    continue
                assert decoder.decode(annotation)  # non-empty, no exception


class TestDigest:
    def test_table_catalog_maps_keys_to_kinds(self):
        catalog = dict(table_catalog())
        assert catalog["commandbuttons"] == "CommandButton"
        assert catalog["objects"] == "Object"

    def test_digest_has_all_sections(self):
        digest = build_digest()
        for marker in ("# LEGEND", "# TABLES", "# MODULES", "# CORE KINDS", "# ENUMS"):
            assert marker in digest

    def test_index_is_lean_where_to_look_map(self):
        # The always-loaded tier: the maps, but no per-kind field schemas or enum dumps.
        index = build_index()
        assert "# TABLES" in index and "# MODULES" in index
        assert "# CORE KINDS" not in index
        assert "commandbuttons: CommandButton" in index
        assert len(index) < len(build_digest())

    def test_numbered_slot_block_gets_synthetic_slot_line(self):
        # CommandSet's payload is digit-keyed button slots, not Python-annotatable fields.
        assert "<1..N>: R:commandbuttons" in expand_kind("CommandSet")

    def test_open_enum_is_labelled_not_blank(self):
        assert dump_enum("Stances") == "E:Stances = (open: any token)"

    def test_expand_unknown_kind_is_graceful(self):
        assert "no modeled kind" in expand_kind("NotAKind")


class TestPrimerCommand:
    def test_default_emits_lean_index(self, capsys):
        assert main(["primer"]) == 0
        out = capsys.readouterr().out
        assert "# TABLES" in out and "# CORE KINDS" not in out

    def test_full_emits_core_schemas(self, capsys):
        assert main(["primer", "full"]) == 0
        assert "# CORE KINDS" in capsys.readouterr().out

    def test_expand_prints_one_kind(self, capsys):
        assert main(["primer", "expand", "Weapon"]) == 0
        assert "Weapon  [table:weapons]" in capsys.readouterr().out

    def test_enum_prints_members(self, capsys):
        assert main(["primer", "enum", "SlotTypes"]) == 0
        assert "PRIMARY" in capsys.readouterr().out
