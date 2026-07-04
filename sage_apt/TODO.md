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
- **poflags honesty in the editor**: applying changes now adds `HasMatrix` only when a
  matrix/translation field actually changed and `HasColorTransform` only when a colour
  field changed (pre-existing flags are always kept), instead of force-adding both.
- **Editor page is a package asset**: the editor UI moved from an embedded string in
  `editor.py` to `sage_apt/assets/editor.html`, loaded via `importlib.resources`; the
  `editor.py` E501 ruff ignore is gone and a real endpoint smoke test replaces it.

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
- Some mod files (`LoadScreen.apt`, `StrategicDetailsTray.apt`, ...) ship without a
  loose `.const` — presumably inside `.big` archives. Reading the pair out of BIGs
  (pybig / `sage_utils.sources`) would cover them.
- edittext colour attributes are byte-swapped relative to placeobject colours
  (red=alpha, green=red, ...); the XML mirrors the raw layout and only the editor UI
  warns about it. Decoding to true RGBA in the XML would be friendlier but breaks
  existing XML files.

## Viewer / editor improvements

- Images are drawn as crossed-box placeholders. Textures could be resolved through
  the `aptimages` mapping + `sage_utils.textures` (pybig) for a real WYSIWYG preview.
- Both render one accumulated frame chosen by label heuristic (`_fade_in`, `_on`,
  `_active`, `_purchased`, else frame 0); a timeline/label scrubber would show the
  other states.
- Editor edits are limited to placeobject placement/colour/name and a few character
  fields; no add/delete/duplicate of elements, no undo/redo, no drag-to-move on the
  stage, no bytecode editing.
- Text is rendered with a generic sans font; the file's own fonts (glyph advances are
  parsed already) are ignored.

## Code health

- Untyped port: dict-based in-memory model, no annotations, excluded from the mypy
  `files` list. A typed model (dataclasses like `sage_replay.replay`) is the natural
  next step; `sage_utils.stream.BinaryStream` could replace the raw `struct` offsets.
