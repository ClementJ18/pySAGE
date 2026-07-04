# sage_apt

Tooling for SAGE `.apt` UI movies — the Flash-derived format behind BFME's menus and
in-game HUD (palantír, command bar, spellbook store, ...).

An APT ships as a binary pair: `.apt` holds the movie structure (characters, sprite
frames, placeobjects) and the ActionScript bytecode, `.const` the constant pool the
bytecode indexes into. `sage_apt` decompiles the pair into an editable XML form and
compiles the XML back — a Python port of Stephan Vedder's C++ AptConverter — and adds
two ways to see what you are editing:

- **viewer** — a self-contained HTML/SVG page of the movieclip's first frame, drawn to
  scale with per-type colouring, tooltips, and pan/zoom.
- **editor** — a local browser app: click an element on the stage, edit its placement /
  colour / text in a properties panel, save the XML, and export straight to `.apt`.

## Command line

```sh
# Decompile: SpellStore.apt + SpellStore.const -> SpellStore.xml
python -m sage_apt to-xml SpellStore.apt

# Compile the XML back into the binary pair
python -m sage_apt to-apt SpellStore.xml

# Round-trip a whole directory of pairs and report ok/unstable/error
python -m sage_apt check path/to/apt path/to/apt_widescreen

# Write a static SpellStore.html visualisation
python -m sage_apt view SpellStore.xml

# Open the interactive editor (saves the XML, exports .apt on demand)
python -m sage_apt edit SpellStore.xml --port 8080
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

- Only the `.apt`/`.const` pair is handled; textures referenced by `image` characters
  live in the accompanying `.dat`/texture files and are not parsed (the viewer draws
  image placeholders).
- `edittext` colour attributes are stored byte-swapped relative to placeobjects
  (red=alpha, green=red, blue=green, alpha=blue); the XML mirrors the raw layout and
  the editor shows a warning in the edittext panel.
- Deliberate quirks of the original C++ converter (pushwordconstant fall-through,
  pushregister emitting the opcode as its value) are replicated so round-trips match
  the reference tool; see the comments in `actions.py`.
- Branches (`branchalways`/`branchiftrue`/`branchiffalse`) carry a resolvable
  `target` label pointing at the destination instruction (which is tagged with a
  matching `anchor` — a separate attribute because `gotolabel` already uses `label`
  for its frame-label string), so edits that shift byte counts keep the branch
  aligned. The raw `offset` attribute is legacy/advisory; a branch with only an
  `offset` and no `target` compiles that value verbatim as a fallback.
