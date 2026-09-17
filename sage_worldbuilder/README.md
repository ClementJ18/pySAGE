# sage_worldbuilder

A map editor for the SAGE engine games, written to replace WorldBuilder - the editor EA shipped
with *The Battle for Middle-earth*. It opens, edits and saves `.map` and `.bse` files, and reads
the installed game (and any mods mounted over it) for the object, texture, road, water, script and
faction tables a map refers to.

It is the front end of the rest of pySAGE: [`sage_map`](../sage_map) reads and writes the binary
map, [`sage_ini`](../sage_ini) assembles the game data, [`sage_w3d`](../sage_w3d) supplies the
models the 3D view draws, and [`sage_utils`](../sage_utils) the virtual file system that mounts an
install, its `.big` archives and a mod folder in the order the game does.

Everything is checked against the real thing: WorldBuilder's own behaviour was read out of
`worldbuilder.exe` where it mattered, its command ids, keyboard accelerators, script templates and
icons are extracted from the binary by the scripts in [tools/](../tools), and the parsing rules are
verified against a corpus of about 1,100 shipped and mod maps.

## Running

Needs the `worldbuilder` extra (PyQt6, pyBIG, numpy, PyOpenGL, Pillow):

```sh
pip install "pysage-tools[worldbuilder]"   # from a checkout: pip install -e ".[worldbuilder]"
sage-worldbuilder                          # or: python -m sage_worldbuilder.ui
```

```
sage-worldbuilder [map] [-mod FOLDER]... [-sagepatch FILE]
```

`-mod` mounts an unpacked mod above the install before anything opens, as the game's own switch
does; repeat it and the mods load in that order, a later one winning. `-sagepatch` points at the
`.sagepatch` of a patched `game.dat`, so the INI fields, block types and tokens its patches add are
read as game data rather than reported as mistakes. A token a patch adds to a list the map itself
stores reaches the editor the same way: `desert-weather` names a third weather, and Map Settings
offers Desert once that `.sagepatch` is loaded.

A mapper without Python runs the standalone bundle instead: `pyinstaller
sage_worldbuilder/sage-worldbuilder.spec` builds `dist/Worldbuilder.exe`.

## How it is put together

- **The model layer is Qt-free.** `MapDocument` holds the `sage_map.Map`, its undo stack and its
  change notifications; `categories`, `objects`, `terrain/`, `roads`, `water`, `dressing`,
  `cameras`, `scripting`, `exchange` and the rest are plain Python over it. `ui/` is the shell.
- **Every edit is a `Command`.** It goes through `MapDocument.execute`, so it is undoable, and it
  declares what it changed (`Change(kind, region)`) so each view refreshes only what it shows -
  a brush stroke repaints its cells, not the map.
- **A map saves back byte-identical when nothing changed** - including a map whose edits were all
  undone, and including the chunks the editor does not show. This is the rule the corpus gate
  enforces (`tests/sage_map/test_corpus_maps.py --full`), and the reason edits patch the stored
  arrays in place rather than rebuilding them.
- **Parity is by the numbers, not by eye.** Menu items carry WorldBuilder's command ids, the 65
  keyboard accelerators come from `keymap.json` as extracted from the binary, and where its
  behaviour could not be read the choice made instead is written down next to the code.

## What it does

**Opening and saving.** The Open and Save As dialogs list maps by WorldBuilder's six categories,
resolved through the game's file system, so maps shipped inside `.big` archives are listed too and
open read-only. Recent maps, unsaved-change prompts, and autosave to the same rotating three files
WorldBuilder uses, in the same user-data folder. **New** makes an empty map (size and border in
cells, starting height, covering texture, Living World flag); **Resize** changes the size around a
chosen anchor and moves everything on the map with it; heightmaps import and export as raw 16-bit
images, and **Open from TGA** builds a map from a grey image.

**Two views.** A top-down view and a 3D view (F3) of the same document, sharing tools, selection
and options. With game data loaded the 3D view draws the terrain as the game does - each cell's
tile, its blend and its 3-way blend through the game's own masks, out of an atlas built from the
map's texture cells - lit by the map's own global lighting, with models, roads and water over it.
A model shows only its front faces, as the game draws it, so a building seen from above is its
inside rather than a lid over it; a mesh that is itself a picture of light - a flame, a glow, a
sky dome - is added to the scene instead of mixed into it, and the map's lights do not dim it. An
object keeps a dot at its centre over its model, smaller than the top-down view's: it is what a
click picks the object by, whatever stands in front of it, and 3D Options > Show Object Dots
turns it off for a clean picture. Without game data both views fall back to a height ramp.

**Panels.** Every panel docks, tabs, or is pulled out into a window of its own; an undocked one
stays above the main window and comes back up with it whenever the editor is focused. Window >
Lock Layout holds them where they are: a panel dragged over another then only moves, instead of
docking or tabbing itself into it.

**Objects.** The Object Palette lists the game's objects by side and `EditorSorting`; Place Object
puts one down, a drag turns it. Click, Shift-click and marquee select; drag moves, Alt-drag
rotates by the Group Edit Method; Pick Allowances limit what a click may take. Object Properties
edits position, angle and every stored key of the whole selection as one undo entry. The Item List
searches the map's objects, waypoints, areas and teams, and can filter the view down to what it
matches. The Edit menu selects similar, duplicate, deprecated or missing objects, objects on
missing teams, and the objects of a base.

**Move, Rotate and the front handle.** Also beyond WorldBuilder. A selected object carries a
short handle out of its ring along its facing: it shows which way the object's front points, and
dragging it turns the object. The **Move** and **Rotate** tools put a Blender-style gizmo on the
whole selection - an arrow per axis, X and Y along the ground and a height arrow leaning clear of
them, with a knob at the centre for a free drag; X, Y and Z switch the axis in the middle of a
drag, and the axis in use frees it again. Rotate draws the one ring the format allows: an object
stores a heading, not a pitch or a roll, so there is no second or third ring to give it. Both
tools are Select and Move underneath, so a press that misses the gizmo still selects, marquees and
drags; Snap To Grid and Lock Angle apply as they do everywhere else.

**Radial Array.** Beyond WorldBuilder: press where a base's centre goes and drag outwards, and
the palette's object is repeated evenly around that ring - the same distance, the same spacing,
every copy aimed at the centre (or away, along the ring, or left as it lies, plus an angle offset).
With objects selected it repeats those instead, keeping the group's arrangement, and a press with
no drag builds the ring through the selection where it already stands, so one marketplace placed
by hand becomes four the same way round. The ring is drawn as it is dragged, each copy's footprint
with a tick for its facing, and the finished ring is left selected for a group edit.

**Waypoints, trigger areas and layers.** The Waypoint tool adds and links waypoints; the Polygon
tool clicks out a trigger area. The Layers List shows what is on each layer, hides layers and sets
the one new items go on. The Ruler measures in feet and cells.

**Terrain.** Height Brush, Mound, Dig and Smooth Height, with a brush width and feather ring in
cells and steps in feet; contour lines; per-cell attributes (the three passability layers, passage
width, taintability, flammability, visibility) painted with Single Tile and Large Tile, and tinted
while you paint them.

**Textures and blending.** Paint a texture with Single Tile, Large Tile or Flood Fill, pick one up
with the eyedropper, and blend edges by hand (Blend Single Edge) or a whole area at once (Auto Edge
In / Out). **Apply To Tiles** paints between two slopes, between two heights, or at a random
saturation. The Texture Sizing menu remaps a texture to another of the same size, removes cliff
mapping, and rebuilds the texture and blend tables from what the map still uses; Show Unblended and
Show Stretched Tiles mark the cells worth looking at. **Terrain Copy** lifts a selection of cells -
heights, textures, blends and passability - and stamps it elsewhere, flipped and turned.

**Roads and water.** Drag a road or bridge segment with the Road tool, joining onto an existing
end; Apply To Selection re-types selected segments, and a segment's two ends always travel
together through cut, copy, paste and delete. Lakes are clicked out as outlines, rivers built from
bank lines, wave areas dragged; Water Options edits an area's height, textures, colours and the
map-wide alpha depths.

**World dressing.** Scorch marks, groves (up to five weighted tree types, kept out of water and off
cliffs), fences, ramps, borders and mesh molds - each writing ordinary map data, each driven from
the Dressing Options panel.

**Scripts, teams and players.** The Scripts panel is a tree of every player's groups and scripts
with an editor for the selected one - properties, IF/OR conditions and both action lists - built
from the action and condition templates extracted from WorldBuilder. The Player List adds and
removes players (or every player a skirmish map needs at once) and edits faction, AI type,
relations, colour and library maps; teams are created, copied and repaired; the Build List panel
edits a player's skirmish AI build list, and the Build List tool places its entries on the map.

**Export and import.** A `.scb` script library exports the chosen players' units, scripts and the
items those scripts reference, and imports back into another map as one undoable edit - reanchored
for a different map size, with duplicate names, missing players and clashing script names resolved
the way WorldBuilder resolves them. Terrain textures are the one thing not imported, and the import
report says so.

**Cameras, lighting and sound.** A camera animation's keys stand in the 3D view as objects with
drag handles - move a key along an axis, or turn it about one - and what the chosen camera sees is
drawn in a preview pane, so scrubbing an animation never moves the view being worked in. Named
cameras are saved from the view and gone to. Global Light Options edits the lights of the map's
time of day, overbright and bloom; Environment Options the macro and cloud textures and the post
effect. **Listen To Map** plays the ambient sounds of the objects the view is looking at.

**Bases.** Saving a `.bse` rebuilds its castle-template chunk from its own objects and trigger
areas when they changed, so a base edited here builds in the game as edited. The generator was
proven against all 1,035 bases in the corpus before it was trusted.

**Validation.** Generate Report checks the open map against the loaded game - the same rules
`sage-lint` runs over maps - lists what is wrong, and repairs teams. A mod overlay adds its own
rule set (see below).

**Game data and Jump To Game.** The install is found automatically; mods are loaded, reordered and
unloaded from the Game menu without restarting. **Jump To Game** launches the open map in the real
game: it copies the map where the engine will find it, passes each loaded mod, applies the engine
patches a command-line skirmish needs for the session (and takes them off again afterwards), and
sets up the lobby - who sits where, factions, colours, teams, difficulty, starting resources and
seed.

**MapCache Entry.** A map the mod's `maps\mapcache.ini` does not name cannot be listed in the
lobby or started at all, and the engine never rewrites that file for a map inside a `.big` - so
Game > MapCache Entry derives the block a finished map needs, ready to paste. The key, the file's
size, the engine's own CRC and its timestamp, the playable extents, the player starts, the initial
camera and the supply markers all come from the map; the two labels, `isOfficial`, `isMultiplayer`,
`isScenarioMP` and the map-list-symbols patch's `mapSymbol` are the mod's to set. Where a new
entry belongs in a hand-ordered cache is the mapper's call, so the dialog copies the block rather
than writing the file.

## The model layer

Everything above the UI is importable on its own, with no Qt and no game data:

```python
from sage_worldbuilder import Change, ChangeKind, MapDocument, SetAttribute

document = MapDocument.open("maps/my map/my map.map")
document.subscribe(lambda change: print("changed:", change.kind))

first = document.map.objects_list.object_list[0]
document.execute(SetAttribute(first, "angle", 1.57, Change(ChangeKind.OBJECTS)))

document.stack.undo()   # every edit is undoable
document.save()         # byte-identical again, and compressed exactly as it was
```

`MapDocument` also caches the decoded terrain (`terrain`, `cells`) and patches it in place through
`write_heights` / `write_cells`, which is what keeps a brush stroke cheap. `CompositeCommand` and
`UndoStack.group` fold a gesture into one undo entry.

## Mod overlays

pySAGE stays engine-generic, so a mod's own conventions live in its overlay package and are wired
in at startup: `sage_worldbuilder.ui.app.main(extra_checks=...)` takes a rule set with the
signature `sage-lint`'s map lint takes, and Generate Report adds its findings to its own. The Edain
overlay is [pySAGE-edain](https://github.com/ClementJ18/pySAGE-edain), which launches the editor
this way.

## Tests

The model layer is covered by a data-free suite; the shell by offscreen Qt tests, which run under
`--full`:

```sh
pytest tests/sage_worldbuilder
pytest tests/sage_worldbuilder --full
```

The OpenGL tests skip wherever no OpenGL 3.3 context can be made, which includes Qt's offscreen
platform - they need a real window, so they are not part of an ordinary run.

## Known gaps

Parity is close but not complete. Still open: cliff UV mapping in the 3D view (a cliff cell draws
its flat texture); road tees, Y and four-way joins are drawn as plain strips; water bump maps,
reflections and animation; skybox drawing; a few view toggles whose meaning was not read (Show
Garrisoned, Show Sound Flags, Show Letterbox, Safe Frame); and the object health presets and
waypoint type names in the properties panel. Show EFX is not ported.
