# sage_apt

Tooling for SAGE `.apt` UI movies - the Flash-derived format behind BFME's menus and
in-game HUD (palantír, command bar, spellbook store, ...).

> **Status: work in progress — not yet fully functional and largely untested.** The
> decompile/compile round-trip and the viewer are usable, but the editor and full format
> coverage are incomplete. Don't rely on it for production edits yet.

An APT ships as a binary pair: `.apt` holds the movie structure (characters, sprite
frames, placeobjects) and the ActionScript bytecode, `.const` the constant pool the
bytecode indexes into. `sage_apt` decompiles the pair into an editable XML form and
compiles the XML back - a Python port of Stephan Vedder's C++ AptConverter - and adds
two ways to see what you are editing:

- **viewer** - a self-contained HTML/SVG page of the movieclip's first frame, drawn to
  scale with per-type colouring, tooltips, and pan/zoom.
- **editor** - a local browser app: click an element on the stage, edit its placement /
  colour / text in a properties panel, drag elements to move them, add / duplicate / delete
  placeobjects, undo/redo, save the XML, and export straight to `.apt`.

## Command line

```sh
# Decompile: SpellStore.apt + SpellStore.const -> SpellStore.xml
python -m sage_apt to-xml SpellStore.apt

# Decompile a .apt whose .const only lives inside the game's .big archives
python -m sage_apt to-xml SpellStore.apt --game "C:/.../BfME2"

# Compile the XML back into the binary pair
python -m sage_apt to-apt SpellStore.xml

# Round-trip a whole directory of pairs and report ok/unstable/error
python -m sage_apt check path/to/apt path/to/apt_widescreen

# Write a static SpellStore.html visualisation
python -m sage_apt view SpellStore.xml

# Render a specific root frame, or a frame-label state (e.g. buttons in their _on state)
python -m sage_apt view SpellStore.xml --frame 5
python -m sage_apt view SpellStore.xml --label _on

# Open the interactive editor (saves the XML, exports .apt on demand)
python -m sage_apt edit SpellStore.xml --port 8080

# Copy a character - and everything it draws - from one movie into another
python -m sage_apt import-character MainMenu.xml Bfme1MainMenu.xml 304 \
    --geometry path/to/bfme1/apt --geometry-out MainMenu_geometry

# Open the editor on a given root frame / frame-label state, for movies whose frame 0 is
# an empty hidden state (the in-game HUD ones: InGameHeroSelect parks on `_hide`)
python -m sage_apt edit InGameHeroSelect.xml --label _show
python -m sage_apt edit InGameHeroSelect.xml --frame 19

# Render real artwork instead of image placeholders (needs the [apt]/[ui] extra)
python -m sage_apt view Palantir.xml --game "C:/.../Edain-Mod/_mod"
python -m sage_apt edit Palantir.xml --game "C:/.../Edain-Mod/_mod"
```

## Library

```python
from sage_apt import AptError, apt_to_xml, xml_to_apt, write_viewer_html

xml = apt_to_xml("SpellStore.apt")       # -> Path("SpellStore.xml")
apt, const = xml_to_apt("SpellStore.xml")  # -> (Path("...apt"), Path("...const"))
write_viewer_html("SpellStore.xml")

try:
    apt_to_xml("Missing.apt")
except AptError as exc:
    print(exc)  # "Missing.apt: file is missing"
```

Both converters raise `AptError` (carrying the offending path and reason) on failure.
`xml_to_apt` builds both output buffers before writing either file, so a failed compile
never leaves a partial `.apt` beside a stale `.const`.

## Notes

- With `--game` and the `[apt]`/`[ui]` extra, both texture paths render real artwork:
  `image` characters via the `.dat` image map (texture id + crop rectangle), and `shape`
  characters via their `<Movie>_geometry/<id>.ru` mesh (solid + textured fills, the latter
  UV-mapped from the `apt_<Movie>_<id>` atlas). This needs the movie's `.dat`, its
  `_geometry/` directory, and the atlas texture reachable under `--game`. Without the
  extra / game dir, elements fall back to placeholders.
- `to-xml --game <dir>` resolves the `.const` (or the `.apt` itself) out of the `.big`
  archives beneath `<dir>` when it is not a loose file - a loose file beside the `.apt`
  still wins. Needs the optional `[apt]` extra (`pip install "pysage-tools[apt]"`, pulls in pyBIG);
  the core stays stdlib-only.
- **Merging characters between movies** (`merge.py`, `import-character`) is renumbering, not
  copying. Characters are an array and every reference is an index into it - a `placeobject`'s
  `character`, a button record's `character`, an `edittext`'s `font` - and two more namespaces hang
  off it: a `shape` names a `<Movie>_geometry/<id>.ru` mesh, and that mesh's `s tc:` fills name
  `image` characters back in the array. That last edge is **not in the XML**, so a merge without
  `--geometry` silently leaves the copied shapes' textures behind. Imports are matched against the
  destination's own by (movie, name) and only added when missing. The `.const` needs no attention:
  it is rebuilt from the XML on every compile. `copy_functions` does the same job for a frame's
  ActionScript, re-indexing a copied `definefunction` against the destination's constant pool -
  which a one-byte operand caps at 256 entries, so it refuses rather than wrapping.
- **An image's texture** is its `->` row if it has one; failing that, a `=` rectangle row means the
  image samples a texture of **its own name**, and only an image with neither row falls back to the
  shared `apt_<Movie>_1` atlas. Every rect key in the corpus - nineteen ROTWK movies and BFME1's
  `MainMenu` - ships an `apt_<Movie>_<key>` beside it.
- **A blank stage usually means frame 0, not a broken file.** Movies that the game shows and
  hides put nothing on frame 0 - `InGameHeroSelect`'s is labelled `_hide` and holds only a
  background, with all 33 elements placed on `_fadein` (frame 9) and revealed by `_show`
  (frame 19). Pass `--frame` / `--label` (or pick a state from the editor's dropdown) to see
  them. Sprites whose own frame 0 is an empty placeholder - a faction switcher parked on
  `_unused`, its images on `_Men` / `_Elves` / ... - fall back to their earliest non-empty
  labelled frame so they still draw.
- A placeobject carrying `Move` without `HasCharacter` (written as `character="-1"`) *updates*
  the object already at its depth, overwriting only the fields its own flags name - it is not
  a removal, which is what `removeobject` is for. The renderers keep the placing record as the
  node the editor writes to, so a `Move` that carries `HasMatrix` shows a position the
  properties panel does not report; no shipped movie does that today.
- `edittext` colour attributes are stored byte-swapped relative to placeobjects
  (red=alpha, green=red, blue=green, alpha=blue); the XML mirrors the raw layout and
  the editor shows a warning in the edittext panel.
- Deliberate quirks of the original C++ converter (pushwordconstant fall-through,
  pushregister emitting the opcode as its value) are replicated so round-trips match
  the reference tool; see the comments in `actions.py`.
- Branches (`branchalways`/`branchiftrue`/`branchiffalse`) carry a resolvable
  `target` label pointing at the destination instruction (which is tagged with a
  matching `anchor` - a separate attribute because `gotolabel` already uses `label`
  for its frame-label string), so edits that shift byte counts keep the branch
  aligned. The raw `offset` attribute is legacy/advisory; a branch with only an
  `offset` and no `target` compiles that value verbatim as a fallback.
