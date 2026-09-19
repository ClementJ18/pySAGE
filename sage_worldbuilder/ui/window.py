"""The editor's main window: the map view, with menus, toolbar, docks and status bar around it.

The shell owns the document lifecycle (open, save, close, recent maps, autosave), the game data
behind it and WorldBuilder's keyboard shortcuts, so each tool plugs into a window that already
behaves the way mappers expect.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Hashable, Sequence
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from PyQt6.QtCore import QByteArray, QChildEvent, QEvent, QMimeData, QObject, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QToolBar,
    QWidget,
)

from sage_map.assets.object_list import Object
from sage_map.assets.trigger_areas import TriggerArea
from sage_map.map import Map
from sage_utils.config import user_config_dir
from sage_utils.elevation import relaunch_elevated
from sage_utils.widgets import Worker, add_help_menu, resource_path, run_worker
from sage_worldbuilder.ambient import (
    ListenMode,
    min_volume_customizations,
    remove_min_volume_customization,
)
from sage_worldbuilder.anchors import RotationAnchors
from sage_worldbuilder.areas import DeleteAreas
from sage_worldbuilder.arrays import ArrayOptions, stamp_objects
from sage_worldbuilder.autosave import Autosaver
from sage_worldbuilder.brush_options import BrushOptions, CopyTerrainOptions, PaintOptions
from sage_worldbuilder.cameras import CameraView
from sage_worldbuilder.castles import is_base_path, refresh_castle_templates
from sage_worldbuilder.categories import MapCategory, MapEntry
from sage_worldbuilder.changes import Change, ChangeKind, Region
from sage_worldbuilder.commands import Command, CompositeCommand
from sage_worldbuilder.document import MapDocument, ReadOnlyMapError
from sage_worldbuilder.dressing import (
    MOLD_FOLDER,
    GroveOptions,
    MoldOptions,
    list_molds,
    mold_triangles,
)
from sage_worldbuilder.footprints import Footprints
from sage_worldbuilder.gamedata import GameContext, is_mod_folder
from sage_worldbuilder.generic_ai import GenericAIType
from sage_worldbuilder.ground import adjust_heights, ground_placements, load_ground_triangles
from sage_worldbuilder.heightmap_io import export_raw, import_raw, read_image_heights
from sage_worldbuilder.influences import Influences
from sage_worldbuilder.jump import JumpMatchError, plan_jump, start_position_count
from sage_worldbuilder.keymap import accelerators, shortcuts_for
from sage_worldbuilder.launch_patch import (
    LaunchPatchError,
    patch_for_launch,
    restore_after_launch,
    restore_pending,
    sagepatch_patches,
)
from sage_worldbuilder.libraries import LibraryMaps
from sage_worldbuilder.lighting import next_time_of_day
from sage_worldbuilder.models import ArtIndex, MapConditions, ObjectModels
from sage_worldbuilder.new_map import DEFAULT_CELL_SIZE, NewMapOptions, new_map
from sage_worldbuilder.objects import (
    CLIPBOARD_MIME,
    Clipboard,
    DeleteObjects,
    GroupEditMethod,
    clipboard_from_json,
    clipboard_to_json,
    copy_objects,
)
from sage_worldbuilder.palette import names_under, object_palette
from sage_worldbuilder.pick import ANYTHING, NOTHING, PickCategory, PickRules
from sage_worldbuilder.render.art import ArtTextures
from sage_worldbuilder.render.model_mesh import load_object_models
from sage_worldbuilder.render.terrain_texturing import TerrainAtlas, build_atlas
from sage_worldbuilder.resize import ResizeMap, ResizeOptions
from sage_worldbuilder.roads import (
    DEFAULT_ROAD_WIDTH,
    CornerType,
    RoadStyles,
    apply_road_style,
    is_road_point,
    selected_segments,
    with_partners,
)
from sage_worldbuilder.safeio import atomic_write
from sage_worldbuilder.script_targets import ScriptTarget, TargetKind
from sage_worldbuilder.selection_helpers import (
    TemplateIndex,
    base_parents,
    base_siblings,
    deprecated_objects,
    duplicate_objects,
    missing_objects,
    objects_with_bad_teams,
    replace_objects,
    similar_objects,
)
from sage_worldbuilder.settings import APP, RecentMap, Settings, same_folder
from sage_worldbuilder.summary import map_summary
from sage_worldbuilder.terrain import FEET_PER_HEIGHT_UNIT
from sage_worldbuilder.terrain.apply_texture import ApplyTextureOptions, apply_texture
from sage_worldbuilder.terrain.brushes import BrushKind
from sage_worldbuilder.terrain.cells import TileLayer, paint_values
from sage_worldbuilder.terrain.edits import (
    PaintTiles,
    PatchHeights,
    RenameTexture,
    ReplaceTerrainTables,
)
from sage_worldbuilder.terrain.sizing import (
    TableEdit,
    blends_removed,
    cliff_mappings_removed,
    optimized_tiles,
)
from sage_worldbuilder.terrain.textures import TextureCapacityError, planned_texture, texture_index
from sage_worldbuilder.texture_colors import (
    BlendTable,
    TextureColors,
    blend_table,
    patch_base_colors,
    patch_picture_colors,
    picture_colors,
    preview_rgb,
    terrain_textures,
    texture_palette,
)
from sage_worldbuilder.ui.ambient_player import AmbientPlayer
from sage_worldbuilder.ui.apply_texture_dialog import ApplyTextureDialog
from sage_worldbuilder.ui.array_options import ArrayOptionsPanel
from sage_worldbuilder.ui.array_tool import RadialArrayTool
from sage_worldbuilder.ui.brush_options import BrushOptionsPanel
from sage_worldbuilder.ui.build_list import BuildListPanel
from sage_worldbuilder.ui.camera_panel import CameraPanel
from sage_worldbuilder.ui.contour_options import ContourOptionsDialog
from sage_worldbuilder.ui.copy_terrain_options import CopyTerrainOptionsPanel
from sage_worldbuilder.ui.dialogs import (
    SAGEPATCH_FILTER,
    GameSettingsDialog,
    OpenMapDialog,
    SaveMapDialog,
    ShortcutsDialog,
)
from sage_worldbuilder.ui.dressing_options import DressingOptionsPanel
from sage_worldbuilder.ui.dressing_tools import (
    BorderTool,
    FenceTool,
    GroveTool,
    MeshMoldTool,
    RampTool,
    ScorchTool,
)
from sage_worldbuilder.ui.environment_options import EnvironmentOptionsPanel
from sage_worldbuilder.ui.generic_ai_options import GenericAIOptionsPanel
from sage_worldbuilder.ui.gizmo_tools import MoveTool, RotateTool
from sage_worldbuilder.ui.global_light_options import GlobalLightOptionsPanel
from sage_worldbuilder.ui.grid_settings import GridSettingsDialog
from sage_worldbuilder.ui.item_list import ItemListPanel
from sage_worldbuilder.ui.jump_dialog import JumpSettingsDialog
from sage_worldbuilder.ui.layers import LayersPanel
from sage_worldbuilder.ui.map_settings import MapSettingsPanel, MultiplayerPositionsPanel
from sage_worldbuilder.ui.map_view import MapView
from sage_worldbuilder.ui.mapcache_dialog import MapCacheDialog
from sage_worldbuilder.ui.new_map_dialog import NewMapDialog
from sage_worldbuilder.ui.object_palette import ObjectPalettePanel
from sage_worldbuilder.ui.object_properties import ObjectPropertiesPanel
from sage_worldbuilder.ui.players import PlayersPanel
from sage_worldbuilder.ui.remap_textures_dialog import RemapTexturesDialog
from sage_worldbuilder.ui.road_options import RoadOptionsPanel
from sage_worldbuilder.ui.road_tool import RoadTool
from sage_worldbuilder.ui.script_debugger import ScriptDebuggerPanel
from sage_worldbuilder.ui.scripts import ScriptsPanel
from sage_worldbuilder.ui.teams import TeamsPanel
from sage_worldbuilder.ui.terrain_copy_tool import TerrainCopyTool
from sage_worldbuilder.ui.terrain_material import PREVIEW_PIXELS, TerrainMaterialPanel
from sage_worldbuilder.ui.terrain_tools import (
    AutoEdgeTool,
    BlendSingleEdgeTool,
    EyedropperTool,
    FloodFillTool,
    HeightBrushTool,
    TilePaintTool,
)
from sage_worldbuilder.ui.tools import (
    BuildListTool,
    GenericAIObjectTool,
    PasteTool,
    PlaceTool,
    PolygonTool,
    RulerTool,
    SelectTool,
    Tool,
    WaypointTool,
)
from sage_worldbuilder.ui.validation import MapChecks, ValidationPanel
from sage_worldbuilder.ui.water_options import WaterOptionsPanel
from sage_worldbuilder.ui.water_tools import WaterTool
from sage_worldbuilder.viewport import PARTIAL_MAP_SIZES
from sage_worldbuilder.water import DeleteWater, WaterKind, default_height, water_kind

if TYPE_CHECKING:
    from sage_ini.model.game import Game
    from sage_worldbuilder.ui.map_view_3d import MapView3D

__all__ = ["APP_NAME", "APP_TITLE", "ICON_ANCHOR", "ICON_FILE", "MainWindow", "app_icon"]

APP_NAME = APP
APP_TITLE = "SAGE WorldBuilder"
# WorldBuilder's own application icon, relative to the package root. `resource_path` looks
# beside its anchor, so anchoring on this `ui` folder resolves it from `sage_worldbuilder/`.
ICON_FILE = "assets/worldbuilder_icons/icons/128.ico"
ICON_ANCHOR = str(Path(__file__).resolve().parent)


def app_icon() -> QIcon:
    return QIcon(str(resource_path(ICON_FILE, ICON_ANCHOR)))


# WorldBuilder's command ids, which key its accelerator table. Most are MFC's standard ids.
CMD_NEW = 57600
CMD_OPEN = 57601
CMD_CLOSE = 57602
CMD_SAVE = 57603
CMD_SAVE_AS = 57604
CMD_REPEAT = 57640
CMD_UNDO = 57643
CMD_REDO = 57644
CMD_EXIT = 57665
CMD_SCRIPTS = 32977
CMD_PLAYERS = 32970
CMD_TEAMS = 32978
CMD_ITEM_LIST = 33355
CMD_ITEM_LIST_ALTERNATE = 33353
CMD_NEXT_PANE = 57680
CMD_PREVIOUS_PANE = 57681
CMD_TOOLBAR = 59392
CMD_STATUS_BAR = 59393
CMD_SHOW_GRID = 32772
CMD_GRID_SETTINGS = 33373
CMD_REVERSE_SCROLL = 33400
CMD_SHOW_TEXTURE = 32927
CMD_SHOW_WAYPOINTS = 32966
CMD_SHOW_AREAS = 32969
CMD_SHOW_LABELS = 33003
CMD_SHOW_OBJECTS = 33004
CMD_SHOW_BOUNDARIES = 33331
CMD_WIREFRAME = 32934
CMD_SHOW_ENTIRE_MAP = 32943
CMD_TOP_DOWN = 32944
CMD_LOCK_VERTICAL = 32963
CMD_RELOAD_TEXTURES = 32974
CMD_SHOW_BOUNDING_BOXES = 33008
CMD_SHOW_SIGHT_RANGES = 33009
CMD_SHOW_WEAPON_RANGES = 33010
CMD_SHOW_SOUND_CIRCLES = 33349
CMD_SHOW_GARRISONED = 33326
CMD_SHOW_SOUND_FLAGS = 33340
CMD_SHOW_LETTERBOX = 33012
CMD_SHOW_SAFE_FRAME = 33411
CMD_SAFE_FRAME_SETTINGS = 33412
CMD_SHOW_ROADS = 33352
CMD_SHOW_WATER = 33351
CMD_GLOBAL_LIGHT_OPTIONS = 32965
CMD_EDIT_SHADOWS = 32975
CMD_EDIT_POST_EFFECTS = 33488
CMD_SELECT_MACROTEXTURE = 32957
CMD_SELECT_CLOUDTEXTURE = 33346
CMD_CAMERA_OPTIONS = 33333
CMD_CAMERA_ANIMATIONS = 33490
CMD_EDIT_SKYBOX = 33348
CMD_REMOVE_MIN_VOLUME = 33398
# View > Listen To Map: (mode, menu text, WorldBuilder command id).
_LISTEN_MODES = (
    (ListenMode.ENABLED, "Play &Enabled Ambient Sounds", 33394),
    (ListenMode.PERMANENT, "Play &Permanent Ambient Sounds", 33395),
    (ListenMode.ALL, "Play &All Ambient Sounds", 33396),
    (ListenMode.NONE, "&Don't Play Ambient Sounds", 33397),
)
# The world dressing tools: (use_tool name, menu text, WorldBuilder command id, its tooltip).
_DRESSING_TOOLS = (
    ("scorch", "Add Scorch&marks", 33007, "Add Scorchmarks to the map."),
    (
        "grove",
        "&Grove",
        32924,
        "Click to place random foliage, drag to place foliage in a rectangular area.",
    ),
    ("fence", "Fen&ce", 32979, "Places a row of objects. Drag then use shift to stretch."),
    ("ramp", "Ra&mp", 33467, "Place Ramps on the map."),
    ("border", "Borde&r Tool", 33330, "Add and adjust borders."),
    ("mesh mold", "Mesh Mo&ld Tool", 32955, "Shapes the terrain using a 3D mesh."),
)
CMD_CUT = 57635
CMD_COPY = 57634
CMD_PASTE = 57637
CMD_DELETE = 32931
CMD_LOCK_SELECTION = 33408
CMD_LOCK_ANGLE = 32962
CMD_SELECT_TOOL = 32921
CMD_PLACE_OBJECT = 32918
CMD_WAYPOINT_TOOL = 32964
CMD_GENERIC_AI_TOOL = 33500
CMD_CHANGE_TIME_OF_DAY = 32942
CMD_POLYGON_TOOL = 32968
CMD_RULER_TOOL = 32958
CMD_BUILD_LIST_TOOL = 32972
CMD_ROAD_TOOL = 32937
# The water tools, with WorldBuilder's tooltips.
_WATER_TOOLS = (
    (WaterKind.LAKE, "lake", "La&ke/Ocean Tool", 32986, "Add and modify lakes and oceans."),
    (WaterKind.RIVER, "river", "Ri&ver Tool", 33441, "Add and modify rivers."),
    (WaterKind.WAVE, "waves", "Wa&ves Tool", 33489, "Add and modify waves."),
)
CMD_SELECT_SIMILAR = 32988
CMD_SELECT_DUPLICATES = 32940
CMD_SELECT_BAD_TEAMS = 33005
CMD_SELECT_DEPRECATED = 33401
CMD_SELECT_SIBLINGS = 33392
CMD_SELECT_BASE_PARENT = 33393
CMD_REPLACE_SELECTED = 57641
# The height tools, with WorldBuilder's tooltips.
_HEIGHT_TOOLS = (
    (BrushKind.SET, "&Height Brush", 32771, "Draw the height on the height map."),
    (BrushKind.RAISE, "&Mound", 32900, "Adds height to (raises) the height map."),
    (BrushKind.LOWER, "&Dig", 32901, "Removes height from (lowers) the height map."),
    (BrushKind.SMOOTH, "Smoot&h Height", 32791, "Smooths the height levels in the height map."),
)
CMD_SINGLE_TILE = 32902
CMD_LARGE_TILE = 32792
CMD_SHOW_IMPASSABLE = 32981
CMD_FLOOD_FILL = 32903
CMD_EYEDROPPER = 32913
CMD_BLEND_SINGLE_EDGE = 32922
CMD_AUTO_EDGE_OUT = 32905
CMD_AUTO_EDGE_IN = 32906
CMD_TERRAIN_COPY = 33436
CMD_OPTIMIZE_TILES = 32916
CMD_REMOVE_CLIFF_MAPPING = 33014
CMD_REMOVE_BLENDS = 33417
CMD_ADJUST_TERRAIN = 33402
CMD_SHOW_STRETCHED = 33376
CMD_STRETCHED_OPTIONS = 33380
CMD_REMAP_TEXTURES = 32929
CMD_SHOW_UNBLENDED = 33377
# The palette group for textures a map uses that the game data does not list.
_THIS_MAP = "This map"
CMD_RESIZE = 32917
CMD_OPEN_FROM_TGA = 33415
CMD_IMPORT_HEIGHTMAP = 33416
CMD_EXPORT_HEIGHTMAP = 33414
# WorldBuilder's heightmap files have no header or extension of their own ("raw image").
_RAW_FILTER = "Raw heightmap (*.raw);;All files (*)"

_GROUP_EDIT_COMMANDS = {
    GroupEditMethod.MATCH_LEAD: 33360,
    GroupEditMethod.AS_GROUP: 33359,
    GroupEditMethod.INDEPENDENT: 33361,
}
CMD_PICK_NOTHING = 33382
CMD_PICK_ANYTHING = 33001
_PICK_COMMANDS = {
    PickCategory.BUILDINGS: 32994,
    PickCategory.UNITS: 32995,
    PickCategory.SHRUBBERY: 32997,
    PickCategory.PROPS: 32998,
    PickCategory.NATURAL: 32999,
    PickCategory.DEBRIS: 33000,
    PickCategory.WAYPOINTS_AREAS: 33002,
    PickCategory.ROADS: 33327,
    PickCategory.SOUNDS: 33341,
}

# View menu toggles: (menu text, ViewOptions attribute, WorldBuilder command id).
_VIEW_TOGGLES = (
    ("Show &Grid", "show_grid", CMD_SHOW_GRID),
    ("Show &Texture", "show_texture", CMD_SHOW_TEXTURE),
    ("Show &Objects", "show_objects", CMD_SHOW_OBJECTS),
    ("Show &Waypoints", "show_waypoints", CMD_SHOW_WAYPOINTS),
    ("Show Trigger &Areas", "show_areas", CMD_SHOW_AREAS),
    ("Show Roa&ds", "show_roads", CMD_SHOW_ROADS),
    ("Show Wat&er", "show_water", CMD_SHOW_WATER),
    ("Show &Labels", "show_labels", CMD_SHOW_LABELS),
    ("Show Map &Boundaries", "show_boundaries", CMD_SHOW_BOUNDARIES),
    ("Show Wire&frame 3D View", "wireframe", CMD_WIREFRAME),
    ("Show All of 3d &Map", "show_entire_map", CMD_SHOW_ENTIRE_MAP),
    ("Show World&Builder Models", "world_builder_models", None),
    ("Show Object &Dots", "show_object_dots", None),
    ("Show Bounding Bo&xes", "show_bounding_boxes", CMD_SHOW_BOUNDING_BOXES),
    ("Show S&ight Ranges", "show_sight_ranges", CMD_SHOW_SIGHT_RANGES),
    ("Show Wea&pon Ranges", "show_weapon_ranges", CMD_SHOW_WEAPON_RANGES),
    ("Show Sou&nd Circles", "show_sound_circles", CMD_SHOW_SOUND_CIRCLES),
    ("Show Sound &Flags", "show_sound_flags", CMD_SHOW_SOUND_FLAGS),
    ("Show &Garrisoned", "show_garrisoned", CMD_SHOW_GARRISONED),
    ("Show Letterbo&x", "show_letterbox", CMD_SHOW_LETTERBOX),
    ("Show Sa&fe Frame Overlay", "show_safe_frame", CMD_SHOW_SAFE_FRAME),
    ("Show &Contours", "show_contours", None),
    ("Show &Impassable Areas", "show_impassable", CMD_SHOW_IMPASSABLE),
    ("Show B&lends", "show_blends", None),
    ("Show St&retched Tiles", "show_stretched", CMD_SHOW_STRETCHED),
    ("Show &Unblended Tiles", "show_unblended", CMD_SHOW_UNBLENDED),
    ("Re&verse Mouse Scrolling", "reverse_scroll", CMD_REVERSE_SCROLL),
)
# Pixels per world unit Zoom To Selected zooms in to at least: five pixels a heightmap cell.
_ZOOM_TO_SCALE = 0.5
# A panel popped out into its own window is sized to its contents within these bounds.
_FLOATING_MINIMUM = QSize(280, 200)
_FLOATING_SCREEN_SHARE = 0.8

_GUIDE_HTML = """
<h2>Getting started</h2>
<p>This is the start of a replacement for WorldBuilder. It opens, saves and autosaves maps, shows
them from above, and edits their objects, waypoints and trigger areas; the other editing tools
are still to come.</p>
<h3>The map view</h3>
<p>Drag with the middle button, or with Space held, to scroll; the wheel zooms about the cursor.
The status bar shows the heightmap sample under the cursor. The <b>View</b> menu shows or hides
the grid, textures and the rest of the terrain under <b>Show Terrain</b>, and the objects,
waypoints, trigger areas and labels under <b>Show Objects</b>; <b>View &gt; Panels</b> shows or
hides the toolbar, the status bar and each panel.</p>
<h3>Selecting and moving</h3>
<p>Click an object to select it, Shift-click to add or remove one, or drag across an empty spot
to select everything inside. Drag a selected object to move the selection, and Alt-drag to rotate
it (<b>Edit &gt; Group Edit Method</b> decides how several objects turn). <b>Edit &gt; Pick
Allowances</b> limits what a click can select. Cut, Copy, Paste and Delete work on the selection
while the map view has focus; Paste puts the copies under the cursor.</p>
<h3>Placing objects</h3>
<p>Choose an object in the <b>Object Palette</b> (search it by name) and click the map to place
it; drag from the spot to turn it. The palette sets the team it belongs to and its height above
the terrain. <b>Tools &gt; Select and Move</b> goes back to selecting.</p>
<h3>Waypoints and trigger areas</h3>
<p>With the <b>Waypoint Tool</b> (W), click to add a waypoint, drag from one waypoint to another to
link them (drag again to remove the link), or drag from a waypoint to an empty spot to add a
linked one. With the <b>Polygon Tool</b>, click the corners of a trigger area and click the first
corner again to close it. Select and Move selects an area by clicking inside it; drag it to move
it, or drag one of its corners to reshape it.</p>
<h3>Layers, helpers and the ruler</h3>
<p>The <b>Layers List</b> shows each layer with what is on it: untick a layer to hide it, and
<b>Set Active</b> to put new objects, waypoints and areas on it. The <b>Edit</b> menu selects
similar, duplicate, deprecated or missing objects and objects on missing teams, and Replace
Selected swaps the selection for the object chosen in the palette. The <b>Ruler Tool</b> measures
distances in feet and cells.</p>
<h3>Build lists</h3>
<p>The <b>Build List</b> panel shows a player's skirmish AI build list: reorder, delete, export or
import its entries, and edit the chosen one. With the <b>Build List Tool</b>, click the map to add
the object chosen in the palette to that player's list, click an entry to choose it, or drag it to
move it.</p>
<h3>Terrain height</h3>
<p><b>Height Brush</b> (H) paints a height, <b>Mound</b> (Shift+H) raises and <b>Dig</b> (Ctrl+H)
lowers the ground, and <b>Smooth Height</b> (S) evens it out as you scrub over it. The <b>Brush
Options</b> panel sets the brush width and the feather ring where its effect fades, the height to
paint and the step to raise or lower by, in feet, and how strongly smoothing works. Each stroke is
one undo entry. <b>View &gt; Show Terrain &gt; Show Contours</b> draws contour lines;
<b>Contour Options</b> sets how many.</p>
<h3>New maps</h3>
<p><b>File &gt; New</b> makes an empty map: its size and border in cells of 10 feet, its starting
height, the texture covering it, and whether it is a Living World script holder. <b>Resize</b>
changes the size and border, keeping the terrain pinned to the anchor you choose; everything on the
map moves with it. <b>Export Heightmap</b> saves the heights as a raw 16-bit image and <b>Import
Heightmap</b> reads one of the same size back; <b>Open from TGA</b> makes a new map from a grey
image.</p>
<h3>Textures</h3>
<p>Choose a texture in the <b>Terrain Material</b> panel (search it by name; the
panel switches to Texture mode). <b>Single Tile</b> (T) and <b>Large Tile</b> (Y) paint it,
<b>Flood Fill</b> (F) paints it over the area of the texture you click, and Shift with Flood Fill
replaces that texture everywhere. Alt-click with any of them, or the <b>Eyedropper</b>, picks the
texture under the cursor. Painting removes the blends on the painted cells.</p>
<h3>Blending</h3>
<p><b>Blend Single Edge</b> (E): drag from a cell onto its neighbour to fade the first cell's
texture onto it from that side; drag with the right mouse button to fade in the chosen texture
instead. <b>Auto Edge Out</b> (Shift+E) fades the texture you click over the cells around its
area, and <b>Auto Edge In</b> (Alt+E) fades the textures around the area onto its edge. Both first
fill in cells that are nearly surrounded. Hold Shift while clicking to edge every area of that
texture on the map.</p>
<p>With the game data loaded, the map shows each blend as its texture's colour fading in from the
side it comes from. <b>View &gt; Show Terrain &gt; Show Blends</b> tints the cells that have a
blend, and those with a 3-way blend as well in white.</p>
<p><b>Apply To Tiles...</b> in the Terrain Material panel paints the chosen texture on the
playable cells between two slopes, between two heights, or at random at a saturation.</p>
<h3>Copying terrain</h3>
<p><b>Terrain Copy</b> works in two modes, set in the <b>Copy Terrain Options</b> panel. In
Selection mode, drag a rectangle or brush over cells to add them to the selection (or remove
them). In Copy mode, the selection follows the cursor, flipped and turned as the panel says, and
a click copies its heights, texture and blends, and passability there. Undo takes a copy back.</p>
<h3>Whole-map texture work</h3>
<p>The <b>Texture Sizing</b> menu has <b>Remap Textures</b> (put another Terrain.ini texture behind
one the map uses, if it is the same size), <b>Remove Cliff Texture Mapping</b> and <b>Optimize
Tiles and Blend Tiles</b> (rebuild the texture and blend tables from what the map still uses).
<b>Edit &gt; Remove All Texture Blends</b> clears every blend. Two views help you check the work:
<b>Show Unblended Tiles</b> marks cells that meet another texture with no blend, and <b>Show
Stretched Tiles</b> marks cells steeper than the angle in <b>Stretched Tiles Options</b>.</p>
<h3>Passability and other cell attributes</h3>
<p><b>Single Tile</b> (T) paints one cell and <b>Large Tile</b> (Y) a square the brush width
across, with what the <b>Terrain Material</b> panel's painting mode says: passable, impassable,
impassable to players or "extra" passable; narrow or open passages; taintable or not; flammability;
visible or not. While painting, the cells that have the attribute are tinted;
<b>View &gt; Show Terrain &gt; Show Impassable Areas</b> (Ctrl+I) tints the passability ones at any
time.</p>
<h3>Roads</h3>
<p>Choose a road or bridge type in <b>Road Options</b> and drag with the <b>Road</b> tool (R) from
where a segment starts to where it ends. An end dropped on an existing road end joins onto it.
Click a segment to select it: <b>Apply To Selection</b> gives the selected segments the panel's
road type, corner type and join setting. Deleting, cutting or copying one end of a segment takes
the whole segment. <b>View &gt; Show Objects &gt; Show Roads</b> shows or hides them; roads are
drawn as plain strips, without the game's curves and joins.</p>
<h3>Water</h3>
<p>The <b>Lake/Ocean Tool</b>: click the corners of a lake, then click the first corner again.
The <b>River Tool</b>: drag across the river from one bank to the other to add a bank line to the
chosen river, or to start a new one; click open ground to finish. The <b>Waves Tool</b>: drag
where a wave area runs. With any of them, click inside an area to choose it, drag it to move it,
or drag one of its points. <b>Water Options</b> edits the chosen area's name, height, textures and
the rest, and a lake's map-wide alpha depth. A new area stands at the height of the lowest ground
under it. <b>View &gt; Show Objects &gt; Show Water</b> shows or hides the areas.</p>
<h3>Scorch marks, groves, fences, ramps, borders and molds</h3>
<p>The <b>Dressing Options</b> panel follows the tool in use. <b>Add Scorchmarks</b>: click to add
one of the chosen type and size, or drag to size it. <b>Grove</b>: choose up to five tree types
with their weights; click to place a cluster of the total count, or drag a rectangle to scatter
them in it; trees keep out of water and off cliffs unless allowed. <b>Fence</b>: choose the object
in the Object Palette and drag a row of it; hold Shift as you let go to stretch the row to the end
of the drag. <b>Ramp</b>: drag from one end of the ramp to the other. <b>Border Tool</b>: click to
add a border to the spot, drag a border's corner to resize it, Alt-click it to remove it. <b>Mesh
Mold Tool</b>: choose a mold, its scale, height and angle, click the map to place it, then
Apply.</p>
<h3>Sounds and skybox</h3>
<p><b>View &gt; Listen To Map</b> plays the ambient sounds of the objects around what the view
looks at: those whose sound is enabled, those that loop, all of them, or none. The Object
Properties <b>Listen</b> button plays the selected object's sound. <b>Validation &gt; Remove
MinVolume Customization</b> clears every object's customized minimum volume, which can silence a
sound. <b>Edit &gt; Edit Skybox Settings</b> adds, edits or removes the map's skybox.</p>
<h3>Cameras</h3>
<p>A camera animation's keys stand in the 3D view: each camera key as a camera, each look-at key as
a marker. Click one to choose it, then drag an arrow to move it along that axis, or turn it about
that axis with <b>Rotation</b> chosen under Drag handles; the arrows point along the map's axes, or
along the camera's own with <b>Local</b>. What the camera sees is drawn in the preview pane in the
corner of the 3D view, so scrubbing and playing an animation never moves the view being worked in.
<p><b>Edit &gt; Camera Options</b> opens the <b>Cameras</b> panel on the map's named cameras: New
saves the view shown, Update replaces the chosen camera with the view, Go To shows it (in the 3D
view; the top-down view centres on what it looks at). <b>Edit Camera Animations</b> opens its
animations: add a free or look-at animation, set its length, move the frame slider to see it, and
set camera and look-at keys from the view; keys are Smooth or Linear. Play runs it, Show Path draws
its path on the map.</p>
<h3>Lighting and environment</h3>
<p><b>Edit &gt; Global Light Options</b> edits the lights of the map's time of day (set in Map
Settings) for the terrain, objects, infantry or everything: the sun's ambient colour, and the
colour, heading and elevation of the sun and two accent lights, with Restore To Default. It also
turns 2X overbright lighting and bloom on or off, and sets the bloom colours, the no-cloud factor
and the shadow colour and intensity. The 3D view is lit by these lights. <b>Edit &gt; Edit Post
Effects</b> and <b>Select Macrotexture</b> / <b>Select Cloudtexture</b> open Environment Options:
the macro and cloud textures, and the post effect's blend factor and lookup image.</p>
<h3>Game data</h3>
<p>The editor reads the installed game (found automatically) and, optionally, unpacked mod
folders mounted above it, the way the game's <code>-mod</code> switch does: their loose files and
<code>.big</code> archives win over the install's, and a mod loaded later wins over one loaded
earlier. <b>Game &gt; Load Mod</b> adds one on top of those already loaded (before or after
opening a map), <b>Recent Mods</b> loads or unloads one (a tick marks the loaded ones) and
<b>Unload All Mods</b> returns to the install alone; <code>sage-worldbuilder -mod &lt;folder&gt;
</code> loads one at startup, and repeating it loads several in that order. <b>Game &gt; Game
Settings</b> sets the install and reorders the loaded mods. <b>Game &gt; Load Patch File</b> picks
the <code>.sagepatch</code> of a patched <code>game.dat</code> (<code>sage-worldbuilder -sagepatch
&lt;file&gt;</code> at startup): the fields, block types and tokens its patches add are read as
game data rather than as mistakes, and <b>Jump To Game</b> applies its patches to
<code>game.dat</code> for the session, putting the original back when WorldBuilder closes. Maps
shipped inside the game's
<code>.big</code> archives are listed and open read-only; use <b>Save As</b> to keep a copy.</p>
<h3>Opening and saving</h3>
<p><b>File &gt; Open</b> lists maps by WorldBuilder's categories. <b>Save As</b> saves into
User Maps (your user-data folder) or, with mods loaded, into the last one loaded. A map saves back
byte-identical when nothing changed, compressed exactly when it was compressed before.</p>
<h3>Shortcuts</h3>
<p>The keys are WorldBuilder's own: <b>Help &gt; Keyboard Shortcuts</b> lists them all.</p>
"""

_ABOUT_HTML = (
    "<p><b>SAGE WorldBuilder</b> is a map editor for the SAGE engine games, part of pySAGE.</p>"
)


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        load_game_data: bool = True,
        initial_path: Path | None = None,
        mods: Sequence[Path] = (),
        sagepatch: Path | None = None,
        extra_checks: MapChecks | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings if settings is not None else Settings.load()
        # A mod overlay's own map rules, which Generate Report adds to its findings.
        self.extra_checks = extra_checks
        self.document: MapDocument | None = None
        self.context: GameContext | None = None
        # The library maps the Scripts panel reads, kept so an item it shows keeps its identity.
        self._library_maps = LibraryMaps(self._read_library_map)
        self.autosaver: Autosaver | None = None
        self.available_commands: set[int] = set()
        self._busy = False
        self._document_links: list[Callable[[], None]] = []
        self._load_generation = 0
        # Texture colours for the map view, kept per loaded game; the generation drops the
        # result of a computation the open map or game has moved on from.
        self._texture_colors: TextureColors | None = None
        # The 3D view's object models and the art they are read from, kept per loaded game.
        self._object_models: ObjectModels | None = None
        self._art_index: ArtIndex | None = None
        # The 3D view's water and road textures, for the game context they were read from.
        self._art_textures: tuple[GameContext, ArtTextures] | None = None
        # Mesh molds' triangles by file name, read once per game.
        self._mold_meshes: dict[str, Any] = {}
        self._apply_texture_options = ApplyTextureOptions()
        # The view's texture colours per heightmap sample, before blends, to patch its picture
        # from; and the blend table, with the description and texture counts it was made for.
        self._sample_colors: np.ndarray | None = None
        self._blend_table: tuple[tuple[int, int], BlendTable] | None = None
        self._texture_previews: dict[str, QPixmap | None] = {}
        # How many textures the map had when the palette was last filled.
        self._catalogue_textures = -1
        self._texture_game: Game | None = None
        self._texture_generation = 0
        # Kinds of change made during a drag in the map view, for the panels to catch up on.
        self._held_changes: set[ChangeKind] = set()
        self._pick_rules: PickRules | None = None
        # The game.dat files Jump To Game patched, put back when the window closes.
        self._patched_game_dats: set[Path] = set()
        # Set once an elevated copy of the editor was started to take over: closing then neither
        # asks about changes nor restores game.dat, which the new editor does on start.
        self._handed_over = False

        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(app_icon())
        self.resize(1280, 800)
        # Panels can be pulled out into windows of their own and dropped onto each other:
        # grouped dragging makes a floating panel a window other panels can be tabbed into,
        # and nested docks let a dropped panel split the side it lands on.
        options = QMainWindow.DockOption
        self._dock_options = (
            options.AnimatedDocks
            | options.AllowTabbedDocks
            | options.AllowNestedDocks
            | options.GroupedDragging
        )
        self.setDockOptions(self._dock_options)
        self.map_view = MapView(self.settings.view)
        # The 3D view, made the first time it is opened.
        self.map_view_3d: MapView3D | None = None
        # The actions whose keys work only while a map view has focus.
        self._map_view_actions: list[QAction] = []
        self.select_tool = SelectTool(self)
        self.place_tool = PlaceTool(self)
        self.paste_tool = PasteTool(self)
        # The tool Paste took over from, given back once the paste is put down or given up.
        self._before_paste: Tool | None = None
        self.array_tool = RadialArrayTool(self)
        self.move_tool = MoveTool(self)
        self.rotate_tool = RotateTool(self)
        self.waypoint_tool = WaypointTool(self)
        self.polygon_tool = PolygonTool(self)
        self.ruler_tool = RulerTool(self)
        self.build_list_tool = BuildListTool(self)
        self.road_tool = RoadTool(self)
        self.generic_ai_tool = GenericAIObjectTool(self)
        self.water_tools = {kind: WaterTool(self, kind) for kind, *_ in _WATER_TOOLS}
        self.mesh_mold_tool = MeshMoldTool(self)
        self.dressing_tools = {
            "scorch": ScorchTool(self),
            "grove": GroveTool(self),
            "fence": FenceTool(self),
            "ramp": RampTool(self),
            "border": BorderTool(self),
            "mesh mold": self.mesh_mold_tool,
        }
        self.height_tools = {kind: HeightBrushTool(self, kind) for kind, *_ in _HEIGHT_TOOLS}
        self.single_tile_tool = TilePaintTool(self, large=False)
        self.large_tile_tool = TilePaintTool(self, large=True)
        self.flood_fill_tool = FloodFillTool(self)
        self.eyedropper_tool = EyedropperTool(self)
        self.blend_single_edge_tool = BlendSingleEdgeTool(self)
        self.auto_edge_out_tool = AutoEdgeTool(self, outward=True)
        self.auto_edge_in_tool = AutoEdgeTool(self, outward=False)
        self.terrain_copy_tool = TerrainCopyTool(self)
        self.map_view.tool = self.select_tool
        self._build_actions()
        self._build_toolbar()
        self._build_docks()
        self._build_menus()
        self._build_status_bar()
        # The central area: the top-down view, or the 3D view once it has been opened.
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.map_view)
        self.setCentralWidget(self.view_stack)
        self.map_view.cursor_moved.connect(self.show_cursor)
        self.map_view.gesture_finished.connect(self._gesture_finished)
        board = QGuiApplication.clipboard()
        if board is not None:
            # Another editor copying objects makes Paste available here.
            board.dataChanged.connect(self._refresh)
        self._default_state = self.saveState()
        self._restore_layout()
        self._apply_layout_lock()

        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave)
        if mods:
            # `-mod` from the command line: these mods, in this order, before any map opens.
            self.settings.mods = []
            for mod in mods:
                self._remember_mod(str(mod))
        if sagepatch is not None:
            self.settings.sagepatch = str(sagepatch)
            self.settings.save()
        # What reading or applying the `.sagepatch` reported, shown with the game status.
        self._engine_problems: list[str] = []
        self.apply_game_layers(load=load_game_data)
        self._restore_leftover_patch()
        self._rebuild_recent_menu()
        self._rebuild_recent_mods_menu()
        self._refresh()
        if self.settings.view.view_3d:
            # The map opens in 3D unless the last run was left in the top-down view; without
            # PyOpenGL `show_3d_view` says so in the status bar and the top-down view stays.
            self.show_3d_view(True)
        if initial_path is not None:
            QTimer.singleShot(0, lambda: self.open_path(initial_path))

    def _action(
        self,
        text: str,
        slot: Callable[[], Any],
        *,
        command: int | None = None,
        fallback: QKeySequence.StandardKey | None = None,
        tip: str | None = None,
    ) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(lambda _checked=False: slot())
        keys = shortcuts_for(command) if command is not None else []
        if keys:
            action.setShortcuts([QKeySequence(key) for key in keys])
        elif fallback is not None:
            action.setShortcuts(QKeySequence.keyBindings(fallback))
        if command is not None:
            self.available_commands.add(command)
        if tip is not None:
            action.setStatusTip(tip)
        self.addAction(action)
        return action

    def _build_actions(self) -> None:
        self.new_action = self._action(
            "&New…", self.new_map, command=CMD_NEW, fallback=QKeySequence.StandardKey.New
        )
        self.open_from_tga_action = self._action(
            "Open from &TGA…",
            self.open_from_tga,
            command=CMD_OPEN_FROM_TGA,
            tip="Make a new map from a grey image: each grey level is 0.625 ft of height.",
        )
        self.import_heightmap_action = self._action(
            "&Import Heightmap…", self.import_heightmap, command=CMD_IMPORT_HEIGHTMAP
        )
        self.export_heightmap_action = self._action(
            "E&xport Heightmap…", self.export_heightmap, command=CMD_EXPORT_HEIGHTMAP
        )
        self.resize_action = self._action("Resi&ze…", self.resize_map, command=CMD_RESIZE)
        self.open_action = self._action("&Open…", self.open_map, command=CMD_OPEN)
        self.close_action = self._action("&Close", self.close_map, command=CMD_CLOSE)
        self.save_action = self._action("&Save", self.save, command=CMD_SAVE)
        self.save_as_action = self._action(
            "Save &As…", self.save_as, command=CMD_SAVE_AS, fallback=QKeySequence.StandardKey.SaveAs
        )
        self.exit_action = self._action(
            "E&xit", self.close, command=CMD_EXIT, fallback=QKeySequence.StandardKey.Quit
        )
        self.undo_action = self._action("&Undo", self.undo, command=CMD_UNDO)
        self.redo_action = self._action("&Redo", self.redo, command=CMD_REDO)
        self.repeat_action = self._action("Re&peat", self.repeat, command=CMD_REPEAT)
        self.reset_layout_action = self._action("&Reset Window Positions", self.reset_layout)
        self.lock_layout_action = QAction("&Lock Layout", self)
        self.lock_layout_action.setCheckable(True)
        self.lock_layout_action.setChecked(self.settings.lock_layout)
        self.lock_layout_action.setStatusTip(
            "Keep the panels where they are: dragging one over another moves it instead of "
            "docking or tabbing the two together."
        )
        self.lock_layout_action.toggled.connect(self.set_layout_locked)
        self.next_pane_action = self._action(
            "&Next Pane", lambda: self._cycle_pane(1), command=CMD_NEXT_PANE
        )
        self.previous_pane_action = self._action(
            "&Previous Pane", lambda: self._cycle_pane(-1), command=CMD_PREVIOUS_PANE
        )
        self.load_mod_action = self._action(
            "Load &Mod…",
            self.choose_mod,
            tip="Mount an unpacked mod folder above the game install and the mods already loaded, "
            "as a later -mod does.",
        )
        self.unload_mod_action = self._action("&Unload All Mods", self.unload_all_mods)
        self.load_sagepatch_action = self._action(
            "Load &Patch File…",
            self.choose_sagepatch,
            tip="Read the INI a patched game.dat accepts from its .sagepatch, and apply its "
            "patches when jumping to the game.",
        )
        self.unload_sagepatch_action = self._action(
            "Unload Patch File", lambda: self.load_sagepatch(None)
        )
        self.game_settings_action = self._action("Game &Settings…", self.edit_game_settings)
        self.reload_game_action = self._action("&Reload Game Data", self.reload_game_data)
        self.shortcuts_action = self._action("&Keyboard Shortcuts…", self.show_shortcuts)
        self.scripts_action = self._action("&Scripts…", self.show_scripts, command=CMD_SCRIPTS)
        self.jump_action = self._action(
            "&Jump To Game",
            self.jump_to_game,
            tip="Save the map and start the game on it (Game > Jump To Game Settings for the "
            "match, Game > Game Settings for the window and arguments).",
        )
        self.script_debugger_action = self._action(
            "Script &Debugger",
            lambda: self._show_dock(self.script_debugger_dock),
            tip="Attach to the running game and follow its scripts, counters, timers and flags.",
        )
        self.mapcache_action = self._action(
            "&MapCache Entry…",
            self.show_mapcache_entry,
            tip="The mapcache.ini entry this map needs before the game will list it.",
        )
        self.jump_settings_action = self._action(
            "Jump To Game Se&ttings…",
            self.edit_jump_settings,
            tip="The match Jump To Game starts: seats, factions, AI difficulty, start positions, "
            "colours, teams, starting resources and seed.",
        )
        self.report_action = self._action("&Generate Report", self.generate_report)
        self.players_action = self._action(
            "Edit &Player List…", lambda: self._show_dock(self.players_dock), command=CMD_PLAYERS
        )
        self.teams_action = self._action(
            "Edit &Teams…", lambda: self._show_dock(self.teams_dock), command=CMD_TEAMS
        )
        self.map_settings_action = self._action(
            "Edit &Map Settings…", lambda: self._show_dock(self.map_settings_dock)
        )
        self.skybox_action = self._action(
            "Edit S&kybox Settings…",
            lambda: self._show_dock(self.environment_dock),
            command=CMD_EDIT_SKYBOX,
        )
        self.remove_min_volume_action = self._action(
            "Remove &MinVolume Customization",
            self.remove_min_volume_customization,
            command=CMD_REMOVE_MIN_VOLUME,
        )
        self.listen_group = QActionGroup(self)
        self.listen_group.setExclusive(True)
        self.listen_actions: dict[ListenMode, QAction] = {}
        for mode, text, command in _LISTEN_MODES:
            action = self._action(text, partial(self.set_listen_mode, mode), command=command)
            action.setCheckable(True)
            action.setChecked(mode is ListenMode.NONE)
            self.listen_group.addAction(action)
            self.listen_actions[mode] = action
        self.camera_options_action = self._action(
            "Camera &Options…", lambda: self._show_cameras(0), command=CMD_CAMERA_OPTIONS
        )
        self.camera_animations_action = self._action(
            "Edit Camera A&nimations…", lambda: self._show_cameras(1), command=CMD_CAMERA_ANIMATIONS
        )
        self.global_light_action = self._action(
            "&Global Light Options…",
            lambda: self._show_dock(self.lighting_dock),
            command=CMD_GLOBAL_LIGHT_OPTIONS,
        )
        self.shadows_action = self._action(
            "Edit S&hadows…", lambda: self._show_dock(self.lighting_dock), command=CMD_EDIT_SHADOWS
        )
        self.time_of_day_action = self._action(
            "Change Time Of Da&y",
            self.change_time_of_day,
            command=CMD_CHANGE_TIME_OF_DAY,
            tip="Step the map's time of day: Morning, Afternoon, Evening, Night.",
        )
        self.post_effects_action = self._action(
            "Edit Post &Effects…",
            lambda: self._show_dock(self.environment_dock),
            command=CMD_EDIT_POST_EFFECTS,
        )
        self.macro_texture_action = self._action(
            "Select Macr&otexture…",
            lambda: self._show_dock(self.environment_dock),
            command=CMD_SELECT_MACROTEXTURE,
        )
        self.cloud_texture_action = self._action(
            "Select Clou&dtexture…",
            lambda: self._show_dock(self.environment_dock),
            command=CMD_SELECT_CLOUDTEXTURE,
        )
        self.mp_positions_action = self._action(
            "M&ultiplayer Positions…", lambda: self._show_dock(self.mp_positions_dock)
        )
        self.item_list_action = self._action(
            "&Item List…", lambda: self._show_dock(self.item_list_dock), command=CMD_ITEM_LIST
        )
        # WorldBuilder binds a second command to the same list; both keys open it here.
        extra_keys = [QKeySequence(key) for key in shortcuts_for(CMD_ITEM_LIST_ALTERNATE)]
        self.item_list_action.setShortcuts(self.item_list_action.shortcuts() + extra_keys)
        self.available_commands.add(CMD_ITEM_LIST_ALTERNATE)

        self.view_actions: dict[str, QAction] = {}
        for text, name, command in _VIEW_TOGGLES:
            action = self._action(text, partial(self._toggle_view, name), command=command)
            action.setCheckable(True)
            action.setChecked(bool(getattr(self.settings.view, name)))
            self.view_actions[name] = action
        self.grid_settings_action = self._action(
            "Grid Se&ttings…", self.edit_grid_settings, command=CMD_GRID_SETTINGS
        )
        self.safe_frame_settings_action = self._action(
            "Safe Frame Overlay &Settings…",
            self.edit_safe_frame_settings,
            command=CMD_SAFE_FRAME_SETTINGS,
        )
        self.fit_view_action = self._action("Show W&hole Map", lambda: self.active_view().fit_map())
        self.view_3d_action = self._action(
            "&3D View",
            lambda: self.show_3d_view(self.view_3d_action.isChecked()),
            tip="Show the map in 3D. Middle-drag pans, Ctrl+middle-drag or right-drag orbits.",
        )
        self.view_3d_action.setCheckable(True)
        self.view_3d_action.setShortcut(QKeySequence("F3"))
        self.top_down_action = self._action(
            "Show From T&op Down View",
            lambda: self._set_top_down(self.top_down_action.isChecked()),
            command=CMD_TOP_DOWN,
        )
        self.top_down_action.setCheckable(True)
        self.game_camera_action = self._action(
            "&Game Camera",
            self.use_game_camera,
            tip="Look from the map's own camera settings: its pitch, yaw and camera height.",
        )
        self.reload_textures_action = self._action(
            "Reload Te&xtures", self.reload_textures, command=CMD_RELOAD_TEXTURES
        )
        self.partial_map_actions = QActionGroup(self)
        self.partial_map_actions.setExclusive(True)
        for size in PARTIAL_MAP_SIZES:
            action = self._action(
                f"Partial Map Size: {size} Cells", partial(self._set_partial_map_size, size)
            )
            action.setCheckable(True)
            action.setChecked(size == self.settings.view.partial_map_size)
            self.partial_map_actions.addAction(action)

        self.cut_action = self._view_action("Cu&t", self.cut, CMD_CUT)
        self.copy_action = self._view_action("&Copy", self.copy, CMD_COPY)
        self.paste_action = self._view_action("&Paste", self.paste, CMD_PASTE)
        self.delete_action = self._view_action("&Delete", self.delete_selection, CMD_DELETE)

        self.group_edit_actions = QActionGroup(self)
        self.group_edit_actions.setExclusive(True)
        for method, command in _GROUP_EDIT_COMMANDS.items():
            action = self._action(
                method.value, partial(self._set_group_edit, method), command=command
            )
            action.setCheckable(True)
            action.setChecked(method is self.settings.group_edit_method)
            self.group_edit_actions.addAction(action)

        self.pick_nothing_action = self._action(
            "Nothing", partial(self._set_allowances, NOTHING), command=CMD_PICK_NOTHING
        )
        self.pick_anything_action = self._action(
            "Anything", partial(self._set_allowances, ANYTHING), command=CMD_PICK_ANYTHING
        )
        self.pick_actions: dict[PickCategory, QAction] = {}
        for category, command in _PICK_COMMANDS.items():
            action = self._action(
                category.value.replace("&", "&&"), self._allowances_toggled, command=command
            )
            action.setCheckable(True)
            action.setChecked(category in self.settings.pick_allowances)
            self.pick_actions[category] = action

        self.lock_selection_action = self._action(
            "Lock &Selection", self._lock_selection_toggled, command=CMD_LOCK_SELECTION
        )
        self.lock_selection_action.setCheckable(True)
        self.lock_angle_action = self._action(
            "Lock &Angle",
            lambda: None,
            command=CMD_LOCK_ANGLE,
            tip="Move objects only along the eight 45-degree directions.",
        )
        self.lock_angle_action.setCheckable(True)
        self.lock_vertical_action = self._action(
            "Lock &Vertical",
            lambda: None,
            command=CMD_LOCK_VERTICAL,
            tip="Drag objects only up and down.",
        )
        self.lock_vertical_action.setCheckable(True)

        self.tool_actions = QActionGroup(self)
        self.tool_actions.setExclusive(True)
        self.select_tool_action = self._action(
            "&Select and Move",
            partial(self.use_tool, "select"),
            command=CMD_SELECT_TOOL,
            tip="Select, move and rotate objects.",
        )
        self.place_tool_action = self._action(
            "&Place Object",
            partial(self.use_tool, "place"),
            command=CMD_PLACE_OBJECT,
            tip="Place the object chosen in the Object Palette; drag to orient.",
        )
        self.move_tool_action = self._action(
            "&Move Tool",
            partial(self.use_tool, "move"),
            tip="Move the selection along one axis: drag an arrow of the gizmo, or its centre "
            "for a free move. X, Y and Z switch the axis during the drag.",
        )
        self.rotate_tool_action = self._action(
            "Rota&te Tool",
            partial(self.use_tool, "rotate"),
            tip="Turn the selection: drag the ring around it. Lock Angle holds it to the eight "
            "45-degree headings.",
        )
        self.array_tool_action = self._action(
            "Radial &Array",
            partial(self.use_tool, "array"),
            tip="Repeat the palette's object, or the selection, evenly around a centre: press "
            "where the centre goes and drag outwards.",
        )
        self.waypoint_tool_action = self._action(
            "&Waypoint Tool",
            partial(self.use_tool, "waypoint"),
            command=CMD_WAYPOINT_TOOL,
            tip="Add and connect waypoints.",
        )
        self.polygon_tool_action = self._action(
            "P&olygon Tool",
            partial(self.use_tool, "polygon"),
            command=CMD_POLYGON_TOOL,
            tip="Create polygon trigger areas: click corners, then click the first one again.",
        )
        self.ruler_tool_action = self._action(
            "&Ruler Tool",
            partial(self.use_tool, "ruler"),
            command=CMD_RULER_TOOL,
            tip="Measure distance between two points.",
        )
        self.build_list_tool_action = self._action(
            "&Build List Tool",
            partial(self.use_tool, "build list"),
            command=CMD_BUILD_LIST_TOOL,
            tip="Add/modify the build list.",
        )
        self.road_tool_action = self._action(
            "Roa&d",
            partial(self.use_tool, "road"),
            command=CMD_ROAD_TOOL,
            tip="Click and Drag to make Roads.",
        )
        self.generic_ai_tool_action = self._action(
            "Generic &AI Object Tool",
            partial(self.use_tool, "generic ai"),
            command=CMD_GENERIC_AI_TOOL,
            tip="Add generic AI objects (wall hubs, expansion locators): click to add, click one "
            "to choose it.",
        )
        self.dressing_tool_actions = {
            name: self._action(text, partial(self.use_tool, name), command=command, tip=tip)
            for name, text, command, tip in _DRESSING_TOOLS
        }
        self.water_tool_actions = {
            kind: self._action(text, partial(self.use_tool, name), command=command, tip=tip)
            for kind, name, text, command, tip in _WATER_TOOLS
        }
        self.height_tool_actions = {
            kind: self._action(text, partial(self.use_tool, kind.value), command=command, tip=tip)
            for kind, text, command, tip in _HEIGHT_TOOLS
        }
        self.single_tile_action = self._action(
            "Single &Tile",
            partial(self.use_tool, "single tile"),
            command=CMD_SINGLE_TILE,
            tip="Draws the current texture tile (or, in another painting mode, the Terrain "
            "Material panel's cell attribute).",
        )
        self.large_tile_action = self._action(
            "&Large Tile",
            partial(self.use_tool, "large tile"),
            command=CMD_LARGE_TILE,
            tip="Draws a Brush Options Size block of the current texture tile (or, in another "
            "painting mode, the Terrain Material panel's cell attribute).",
        )
        self.flood_fill_action = self._action(
            "&Flood Fill",
            partial(self.use_tool, "flood fill"),
            command=CMD_FLOOD_FILL,
            tip="Fills an area with the current texture. Hold SHIFT key to replace all "
            "occurrences of the texture under the tool.",
        )
        self.eyedropper_action = self._action(
            "&Eyedropper",
            partial(self.use_tool, "eyedropper"),
            command=CMD_EYEDROPPER,
            tip="Hot key ALT. Selects the foreground texture by picking on the texture in the "
            "edit windows.",
        )
        self.blend_single_edge_action = self._action(
            "&Blend Single Edge",
            partial(self.use_tool, "blend single edge"),
            command=CMD_BLEND_SINGLE_EDGE,
            tip="Blends a single tile edge. Right mouse uses foreground texture.",
        )
        self.auto_edge_out_action = self._action(
            "Auto Edge &Out",
            partial(self.use_tool, "auto edge out"),
            command=CMD_AUTO_EDGE_OUT,
            tip="Auto edges the current texture area outward. Hold SHIFT to edge every area of "
            "the texture.",
        )
        self.auto_edge_in_action = self._action(
            "Auto Edge &In",
            partial(self.use_tool, "auto edge in"),
            command=CMD_AUTO_EDGE_IN,
            tip="Auto edges the current texture area inward. Hold SHIFT to edge every area of "
            "the texture.",
        )
        self.terrain_copy_action = self._action(
            "Terrain &Copy",
            partial(self.use_tool, "terrain copy"),
            command=CMD_TERRAIN_COPY,
            tip="Select and copy terrain.",
        )
        for action in (
            self.select_tool_action,
            self.move_tool_action,
            self.rotate_tool_action,
            self.place_tool_action,
            self.array_tool_action,
            self.waypoint_tool_action,
            self.polygon_tool_action,
            self.build_list_tool_action,
            self.road_tool_action,
            self.generic_ai_tool_action,
            *self.water_tool_actions.values(),
            *self.dressing_tool_actions.values(),
            self.ruler_tool_action,
            *self.height_tool_actions.values(),
            self.single_tile_action,
            self.large_tile_action,
            self.flood_fill_action,
            self.eyedropper_action,
            self.blend_single_edge_action,
            self.auto_edge_out_action,
            self.auto_edge_in_action,
            self.terrain_copy_action,
        ):
            action.setCheckable(True)
            self.tool_actions.addAction(action)
        self.circular_ruler_action = self._action("&Circular Measurements", self.map_view.update)
        self.circular_ruler_action.setCheckable(True)
        self.contour_options_action = self._action("Co&ntour Options…", self.edit_contour_options)
        self.stretched_options_action = self._action(
            "Stretched Tiles &Options…", self.edit_stretched_options, command=CMD_STRETCHED_OPTIONS
        )
        self.optimize_tiles_action = self._action(
            "&Optimize Tiles and Blend Tiles", self.optimize_tiles, command=CMD_OPTIMIZE_TILES
        )
        self.remove_cliff_mapping_action = self._action(
            "&Remove Cliff Texture Mapping…",
            self.remove_cliff_mappings,
            command=CMD_REMOVE_CLIFF_MAPPING,
        )
        self.remove_blends_action = self._action(
            "Remove All Texture &Blends…", self.remove_all_blends, command=CMD_REMOVE_BLENDS
        )
        self.adjust_terrain_action = self._action(
            "&Adjust Terrain to GROUND Objects…",
            self.adjust_terrain_to_ground,
            command=CMD_ADJUST_TERRAIN,
            tip="Raise the ground to the GROUND meshes of the objects standing on it.",
        )
        self.remap_textures_action = self._action(
            "Re&map Textures…", self.remap_textures, command=CMD_REMAP_TEXTURES
        )

        self.select_similar_action = self._action(
            "Select Si&milar", self.select_similar, command=CMD_SELECT_SIMILAR
        )
        self.select_duplicates_action = self._action(
            "Select D&uplicate Objects",
            lambda: self._select_found(
                lambda map: duplicate_objects(map, anchors=self.map_view.anchors),
                "duplicate objects",
            ),
            command=CMD_SELECT_DUPLICATES,
        )
        self.select_bad_teams_action = self._action(
            "Select Objects w/&bad Teams",
            lambda: self._select_found(objects_with_bad_teams, "objects on missing teams"),
            command=CMD_SELECT_BAD_TEAMS,
        )
        self.select_deprecated_action = self._action(
            "Select D&eprecated Objects",
            lambda: self._select_with_game(deprecated_objects, "deprecated objects"),
            command=CMD_SELECT_DEPRECATED,
        )
        self.select_missing_action = self._action(
            "Select Objects Missing From the &Game",
            lambda: self._select_with_game(missing_objects, "objects the game does not define"),
        )
        self.select_siblings_action = self._action(
            "All &Siblings of Current",
            lambda: self._select_found(
                lambda map: base_siblings(map, self.selected_objects()),
                "objects of the same base",
            ),
            command=CMD_SELECT_SIBLINGS,
            tip="Select every object of the base the selected objects belong to.",
        )
        self.select_base_parent_action = self._action(
            "&Parent of Current",
            lambda: self._select_found(
                lambda map: base_parents(map, self.selected_objects()), "base objects"
            ),
            command=CMD_SELECT_BASE_PARENT,
            tip="Select the object the selected objects' base is built around.",
        )
        self.replace_selected_action = self._action(
            "&Replace Selected…",
            self.replace_selected,
            command=CMD_REPLACE_SELECTED,
            tip="Replace the selected objects with the object chosen in the Object Palette.",
        )
        self.select_tool_action.setChecked(True)

    def _view_action(self, text: str, slot: Callable[[], Any], command: int) -> QAction:
        """An action whose keys work only while the map view has focus, so Delete or Ctrl+C in
        a panel keeps its own meaning there."""
        action = self._action(text, slot, command=command)
        self.removeAction(action)
        self.map_view.addAction(action)
        if self.map_view_3d is not None:
            self.map_view_3d.addAction(action)
        self._map_view_actions.append(action)
        action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        return action

    def _build_toolbar(self) -> None:
        self.toolbar = QToolBar("Toolbar", self)
        self.toolbar.setObjectName("mainToolbar")
        self.toolbar.addActions([self.open_action, self.save_action])
        self.toolbar.addSeparator()
        self.toolbar.addActions([self.undo_action, self.redo_action])
        self.toolbar.addSeparator()
        self.toolbar.addActions(self.tool_actions.actions())
        self.toolbar.addSeparator()
        self.toolbar.addActions(
            [self.lock_selection_action, self.lock_angle_action, self.lock_vertical_action]
        )
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.jump_action)
        self.addToolBar(self.toolbar)
        self.available_commands.update({CMD_TOOLBAR, CMD_STATUS_BAR})

    def _build_docks(self) -> None:
        map_panel = QWidget()
        self.map_form = QFormLayout(map_panel)
        self.map_dock = self._dock("Map", "mapDock", map_panel)

        self.scripts_panel = ScriptsPanel(self, self._library_maps, self.go_to_target)
        self.scripts_dock = self._dock(
            "Scripts", "scriptsDock", self.scripts_panel, Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.validation_panel = ValidationPanel(
            self, self._select_script, extra_checks=self.extra_checks
        )
        self.validation_dock = self._dock(
            "Validation",
            "validationDock",
            self.validation_panel,
            Qt.DockWidgetArea.BottomDockWidgetArea,
        )
        self.script_debugger_panel = ScriptDebuggerPanel(self)
        self.script_debugger_panel.live_changed.connect(self.scripts_panel.set_live)
        self.script_debugger_panel.script_activated.connect(self._select_script)
        self.script_debugger_panel.breakpoints_changed.connect(self.scripts_panel.set_breakpoints)
        self.script_debugger_panel.elevation_requested.connect(self.restart_elevated)
        self.scripts_panel.debugger = self.script_debugger_panel
        self.script_debugger_dock = self._dock(
            "Script Debugger",
            "scriptDebuggerDock",
            self.script_debugger_panel,
            Qt.DockWidgetArea.BottomDockWidgetArea,
        )
        self.tabifyDockWidget(self.validation_dock, self.script_debugger_dock)
        self.validation_dock.raise_()

        left = Qt.DockWidgetArea.LeftDockWidgetArea
        self.players_panel = PlayersPanel(self, self._library_names)
        self.players_dock = self._dock("Player List", "playersDock", self.players_panel, left)
        self.teams_panel = TeamsPanel(self)
        self.teams_dock = self._dock("Teams", "teamsDock", self.teams_panel, left)
        self.map_settings_panel = MapSettingsPanel(self)
        self.map_settings_dock = self._dock(
            "Map Settings", "mapSettingsDock", self.map_settings_panel, left
        )
        self.mp_positions_panel = MultiplayerPositionsPanel(self)
        self.mp_positions_dock = self._dock(
            "Multiplayer Positions", "mpPositionsDock", self.mp_positions_panel, left
        )
        for dock in (
            self.players_dock,
            self.teams_dock,
            self.map_settings_dock,
            self.mp_positions_dock,
        ):
            self.tabifyDockWidget(self.scripts_dock, dock)
        self.scripts_dock.raise_()

        self.item_list_panel = ItemListPanel(
            self, self._select_team, self._zoom_to, self.map_view.set_shown, self._select_item
        )
        self.item_list_dock = self._dock("Item List", "itemListDock", self.item_list_panel)
        self.tabifyDockWidget(self.map_dock, self.item_list_dock)
        self.object_panel = ObjectPropertiesPanel(self)
        self.object_dock = self._dock(
            "Object Properties", "objectPropertiesDock", self.object_panel
        )
        self.tabifyDockWidget(self.map_dock, self.object_dock)
        self.palette_panel = ObjectPalettePanel(self)
        self.palette_panel.template_chosen.connect(self._template_chosen)
        self.palette_dock = self._dock("Object Palette", "objectPaletteDock", self.palette_panel)
        self.tabifyDockWidget(self.map_dock, self.palette_dock)
        self.layers_panel = LayersPanel(self)
        self.layers_panel.visibility_changed.connect(
            lambda: self.map_view.set_hidden_layers(self.layers_panel.hidden)
        )
        self.layers_dock = self._dock("Layers List", "layersDock", self.layers_panel)
        self.tabifyDockWidget(self.map_dock, self.layers_dock)
        self.build_list_panel = BuildListPanel(self)
        self.build_list_panel.entry_changed.connect(self._build_entry_changed)
        self.build_list_dock = self._dock("Build List", "buildListDock", self.build_list_panel)
        self.tabifyDockWidget(self.map_dock, self.build_list_dock)
        self.brush_panel = BrushOptionsPanel(self.settings.brush)
        self.brush_dock = self._dock("Brush Options", "brushOptionsDock", self.brush_panel)
        self.tabifyDockWidget(self.map_dock, self.brush_dock)
        self.terrain_material_panel = TerrainMaterialPanel(self.settings.paint)
        self.terrain_material_panel.set_preview_source(self._texture_preview)
        self.terrain_material_panel.changed.connect(self._update_overlay)
        self.terrain_material_panel.apply_requested.connect(self.apply_texture_to_tiles)
        self.terrain_material_dock = self._dock(
            "Terrain Material", "terrainMaterialDock", self.terrain_material_panel
        )
        self.tabifyDockWidget(self.map_dock, self.terrain_material_dock)
        self.copy_terrain_panel = CopyTerrainOptionsPanel(self.settings.copy_terrain)
        self.copy_terrain_panel.changed.connect(self.map_view.update)
        self.copy_terrain_panel.clear_requested.connect(self._clear_terrain_selection)
        self.copy_terrain_dock = self._dock(
            "Copy Terrain Options", "copyTerrainDock", self.copy_terrain_panel
        )
        self.tabifyDockWidget(self.map_dock, self.copy_terrain_dock)
        self.array_panel = ArrayOptionsPanel(self.settings.array)
        self.array_panel.changed.connect(self.map_view.update)
        self.array_dock = self._dock("Array Options", "arrayOptionsDock", self.array_panel)
        self.tabifyDockWidget(self.map_dock, self.array_dock)
        self.road_panel = RoadOptionsPanel()
        self.road_panel.apply_requested.connect(self.apply_road_options)
        self.road_dock = self._dock("Road Options", "roadOptionsDock", self.road_panel)
        self.tabifyDockWidget(self.map_dock, self.road_dock)
        self.water_panel = WaterOptionsPanel(self)
        self.water_panel.area_chosen.connect(self._select_item)
        self.water_panel.center_requested.connect(self._zoom_to)
        self.water_dock = self._dock("Water Options", "waterOptionsDock", self.water_panel)
        self.tabifyDockWidget(self.map_dock, self.water_dock)
        self.lighting_panel = GlobalLightOptionsPanel(self)
        self.lighting_dock = self._dock(
            "Global Light Options", "globalLightOptionsDock", self.lighting_panel
        )
        self.tabifyDockWidget(self.map_dock, self.lighting_dock)
        self.environment_panel = EnvironmentOptionsPanel(self)
        self.environment_panel.camera_target = lambda: self.current_view().target
        self.ambient_player = AmbientPlayer(self, parent=self)
        self.object_panel.listen = self.listen_to_object
        self.environment_dock = self._dock(
            "Environment Options", "environmentOptionsDock", self.environment_panel
        )
        self.tabifyDockWidget(self.map_dock, self.environment_dock)
        self.dressing_panel = DressingOptionsPanel()
        self.dressing_panel.mold_apply_requested.connect(self.apply_mesh_mold)
        self.dressing_dock = self._dock(
            "Dressing Options", "dressingOptionsDock", self.dressing_panel
        )
        self.tabifyDockWidget(self.map_dock, self.dressing_dock)
        self.generic_ai_panel = GenericAIOptionsPanel(self)
        self.generic_ai_dock = self._dock(
            "Generic AI Object Options", "genericAIObjectOptionsDock", self.generic_ai_panel
        )
        self.tabifyDockWidget(self.map_dock, self.generic_ai_dock)
        self.camera_panel = CameraPanel(self)
        self.camera_panel.view_requested.connect(self.show_camera_view)
        self.camera_panel.path_changed.connect(self._camera_path_changed)
        self.camera_panel.scene_changed.connect(self._camera_scene_changed)
        self.camera_dock = self._dock("Cameras", "camerasDock", self.camera_panel)
        self.camera_dock.visibilityChanged.connect(self._camera_dock_shown)
        self.tabifyDockWidget(self.map_dock, self.camera_dock)
        self.map_dock.raise_()

    def _read_library_map(self, game_path: str) -> Map | None:
        """A library map the open map's players draw scripts from, read from the loaded game."""
        return self.context.read_map(game_path) if self.context is not None else None

    def _library_names(self) -> list[str]:
        if self.context is None:
            return []
        return [entry.name for entry in self.context.maps(MapCategory.LIBRARIES)]

    def _select_team(self, qualified: str) -> bool:
        if not self.teams_panel.select_team(qualified):
            return False
        self._show_dock(self.teams_dock)
        return True

    def _select_player(self, name: str) -> bool:
        if not self.players_panel.select_player(name):
            return False
        self._show_dock(self.players_dock)
        return True

    def go_to_target(self, target: ScriptTarget) -> bool:
        """Show what a script argument names. A team, a player or a script lives in a panel, so
        that panel comes up with it selected; everything else is on the map, so it is selected
        there and the view centres on it."""
        if target.kind is TargetKind.SCRIPT:
            return self._select_script(target.name)
        if target.kind is TargetKind.TEAM:
            return self._select_team(target.name)
        if target.kind is TargetKind.PLAYER:
            return self._select_player(target.name)
        document = self.document
        if document is None:
            return False
        if document.selection.locked:
            _status(self).showMessage("The selection is locked.", 3000)
        elif target.sources:
            document.selection.set(list(target.sources))
        if target.position is not None:
            self._zoom_to(*target.position)
        return True

    def _select_item(self, source: object) -> None:
        """Select a map item chosen in the Item List, so the properties panel shows it."""
        document = self.document
        if document is None:
            return
        if document.selection.locked:
            _status(self).showMessage("The selection is locked.", 3000)
            return
        document.selection.set([source])

    def _zoom_to(self, x: float, y: float) -> None:
        self.map_view.zoom_to(x, y, _ZOOM_TO_SCALE)
        if self.map_view_3d is not None:
            self.map_view_3d.zoom_to(x, y, _ZOOM_TO_SCALE)
        self.active_view().setFocus(Qt.FocusReason.OtherFocusReason)

    def active_view(self) -> MapView | MapView3D:
        """The map view in the central area."""
        view = self.map_view_3d
        if view is not None and self.view_stack.currentWidget() is view:
            return view
        return self.map_view

    def show_3d_view(self, shown: bool) -> None:
        """Show the 3D view in the central area, or the top-down view. The 3D view is made
        the first time, as the twin of the top-down view it takes its state from."""
        if shown and self.map_view_3d is None:
            try:
                from sage_worldbuilder.ui.map_view_3d import MapView3D  # noqa: PLC0415
            except ImportError as exc:
                self.view_3d_action.setChecked(False)
                _status(self).showMessage(f"The 3D view needs PyOpenGL: {exc}", 8000)
                return
            view = MapView3D(self.map_view)
            view.atlas_provider = self._build_terrain_atlas
            view.model_provider = self._load_object_models
            view.art_provider = self._art_textures_for_view
            view.damage_thresholds = MapConditions.of_game(self.game)
            view.cursor_moved.connect(self.show_cursor)
            view.gesture_finished.connect(self._gesture_finished)
            view.camera_host = self
            view.camera_object_picked.connect(self.camera_panel.select_object)
            for action in self._map_view_actions:
                view.addAction(action)
            self.view_stack.addWidget(view)
            self.map_view.twin = view
            self.map_view_3d = view
        target: MapView | MapView3D = self.map_view
        if shown and self.map_view_3d is not None:
            target = self.map_view_3d
        self.view_stack.setCurrentWidget(target)
        self.view_3d_action.setChecked(target is not self.map_view)
        # Remembered for the next run, which opens in the view left behind.
        self.settings.view.view_3d = target is not self.map_view
        target.setFocus(Qt.FocusReason.OtherFocusReason)

    def _art_textures_for_view(self) -> ArtTextures | None:
        """The textures and FX materials the 3D view draws water and roads with, read from the
        game install (and mod) the window has open; kept until the art is reloaded."""
        context = self.context
        if context is None:
            return None
        if self._art_textures is None or self._art_textures[0] is not context:
            self._art_textures = (context, ArtTextures(ArtIndex(context.art_filesystem())))
        return self._art_textures[1]

    def _load_object_models(self, names: list[str]) -> None:
        """Load the 3D view's models for these object names off the UI thread. Without game
        data there are none to load."""
        view, context, game = self.map_view_3d, self.context, self.game
        if view is None or context is None or game is None:
            return
        world_builder = self.settings.view.world_builder_models
        models = self._object_models
        if models is None or models.game is not game or models.world_builder != world_builder:
            self._object_models = ObjectModels(game, world_builder)
            self._art_index = ArtIndex(context.art_filesystem())
        models, art = self._object_models, self._art_index
        assert models is not None and art is not None

        def work() -> object:
            return load_object_models(names, models, art)

        def done(result: object) -> None:
            if self.map_view_3d is view and isinstance(result, tuple):
                view.set_models(*result)

        def failed(message: str) -> None:
            _status(self).showMessage(f"Object models could not be read: {message}", 5000)

        run_worker(self, work, done, failed)

    def _build_terrain_atlas(self, key: Hashable, max_size: int) -> None:
        """Make the 3D view's atlas of the open map's texture cells off the UI thread, for
        the texture table `key` it asked about. Without game data there is none to make."""
        view, document, colors = self.map_view_3d, self.document, self._game_texture_colors()
        blend = document.map.blend_tile_data if document is not None else None
        if view is None or blend is None or colors is None:
            return
        textures = list(blend.textures)

        def work() -> object:
            return build_atlas(
                textures,
                lambda texture, pixels: colors.cells(texture.name, texture.cell_size, pixels),
                max_size,
            )

        def done(result: object) -> None:
            if self.map_view_3d is view and isinstance(result, TerrainAtlas):
                view.set_atlas(key, result)

        def failed(message: str) -> None:
            _status(self).showMessage(f"Terrain textures could not be read: {message}", 5000)

        run_worker(self, work, done, failed)

    def _update_texture_colors(self) -> None:
        """Colour the map view by its painted textures, worked out off the UI thread. Without
        game data the view keeps its height ramp."""
        self._texture_generation += 1
        if self.map_view_3d is not None:
            self.map_view_3d.textures_changed()
        document, context = self.document, self.context
        if document is None or context is None or context.game is None:
            return
        blend, grid = document.map.blend_tile_data, document.terrain
        if blend is None or grid is None:
            return
        game, generation, heights = context.game, self._texture_generation, grid.heights

        def work() -> object:
            if self._texture_colors is None or self._texture_game is not game:
                self._texture_colors = TextureColors(
                    context.art_filesystem(), terrain_textures(game)
                )
                self._texture_game = game
            return picture_colors(blend, heights, self._texture_colors)

        def done(result: object) -> None:
            if generation == self._texture_generation and document is self.document:
                base, picture, table = result  # type: ignore[misc]
                self._sample_colors = base
                self._blend_table = ((len(table[0]) - 1, len(blend.textures)), table)
                self.map_view.set_base_colors(picture)

        def failed(message: str) -> None:
            if generation == self._texture_generation:
                _status(self).showMessage(f"Terrain textures could not be read: {message}", 5000)

        run_worker(self, work, done, failed)

    def pick_rules(self) -> PickRules:
        game = self.game
        rules = self._pick_rules
        if (
            rules is None
            or rules.game is not game
            or rules.allowed != self.settings.pick_allowances
        ):
            rules = self._pick_rules = PickRules(game, self.settings.pick_allowances)
        return rules

    def group_edit_method(self) -> GroupEditMethod:
        return self.settings.group_edit_method

    def angle_locked(self) -> bool:
        return self.lock_angle_action.isChecked()

    def vertical_locked(self) -> bool:
        return self.lock_vertical_action.isChecked()

    def _set_top_down(self, on: bool) -> None:
        view = self.map_view_3d
        if view is None or self.active_view() is not view:
            self.top_down_action.setChecked(False)
            _status(self).showMessage("Show From Top Down View is for the 3D view (F3).", 5000)
            return
        view.set_top_down(on)

    def use_game_camera(self) -> None:
        """Game Camera: the 3D view looks from the map's own camera settings."""
        view = self.map_view_3d
        if view is None or self.active_view() is not view:
            _status(self).showMessage("Game Camera is for the 3D view (F3).", 5000)
            return
        if not view.game_camera():
            _status(self).showMessage("The map stores no camera settings.", 5000)
            return
        self.top_down_action.setChecked(False)

    def reload_textures(self) -> None:
        """Reload Textures: read the terrain textures and object models again."""
        self._texture_colors = None
        self._texture_game = None
        self._object_models = None
        self._art_index = None
        self._art_textures = None
        self._mold_meshes.clear()
        self._texture_previews.clear()
        if self.map_view_3d is not None:
            self.map_view_3d.reload_art()
        self._update_texture_colors()

    def _set_partial_map_size(self, size: int) -> None:
        self.settings.view.partial_map_size = size
        self.map_view.options_changed()

    def place_template(self) -> str | None:
        return self.palette_panel.template()

    def place_owner(self) -> str:
        return self.palette_panel.default_owner()

    def place_height(self) -> float:
        return self.palette_panel.height_above_terrain()

    def _template_chosen(self, _name: str) -> None:
        """Choosing an object in the palette goes to Place Object, unless the tool in use places
        the palette's object itself."""
        if self.map_view.tool is not self.array_tool:
            self.use_tool("place")

    def array_options(self) -> ArrayOptions:
        return self.settings.array

    def _array_selection(self) -> bool:
        """Whether the Radial Array tool would repeat the selection rather than the palette."""
        document = self.document
        if document is None or not self.settings.array.use_selection:
            return False
        return bool(stamp_objects(document.selection.items))

    def brush_options(self) -> BrushOptions:
        return self.settings.brush

    def paint_options(self) -> PaintOptions:
        return self.settings.paint

    def _game_texture_colors(self) -> TextureColors | None:
        """The loaded game's terrain texture reader, made on first use."""
        context, game = self.context, self.game
        if context is None or game is None:
            return None
        if self._texture_colors is None or self._texture_game is not game:
            self._texture_colors = TextureColors(context.art_filesystem(), terrain_textures(game))
            self._texture_game = game
        return self._texture_colors

    def texture_cell_size(self, name: str) -> int:
        colors = self._game_texture_colors()
        size = colors.cell_size(name) if colors is not None else None
        return size or DEFAULT_CELL_SIZE

    def copy_terrain_options(self) -> CopyTerrainOptions:
        return self.settings.copy_terrain

    def _clear_terrain_selection(self) -> None:
        self.terrain_copy_tool.clear_selection()
        self.map_view.update()

    def apply_texture_to_tiles(self) -> None:
        """Terrain Material's Apply To Tiles...: the chosen texture on the playable cells between
        the slopes and heights asked for, at the saturation asked for, as one undo entry."""
        document = self.document
        blend = document.map.blend_tile_data if document is not None else None
        height_map = document.map.height_map_data if document is not None else None
        grid = document.terrain if document is not None else None
        if document is None or blend is None or height_map is None or grid is None:
            return
        name = self.settings.paint.texture
        if not name:
            self.show_status("Choose a texture in the Terrain Material panel.")
            return
        dialog = ApplyTextureDialog(self._apply_texture_options, self)
        if not dialog.exec():
            return
        self._apply_texture_options = dialog.options()
        index = texture_index(blend, name)
        new = None
        if index is not None:
            entry = blend.textures[index]
        else:
            try:
                entry = new = planned_texture(blend, name, self.texture_cell_size(name))
            except TextureCapacityError as exc:
                self.show_status(str(exc))
                return
        layers = {layer: document.cells(layer) for layer in TileLayer}
        if layers[TileLayer.TILES] is None:
            return
        painted = apply_texture(
            layers,  # type: ignore[arg-type]
            grid.heights,
            blend.textures,
            entry,
            height_map.border_width,
            self._apply_texture_options,
        )
        if painted is None:
            self.show_status("No cell matches.")
            return
        x0, y0, blocks = painted
        command = PaintTiles(x0, y0, blocks, new, "Apply Texture to Tiles")
        self.execute(command)
        command.closed = True

    def _tile_layers(self) -> dict[TileLayer, np.ndarray | None] | None:
        document = self.document
        if document is None or document.map.blend_tile_data is None:
            return None
        layers = {layer: document.cells(layer) for layer in TileLayer}
        return layers if layers[TileLayer.TILES] is not None else None

    def _run_table_edit(self, edit: TableEdit | None, label: str, nothing: str) -> None:
        if edit is None:
            self.show_status(nothing)
            return
        command = ReplaceTerrainTables(
            edit.patches, edit.textures, edit.descriptions, edit.cliff_mappings, label
        )
        self.execute(command)

    def optimize_tiles(self) -> None:
        """Texture Sizing > Optimize tiles and blend tiles."""
        layers = self._tile_layers()
        if layers is None or self.document is None:
            return
        blend = self.document.map.blend_tile_data
        assert blend is not None
        edit = optimized_tiles(
            layers, blend.textures, blend.blend_descriptions, blend.cliff_texture_mappings
        )
        self._run_table_edit(edit, "Optimize Tiles and Blend Tiles", "Nothing to optimize.")

    def remove_cliff_mappings(self) -> None:
        """Texture Sizing > Remove Cliff Tex Mapping, once confirmed."""
        layers = self._tile_layers()
        if layers is None or self.document is None:
            return
        answer = QMessageBox.question(
            self, APP_TITLE, "Remove all cliff mapping in the entire map?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        blend = self.document.map.blend_tile_data
        assert blend is not None
        edit = cliff_mappings_removed(layers, blend.cliff_texture_mappings)
        self._run_table_edit(edit, "Remove Cliff Texture Mapping", "The map has no cliff mapping.")

    def adjust_terrain_to_ground(self) -> None:
        """Edit > Special > Adjust Terrain to GROUND Objects: the ground takes the shape of the
        `.GROUND` meshes of the objects standing on it, once confirmed."""
        document, context, game = self.document, self.context, self.game
        if document is None or self._busy:
            return
        grid = document.terrain
        if grid is None or context is None or game is None:
            QMessageBox.warning(
                self, APP_TITLE, "This needs a map with a heightmap and the game data loaded."
            )
            return
        answer = QMessageBox.question(
            self,
            APP_TITLE,
            "This changes the terrain height of the current map. Do you really want to do this?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        listed = document.map.objects_list
        names = sorted({obj.type_name for obj in (listed.object_list if listed else [])})
        models = ObjectModels(game, self.settings.view.world_builder_models)
        art = ArtIndex(context.art_filesystem())
        map = document.map

        def work() -> object:
            triangles = load_ground_triangles(names, models, art)
            return adjust_heights(grid, ground_placements(map, triangles))

        def done(result: object) -> None:
            if result is None:
                _status(self).showMessage("No GROUND object changes the terrain.", 5000)
                return
            x0, y0, values = result
            self.execute(PatchHeights(x0, y0, values, "Adjust Terrain to GROUND Objects"))
            self.active_view().update()

        self._run_busy("Adjusting terrain to GROUND objects…", work, done)

    def remove_all_blends(self) -> None:
        """Edit > Remove All Texture Blends, once confirmed."""
        layers = self._tile_layers()
        if layers is None:
            return
        answer = QMessageBox.question(
            self, APP_TITLE, "Remove every texture blend on the map? Are you sure?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._run_table_edit(
            blends_removed(layers), "Remove All Texture Blends", "The map has no blends."
        )

    def remap_textures(self) -> None:
        """Texture Sizing > Remap Textures: another Terrain.ini texture behind each of the map's,
        as one undo entry. A replacement of another size is refused, since the map's tiles are
        cells of the texture they were painted from."""
        document = self.document
        blend = document.map.blend_tile_data if document is not None else None
        if document is None or blend is None or not blend.textures:
            return
        names = [texture.name for texture in blend.textures]
        dialog = RemapTexturesDialog(names, self.terrain_material_panel.texture_names(), self)
        if not dialog.exec():
            return
        renames: list[Command] = []
        refused = []
        for index, name in dialog.replacements().items():
            if name.lower() == names[index].lower():
                continue
            if self.texture_cell_size(name) == blend.textures[index].cell_size:
                renames.append(RenameTexture(index, name, "Remap Textures"))
            else:
                refused.append(name)
        if refused:
            self.show_status(f"Not the same size, so left alone: {', '.join(refused)}")
        if renames:
            self.execute(CompositeCommand("Remap Textures", renames))

    def edit_stretched_options(self) -> None:
        view = self.settings.view
        value, accepted = QInputDialog.getDouble(
            self,
            "Stretched Tiles",
            "Show cells steeper than (degrees):",
            view.stretched_threshold,
            0.0,
            90.0,
            1,
        )
        if accepted:
            view.stretched_threshold = value
            self.map_view.options_changed()

    def edit_safe_frame_settings(self) -> None:
        """Safe Frame Overlay Settings: how wide the safe frame is, in percent of the 3D view."""
        view = self.settings.view
        value, accepted = QInputDialog.getInt(
            self,
            "Safe Frame Overlay Settings",
            "Scale (% of the view's width):",
            round(view.safe_frame_scale * 100),
            0,
            100,
        )
        if accepted:
            view.safe_frame_scale = value / 100
            self.map_view.options_changed()

    def pick_texture(self, name: str) -> None:
        self.terrain_material_panel.select_texture(name)
        _status(self).showMessage(f"Texture: {name}", 3000)

    def show_status(self, text: str) -> None:
        _status(self).showMessage(text, 5000)

    def confirm_replace_all(self, name: str) -> bool:
        answer = QMessageBox.question(self, APP_TITLE, f"Replace all occurences of texture {name}?")
        return answer == QMessageBox.StandardButton.Yes

    def _texture_preview(self, name: str) -> QPixmap | None:
        key = name.lower()
        if key not in self._texture_previews:
            colors = self._game_texture_colors()
            data = colors.image(name) if colors is not None else None
            preview = preview_rgb(data, PREVIEW_PIXELS) if data is not None else None
            pixmap = None
            if preview is not None:
                pixels, width, height = preview
                image = QImage(pixels, width, height, 3 * width, QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(image.copy())
            if colors is None:
                return pixmap  # not kept: the game data may still arrive
            self._texture_previews[key] = pixmap
        return self._texture_previews[key]

    def _refresh_texture_catalogue(self) -> None:
        """Offer the game's terrain textures, and under "This map" any the map uses that the game
        data does not list."""
        catalogue = texture_palette(self.game) if self.game is not None else {}
        document = self.document
        blend = document.map.blend_tile_data if document is not None else None
        self._catalogue_textures = len(blend.textures) if blend is not None else -1
        if blend is not None:
            listed = {
                name.lower()
                for regions in catalogue.values()
                for names in regions.values()
                for name in names
            }
            on_map = sorted(
                {texture.name for texture in blend.textures if texture.name.lower() not in listed},
                key=str.lower,
            )
            if on_map:
                catalogue = {**catalogue, _THIS_MAP: {"": on_map}}
        self.terrain_material_panel.set_catalogue(catalogue)

    def _patch_texture_colors(self, region: Region) -> None:
        """Recolour the view's texture colours where a paint or a blend changed the tiles."""
        document, base, colors = self.document, self._sample_colors, self._texture_colors
        picture = self.map_view.base_colors
        blend = document.map.blend_tile_data if document is not None else None
        if document is None or blend is None:
            return
        if len(blend.textures) != self._catalogue_textures:
            self._refresh_texture_catalogue()
        if colors is None or not (isinstance(base, np.ndarray) and isinstance(picture, np.ndarray)):
            return
        tiles = document.cells(TileLayer.TILES)
        blends = document.cells(TileLayer.BLENDS)
        three_way = document.cells(TileLayer.THREE_WAY_BLENDS)
        if tiles is None or blends is None or three_way is None or base.shape[:2] != tiles.shape:
            return
        box = (region.x0, region.y0, region.x1, region.y1)
        patch_base_colors(base, blend.textures, tiles, colors, box)
        key = (len(blend.blend_descriptions), len(blend.textures))
        if self._blend_table is None or self._blend_table[0] != key:
            self._blend_table = (key, blend_table(blend.blend_descriptions, blend.textures, colors))
        patch_picture_colors(picture, base, blends, three_way, self._blend_table[1], box)

    def _update_overlay(self) -> None:
        """While a tile tool is chosen, tint the cell attribute it paints."""
        tool = self.map_view.tool
        painting = isinstance(tool, TilePaintTool)
        self.map_view.set_overlay_layers(paint_values(self.settings.paint) if painting else ())

    def use_tool(self, name: str) -> None:
        """Switch the map view to a tool by name: `select`, `place`, `waypoint`, `polygon`,
        `ruler`, `build list`, or a height tool's name (`Height Brush`, `Mound`, ...)."""
        tools = self._tools()
        tool, action = tools.get(name, tools["select"])
        self._before_paste = None
        if tool is not self.map_view.tool:
            self.map_view.tool.cancel()
        self.map_view.tool = tool
        action.setChecked(True)
        self._tool_chosen(tool)

    def _tools(self) -> dict[str, tuple[Tool, QAction]]:
        """The tools chosen from the toolbar, by name, and their actions."""
        tools: dict[str, tuple[Tool, QAction]] = {
            "select": (self.select_tool, self.select_tool_action),
            "move": (self.move_tool, self.move_tool_action),
            "rotate": (self.rotate_tool, self.rotate_tool_action),
            "place": (self.place_tool, self.place_tool_action),
            "array": (self.array_tool, self.array_tool_action),
            "waypoint": (self.waypoint_tool, self.waypoint_tool_action),
            "polygon": (self.polygon_tool, self.polygon_tool_action),
            "ruler": (self.ruler_tool, self.ruler_tool_action),
            "build list": (self.build_list_tool, self.build_list_tool_action),
            "road": (self.road_tool, self.road_tool_action),
            "generic ai": (self.generic_ai_tool, self.generic_ai_tool_action),
        }
        for kind, tool_name, *_ in _WATER_TOOLS:
            tools[tool_name] = (self.water_tools[kind], self.water_tool_actions[kind])
        for dressing_name, dressing_tool in self.dressing_tools.items():
            tools[dressing_name] = (dressing_tool, self.dressing_tool_actions[dressing_name])
        for kind, tool in self.height_tools.items():
            tools[kind.value] = (tool, self.height_tool_actions[kind])
        tools["single tile"] = (self.single_tile_tool, self.single_tile_action)
        tools["large tile"] = (self.large_tile_tool, self.large_tile_action)
        tools["flood fill"] = (self.flood_fill_tool, self.flood_fill_action)
        tools["eyedropper"] = (self.eyedropper_tool, self.eyedropper_action)
        tools["blend single edge"] = (self.blend_single_edge_tool, self.blend_single_edge_action)
        tools["auto edge out"] = (self.auto_edge_out_tool, self.auto_edge_out_action)
        tools["auto edge in"] = (self.auto_edge_in_tool, self.auto_edge_in_action)
        tools["terrain copy"] = (self.terrain_copy_tool, self.terrain_copy_action)
        return tools

    def _tool_chosen(self, tool: Tool) -> None:
        """Show what goes with the tool just chosen: its overlay and its panel."""
        self._update_overlay()
        if isinstance(tool, HeightBrushTool):
            self._show_dock(self.brush_dock)
        if isinstance(
            tool, (TilePaintTool, FloodFillTool, EyedropperTool, BlendSingleEdgeTool, AutoEdgeTool)
        ):
            self._show_dock(self.terrain_material_dock)
        if tool is self.terrain_copy_tool:
            self._show_dock(self.copy_terrain_dock)
        if tool is self.build_list_tool:
            self._show_dock(self.build_list_dock)
        page = next((key for key, each in self.dressing_tools.items() if each is tool), None)
        if page is not None:
            self.dressing_panel.show_page(page)
            if page == "fence":
                self.dressing_panel.set_fence_object(self.palette_panel.template())
            if page in ("grove", "mesh mold"):
                self._refresh_dressing_lists()
            self._show_dock(self.dressing_dock)
        if isinstance(tool, WaterTool):
            self.water_panel.set_kind(tool.kind)
            self._show_dock(self.water_dock)
        if tool is self.generic_ai_tool:
            self.generic_ai_panel.refresh()
            self._show_dock(self.generic_ai_dock)
        if tool is self.road_tool:
            self._show_dock(self.road_dock)
            if self.road_panel.road_type() is None:
                _status(self).showMessage("Choose a road type in Road Options.", 5000)
        if tool is self.array_tool:
            self.array_panel.refresh()
            self._show_dock(self.array_dock)
            if self.palette_panel.template() is None and not self._array_selection():
                self._show_dock(self.palette_dock)
                _status(self).showMessage(
                    "Choose an object in the Object Palette, or select the objects to repeat.", 5000
                )
        if tool is self.place_tool and self.palette_panel.template() is None:
            self._show_dock(self.palette_dock)
            _status(self).showMessage("Choose an object in the Object Palette.", 5000)
        self.map_view.update()

    def change_time_of_day(self) -> None:
        document = self.document
        lighting = document.map.global_lighting if document is not None else None
        if lighting is None or self._busy:
            return
        self.execute(next_time_of_day(lighting))
        _status(self).showMessage(f"Time of day: {lighting.time_of_the_day.name}.", 5000)

    def _set_group_edit(self, method: GroupEditMethod) -> None:
        self.settings.group_edit_method = method

    def _set_allowances(self, allowed: frozenset[PickCategory]) -> None:
        for category, action in self.pick_actions.items():
            action.setChecked(category in allowed)
        self._allowances_toggled()

    def _allowances_toggled(self) -> None:
        self.settings.pick_allowances = frozenset(
            category for category, action in self.pick_actions.items() if action.isChecked()
        )

    def _lock_selection_toggled(self) -> None:
        if self.document is not None:
            self.document.selection.locked = self.lock_selection_action.isChecked()

    def selected_objects(self) -> list[Object]:
        document = self.document
        if document is None:
            return []
        return [item for item in document.selection if isinstance(item, Object)]

    def copy(self) -> None:
        """Copy the selected objects to the system clipboard, where this editor or another one
        can paste them from."""
        objects = self.selected_objects()
        board = QGuiApplication.clipboard()
        if self.document is None or not objects or board is None:
            return
        clipboard = copy_objects(self.document.map, with_partners(self.document.map, objects))
        data = QMimeData()
        data.setData(CLIPBOARD_MIME, QByteArray(clipboard_to_json(clipboard).encode("utf-8")))
        board.setMimeData(data)
        _status(self).showMessage(f"Copied {len(objects)} object(s)", 3000)
        self._refresh()

    def clipboard_objects(self) -> Clipboard | None:
        """The objects on the system clipboard, copied here or in another editor, or None."""
        board = QGuiApplication.clipboard()
        data = board.mimeData() if board is not None else None
        if data is None or not data.hasFormat(CLIPBOARD_MIME):
            return None
        return clipboard_from_json(bytes(data.data(CLIPBOARD_MIME)).decode("utf-8", "replace"))

    def _clipboard_has_objects(self) -> bool:
        board = QGuiApplication.clipboard()
        data = board.mimeData() if board is not None else None
        return data is not None and data.hasFormat(CLIPBOARD_MIME)

    def cut(self) -> None:
        objects = self.selected_objects()
        if not objects or self._busy:
            return
        self.copy()
        assert self.document is not None
        self.execute(DeleteObjects(with_partners(self.document.map, objects), "Cut"))

    def active_layer(self) -> str:
        return self.layers_panel.active

    def generic_ai_type(self) -> GenericAIType:
        return self.generic_ai_panel.new_type()

    def generic_ai_wall_hub(self) -> int:
        return self.generic_ai_panel.new_wall_hub()

    def build_side(self) -> int | None:
        return self.build_list_panel.current_side()

    def select_build_entry(self, entry: object) -> None:
        self.build_list_panel.select_entry(entry)  # type: ignore[arg-type]

    def _build_entry_changed(self, entry: object) -> None:
        self.map_view.build_entry = entry
        self.map_view.update()

    def ruler_circular(self) -> bool:
        return self.circular_ruler_action.isChecked()

    def show_measurement(self, text: str) -> None:
        _status(self).showMessage(text)

    def set_listen_mode(self, mode: ListenMode) -> None:
        """View > Listen To Map: play the map's ambient sounds of one kind, or none."""
        self.listen_actions[mode].setChecked(True)
        self.ambient_player.set_mode(mode)

    def listener_position(self) -> tuple[float, float] | None:
        """Where the ambient sounds are heard from: what the view looks at."""
        if self.document is None:
            return None
        x, y, _z = self.current_view().target
        return (x, y)

    def read_sound(self, path: str) -> bytes | None:
        context = self.context
        if context is None:
            return None
        filesystem = context.art_filesystem()
        entry = filesystem.find(path)
        return filesystem.read_bytes(entry) if entry is not None else None

    def listen_to_object(self, obj: Object) -> None:
        """The object sheet's Listen button."""
        if not self.ambient_player.listen(obj):
            self.show_status("This object has no ambient sound the game can play.")

    def remove_min_volume_customization(self) -> None:
        """Validation > Remove MinVolume Customization."""
        document = self.document
        if document is None:
            return
        count = len(min_volume_customizations(document.map))
        command = remove_min_volume_customization(document.map)
        if command is None:
            self.show_status("No objects have the customized minimum volume property.")
            return
        self.execute(command)
        noun = "object" if count == 1 else "objects"
        self.show_status(f"Removed the customized minimum volume from {count} {noun}.")

    def _refresh_skybox_schemes(self) -> None:
        game = self.game
        names = list(game.tables.get("skyboxtexturesets", {})) if game is not None else []
        self.environment_panel.set_skybox_schemes(names)

    def _show_cameras(self, tab: int) -> None:
        self.camera_panel.tabs.setCurrentIndex(tab)
        self._show_dock(self.camera_dock)
        self.camera_panel.refresh_scene()

    def current_view(self) -> CameraView:
        """The camera of the view shown: the 3D view's own, or for the top-down view one looking
        straight down at its centre from as high as its picture spans."""
        view = self.map_view_3d
        if view is not None and self.active_view() is view:
            camera = view.camera
            return CameraView(
                (camera.target_x, camera.target_y, camera.target_z),
                camera.yaw,
                camera.pitch,
                camera.distance,
                camera.fov,
            )
        transform = self.map_view.transform
        span = max(transform.width, transform.height) / max(transform.scale, 1e-6)
        return CameraView((transform.center_x, transform.center_y, 0.0), 0.0, 90.0, span, 45.0)

    def show_camera_view(self, view: object) -> None:
        """Show a named camera or an animation frame: in the 3D view when it is shown, else by
        centring the top-down view on what the camera looks at."""
        view_3d = self.map_view_3d
        if view_3d is not None and self.active_view() is view_3d:
            view_3d.show_camera(view)
            return
        target = getattr(view, "target", None)
        if target is not None:
            self.map_view.transform.center_on(target[0], target[1])
            self.map_view.update()

    def _camera_path_changed(self, path: object) -> None:
        self.map_view.camera_path = path  # type: ignore[assignment]
        self.map_view.update()

    def _camera_dock_shown(self, _shown: bool) -> None:
        """Opening or closing the Cameras panel puts its objects into the world or takes them
        out again."""
        self.camera_panel.refresh_scene()

    def _camera_scene_changed(self, scene: object) -> None:
        """The Cameras panel's objects for the 3D view: the keys it draws as cameras, the handles
        a drag may take hold of, and the pose its preview looks from. They are drawn only while
        the panel is open, as WorldBuilder draws them while its dialog is."""
        shown = self.camera_dock.isVisibleTo(self)
        self.map_view.camera_scene = scene if shown else None
        if self.map_view_3d is not None:
            self.map_view_3d.update()

    def scorch_settings(self) -> tuple[int, float]:
        return self.dressing_panel.scorch_settings()

    def grove_settings(self) -> GroveOptions:
        return self.dressing_panel.grove_settings()

    def fence_spacing(self) -> float:
        return self.dressing_panel.fence_spacing()

    def ramp_width(self) -> float:
        return self.dressing_panel.ramp_width()

    def mold_settings(self) -> MoldOptions:
        return self.dressing_panel.mold_settings()

    def mold_mesh(self, name: str) -> Any:
        """A mold's triangles in model space, read from the game data the first time; None when
        it cannot be read."""
        if name not in self._mold_meshes:
            self._mold_meshes[name] = self._read_mold(name)
        return self._mold_meshes[name]

    def _read_mold(self, name: str) -> Any:
        context = self.context
        if context is None:
            return None
        from sage_w3d.render.scene import build_scene  # noqa: PLC0415 - lazy: parsing on demand
        from sage_w3d.w3d import parse_w3d  # noqa: PLC0415

        filesystem = context.art_filesystem()
        try:
            entry = next(
                (
                    each
                    for each in filesystem.listdir(MOLD_FOLDER)
                    if str(each.path).replace("\\", "/").rsplit("/", 1)[-1].lower() == name.lower()
                ),
                None,
            )
            if entry is None:
                return None
            return mold_triangles(build_scene(parse_w3d(filesystem.read_bytes(entry))))
        except Exception:  # noqa: BLE001 - an unreadable mold is reported as missing
            return None

    def apply_mesh_mold(self) -> None:
        """Dressing Options' Apply: shape the ground under the placed mold."""
        if not self._busy and self.mesh_mold_tool.apply(self.document):
            self.active_view().update()

    def _refresh_dressing_lists(self) -> None:
        """Offer the game's shrubbery and natural props as grove trees, and its molds."""
        game = self.game
        groups = object_palette(game) if game is not None else {}
        self.dressing_panel.set_tree_choices(names_under(groups, "Shrubbery", "Natural props"))
        molds: list[str] = []
        if self.context is not None:
            try:
                molds = list_molds(self.context.art_filesystem())
            except OSError:
                molds = []
        self.dressing_panel.set_molds(molds)

    def water_height(self, points: Any) -> int:
        document = self.document
        return default_height(document.terrain if document is not None else None, points)

    def road_type(self) -> tuple[str, bool] | None:
        return self.road_panel.road_type()

    def road_corner(self) -> CornerType:
        return self.road_panel.corner()

    def road_join(self) -> bool:
        return self.road_panel.join()

    def road_width(self, type_name: str) -> float:
        styles = self.map_view.road_styles
        return styles.get(type_name).width if styles is not None else DEFAULT_ROAD_WIDTH

    def apply_road_options(self) -> None:
        """Road Options' Apply To Selection, on every segment with an end selected."""
        document = self.document
        if document is None:
            return
        segments = selected_segments(document.map, document.selection)
        if not segments:
            _status(self).showMessage("Select road segments to apply the road options to.", 5000)
            return
        chosen = self.road_panel.road_type()
        name, bridge = chosen if chosen is not None else (None, False)
        command = apply_road_style(
            segments, name, bridge, self.road_panel.corner(), self.road_panel.join()
        )
        if command.commands:
            self.execute(command)

    def _refresh_road_catalogue(self) -> None:
        """List the game's road and bridge types in Road Options, and the map's other ones."""
        styles = self.map_view.road_styles
        roads, bridges = styles.names() if styles is not None else ([], [])
        known = {name.lower() for name in roads + bridges}
        scene = self.map_view.scene
        used = {segment.type_name for segment in scene.roads} if scene is not None else set()
        on_map = sorted((name for name in used if name.lower() not in known), key=str.lower)
        self.road_panel.set_catalogue(roads, bridges, on_map)

    def _select(self, found: list[Object], what: str) -> None:
        document = self.document
        if document is None:
            return
        if document.selection.locked:
            _status(self).showMessage("The selection is locked.", 3000)
            return
        document.selection.set(found)
        _status(self).showMessage(f"Selected {len(found)} {what}", 5000)

    def select_similar(self) -> None:
        document, objects = self.document, self.selected_objects()
        if document is not None and objects:
            self._select(similar_objects(document.map, objects), "similar objects")

    def _select_found(self, finder: Callable[[Any], list[Object]], what: str) -> None:
        if self.document is not None:
            self._select(finder(self.document.map), what)

    def _select_with_game(
        self, finder: Callable[[Any, TemplateIndex], list[Object]], what: str
    ) -> None:
        if self.document is None:
            return
        if self.game is None:
            _status(self).showMessage("This needs the game data, which has not loaded.", 5000)
            return
        self._select(finder(self.document.map, TemplateIndex(self.game)), what)

    def replace_selected(self) -> None:
        objects, template = self.selected_objects(), self.palette_panel.template()
        if not objects:
            return
        if template is None:
            self._show_dock(self.palette_dock)
            _status(self).showMessage("Choose the replacement in the Object Palette.", 5000)
            return
        command = replace_objects(objects, template)
        if command.commands:
            self.execute(command)

    def delete_selection(self) -> None:
        document = self.document
        if document is None:
            return
        objects = self.selected_objects()
        areas = [item for item in document.selection if isinstance(item, TriggerArea)]
        commands: list[Command] = []
        if objects:
            # Deleting one end of a road takes the whole segment.
            commands.append(DeleteObjects(with_partners(document.map, objects)))
        if areas:
            commands.append(DeleteAreas(areas))
        water = [item for item in document.selection if water_kind(item) is not None]
        if water:
            commands.append(DeleteWater(water))  # type: ignore[arg-type]
        if len(commands) == 1:
            self.execute(commands[0])
        elif commands:
            self.execute(CompositeCommand("Delete", commands))

    def paste(self) -> None:
        """Hand the clipboard's objects to the paste tool, which shows them following the cursor
        until a click puts them down."""
        document, clipboard = self.document, self.clipboard_objects()
        if document is None or clipboard is None or not clipboard.objects or self._busy:
            return
        if document.map.objects_list is None:
            _status(self).showMessage("Cannot paste: the map has no object list", 5000)
            return
        view = self.active_view()
        if self.map_view.tool is not self.paste_tool:
            self._before_paste = self.map_view.tool
            self.map_view.tool.cancel()
        self.paste_tool.start(clipboard, view.paste_position())
        self.map_view.tool = self.paste_tool
        _status(self).showMessage("Click to paste; Esc to cancel", 5000)
        view.setFocus(Qt.FocusReason.OtherFocusReason)
        view.update()

    def paste_done(self) -> None:
        previous = self._before_paste or self.select_tool
        name = next(
            (key for key, (tool, _action) in self._tools().items() if tool is previous), "select"
        )
        self.use_tool(name)
        self.active_view().update()

    def _selection_changed(self) -> None:
        document = self.document
        if document is not None and any(
            isinstance(item, Object) and is_road_point(item) for item in document.selection
        ):
            # One segment selected: Road Options shows its settings, ready to change and apply.
            segments = selected_segments(document.map, document.selection)
            if len(segments) == 1:
                segment = segments[0]
                self.road_panel.show_style(segment.type_name, segment.corner, segment.join)
        if document is not None:
            water = [item for item in document.selection if water_kind(item) is not None]
            if len(water) == 1:
                self.water_panel.show_area(water[0])  # type: ignore[arg-type]
        self.generic_ai_panel.refresh()
        self.map_view.update()
        self.object_panel.refresh()
        self._refresh()

    def _toggle_view(self, name: str) -> None:
        setattr(self.settings.view, name, self.view_actions[name].isChecked())
        if name == "world_builder_models":
            self._object_models = None
            if self.map_view_3d is not None:
                self.map_view_3d.models_changed()
        self.map_view.options_changed()

    def edit_grid_settings(self) -> None:
        dialog = GridSettingsDialog(self.settings.view, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dialog.apply(self.settings.view)
        self.view_actions["show_grid"].setChecked(self.settings.view.show_grid)
        self.map_view.options_changed()

    def edit_contour_options(self) -> None:
        dialog = ContourOptionsDialog(self.settings.view, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dialog.apply(self.settings.view)
        self.view_actions["show_contours"].setChecked(self.settings.view.show_contours)
        self.map_view.options_changed()

    def _dock(
        self,
        title: str,
        name: str,
        widget: QWidget,
        area: Qt.DockWidgetArea = Qt.DockWidgetArea.RightDockWidgetArea,
    ) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        dock.topLevelChanged.connect(partial(_fit_when_floated, dock))
        return dock

    @property
    def game(self) -> Game | None:
        return self.context.game if self.context is not None else None

    def execute(self, command: Command) -> None:
        """Run an edit from a panel on the open map, unless the window is busy."""
        if self.document is not None and not self._busy:
            self.document.execute(command)

    def show_scripts(self) -> None:
        self._show_dock(self.scripts_dock)

    def _show_dock(self, dock: QDockWidget) -> None:
        dock.show()
        dock.raise_()
        # A panel sharing a window with others comes up only as far as that window: bring the
        # window up too, or asking for the panel would leave it behind whatever covers it.
        window = floating_window(dock)
        if window is not None:
            window.raise_()

    def _select_script(self, name: str) -> bool:
        if not self.scripts_panel.select_script(name):
            return False
        self.show_scripts()
        return True

    def generate_report(self) -> None:
        self.validation_dock.show()
        self.validation_dock.raise_()
        self.validation_panel.run()

    def show_mapcache_entry(self) -> None:
        """The mapcache.ini entry the open map needs, for pasting into a mod's own cache."""
        document = self.document
        if document is None or self._busy:
            return
        if document.path is None:
            QMessageBox.information(
                self,
                APP_TITLE,
                "Save the map first: its entry is keyed by the file name the game will find it "
                "under, and describes the file on disk.",
            )
            return
        if is_base_path(document.path):
            QMessageBox.information(
                self, APP_TITLE, "A base is not a map, and the map cache holds no entry for one."
            )
            return
        MapCacheDialog(
            document.map,
            document.path,
            self,
            game=self.game,
            modified=document.dirty,
        ).exec()

    def jump_to_game(self) -> None:
        """Start the game on the open map: saved first when its file has unsaved changes, and
        copied into the user Maps folder when the game could not find it where it is."""
        document, context = self.document, self.context
        if document is None or self._busy:
            return
        if context is None:
            QMessageBox.warning(self, APP_TITLE, "Set the game install in Game > Game Settings.")
            return
        if context.user_data is None:
            QMessageBox.warning(self, APP_TITLE, "The game's user-data folder was not found.")
            return
        # Resolved before saving, so a match that cannot start does not save the map for nothing.
        game_info = None
        if self.settings.jump_match.enabled:
            try:
                game_info = self.settings.jump_match.game_info(context.game)
            except JumpMatchError as exc:
                QMessageBox.warning(
                    self,
                    APP_TITLE,
                    f"{exc}\n\nChange the match in Game > Jump To Game Settings, or turn it off "
                    "there to start the default one.",
                )
                return
        if document.path is not None and document.dirty:
            self.save(then=self.jump_to_game)
            return
        game_dat = context.layers.install / "game.dat"
        try:
            if patch_for_launch(game_dat, sagepatch_patches(context.engine)):
                self._patched_game_dats.add(game_dat)
        except LaunchPatchError as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return
        plan = plan_jump(
            document.path,
            document.title,
            context.layers,
            context.user_data,
            self.settings.jump_options(game_info),
        )
        try:
            if plan.install_to is not None:
                plan.install_to.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(plan.install_to, document.to_bytes())
            self.launch_game(plan.arguments, plan.working_directory)
        except OSError as exc:
            QMessageBox.critical(self, APP_TITLE, f"Could not start the game:\n{exc}")
            return
        _status(self).showMessage(f"Started the game on {document.title}", 5000)
        # The Script Debugger follows the game it just started, once there is a game to read.
        self.script_debugger_panel.attach_when_ready()

    def launch_game(self, arguments: list[str], working_directory: Path) -> None:
        subprocess.Popen(arguments, cwd=str(working_directory))

    def _restore_leftover_patch(self) -> None:
        """Put back a game.dat an earlier session patched and could not restore: it crashed, or
        closed while the game still held the file. Still held, it is restored on close instead."""
        if not self.settings.install:
            return
        game_dat = Path(self.settings.install) / "game.dat"
        if not restore_pending(game_dat):
            return
        problem = restore_after_launch(game_dat)
        if restore_pending(game_dat):
            self._patched_game_dats.add(game_dat)
        elif problem is not None:
            _status(self).showMessage(problem, 10000)

    def restart_elevated(self) -> None:
        """Start the editor again as administrator on the open map and close this one, once its
        changes are saved or discarded: the game runs elevated, and only an elevated editor can
        read it."""
        if not self._busy:
            self._when_changes_handled(self._hand_over_elevated)

    def _hand_over_elevated(self) -> None:
        document = self.document
        arguments = [str(document.path)] if document is not None and document.path else []
        # Saved first, so the new editor starts with this one's mods, install and layout.
        self._store_layout()
        self.settings.save()
        if not relaunch_elevated(arguments):
            _status(self).showMessage("The editor was not restarted as administrator.", 5000)
            return
        self._handed_over = True
        self.close()

    def restore_game_dats(self) -> bool:
        """Put back every game.dat Jump To Game patched. False when the mapper chose to keep the
        window open instead of leaving one patched."""
        for game_dat in sorted(self._patched_game_dats):
            while (problem := restore_after_launch(game_dat)) is not None:
                if not restore_pending(game_dat):
                    QMessageBox.warning(self, APP_TITLE, problem)
                    break
                choice = QMessageBox.warning(
                    self,
                    APP_TITLE,
                    f"{problem}\n\nClose the game and retry, or close WorldBuilder anyway and "
                    "leave it patched until WorldBuilder next starts.",
                    QMessageBox.StandardButton.Retry
                    | QMessageBox.StandardButton.Ignore
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Retry,
                )
                if choice == QMessageBox.StandardButton.Cancel:
                    return False
                if choice == QMessageBox.StandardButton.Ignore:
                    break
            self._patched_game_dats.discard(game_dat)
        return True

    def edit_jump_settings(self) -> None:
        """Choose the match Jump To Game starts, against the loaded game and the open map."""
        if self._busy:
            return
        game = self.context.game if self.context is not None else None
        positions = start_position_count(self.document.map) if self.document is not None else 0
        dialog = JumpSettingsDialog(
            self.settings.jump_match,
            game,
            positions,
            self,
            options=self.settings.jump_options(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.settings.jump_match = dialog.match
        self.settings.set_jump_options(dialog.options)
        self.settings.save()
        if dialog.jump_requested:
            self.jump_to_game()

    @staticmethod
    def _value_label(text: str = "") -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _build_menus(self) -> None:
        bar = self.menuBar()
        assert bar is not None
        file_menu = _menu(bar.addMenu("&File"))
        file_menu.addActions([self.new_action, self.open_action])
        self.recent_menu = _menu(file_menu.addMenu("Recent &Maps"))
        file_menu.addAction(self.close_action)
        file_menu.addSeparator()
        file_menu.addActions([self.save_action, self.save_as_action])
        file_menu.addSeparator()
        file_menu.addActions(
            [
                self.open_from_tga_action,
                self.import_heightmap_action,
                self.export_heightmap_action,
            ]
        )
        file_menu.addSeparator()
        file_menu.addAction(self.resize_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        edit_menu = _menu(bar.addMenu("&Edit"))
        edit_menu.addActions([self.undo_action, self.redo_action, self.repeat_action])
        edit_menu.addSeparator()
        edit_menu.addActions(
            [self.cut_action, self.copy_action, self.paste_action, self.delete_action]
        )
        group_menu = _menu(edit_menu.addMenu("&Group Edit Method"))
        group_menu.addActions(self.group_edit_actions.actions())
        edit_menu.addSeparator()
        edit_menu.addActions(
            [
                self.select_similar_action,
                self.select_duplicates_action,
                self.select_bad_teams_action,
                self.select_deprecated_action,
                self.select_missing_action,
                self.replace_selected_action,
            ]
        )
        base_menu = _menu(edit_menu.addMenu("Select &Base Object(s)"))
        base_menu.addActions([self.select_siblings_action, self.select_base_parent_action])
        edit_menu.addSeparator()
        pick_menu = _menu(edit_menu.addMenu("Pick &Allowances"))
        pick_menu.addActions([self.pick_nothing_action, self.pick_anything_action])
        pick_menu.addSeparator()
        pick_menu.addActions(list(self.pick_actions.values()))
        edit_menu.addActions(
            [self.lock_selection_action, self.lock_angle_action, self.lock_vertical_action]
        )
        edit_menu.addSeparator()
        special_menu = _menu(edit_menu.addMenu("&Special"))
        special_menu.addActions([self.adjust_terrain_action, self.remove_blends_action])
        edit_menu.addSeparator()
        edit_menu.addActions(
            [
                self.scripts_action,
                self.teams_action,
                self.players_action,
                self.mp_positions_action,
                self.map_settings_action,
                self.skybox_action,
                self.camera_options_action,
                self.camera_animations_action,
                self.global_light_action,
                self.shadows_action,
                self.post_effects_action,
                self.macro_texture_action,
                self.cloud_texture_action,
                self.item_list_action,
            ]
        )

        view_menu = _menu(bar.addMenu("&View"))
        view_menu.addActions(
            [
                self.view_3d_action,
                self.top_down_action,
                self.game_camera_action,
                self.fit_view_action,
            ]
        )
        view_menu.addSeparator()

        terrain_menu = _menu(view_menu.addMenu("Show &Terrain"))
        terrain_menu.addActions([self.view_actions["show_grid"], self.grid_settings_action])
        terrain_menu.addSeparator()
        terrain_menu.addActions(
            [
                self.view_actions["show_texture"],
                self.view_actions["show_blends"],
                self.view_actions["show_contours"],
                self.contour_options_action,
            ]
        )
        terrain_menu.addSeparator()
        terrain_menu.addActions(
            [
                self.view_actions["show_stretched"],
                self.stretched_options_action,
                self.view_actions["show_unblended"],
            ]
        )
        terrain_menu.addSeparator()
        terrain_menu.addActions(
            [self.view_actions["show_impassable"], self.view_actions["show_boundaries"]]
        )
        terrain_menu.addSeparator()
        terrain_menu.addAction(self.reload_textures_action)

        objects_menu = _menu(view_menu.addMenu("Show O&bjects"))
        objects_menu.addActions(
            [
                self.view_actions["show_objects"],
                self.view_actions["world_builder_models"],
                self.view_actions["show_garrisoned"],
                self.view_actions["show_labels"],
            ]
        )
        objects_menu.addSeparator()
        objects_menu.addActions(
            [
                self.view_actions["show_waypoints"],
                self.view_actions["show_areas"],
                self.view_actions["show_roads"],
                self.view_actions["show_water"],
            ]
        )
        objects_menu.addSeparator()
        objects_menu.addActions(
            [
                self.view_actions["show_bounding_boxes"],
                self.view_actions["show_sight_ranges"],
                self.view_actions["show_weapon_ranges"],
                self.view_actions["show_sound_circles"],
                self.view_actions["show_sound_flags"],
            ]
        )

        options_3d_menu = _menu(view_menu.addMenu("3&D Options"))
        options_3d_menu.addActions(
            [
                self.view_actions["wireframe"],
                self.view_actions["show_object_dots"],
                self.view_actions["show_entire_map"],
            ]
        )
        options_3d_menu.addSeparator()
        options_3d_menu.addActions(
            [
                self.view_actions["show_letterbox"],
                self.view_actions["show_safe_frame"],
                self.safe_frame_settings_action,
            ]
        )
        options_3d_menu.addSeparator()
        options_3d_menu.addActions(self.partial_map_actions.actions())

        panels_menu = _menu(view_menu.addMenu("&Panels"))
        toolbar_toggle = self.toolbar.toggleViewAction()
        if toolbar_toggle is not None:
            toolbar_toggle.setText("&Toolbar")
            panels_menu.addAction(toolbar_toggle)
        self.status_bar_action = QAction("&Status Bar", self)
        self.status_bar_action.setCheckable(True)
        self.status_bar_action.setChecked(True)
        self.status_bar_action.toggled.connect(lambda visible: _status(self).setVisible(visible))
        panels_menu.addAction(self.status_bar_action)
        panels_menu.addSeparator()
        for dock in self._docks():
            toggle = dock.toggleViewAction()
            if toggle is not None:
                panels_menu.addAction(toggle)

        listen_menu = _menu(view_menu.addMenu("&Listen To Map"))
        listen_menu.addActions(self.listen_group.actions())
        listen_menu.setEnabled(self.ambient_player.available)
        view_menu.addSeparator()
        view_menu.addActions([self.time_of_day_action, self.view_actions["reverse_scroll"]])

        tools_menu = _menu(bar.addMenu("&Tools"))
        tools_menu.addActions(self.tool_actions.actions())
        tools_menu.addSeparator()
        tools_menu.addAction(self.circular_ruler_action)

        texture_menu = _menu(bar.addMenu("Te&xture Sizing"))
        texture_menu.addActions(
            [
                self.remap_textures_action,
                self.remove_cliff_mapping_action,
                self.optimize_tiles_action,
            ]
        )

        window_menu = _menu(bar.addMenu("&Window"))
        window_menu.addAction(self.lock_layout_action)
        window_menu.addAction(self.reset_layout_action)
        window_menu.addSeparator()
        window_menu.addActions([self.next_pane_action, self.previous_pane_action])

        game_menu = _menu(bar.addMenu("&Game"))
        game_menu.addAction(self.load_mod_action)
        self.recent_mods_menu = _menu(game_menu.addMenu("Recent M&ods"))
        game_menu.addAction(self.unload_mod_action)
        game_menu.addSeparator()
        game_menu.addActions([self.load_sagepatch_action, self.unload_sagepatch_action])
        game_menu.addSeparator()
        game_menu.addActions([self.game_settings_action, self.reload_game_action])
        game_menu.addSeparator()
        game_menu.addActions(
            [self.jump_action, self.jump_settings_action, self.script_debugger_action]
        )
        game_menu.addSeparator()
        game_menu.addAction(self.mapcache_action)

        validation_menu = _menu(bar.addMenu("Va&lidation"))
        validation_menu.addAction(self.report_action)
        validation_menu.addAction(self.remove_min_volume_action)

        add_help_menu(
            self,
            guide_title=f"{APP_TITLE}: getting started",
            guide_html=_GUIDE_HTML,
            about_title=f"About {APP_TITLE}",
            about_html=_ABOUT_HTML,
            icon=app_icon(),
        )
        help_action = bar.actions()[-1]
        help_menu = help_action.menu()
        if help_menu is not None:
            help_menu.addSeparator()
            help_menu.addAction(self.shortcuts_action)

    def _build_status_bar(self) -> None:
        status = _status(self)
        self.game_label = QLabel()
        self.cell_label = QLabel()
        self.height_label = QLabel()
        for label in (self.game_label, self.cell_label, self.height_label):
            status.addPermanentWidget(label)
        self.show_cursor(None, None)

    def show_cursor(self, cell: tuple[int, int] | None, height: float | None) -> None:
        """Report the heightmap cell under the cursor and its height (set by the map view)."""
        self.cell_label.setText(f"Cell: {cell[0]}, {cell[1]}" if cell is not None else "Cell: -")
        self.height_label.setText(
            f"Height: {height:.0f} ({height * FEET_PER_HEIGHT_UNIT:.1f} ft)"
            if height is not None
            else "Height: -"
        )

    def apply_game_layers(self, *, load: bool = True) -> None:
        """Mount the configured install and mod folders, then (optionally) load their data."""
        self._load_generation += 1
        self.context = None
        self._library_maps.clear()
        self.map_view.footprints = None
        self.map_view.influences = None
        self.map_view.road_styles = None
        self.map_view.set_anchors(None)
        self.palette_panel.refresh()
        layers = self.settings.layers()
        if layers is None:
            self._set_game_status("No game install found: set one in Game > Game Settings.")
        else:
            try:
                self.context = GameContext.open(layers)
            except OSError as exc:
                self._set_game_status(f"Cannot read the game: {exc}")
        folder = self.context.user_data if self.context is not None else None
        self.autosaver = Autosaver(
            folder or user_config_dir(APP), self.settings.autosave_settings()
        )
        self._apply_autosave_settings()
        if self.context is not None:
            if load:
                self.reload_game_data()
            else:
                self._set_game_status("Game data not loaded")
        self._refresh()

    def reload_game_data(self) -> None:
        context = self.context
        if context is None or self._busy:
            return
        self._load_generation += 1
        generation = self._load_generation
        workers: list[Worker] = []

        def report(text: str) -> None:
            if workers:
                workers[0].progress.emit(text)

        def current() -> bool:
            return generation == self._load_generation and context is self.context

        def loaded(game: Any) -> None:
            if current():
                context.game = game
                mods = context.layers.mods
                names = ", ".join(mod.name for mod in mods)
                with_mods = f", {'mod' if len(mods) == 1 else 'mods'} {names}" if mods else ""
                with_patches = ""
                if context.layers.sagepatch is not None:
                    count = len(context.engine.patches)
                    with_patches = f", {count} engine patch{'' if count == 1 else 'es'}"
                problems = ""
                if self._engine_problems:
                    problems = f"; {len(self._engine_problems)} .sagepatch problems"
                self._set_game_status(
                    f"Loaded ({len(game.objects)} objects{with_mods}{with_patches}){problems}"
                )
                # Other game data (another mod, or edited files) can show other models and read
                # other art: the 3D view must not keep what it loaded for the previous game.
                self._object_models = None
                self._art_index = None
                self._art_textures = None
                if self.map_view_3d is not None:
                    self.map_view_3d.damage_thresholds = MapConditions.of_game(game)
                    self.map_view_3d.reload_art()
                self._refresh()
                self._update_texture_colors()
                self._texture_previews.clear()
                self._refresh_texture_catalogue()
                self.terrain_material_panel.refresh()
                self.map_view.footprints = Footprints(game)
                self.map_view.influences = Influences(game)
                self.map_view.road_styles = RoadStyles(game)
                self._mold_meshes.clear()
                self._refresh_road_catalogue()
                self._refresh_skybox_schemes()
                self.ambient_player.refresh()
                self.map_view.set_anchors(RotationAnchors(game))
                self.palette_panel.refresh()
                # The scripts can only be checked for live warnings once the game is known.
                self.scripts_panel.update_warnings()

        def failed(message: str) -> None:
            if current():
                self._set_game_status(f"Failed to load: {message}")

        def progressed(text: str) -> None:
            if current():
                self._set_game_status(text)

        context.game = None
        # Applied here rather than on the worker: the model it changes is read by the UI.
        self._engine_problems = context.apply_engine()
        self.game_label.setToolTip("\n".join(self._engine_problems))
        # A patched engine can name map settings the stock one has no word for - a weather
        # the `.sagepatch` adds - so the settings form is refilled from the engine just
        # applied.
        self.map_settings_panel.refresh()
        self._set_game_status("Loading…")
        worker = run_worker(self, lambda: context.load(report), loaded, failed)
        workers.append(worker)
        worker.progress.connect(progressed)

    def _set_game_status(self, text: str) -> None:
        self.game_label.setText(f"Game: {text}")

    def _apply_autosave_settings(self) -> None:
        settings = self.settings.autosave_settings()
        if self.autosaver is not None:
            self.autosaver.settings = settings
        self.autosave_timer.setInterval(settings.interval_seconds * 1000)
        if settings.enabled:
            self.autosave_timer.start()
        else:
            self.autosave_timer.stop()

    def edit_game_settings(self) -> None:
        if self._busy:
            return
        dialog = GameSettingsDialog(self.settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = (dialog.install, dialog.mods, dialog.sagepatch)
        layers_changed = chosen != (
            self.settings.install,
            self.settings.mods,
            self.settings.sagepatch,
        )
        self.settings.install = dialog.install
        self.settings.mods = dialog.mods
        self.settings.sagepatch = dialog.sagepatch
        for folder in dialog.mods:
            self.settings.add_recent_mod(folder)
        self._rebuild_recent_mods_menu()
        self.settings.autosave_enabled = dialog.autosave_enabled
        self.settings.autosave_interval_seconds = dialog.autosave_interval
        self.settings.save()
        if layers_changed:
            self.apply_game_layers()
        else:
            self._apply_autosave_settings()

    def choose_mod(self) -> None:
        if self._busy:
            return
        loaded = self.settings.mods or self.settings.recent_mods or [""]
        start = loaded[-1] if self.settings.mods else loaded[0]
        folder = QFileDialog.getExistingDirectory(self, "Load Mod", start)
        if folder:
            self.load_mod(Path(folder))

    def load_mod(self, folder: Path) -> None:
        """Mount the unpacked mod `folder` above the install and every mod already loaded (one
        already loaded moves to the top), and reload the game data. An open map stays open and
        resolves against it."""
        if self._busy:
            return
        if not folder.is_dir():
            QMessageBox.warning(
                self, APP_TITLE, f"{folder} no longer exists; it is removed from the list."
            )
            self.settings.remove_recent_mod(str(folder))
            self.settings.unload_mod(str(folder))
            self.settings.save()
            self._rebuild_recent_mods_menu()
            self._refresh()
            return
        if not is_mod_folder(folder):
            answer = QMessageBox.question(
                self,
                APP_TITLE,
                f"{folder} holds neither a data folder nor .big archives, so the game would "
                "find nothing in it. Load it anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._remember_mod(str(folder))
        self._rebuild_recent_mods_menu()
        self.apply_game_layers()

    def unload_mod(self, folder: Path) -> None:
        """Take `folder` out of the loaded mods, keeping the others' order, and reload."""
        if self._busy or not self.settings.has_mod(str(folder)):
            return
        self.settings.unload_mod(str(folder))
        self.settings.save()
        self._rebuild_recent_mods_menu()
        self.apply_game_layers()

    def unload_all_mods(self) -> None:
        """Go back to the install alone."""
        if self._busy or not self.settings.mods:
            return
        self.settings.mods = []
        self.settings.save()
        self._rebuild_recent_mods_menu()
        self.apply_game_layers()

    def toggle_mod(self, folder: Path) -> None:
        """Unload `folder` when it is loaded, and load it on top otherwise."""
        if self.settings.has_mod(str(folder)):
            self.unload_mod(folder)
        else:
            self.load_mod(folder)

    def _remember_mod(self, folder: str) -> None:
        self.settings.load_mod(folder)
        self.settings.add_recent_mod(folder)
        self.settings.save()

    def _rebuild_recent_mods_menu(self) -> None:
        self.recent_mods_menu.clear()
        loaded = self.settings.mods
        for index, folder in enumerate(self.settings.recent_mods, start=1):
            prefix = f"&{index}" if index < 10 else "1&0"
            position = next(
                (number for number, mod in enumerate(loaded, 1) if same_folder(mod, folder)), None
            )
            # With several loaded, where each sits in the load order (the last one wins).
            order = ""
            if position is not None and len(loaded) > 1:
                order = f"  (loaded {position} of {len(loaded)})"
            action = self.recent_mods_menu.addAction(f"{prefix} {folder}{order}")
            if action is not None:
                action.setCheckable(True)
                action.setChecked(position is not None)
                action.triggered.connect(
                    lambda _checked=False, folder=folder: self.toggle_mod(Path(folder))
                )
        if self.settings.recent_mods:
            self.recent_mods_menu.addSeparator()
            self.recent_mods_menu.addAction("Clear List", self._clear_recent_mods)
        self._refresh()

    def _clear_recent_mods(self) -> None:
        self.settings.recent_mods.clear()
        self.settings.save()
        self._rebuild_recent_mods_menu()

    def choose_sagepatch(self) -> None:
        if self._busy:
            return
        start = self.settings.sagepatch or (self.settings.mods or [""])[-1]
        path, _ = QFileDialog.getOpenFileName(self, "Load Patch File", start, SAGEPATCH_FILTER)
        if path:
            self.load_sagepatch(Path(path))

    def load_sagepatch(self, path: Path | None) -> None:
        """Read the game data as the patched `game.dat` the `.sagepatch` at `path` describes, and
        apply its patches on Jump To Game; `None` goes back to the stock engine. An open map stays
        open."""
        if self._busy:
            return
        if path is not None and not path.is_file():
            QMessageBox.warning(self, APP_TITLE, f"There is no .sagepatch at {path}.")
            return
        self.settings.sagepatch = str(path) if path is not None else None
        self.settings.save()
        self.apply_game_layers()

    def open_map(self) -> None:
        if self._busy:
            return
        dialog = OpenMapDialog(self.context, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        browsed, selected = dialog.browsed, dialog.selected
        if browsed is not None:
            self._when_changes_handled(lambda: self.open_path(browsed))
        elif selected is not None:
            self._when_changes_handled(lambda: self.open_entry(selected))

    def open_path(self, path: Path) -> None:
        path = Path(path)
        self._run_busy(
            f"Opening {path.name}…",
            lambda: MapDocument.open(path),
            lambda document: self._opened(document, RecentMap("file", str(path))),
        )

    def open_entry(self, entry: MapEntry) -> None:
        context = self.context
        if context is None:
            return
        if entry.entry.file is not None:
            recent = RecentMap("file", str(entry.entry.file))
        else:
            recent = RecentMap("game", entry.entry.path)
        self._run_busy(
            f"Opening {entry.name}…",
            lambda: context.open_map(entry),
            lambda document: self._opened(document, recent),
        )

    def open_recent(self, recent: RecentMap) -> None:
        if self._busy:
            return
        if recent.kind == "file":
            path = Path(recent.path)
            if not path.is_file():
                self._forget_missing(recent)
                return
            self._when_changes_handled(lambda: self.open_path(path))
            return
        entry = self.context.find_map(recent.path) if self.context is not None else None
        if entry is None:
            self._forget_missing(recent)
            return
        self._when_changes_handled(lambda: self.open_entry(entry))

    def _opened(self, document: MapDocument, recent: RecentMap) -> None:
        self._set_document(document)
        self._remember(recent)
        _status(self).showMessage(f"Opened {document.title}", 5000)

    def close_map(self) -> None:
        if not self._busy:
            self._when_changes_handled(lambda: self._set_document(None))

    def new_map(self) -> None:
        if self._busy:
            return
        textures = sorted(terrain_textures(self.game)) if self.game is not None else []
        dialog = NewMapDialog(NewMapOptions(), textures, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        options = dialog.new_map_options()
        self._when_changes_handled(lambda: self.create_new_map(options))

    def create_new_map(self, options: NewMapOptions) -> None:
        """Open a new, untitled map made from `options` (its first save asks where)."""
        try:
            document = MapDocument(new_map(options))
        except ValueError as exc:
            _status(self).showMessage(f"Cannot create the map: {exc}", 5000)
            return
        self._set_document(document)
        _status(self).showMessage(f"New map, {options.width} x {options.height} cells", 5000)

    def resize_map(self) -> None:
        document = self.document
        height_map = document.map.height_map_data if document is not None else None
        if height_map is None or self._busy:
            return
        current = NewMapOptions(
            width=height_map.width,
            height=height_map.height,
            border=height_map.border_width,
            initial_height=0.0,
        )
        dialog = NewMapDialog(current, [], self, resize=True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_resize(dialog.resize_options())

    def apply_resize(self, options: ResizeOptions) -> None:
        document = self.document
        if document is None or self._busy:
            return
        try:
            command = ResizeMap(document.map, options)
        except ValueError as exc:
            _status(self).showMessage(f"Cannot resize: {exc}", 5000)
            return
        self.execute(command)
        self.map_view.fit_map()
        if self.map_view_3d is not None:
            self.map_view_3d.fit_map()

    def import_heightmap(self, path: Path | None = None) -> bool:
        """Replace the heights with a heightmap exported at this map's size (asks for the file
        and confirms, as WorldBuilder does, when no path is given)."""
        document = self.document
        grid = document.terrain if document is not None else None
        if document is None or grid is None or self._busy:
            return False
        if path is None:
            chosen, _ = QFileDialog.getOpenFileName(self, "Import Heightmap", "", _RAW_FILTER)
            if not chosen:
                return False
            answer = QMessageBox.question(
                self,
                APP_TITLE,
                "This changes the terrain height of the current map. Do you really want to do "
                "this?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
            path = Path(chosen)
        try:
            heights = import_raw(Path(path).read_bytes(), grid.width, grid.height)
        except OSError:
            _status(self).showMessage("Can't open file.", 5000)
            return False
        except ValueError:
            _status(self).showMessage("Wrong file size.", 5000)
            return False
        command = PatchHeights(0, 0, heights, "Import Heightmap")
        self.execute(command)
        command.closed = True
        return True

    def export_heightmap(self, path: Path | None = None) -> bool:
        document = self.document
        grid = document.terrain if document is not None else None
        if document is None or grid is None:
            return False
        if path is None:
            chosen, _ = QFileDialog.getSaveFileName(
                self, "Export heightmap", f"{document.title}.raw", _RAW_FILTER
            )
            if not chosen:
                return False
            path = Path(chosen)
        try:
            atomic_write(Path(path), export_raw(grid.heights))
        except OSError:
            _status(self).showMessage("Can't create file.", 5000)
            return False
        _status(self).showMessage(
            f"Exported as {grid.width} x {grid.height} pixel raw image.", 5000
        )
        return True

    def open_from_tga(self) -> None:
        if self._busy:
            return
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Open from TGA", "", "Targa (*.tga);;Images (*.tga *.png *.bmp);;All files (*)"
        )
        if chosen:
            self._when_changes_handled(lambda: self.open_from_image(Path(chosen)))

    def open_from_image(self, path: Path) -> None:
        """A new map the size of a grey image, its heights read from the grey levels."""
        try:
            heights = read_image_heights(Path(path).read_bytes())
        except OSError as exc:
            _status(self).showMessage(f"Cannot read {Path(path).name}: {exc}", 5000)
            return
        rows, columns = heights.shape
        border = min(30, max(0, (min(rows, columns) - 1) // 4))
        map = new_map(NewMapOptions(width=columns, height=rows, border=border))
        height_map = map.height_map_data
        assert height_map is not None
        height_map.elevations = heights[::-1].tolist()
        height_map.min_height, height_map.max_height = int(heights.min()), int(heights.max())
        self._set_document(MapDocument(map, name=Path(path).stem))
        _status(self).showMessage(f"New map from {Path(path).name}, {columns} x {rows}", 5000)

    def save(self, then: Callable[[], Any] | None = None) -> None:
        if self.document is not None and not self._busy:
            self._save_to(None, None, then)

    def save_as(self, then: Callable[[], Any] | None = None) -> None:
        document = self.document
        if document is None or self._busy:
            return
        dialog = SaveMapDialog(
            self.context, document.title, compressed=document.compressed, parent=self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.target is None:
            return
        target = dialog.target
        if target.exists():
            answer = QMessageBox.question(self, APP_TITLE, f"{target} already exists. Replace it?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, APP_TITLE, f"Cannot create {target.parent}:\n{exc}")
            return
        self._save_to(target, dialog.compress, then)

    def _save_to(
        self, path: Path | None, compress: bool | None, then: Callable[[], Any] | None
    ) -> None:
        document = self.document
        if document is None:
            return
        try:
            target = document.save_target(path)
        except ReadOnlyMapError:
            QMessageBox.warning(
                self,
                APP_TITLE,
                "The file is read-only. Change the protection, or use Save As to save a copy.",
            )
            self.save_as(then)
            return
        except ValueError:
            self.save_as(then)
            return
        use_compression = document.compressed if compress is None else compress
        if is_base_path(target) and document.castle_templates_stale:
            if not refresh_castle_templates(document.map, target, self.game, self.map_view.anchors):
                QMessageBox.warning(
                    self,
                    APP_TITLE,
                    "The castle templates were not rebuilt, as no game data is loaded: the game "
                    "will build this base's castle as it was before these edits.",
                )

        def written(data: bytes) -> None:
            try:
                document.save(target, compress=use_compression, data=data)
            except OSError as exc:
                QMessageBox.critical(self, APP_TITLE, f"Could not save {target}:\n{exc}")
                return
            self._remember(RecentMap("file", str(target)))
            _status(self).showMessage(f"Saved {target}", 5000)
            self._refresh()
            if then is not None:
                then()

        self._run_busy(
            f"Saving {target.name}…", lambda: document.to_bytes(use_compression), written
        )

    def undo(self) -> None:
        if self.document is not None and not self._busy:
            self.document.stack.undo()

    def redo(self) -> None:
        if self.document is not None and not self._busy:
            self.document.stack.redo()

    def repeat(self) -> None:
        if self.document is not None and not self._busy and not self.document.stack.repeat():
            _status(self).showMessage("The last action cannot be repeated.", 3000)

    def autosave(self) -> None:
        document = self.document
        if document is None or self._busy or self.autosaver is None:
            return
        try:
            written = self.autosaver.save(document)
        except OSError:
            _status(self).showMessage("Unable to autosave file.", 5000)
            return
        if written is not None:
            _status(self).showMessage(f"Autosaved to {written}", 3000)

    def _docks(self) -> tuple[QDockWidget, ...]:
        return (
            self.scripts_dock,
            self.players_dock,
            self.teams_dock,
            self.map_settings_dock,
            self.mp_positions_dock,
            self.map_dock,
            self.item_list_dock,
            self.object_dock,
            self.palette_dock,
            self.layers_dock,
            self.build_list_dock,
            self.brush_dock,
            self.terrain_material_dock,
            self.copy_terrain_dock,
            self.array_dock,
            self.road_dock,
            self.water_dock,
            self.lighting_dock,
            self.environment_dock,
            self.dressing_dock,
            self.generic_ai_dock,
            self.camera_dock,
            self.validation_dock,
            self.script_debugger_dock,
        )

    def set_layout_locked(self, locked: bool) -> None:
        """Lock Layout: hold the panels where they are, so dragging one over another only moves
        it."""
        self.settings.lock_layout = locked
        self.settings.save()
        self._apply_layout_lock()

    def _apply_layout_lock(self) -> None:
        """Take the drop targets away while the layout is locked.

        Three things have to go, because a panel can be swallowed in three ways: Qt refuses to
        start a dock drag at all without `DockWidgetMovable`; an area that allows nothing can
        take no panel, whichever way the drag began; and without grouped dragging and tabbed
        docks two panels cannot merge into one window. A locked panel keeps its close and float
        buttons, and a floating one is still dragged about by its title bar - the window manager
        moves it, and there is no longer anywhere for it to land.
        """
        locked = self.settings.lock_layout
        movable = QDockWidget.DockWidgetFeature.DockWidgetMovable
        areas = (
            Qt.DockWidgetArea.NoDockWidgetArea if locked else Qt.DockWidgetArea.AllDockWidgetAreas
        )
        for dock in self._docks():
            features = dock.features()
            dock.setFeatures(features & ~movable if locked else features | movable)
            dock.setAllowedAreas(areas)
        options = QMainWindow.DockOption
        held = options.GroupedDragging | options.AllowTabbedDocks
        self.setDockOptions(self._dock_options & ~held if locked else self._dock_options)

    def childEvent(self, event: QChildEvent | None) -> None:  # noqa: N802 - Qt override
        super().childEvent(event)
        # Polished, not added: a child is announced while it is still being constructed, before
        # its class name is its own.
        if event is not None and event.type() == QEvent.Type.ChildPolished:
            child = event.child()
            if child is not None and is_group_window(child):
                child.installEventFilter(self)

    def eventFilter(self, watched: QObject | None, event: QEvent | None) -> bool:  # noqa: N802
        """Keep a locked layout's floating group windows from docking.

        Qt ignores the panels' allowed areas for a window holding more than one of them - such a
        window may dock anywhere - and the panels inside are not floating by its reckoning, so
        taking `DockWidgetMovable` away does not turn the drag into a plain window move either.
        Swallowing the title-bar press stops Qt's drag from starting at all; the window manager
        still moves the window, as it does a lone locked panel.
        """
        if (
            self.settings.lock_layout
            and event is not None
            and event.type() == QEvent.Type.NonClientAreaMouseButtonPress
            and watched is not None
            and is_group_window(watched)
        ):
            return True
        return super().eventFilter(watched, event)

    def raise_floating_docks(self) -> None:
        """Bring the undocked panels above the main window, so focusing the editor never leaves
        one buried behind it.

        Qt hands a floating panel the main window as its owner, which most window managers
        already keep it above; this also covers the ones that do not, and panels dropped together
        into a window of Qt's own.
        """
        windows = {floating_window(dock): None for dock in self._docks()}
        for window in windows:
            if window is not None:
                window.raise_()

    def reset_layout(self) -> None:
        self.restoreState(self._default_state)
        self.toolbar.show()
        for dock in self._docks():
            dock.show()
        self.status_bar_action.setChecked(True)

    def show_shortcuts(self) -> None:
        ShortcutsDialog(accelerators(), self.available_commands, self).exec()

    def _cycle_pane(self, step: int) -> None:
        panes = [dock for dock in self._docks() if dock.isVisible()]
        if not panes:
            return
        focus = QApplication.focusWidget()
        current = next(
            (i for i, dock in enumerate(panes) if focus is not None and dock.isAncestorOf(focus)),
            -1 if step > 0 else 0,
        )
        target = panes[(current + step) % len(panes)]
        target.raise_()
        content = target.widget()
        if content is not None:
            content.setFocus(Qt.FocusReason.OtherFocusReason)

    def ask_save_changes(self, document: MapDocument) -> str:
        """Ask whether to save `document` first: returns `save`, `discard` or `cancel`."""
        buttons = QMessageBox.StandardButton
        answer = QMessageBox.question(
            self,
            APP_TITLE,
            f"Save changes to {document.title}?",
            buttons.Save | buttons.Discard | buttons.Cancel,
            buttons.Save,
        )
        return {buttons.Save: "save", buttons.Discard: "discard"}.get(answer, "cancel")

    def _when_changes_handled(self, then: Callable[[], Any]) -> None:
        """Run `then` once the open map's unsaved changes are saved or discarded."""
        document = self.document
        if document is None or not document.dirty:
            then()
            return
        choice = self.ask_save_changes(document)
        if choice == "save":
            self.save(then=then)
        elif choice == "discard":
            then()

    def _set_document(self, document: MapDocument | None) -> None:
        for unlink in self._document_links:
            unlink()
        self._document_links = []
        self.document = document
        if document is not None:
            self._document_links = [
                document.subscribe(self._on_change),
                document.stack.subscribe(self._refresh),
                document.selection.subscribe(self._selection_changed),
            ]
            document.selection.locked = self.lock_selection_action.isChecked()
        self.map_view.set_document(document)
        self._update_texture_colors()
        self._refresh_texture_catalogue()
        self._refresh_road_catalogue()
        self.ambient_player.refresh()
        self._refresh()
        self.scripts_panel.selected = None
        self.scripts_panel.refresh()
        self.script_debugger_panel.document_changed()
        self.validation_panel.clear()
        for panel in (
            self.players_panel,
            self.teams_panel,
            self.map_settings_panel,
            self.mp_positions_panel,
            self.item_list_panel,
            self.object_panel,
            self.palette_panel,
            self.layers_panel,
            self.build_list_panel,
            self.water_panel,
            self.lighting_panel,
            self.environment_panel,
            self.camera_panel,
        ):
            panel.refresh()

    def _on_change(self, change: Change) -> None:
        self._refresh()
        if change.kind is ChangeKind.TERRAIN and change.region is not None:
            self._patch_texture_colors(change.region)
        elif change.kind is ChangeKind.TERRAIN:
            self._update_texture_colors()
        self.map_view.on_change(change)
        if self.map_view.gesture_active and change.kind is not ChangeKind.WHOLE:
            # Mid-drag: the view is up to date; the panels catch up once the button comes up.
            self._held_changes.add(change.kind)
            return
        self._refresh_panels_for(change)

    def _gesture_finished(self) -> None:
        held, self._held_changes = self._held_changes, set()
        for kind in held:
            self._refresh_panels_for(Change(kind))

    def _refresh_panels_for(self, change: Change) -> None:
        whole = change.kind is ChangeKind.WHOLE
        # A player's library maps are side data, and they decide what the scripts tree imports.
        if whole or change.kind in (ChangeKind.SCRIPTS, ChangeKind.SIDES):
            self.scripts_panel.refresh()
        if whole or change.kind in (ChangeKind.SIDES, ChangeKind.SCRIPTS):
            self.players_panel.refresh()
            self.teams_panel.refresh()
            self.palette_panel.refresh()
            self.build_list_panel.refresh()
        if whole or change.kind is ChangeKind.WATER:
            self.water_panel.refresh()
        if whole or change.kind is ChangeKind.CAMERAS:
            self.camera_panel.refresh()
        if whole or change.kind is ChangeKind.OBJECTS:
            self.ambient_player.refresh()
            self.generic_ai_panel.refresh()
        if whole or change.kind is ChangeKind.SETTINGS:
            self.lighting_panel.refresh()
            self.environment_panel.refresh()
            self.map_settings_panel.refresh()
            self.mp_positions_panel.refresh()
        listed = (ChangeKind.OBJECTS, ChangeKind.WAYPOINTS, ChangeKind.AREAS, ChangeKind.SIDES)
        if whole or change.kind in listed:
            self.item_list_panel.refresh()
            self.object_panel.refresh()
            self.layers_panel.refresh()

    def _remember(self, recent: RecentMap) -> None:
        self.settings.add_recent(recent)
        self.settings.save()
        self._rebuild_recent_menu()

    def _forget_missing(self, recent: RecentMap) -> None:
        QMessageBox.warning(
            self, APP_TITLE, f"{recent.label()} no longer exists; it is removed from the list."
        )
        self.settings.remove_recent(recent)
        self.settings.save()
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        for index, recent in enumerate(self.settings.recent, start=1):
            prefix = f"&{index}" if index < 10 else str(index)
            action = self.recent_menu.addAction(f"{prefix} {recent.label()}")
            if action is not None:
                action.triggered.connect(
                    lambda _checked=False, recent=recent: self.open_recent(recent)
                )
        if self.settings.recent:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Clear List", self._clear_recent)
        self._refresh()

    def _clear_recent(self) -> None:
        self.settings.recent.clear()
        self.settings.save()
        self._rebuild_recent_menu()

    def _run_busy(
        self, message: str, work: Callable[[], Any], on_done: Callable[[Any], None]
    ) -> None:
        """Run `work` on a worker with the window locked, then `on_done` with its result."""
        self._set_busy(True, message)

        def done(result: Any) -> None:
            self._set_busy(False)
            on_done(result)

        def failed(error: str) -> None:
            self._set_busy(False)
            QMessageBox.critical(self, APP_TITLE, f"{message.rstrip('…')} failed.\n\n{error}")

        run_worker(self, work, done, failed)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        bar = self.menuBar()
        for widget in (bar, self.toolbar, *self._docks()):
            if widget is not None:
                widget.setEnabled(not busy)
        if busy:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            _status(self).showMessage(message)
        else:
            QApplication.restoreOverrideCursor()
            _status(self).clearMessage()
        self._refresh()

    @property
    def busy(self) -> bool:
        return self._busy

    def _refresh(self) -> None:
        if not hasattr(self, "recent_menu"):
            return  # still being built
        document = self.document
        idle = not self._busy
        stack = document.stack if document is not None else None
        self.open_action.setEnabled(idle)
        self.new_action.setEnabled(idle)
        self.open_from_tga_action.setEnabled(idle)
        for action in (self.close_action, self.save_action, self.save_as_action):
            action.setEnabled(idle and document is not None)
        has_terrain = idle and document is not None and document.map.height_map_data is not None
        for action in (
            self.import_heightmap_action,
            self.export_heightmap_action,
            self.resize_action,
        ):
            action.setEnabled(has_terrain)
        self.undo_action.setEnabled(idle and stack is not None and stack.can_undo)
        self.redo_action.setEnabled(idle and stack is not None and stack.can_redo)
        self.repeat_action.setEnabled(idle and stack is not None and stack.can_undo)
        undo_label = stack.undo_label if stack is not None else None
        redo_label = stack.redo_label if stack is not None else None
        self.undo_action.setText(f"&Undo {undo_label}" if undo_label else "&Undo")
        self.redo_action.setText(f"&Redo {redo_label}" if redo_label else "&Redo")
        self.reload_game_action.setEnabled(idle and self.context is not None)
        self.game_settings_action.setEnabled(idle)
        self.load_mod_action.setEnabled(idle)
        self.unload_mod_action.setEnabled(idle and bool(self.settings.mods))
        self.load_sagepatch_action.setEnabled(idle)
        self.unload_sagepatch_action.setEnabled(idle and self.settings.sagepatch is not None)
        self.recent_mods_menu.setEnabled(idle and bool(self.settings.recent_mods))
        self.jump_action.setEnabled(idle and document is not None and self.context is not None)
        self.report_action.setEnabled(idle and document is not None)
        self.mapcache_action.setEnabled(idle and document is not None)
        self.recent_menu.setEnabled(idle and bool(self.settings.recent))
        self.fit_view_action.setEnabled(document is not None)
        has_objects = idle and bool(self.selected_objects())
        for action in (
            self.cut_action,
            self.copy_action,
            self.select_similar_action,
            self.replace_selected_action,
            self.select_siblings_action,
            self.select_base_parent_action,
        ):
            action.setEnabled(has_objects)
        self.delete_action.setEnabled(idle and document is not None and bool(document.selection))
        self.paste_action.setEnabled(
            idle and document is not None and self._clipboard_has_objects()
        )

        if document is None:
            self.setWindowTitle(APP_TITLE)
            self.setWindowModified(False)
            self.map_view.message = "No map open.\n\nFile > Open lists the game's maps by category."
        else:
            suffix = " (read-only)" if document.read_only else ""
            self.setWindowTitle(f"{document.title}{suffix}[*] - {APP_TITLE}")
            self.setWindowModified(document.dirty)
        self._fill_map_info()

    def _fill_map_info(self) -> None:
        while self.map_form.rowCount():
            self.map_form.removeRow(0)
        document = self.document
        if document is None:
            self.map_form.addRow(QLabel("No map open"))
            return
        rows = [
            ("Name", document.title),
            ("File", str(document.path) if document.path else "(inside a game archive)"),
            ("Access", "read-only" if document.read_only else "writable"),
            ("Compression", "RefPack" if document.compressed else "none"),
            ("Unsaved changes", "yes" if document.dirty else "no"),
            *map_summary(document.map),
        ]
        for label, value in rows:
            self.map_form.addRow(label, self._value_label(value))

    def _restore_layout(self) -> None:
        if self.settings.window_geometry:
            self.restoreGeometry(
                QByteArray.fromBase64(self.settings.window_geometry.encode("ascii"))
            )
        if self.settings.window_state:
            self.restoreState(QByteArray.fromBase64(self.settings.window_state.encode("ascii")))

    def _store_layout(self) -> None:
        self.settings.window_geometry = _base64(self.saveGeometry())
        self.settings.window_state = _base64(self.saveState())

    def changeEvent(self, event: QEvent | None) -> None:  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event is not None and event.type() == QEvent.Type.ActivationChange:
            # Not when a panel itself took the focus: the window counts as active then too, and
            # raising them all would shuffle the one the user just clicked back under the others.
            if QApplication.activeWindow() is self:
                self.raise_floating_docks()

    def closeEvent(self, event: QCloseEvent | None) -> None:  # noqa: N802 - Qt override
        if event is None:
            return
        if self._busy:
            event.ignore()
            return
        document = self.document
        if document is not None and document.dirty and not self._handed_over:
            choice = self.ask_save_changes(document)
            if choice == "cancel":
                event.ignore()
                return
            if choice == "save":
                event.ignore()
                self.save(then=self.close)
                return
        if not self._handed_over and not self.restore_game_dats():
            event.ignore()
            return
        self.autosave_timer.stop()
        self.ambient_player.stop()
        self.script_debugger_panel.shutdown()
        self._store_layout()
        self.settings.save()
        event.accept()


def _fit_when_floated(dock: QDockWidget, floating: bool) -> None:
    # Size the panel and bring it up once Qt has finished making it a window of its own.
    if floating:
        QTimer.singleShot(0, partial(_settle_floating_dock, dock))


def _settle_floating_dock(dock: QDockWidget) -> None:
    fit_floating_dock(dock)
    window = floating_window(dock)
    if window is not None:
        window.raise_()


def is_group_window(widget: QObject) -> bool:
    """Whether `widget` is the window Qt makes when floating panels are dropped together."""
    meta = widget.metaObject()
    return meta is not None and meta.className() == "QDockWidgetGroupWindow"


def floating_window(dock: QDockWidget) -> QWidget | None:
    """The window a panel floats in: the panel itself while it is out on its own, the window a
    group shares once it was dropped onto another floating panel, and None while it is docked."""
    window = dock.window()
    if window is dock:
        return dock if dock.isFloating() else None
    # Grouped dragging puts floating panels inside a window of Qt's own; the main window means
    # the panel is docked, so there is nothing of its own to size.
    return None if isinstance(window, QMainWindow) else window


def fit_floating_dock(dock: QDockWidget) -> None:
    """Size a floating panel to what its contents ask for: at least a readable minimum, at most
    most of the screen, and moved back onto the screen if that made it hang off an edge. A panel
    grouped with others is sized through the window they share."""
    window = floating_window(dock)
    if window is None:
        return
    size = window.sizeHint().expandedTo(window.minimumSizeHint()).expandedTo(_FLOATING_MINIMUM)
    screen = window.screen()
    if screen is not None:
        available = screen.availableGeometry()
        size = size.boundedTo(
            QSize(
                int(available.width() * _FLOATING_SCREEN_SHARE),
                int(available.height() * _FLOATING_SCREEN_SHARE),
            )
        )
        window.resize(size)
        frame = window.frameGeometry()
        left = min(max(frame.left(), available.left()), available.right() - frame.width())
        top = min(max(frame.top(), available.top()), available.bottom() - frame.height())
        window.move(left, top)
        return
    window.resize(size)


def _menu(menu: QMenu | None) -> QMenu:
    assert menu is not None
    return menu


def _status(window: QMainWindow) -> Any:
    status = window.statusBar()
    assert status is not None
    return status


def _base64(data: QByteArray) -> str:
    return bytes(data.toBase64().data()).decode("ascii")
