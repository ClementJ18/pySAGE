# sage_apt — known gaps and improvement ideas

Findings from moving the `apt_editor` prototype into the monorepo, validated against
the 17 `.apt`/`.const` pairs in the Edain mod tree (`_mod/apt` + `_mod/apt_widescreen`):
every file now survives `apt -> xml -> apt -> xml` with byte-identical XML.

Fixed during the move (each was silently corrupting exports):

- **Button struct layout**: the writer emitted `records_ptr` at +44 / `actions_ptr` at
  +48 and never wrote `recordcount`/`actioncount` at all, while the reader (correct
  per real game files) expects count/ptr pairs at +44/+48 and +52/+56. Exports were
  unreadable — including the tool's own `SpellStore.apt` that shipped with the
  prototype (the pristine mod file replaced it as the test fixture).
- **ConstantPool action padding**: the writer emitted 4 extra zero bytes after the
  count + pointer; on re-read the zero parsed as `ACTION_END`, silently dropping all
  bytecode after the constant pool (whole function bodies vanished).
- **`<empty id="0"/>` double-count**: character 0 is the movie itself; rebuilding from
  XML added it as an extra empty slot, shifting every character id by one so all
  placeobject references pointed at the wrong characters.
- **Empty-string edittext text/variable**: a pointer to `""` decompiled to
  `<etvar variable=""/>` but recompiled to a null pointer, so the element flapped
  between generations.
- **ButtonAction key flags**: parsing lowercased the whole flag string, so `Key:A`
  came back as `a` (wrong keycode).

Fixed since:

- **`sage-apt check` batch validator**: round-trips every `.apt`/`.const` pair
  (files or directories) in a temp dir, classifying `ok`/`unstable`/`error`;
  `tests/sage_apt/test_corpus.py` runs the Edain corpus through the same machinery.
- **Errors are exceptions, writes are atomic**: `apt_to_xml`/`xml_to_apt` raise
  `AptError` (path + reason) instead of `print` + `False`, and the compiler builds
  both output buffers in memory before writing either file — a failure can no longer
  leave a partial `.apt` next to a stale `.const`.
- **`pushregister` operand**: the decompiler now emits the real one-byte register
  operand instead of the opcode (185), so a round-trip preserves the register number.
- **`pushwordconstant` operand**: the reader now reads exactly one uint16 and no
  longer fabricates a phantom `pushshort` / eats two extra bytes.
- **Recomputed `definefunction[2]` body sizes**: the compiler measures each body's
  emitted byte count and patches the `size` field (nested bodies included); the XML
  `size` attribute is now advisory, so editing actions inside a function body no
  longer corrupts the export.
- **Label-resolved branch targets**: `branchalways` / `branchiftrue` /
  `branchiffalse` now carry a `target` label matching an `anchor` attribute on the
  destination instruction (`anchor`, not `label`, because `gotolabel` uses `label`
  for its frame-label string); the compiler recomputes the signed delta after laying
  out the block, so an edit that shifts byte counts no longer strands the branch.
  Offsets are relative to the byte after the operand field (confirmed against 848
  corpus branches). A branch with only a raw `offset` (pre-Phase-4 XML, or a
  destination outside the block) still compiles the offset verbatim as a fallback.
- **Real textures for `image` characters**: `view`/`edit --game-dir <dir>` (needs the
  `[apt]`/`[ui]` extra) resolves each image through the movie's `.dat` image map
  (`sage_apt.imagemap`) and crops it out of the `apt_<Movie>_<textureId>` atlas via
  `sage_utils.textures` (`sage_apt.textures.AptTextureResolver`). The static viewer inlines
  the crop as a `data:` URI; the editor serves it from `/api/texture/<id>` (manifest at
  `/api/textures`). Validated against real Palantir textures (crops at exact rect sizes).
  Without the extra / game dir, `build_resolver` returns None and placeholder rendering is
  unchanged.
- **Real textures for `shape` characters (geometry)**: the bulk of textured UI is drawn by
  `shape` characters whose `<Movie>_geometry/<id>.ru` mesh carries the UVs. `sage_apt.geometry`
  parses the `.ru` fills (solid `s:` + textured `tc:` with a pos->uv matrix); the resolver
  loads the `_geometry` dir and exposes `shape_fills` / `atlas_png` / `geometry_manifest`.
  The viewer draws each fill as SVG (solid triangles; textured = the atlas clipped to the
  triangles and mapped by the inverse matrix, atlas inlined once via `<defs>`+`<use>`); the
  editor renders the same client-side from `/api/geometry` + `/api/atlas/<tex>`. Validated:
  the SpellStore atlas regions the shapes sample are correct real art (crop proofs).
- **Golden byte-freeze + pragmatic typing (Phase 7, partial)**: `tests/sage_apt/fixtures/
  golden/` freezes the decompiled XML and the recompiled `.apt`/`.const` for SpellStore,
  asserted by `test_golden.py`, so any later codec refactor is diffed against frozen bytes.
  `sage_apt` now ships `py.typed` and is type-checked by mypy; `flags.py`/`imagemap.py`/
  `textures.py`/`check.py` and the module signatures are annotated. The dict-based binary
  codec (`aptfile.py`, `actions.py`) passes mypy as-is (`annotation-unchecked` disabled) but
  is **not** yet rewritten into dataclasses — that full typed-model rewrite (Phase 7 steps
  2–3) is deliberately deferred; the golden freeze is the safety net for doing it later.
- **Editing depth in the editor**: add / duplicate / delete placeobjects (toolbar buttons
  + Ctrl+D / Del), drag-to-move an element on the stage (screen delta → tx/ty via the SVG
  CTM), and an undo/redo stack (Ctrl+Z / Ctrl+Y, snapshots of the serialized XML) covering
  every mutation including property Apply. Add builds a minimal
  `HasCharacter|HasMatrix` placeobject in the on-screen root frame. The add/delete → save →
  export → re-decompile round-trip is covered by an API-level test (`test_editing.py`); the
  pure-JS drag/undo/redo are a manual checklist + an in-game spot check (M1 procedure).
- **Frame / label selection**: the static viewer (`view --frame N` / `--label X`,
  library `render_viewer_html(xml, frame=, label=)`) renders a chosen root frame or a
  frame-label state instead of only frame 0 — a `--label` also biases each sprite's
  display frame, so `_on` vs `_off` render the matching state. The editor gains a "state"
  dropdown in the stage toolbar (union of every root/sprite label) that re-renders the
  stage and keeps the current selection.
- **poflags honesty in the editor**: applying changes now adds `HasMatrix` only when a
  matrix/translation field actually changed and `HasColorTransform` only when a colour
  field changed (pre-existing flags are always kept), instead of force-adding both.
- **Editor page is a package asset**: the editor UI moved from an embedded string in
  `editor.py` to `sage_apt/assets/editor.html`, loaded via `importlib.resources`; the
  `editor.py` E501 ruff ignore is gone and a real endpoint smoke test replaces it.
- **M1 in-game validation passed**: a round-tripped export loads in the actual game and
  renders/behaves correctly (validated on `Palantir.apt`). The writer-touching phases
  (5+) that M1 gated are unblocked.
- **BIG-archive `.const` sources**: `to-xml --game-dir <dir>` (library:
  `apt_to_xml(path, game_dir=...)`) resolves the `.const` — or the `.apt` itself — out of
  the `.big`s under `<dir>` when it is not a loose file, so the mod files that ship without
  a loose `.const` (`LoadScreen.apt`, ...) now decompile. Loose file wins; pyBIG is
  lazy-imported behind the optional `[apt]` extra so the core stays stdlib-only.

## Broken / suspect

- **One out-of-block branch in `MainMenu.apt`**: a single `branchalways` jumps nine
  bytes past its own block's `ACTION_END` into the following string data (the reader
  ends a block at the first `ACTION_END`, so the destination is not a boundary it can
  see). It cannot be labelled and stays offset-only; harmless while unedited, but an
  edit before it would not track it. The other 847 corpus branches all resolve to
  labels.
- **Round-tripped binaries are not byte-identical** (SpellStore: 135004 → 135760
  bytes): section ordering/interleaving differs from EA's original layout even though
  the content is equivalent. Untested in the actual game — the next real validation
  step is loading an exported file in-game.

## Format gaps

- `movieclip` unknown fields: movie `unknown=33`, placeobject `unknown`, button
  `unknown`/`unknown2`, text record `u1..u4` — OpenSAGE may have names for some.
- Nested `MOVIE` characters are emitted as `<empty>` (matches the C++; never seen in
  the corpus).
- `.const` items only handle strings and uint32s (`TYPE_UNDEF` unused).
- edittext colour attributes are byte-swapped relative to placeobject colours
  (red=alpha, green=red, ...); the XML mirrors the raw layout and only the editor UI
  warns about it. Decoding to true RGBA in the XML would be friendlier but breaks
  existing XML files.

## Viewer / editor improvements

- Real artwork now renders for both `image` characters (`.dat` crop rect) and `shape`
  characters (`_geometry` mesh UVs) with `--game-dir` + the `[apt]` extra. Still open:
  (a) movies whose `.dat`/`_geometry`/atlas aren't beside the XML (they ship in a base-game
  `.big`); resolving those through `--game-dir` `.big`s (like Phase 5 does for `.const`)
  would remove the manual-extract step. (b) the RGBA tint on textured fills and line-stroke
  styles are ignored. (c) most `image` characters still aren't *surfaced* in the default
  accumulated frame, so image-character artwork only shows where one is actually placed.
- Frame/label state can now be picked (viewer `--frame`/`--label`, editor state
  dropdown); a full timeline scrubber that plays through frames is still missing.
- Editor now does placement/colour/name + a few character fields, add/duplicate/delete
  placeobjects, drag-to-move, and undo/redo. Still missing: bytecode/action editing, editing
  character geometry (shapes/buttons), and drag is a root-space delta so it is only exact for
  top-level elements (approximate under a scaled/rotated parent sprite).
- Text is rendered with a generic sans font; the file's own fonts (glyph advances are
  parsed already) are ignored.

## Code health

- `sage_apt` is now on the mypy `files` list with `py.typed`; the peripheral modules are
  annotated. Still a dict-based port at the core: `aptfile.py`/`actions.py` pass mypy only
  because unannotated bodies are unchecked. The typed-model rewrite (dataclasses like
  `sage_replay.replay` over `sage_utils.stream.BinaryStream`, byte-identical to the golden
  freeze) is the remaining Phase 7 work, deferred by decision.
