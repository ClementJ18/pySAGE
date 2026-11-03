# sage_worldbuilder

A map editor for the SAGE engine games, written to replace WorldBuilder, the editor EA shipped with
*The Battle for Middle-earth*. It opens, edits and saves `.map` and `.bse` files, reading the
installed game (and any mods over it) for the objects, textures, roads, water, scripts and factions
a map refers to.

It builds on the rest of pySAGE: [`sage_map`](../sage_map) reads and writes the map,
[`sage_ini`](../sage_ini) assembles the game data, [`sage_w3d`](../sage_w3d) supplies the 3D view's
models, and [`sage_utils`](../sage_utils) mounts an install, its `.big` archives and a mod folder in
the game's order. WorldBuilder's command ids, keyboard shortcuts, script templates and icons are
extracted from `worldbuilder.exe` by the scripts in [tools/](../tools), and the parsing is checked
against about 1,100 shipped and mod maps.

## Running

Needs the `worldbuilder` extra (PyQt6, pyBIG, numpy, PyOpenGL, Pillow):

```sh
pip install "pysage-tools[worldbuilder]"   # from a checkout: pip install -e ".[worldbuilder]"
sage-worldbuilder [map] [-mod FOLDER]... [-sagepatch FILE]   # or: python -m sage_worldbuilder.ui
```

- `-mod` mounts an unpacked mod over the install, as the game's own switch does; repeated, a later
  mod wins.
- `-sagepatch` reads a patched `game.dat`'s `.sagepatch`, so the fields and tokens its patches add
  are game data rather than errors (with `desert-weather`, Map Settings offers Desert).

For mappers without Python, `pyinstaller sage_worldbuilder/sage-worldbuilder.spec` builds
`dist/WorldbuilderV2.exe`.

**Help > Getting started** tours the window; **Keyboard Shortcuts** lists WorldBuilder's 65 keys.
**Help > Report a bug** opens a report naming the build, install, mods and open map. An unexpected
error opens the same report with the traceback, and the editor keeps running: save first.

## How it is put together

- **The model layer is Qt-free.** `MapDocument` holds the `sage_map.Map`, its undo stack and change
  notifications; `terrain/`, `roads`, `water`, `scripting` and the rest are plain Python over it.
  `ui/` is the shell.
- **Every edit is a `Command`** run through `MapDocument.execute`, so it is undoable, and it declares
  what it changed so each view refreshes only that.
- **A map saves back byte-identical when nothing changed**, including unshown chunks and edits that
  were all undone. The corpus test (`tests/sage_map/test_corpus_maps.py --full`) enforces it.
- **Parity is by the numbers**: menu items carry WorldBuilder's command ids and the shortcuts come
  from `keymap.json`. Where WorldBuilder's behaviour could not be read, the choice made is noted in
  the code.

## What it does

**Opening and saving.** Maps are listed by WorldBuilder's six categories, including those inside
`.big` archives (opened read-only). Recent maps, unsaved-change prompts, and autosave to
WorldBuilder's three rotating files. **New** makes an empty map; **Resize** changes size around an
anchor, moving everything with it; heightmaps import and export as 16-bit images, and **Open from
TGA** builds a map from a grey image.

**Two views.** A top-down view and a 3D view (F3) sharing tools and selection. Right- or Space-drag
moves the camera, middle-drag turns it, the wheel zooms. With game data loaded the 3D view draws
terrain, blends and cliffs as the game does, under the map's lighting, with models, roads and water.
Each object draws all its `Draw` modules, in the condition state WorldBuilder picks (damage, night,
snow, garrisoned). A dot at each object's centre is what a click picks by (3D Options > Show Object
Dots hides them). Show Sound Flags marks audio objects; Letterbox and Safe Frame show 16:9 and 4:3.
Without game data both views show a height ramp.

**Panels.** Every panel docks, tabs or floats; Window > Lock Layout stops them re-docking.

**Objects.** Place from the Object Palette (by side and `EditorSorting`); select by click,
Shift-click or marquee; drag to move, Alt-drag to rotate. Object Properties edits the whole
selection as one undo entry, on WorldBuilder's General, Logical and Sound pages, with its
**Available Upgrades** list (plus a search box). The Item List searches objects, waypoints, areas
and teams; the Edit menu selects similar, duplicate, deprecated or missing objects.

**Move, Rotate and the front handle** (beyond WorldBuilder). A selected object shows a handle along
its facing that can be dragged to turn it. The Move and Rotate tools put a Blender-style gizmo on the
selection; X, Y and Z switch axis mid-drag. Rotate has one ring, since an object stores only a
heading. Snap To Grid and Lock Angle apply.

**Radial Array** (beyond WorldBuilder). Drag out a ring and the palette's object, or the selection,
is repeated evenly around it, facing the centre, outward, along the ring or unchanged.

**Waypoints, trigger areas and layers.** Waypoint and Polygon tools; the Layers List shows, hides and
targets layers; the Ruler measures in feet and cells.

**Terrain.** Height Brush, Mound, Dig and Smooth; contour lines; per-cell attributes (passability,
passage width, taintability, flammability, visibility) painted with a tint.

**Textures and blending.** Paint with Single Tile, Large Tile or Flood Fill, pick with the eyedropper,
blend by hand or by area. **Apply To Tiles** paints by slope, height or random saturation. Texture
Sizing remaps textures, removes cliff mapping and rebuilds the tables. **Terrain Copy** stamps a
selection of cells elsewhere, flipped and turned.

**Roads and water.** The Road tool drags road and bridge segments; the 3D view draws curves, mitres
and junctions as the game does. Lakes, rivers and wave areas each have a tool, and any of them can
select and reshape water of every kind. Water is drawn still.

**World dressing.** Scorch marks, groves, fences, ramps, borders and mesh molds, from the Dressing
Options panel; each writes ordinary map data.

**Scripts, teams and players.** The Scripts panel edits every player's groups and scripts with
WorldBuilder's extracted templates (Living World templates only on Living World maps). Arguments are
offered the map's names plus WorldBuilder's run-time ones (`<This Player>`, `<This Team>`, ...).
Scripts inherited from library maps are shown read-only; **Override** copies one into the map. A Go
To button jumps to the unit, waypoint, area, team, player or script an argument names. The Player
List edits players, factions, AI, relations and library maps; teams are created, copied and
repaired; the Build List panel and tool edit a skirmish AI's build list.

**Export and import.** A `.scb` library exports chosen players' units and scripts, and imports into
another map as one undoable edit, resolving size, name and player clashes as WorldBuilder does.

**Cameras, lighting and sound.** Camera-animation keys stand in the 3D view with drag handles, with a
preview pane. Named cameras are saved and gone to. Global Light and Environment Options edit
lighting, bloom and textures. **Listen To Map** plays nearby ambient sounds. **Set LOD** picks a
static detail level and drops `Draw` modules the game would drop at it.

**Bases.** Saving a `.bse` rebuilds its castle template from its objects and areas (proven against
all 1,035 corpus bases).

**Validation.** Generate Report checks the map against the loaded game with `sage-lint`'s map rules
and repairs teams. A mod overlay can add rules (below).

**Game data and Jump To Game.** The install is found automatically; mods load and reorder from the
Game menu. **Jump To Game** launches the open map in the real game, with its mods, the engine
patches a command-line skirmish needs (removed afterwards) and a configured lobby.

**MapCache Entry.** Game > MapCache Entry builds the `maps\mapcache.ini` block a finished map needs
(the engine will not add one for a map inside a `.big`), ready to paste.

## The model layer

Everything above the UI imports on its own, with no Qt and no game data:

```python
from sage_worldbuilder import Change, ChangeKind, MapDocument, SetAttribute

document = MapDocument.open("maps/my map/my map.map")
document.subscribe(lambda change: print("changed:", change.kind))

first = document.map.objects_list.object_list[0]
document.execute(SetAttribute(first, "angle", 1.57, Change(ChangeKind.OBJECTS)))

document.stack.undo()  # every edit is undoable
document.save()  # byte-identical again, compressed as it was
```

`MapDocument` caches the decoded terrain and patches it in place (`write_heights`, `write_cells`).
`CompositeCommand` and `UndoStack.group` fold a gesture into one undo entry.

## MCP server

`sage-worldbuilder-mcp` (the `worldbuilder-mcp` extra) serves the model layer to an agent over
stdio: open and save a map, list and inspect objects, place, move, rotate and delete them, set
their properties, read and set the selection, sample and flatten terrain, undo and redo. Each
call is one undo entry.

It runs in one of two modes:

```sh
# Headless, on its own copy of a map.
claude mcp add sage-worldbuilder -- sage-worldbuilder-mcp "maps/my map/my map.map"
# Driving the running editor: turn on Tools > Allow Agent Connections first.
claude mcp add sage-worldbuilder -- sage-worldbuilder-mcp --bridge
```

Connected to the editor, the agent edits the window's own map, so every edit shows at once and
sits on the undo stack the user sees. It can also move the view (`view_at`) and capture it
(`screenshot`). The editor listens on localhost only, and only while that menu item is checked.
It writes the port and a random token to `mcp_bridge.json` in its settings folder, and removes
the file when it stops; every request must carry the token. The agent can't open another map
over unsaved edits, or save a `.bse` base (the editor must rebuild its castle templates).

**Markers** let the user point at a place instead of describing it. The Markers panel (Tools >
Markers) draws three kinds: areas, as dragged rectangles or clicked polygons, named A, B, C, ...;
points, named P1, P2, ...; and paths through points, named L1, L2, ... A path holds its points by
name, so dragging a point reshapes every path through it. The panel's Edit mode drags whole
markers, corners and points; Shift-click adds a corner or a point on a path's leg, Alt-click
removes one, Delete removes the chosen marker. The list renames markers in place (a name the user
tells the agent), frames them on double-click, and deletes them. Markers show under every tool
and are never saved or put on the undo stack.

The agent reads them with `get_markers` and `describe_marker` (an area's objects by template,
waypoints, trigger areas, heights, slope and textures; a point's height, texture and nearby
objects; a path's segments, height profile, steepest grade and textures crossed). It passes an
area as `region="A"` to `list_objects`, `sample_heights`, `set_terrain_height` and the texturing
tools, which keep to a polygon's shape, and `marker=` to `screenshot` (which crops to it, framing
it first when it is off screen). It can show the user where it means with `mark_area`,
`mark_point` and `mark_path` (a path's stops are point names or positions, which mark new
points), change a marker with `edit_marker` (move, reshape, re-route, rename) and remove them
with `delete_markers`. A marker can also be attached to a message: the `markers://all` resource
(`@` in Claude Code) or the `marker` prompt, which adds a picture of it.

**Texturing.** `paint_texture` paints a rectangle or area (optionally `only_over` one
texture), `paint_texture_by_terrain` is Apply To Tiles limited to an area, and
`flood_fill_texture` and `auto_blend` are Flood Fill and Auto Edge at a point. `blend_region` runs
Auto Edge over every unblended texture area in an area, as one undo entry. `paint_path` paints a
band of a given width along a path and Auto Edges it, so "a blended dirt road along L1" is one
call and one undo entry. `list_textures` gives
the map's textures and, with the editor's game data loaded, the game's; headless, only textures
already on the map can be painted, since a name the game lacks would ruin the map.

For mappers without Python there is a Claude Desktop extension, `SageWorldBuilder.mcpb`, built
by the release (`tools/build_release.py`). It packs the server frozen by
`sage-worldbuilder-mcp.spec` with a manifest made by `tools/build_mcpb.py`, which takes the
version from `pyproject.toml` and the tool list from the server. Double-clicking the file, or
dragging it into Claude Desktop's Settings > Extensions, installs it in bridge mode. To pack one
by hand:

```sh
pyinstaller sage_worldbuilder/sage-worldbuilder-mcp.spec
python tools/build_mcpb.py dist/sage-worldbuilder-mcp.exe
```

The tools are plain functions in `mcp_server/tools.py` (`WorldBuilderSession`), with no Qt and no
MCP in them. `mcp_server/server.py` wraps them for MCP, `mcp_server/bridge.py` is the line
protocol and client, and `ui/mcp_bridge.py` is the editor's listener.

## Mod overlays

A mod's conventions live in its overlay: `sage_worldbuilder.ui.app.main(extra_checks=...)` takes a
rule set with the signature of `sage-lint`'s map lint, and Generate Report adds its findings.
[pySAGE-edain](https://github.com/ClementJ18/pySAGE-edain) launches the editor this way.

## Tests

```sh
pytest tests/sage_worldbuilder          # the model layer, data-free
pytest tests/sage_worldbuilder --full   # plus the offscreen Qt tests
```

The OpenGL tests need a real window and skip where no OpenGL 3.3 context can be made.

## Not ported, by choice

- **Show EFX** and **Enable Music Scripting**: WorldBuilder-only previews that write nothing.
- **Water in motion**: water is drawn still.
- **Drawing the `SkyboxSettings` chunk**: it is edited, but RotWK never reads it.
- **The rest of a `StaticGameLOD` bucket**: Set LOD only applies `ModelLOD`.
