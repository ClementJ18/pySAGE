"""Copying a character between movies (`sage_apt.merge`).

Renumbering is the kind of code whose off-by-one is invisible in a diff: the merged XML looks
plausible whichever way the indices came out, and the movie only misbehaves in the game. So these
tests are written against **invariants** rather than against expected index values - after a merge,
every reference in the destination still resolves, and every one inside the copied subtree points
at the copy of what it pointed at before.

The movies are hand-written and tiny. `test_corpus.py` is what exercises the real ones.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from sage_apt.merge import (
    POOL_LIMIT,
    character_index,
    closure,
    constant_index,
    copy_functions,
    geometry_images,
    merge_character,
    rewrite_geometry,
)

# A destination with three characters (0 is the movie itself) and one import at slot 2.
DESTINATION = """\
<aptdata>
  <movieclip>
    <imports>
      <import name="glow" movie="MenuExport" character="2"/>
    </imports>
    <exports/>
    <frames>
      <frame id="0">
        <action>
          <constantpool>
            <constant id="0" string="_root"/>
            <constant id="1" string="GameCode"/>
          </constantpool>
          <end/>
        </action>
      </frame>
    </frames>
  </movieclip>
  <empty id="0"/>
  <shape id="1" geometry="7"/>
  <empty id="2"/>
</aptdata>
"""

# A source whose sprite 5 draws a shape, a button, an imported glow and a font-bearing text field.
# Shape 3's mesh samples image 4, which is reachable *only* through the geometry.
SOURCE = """\
<aptdata>
  <movieclip>
    <imports>
      <import name="glow" movie="MenuExport" character="1"/>
      <import name="cloud" movie="MenuExport" character="7"/>
    </imports>
    <exports/>
    <frames>
      <frame id="0">
        <action>
          <constantpool>
            <constant id="0" string="hello"/>
            <constant id="1" string="_root"/>
            <constant id="2" string="trace me"/>
          </constantpool>
          <definefunction name="Greet" size="0">
            <body>
              <pushconstant val="2"/>
              <trace/>
              <pushvalue val="1"/>
              <pushconstant val="0"/>
            </body>
          </definefunction>
          <definefunction name="Branchy" size="0">
            <body>
              <pushzero/>
              <branchiftrue offset="2" target="L1"/>
              <trace anchor="L1"/>
            </body>
          </definefunction>
          <definefunction name="Stray" size="0">
            <body>
              <branchalways offset="2" target="Lgone"/>
            </body>
          </definefunction>
          <end/>
        </action>
      </frame>
    </frames>
  </movieclip>
  <empty id="0"/>
  <empty id="1"/>
  <font id="2"/>
  <shape id="3" geometry="11"/>
  <image id="4" image="4"/>
  <sprite id="5">
    <frames>
      <frame id="0">
        <placeobject depth="1" character="3"/>
        <placeobject depth="2" character="6"/>
        <placeobject depth="3" character="1"/>
        <placeobject depth="4" character="8"/>
        <placeobject depth="5" character="7"/>
      </frame>
    </frames>
  </sprite>
  <button id="6">
    <buttonrecord character="3"/>
  </button>
  <empty id="7"/>
  <edittext id="8" font="2"/>
</aptdata>
"""

MESHES = {
    11: "c\ns tc:255:255:255:255:4:1.0:0.0:0.0:1.0:10.0:20.0\nt 0:0:1:1:2:2\n",
}

_REFS = {
    "placeobject": ("character",),
    "buttonrecord": ("character",),
    "edittext": ("font",),
    "textrecord": ("font",),
    "morph": ("start", "end"),
}


def references(root: ET.Element) -> list[int]:
    return [
        int(node.get(attribute))
        for node in root.iter()
        for attribute in _REFS.get(node.tag, ())
        if node.get(attribute) is not None
    ]


@pytest.fixture
def destination() -> ET.Element:
    return ET.fromstring(DESTINATION)


@pytest.fixture
def source() -> ET.Element:
    return ET.fromstring(SOURCE)


class TestClosure:
    def test_it_stops_at_what_the_character_actually_draws(self, source: ET.Element) -> None:
        assert closure(source, 6) == {6, 3}

    def test_a_mesh_pulls_in_the_image_its_fill_samples(self, source: ET.Element) -> None:
        """The edge that is not in the XML. Shape 3 names geometry 11, whose fill names image 4 -
        so image 4 belongs to the subtree even though nothing places it."""
        assert 4 not in closure(source, 5)
        assert 4 in closure(source, 5, MESHES)

    def test_it_reaches_the_whole_sprite(self, source: ET.Element) -> None:
        assert closure(source, 5, MESHES) == {1, 2, 3, 4, 5, 6, 7, 8}

    def test_geometry_images_reads_only_textured_fills(self) -> None:
        text = "c\ns s:1:2:3:4\ns tc:0:0:0:0:19:1:0:0:1:0:0\ns l:1:2:3:4:5\n"
        assert geometry_images(text) == {19}


class TestMerge:
    def test_every_reference_in_the_result_resolves(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        merge_character(destination, source, 5, MESHES)
        count = len(character_index(destination))
        assert all(0 <= ref < count for ref in references(destination))

    def test_the_copied_subtree_keeps_its_shape(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        """Structure-preserving is the whole contract: whatever pointed at X now points at the
        copy of X, and at nothing else."""
        plan = merge_character(destination, source, 5, MESHES)
        after = character_index(destination)
        for old, new in plan.characters.items():
            before_refs = sorted(references(character_index(source)[old]))
            expected = sorted(plan.characters[ref] for ref in before_refs)
            if after[new].tag != "empty":
                assert sorted(references(after[new])) == expected

    def test_an_import_the_destination_already_has_is_reused(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        """Both movies import `glow` from `MenuExport`, so the merge must not add a second one -
        it maps the source's slot onto the destination's."""
        plan = merge_character(destination, source, 5, MESHES)
        assert ("MenuExport", "glow", 2) not in plan.imports
        assert plan.characters[1] == 2
        records = destination.find("movieclip").find("imports")
        assert sum(el.get("name") == "glow" for el in records) == 1

    def test_an_import_the_destination_lacks_is_added_with_its_own_slot(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        """`cloud` is imported by the source and not by the destination, so it needs a new import
        record - and a slot of its own in the array, holding an `<empty>`."""
        plan = merge_character(destination, source, 5, MESHES)
        assert plan.imports == [("MenuExport", "cloud", plan.characters[7])]
        assert character_index(destination)[plan.characters[7]].tag == "empty"
        records = destination.find("movieclip").find("imports")
        assert [(el.get("movie"), el.get("name")) for el in records] == [
            ("MenuExport", "glow"),
            ("MenuExport", "cloud"),
        ]

    def test_a_subtree_with_no_imports_adds_none(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        assert merge_character(destination, source, 8, MESHES).imports == []

    def test_meshes_and_textures_are_renumbered_above_the_destination(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        plan = merge_character(destination, source, 5, MESHES)
        assert plan.geometry == {11: 8}  # the destination's highest geometry is 7
        assert plan.textures == {4: plan.characters[4]}

    def test_a_copied_mesh_points_at_the_copied_image(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        plan = merge_character(destination, source, 5, MESHES)
        rewritten = rewrite_geometry(MESHES[11], plan)
        assert geometry_images(rewritten) == {plan.characters[4]}
        # the fill's colour, matrix and the triangles either side of it are untouched: only the
        # sixth field of the `s tc:` line changes.
        original = MESHES[11].splitlines()
        changed = rewritten.splitlines()
        assert len(original) == len(changed)
        for before, after in zip(original, changed, strict=True):
            if not before.startswith("s tc:"):
                assert before == after
            else:
                fields_before, fields_after = before.split(":"), after.split(":")
                assert fields_after[5] == str(plan.characters[4])
                assert fields_before[:5] == fields_after[:5]
                assert fields_before[6:] == fields_after[6:]

    def test_the_image_character_still_names_itself(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        """The invariant the whole corpus holds, and the one the renumbering leans on."""
        plan = merge_character(destination, source, 5, MESHES)
        image = character_index(destination)[plan.characters[4]]
        assert image.tag == "image"
        assert int(image.get("image")) == plan.characters[4]

    def test_the_array_stays_dense(self, destination: ET.Element, source: ET.Element) -> None:
        merge_character(destination, source, 5, MESHES)
        for index, element in enumerate(character_index(destination)):
            assert int(element.get("id")) == index

    def test_the_source_is_not_modified(self, destination: ET.Element, source: ET.Element) -> None:
        before = ET.tostring(source)
        merge_character(destination, source, 5, MESHES)
        assert ET.tostring(source) == before

    def test_a_character_that_is_not_one_is_refused(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        with pytest.raises(ValueError, match="not a character"):
            merge_character(destination, source, 7, MESHES)  # an import slot
        with pytest.raises(ValueError, match="not a character"):
            merge_character(destination, source, 99, MESHES)

    def test_an_image_naming_a_foreign_texture_is_refused(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        character_index(source)[4].set("image", "77")
        with pytest.raises(ValueError, match="other than themselves"):
            merge_character(destination, source, 5, MESHES)

    def test_a_dangling_reference_is_refused(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        character_index(source)[5][0][0][0].set("character", "42")
        with pytest.raises(ValueError, match="neither defines nor imports"):
            merge_character(destination, source, 5, MESHES)


class TestCopyFunctions:
    def _actions(self, destination: ET.Element, source: ET.Element):
        return (
            destination.find("movieclip").find("frames")[0].find("action"),
            source.find("movieclip").find("frames")[0].find("action"),
        )

    def test_constant_index_finds_then_appends(self, destination: ET.Element) -> None:
        action = destination.find("movieclip").find("frames")[0].find("action")
        assert constant_index(action, "_root") == 0
        assert constant_index(action, "GameCode") == 1
        assert constant_index(action, "brand new") == 2
        assert constant_index(action, "brand new") == 2  # idempotent

    def test_a_copied_function_is_re_indexed_against_the_new_pool(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        into, out_of = self._actions(destination, source)
        copy_functions(into, out_of, ["Greet"])
        pool = [c.get("string") for c in into.find("constantpool")]
        copied = next(el for el in into if el.get("name") == "Greet")
        body = copied.find("body")
        assert pool[int(body.find("pushconstant").get("val"))] == "trace me"
        assert pool[int(body.find("pushvalue").get("val"))] == "_root"

    def test_it_lands_before_the_blocks_end(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        into, out_of = self._actions(destination, source)
        copy_functions(into, out_of, ["Greet"])
        children = list(into)
        copied = next(el for el in into if el.get("name") == "Greet")
        assert children.index(copied) < children.index(into.find("end"))

    def test_the_name_is_in_the_pool_so_a_caller_can_reach_it(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        into, out_of = self._actions(destination, source)
        indices = copy_functions(into, out_of, ["Greet"])
        pool = [c.get("string") for c in into.find("constantpool")]
        assert pool[indices["Greet"]] == "Greet"

    def test_a_self_contained_branch_survives(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        into, out_of = self._actions(destination, source)
        copy_functions(into, out_of, ["Branchy"])
        copied = next(el for el in into if el.get("name") == "Branchy")
        assert copied.find("body").find("trace").get("anchor") == "L1"

    def test_a_branch_out_of_the_function_is_refused(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        into, out_of = self._actions(destination, source)
        with pytest.raises(ValueError, match="outside the function"):
            copy_functions(into, out_of, ["Stray"])

    def test_an_absent_function_is_refused(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        into, out_of = self._actions(destination, source)
        with pytest.raises(ValueError, match="defines no"):
            copy_functions(into, out_of, ["Nope"])

    def test_a_pool_that_would_outgrow_a_byte_operand_is_refused(
        self, destination: ET.Element, source: ET.Element
    ) -> None:
        """`pushconstant` and friends carry a one-byte index, so a destination already near the
        limit cannot take another function - and has to say so rather than emit an index that
        wraps."""
        into, out_of = self._actions(destination, source)
        pool = into.find("constantpool")
        for filler in range(POOL_LIMIT):
            ET.SubElement(pool, "constant", {"id": str(filler), "string": f"filler{filler}"})
        with pytest.raises(ValueError, match="one-byte operand"):
            copy_functions(into, out_of, ["Greet"])
