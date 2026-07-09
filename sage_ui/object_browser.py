"""A floating object browser that stays above the main window, with two views:

- **All objects** - every loaded object grouped by Side then EditorSorting.
- **By faction** - the `sage_utils.factiongraph` ownership graph as a drill-down: faction →
  spellbook /
  structures → the units, heroes and upgrades each structure produces. This is the
  "explore the game without launching it" path for someone who doesn't know template
  names - built lazily on a worker the first time the tab is opened, since assembling
  the graphs walks the whole game.

Double-clicking a leaf loads that object as the primary unit; right-clicking loads it as
the comparison unit. Opened from the main window's "Browser" menu action and rebuilt
whenever a new source set is loaded."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sage_utils.factiongraph import FactionGraph, Power
from sage_utils.views import clean_text, display_name, safe
from sage_utils.widgets import CopyableLabel as QLabel
from sage_utils.widgets import resource_path

ICON_FILE = "icon.ico"

_NO_SIDE = "Civilian"  # objects with no Side are sideless civilians in-game
_NO_SORTING = "NONE"  # objects with no EditorSorting (the engine's default)


def group_objects(game) -> dict[str, dict[str, list[tuple[str, str]]]]:
    """Group the game's objects by Side then EditorSorting. Returns a nested mapping
    `side -> sorting -> [(raw name, display label), …]`, each leaf list sorted by label.
    Objects with no Side fall under "Civilian"; those with no EditorSorting under "NONE"."""
    groups: dict[str, dict[str, list[tuple[str, str]]]] = {}
    for obj in game.objects.values():
        side = safe(lambda o=obj: o.Side) or _NO_SIDE
        sorting = safe(lambda o=obj: o.EditorSorting)
        sorting_name = getattr(sorting, "name", None) or _NO_SORTING
        # Lead with the raw template name, then the localized display name in brackets.
        shown = display_name(game, obj)
        label = f"{obj.name}  ({shown})" if shown else obj.name
        groups.setdefault(side, {}).setdefault(sorting_name, []).append((obj.name, label))
    for sortings in groups.values():
        for leaves in sortings.values():
            leaves.sort(key=lambda pair: pair[1].casefold())
    return groups


def _ordered_keys(keys) -> list[str]:
    """Alphabetical order with the placeholder buckets (parenthesised) sorted last."""
    return sorted(keys, key=lambda k: (k.startswith("("), k.casefold()))


def _node(label: str, *, obj: str | None = None, tooltip: str = "", children=None) -> dict:
    """One faction-tree node as plain data: `obj` (a raw object name) makes it a loadable
    leaf; a node without one is a group / info line."""
    return {"label": label, "object": obj, "tooltip": tooltip, "children": children or []}


def _leaf(display: str, name: str, tooltip: str = "") -> dict:
    label = f"{display}  ({name})" if display and display != name else name
    return _node(label, obj=name, tooltip=tooltip or name)


def _grouped_leaves(records) -> list[dict]:
    """Leaves for unit/hero records, in first-seen order - but records sharing one display
    name (rank/variant duplicates like "Lossarnach Axe Warriors" ×4) collapse under a
    single `display (N)` group that expands to their object names, so the list reads
    clean and every variant stays reachable."""
    by_display: dict[str, list] = {}
    order: list[str] = []
    for record in records:
        key = (record.display or record.name).casefold()
        if key not in by_display:
            by_display[key] = []
            order.append(key)
        by_display[key].append(record)
    nodes = []
    for key in order:
        group = by_display[key]
        if len(group) == 1:
            record = group[0]
            nodes.append(_leaf(record.display, record.name, clean_text(record.description) or ""))
        else:
            display = group[0].display or group[0].name
            children = [
                _node(
                    record.name,
                    obj=record.name,
                    tooltip=clean_text(record.description) or record.name,
                )
                for record in group
            ]
            nodes.append(_node(f"{display}  ({len(group)})", children=children))
    return nodes


def _power_node(power: Power) -> dict:
    """A spellbook power / ability, with the objects it creates or turns into as loadable
    children (they carry stat profiles of their own)."""
    label = power.display
    if power.cooldown:
        label += f"  ({power.cooldown:g}s)"
    children = [_leaf(display or name, name) for name, display in power.creates]
    children += [
        _leaf(f"becomes: {display or name}", name) for name, display in power.transforms_into
    ]
    return _node(label, tooltip=clean_text(power.effect) or power.name, children=children)


def _structure_node(graph: FactionGraph, structure) -> dict:
    """A structure with what it produces beneath it - the drill-down's middle layer."""
    trained = [graph.units[u] for u in structure.trains_units if u in graph.units]
    recruited = [graph.heroes[h] for h in structure.recruits_heroes if h in graph.heroes]
    children = _grouped_leaves(trained) + _grouped_leaves(recruited)
    for upgrade_name in structure.researches_upgrades:
        upgrade = graph.upgrades.get(upgrade_name)
        if upgrade is None:
            continue
        cost = f" - {upgrade.cost:g}" if upgrade.cost else ""
        affected = ", ".join(display for _n, display in upgrade.affects)
        tooltip = clean_text(upgrade.description) or upgrade.name
        if affected:
            tooltip = f"{tooltip}\nAffects: {affected}"
        children.append(_node(f"research: {upgrade.display}{cost}", tooltip=tooltip))
    return _node(
        f"{structure.display}  [{structure.role.value.replace('_', ' ')}]",
        obj=structure.name,
        tooltip=clean_text(structure.description) or structure.name,
        children=children,
    )


def faction_tree(graphs: list[FactionGraph]) -> list[dict]:
    """The By-faction drill-down as plain data (testable without Qt): one node per
    faction, holding its spellbook, its structures (each with what it produces), and flat
    unit/hero lists for quick scanning."""
    nodes = []
    for graph in graphs:
        children = []
        if graph.spellbook is not None and graph.spellbook.powers:
            children.append(
                _node(
                    f"Spellbook  ({len(graph.spellbook.powers)})",
                    children=[_power_node(p) for p in graph.spellbook.powers],
                )
            )
        if graph.structures:
            children.append(
                _node(
                    f"Structures  ({len(graph.structures)})",
                    children=[
                        _structure_node(graph, structure) for structure in graph.structures.values()
                    ],
                )
            )
        if graph.units:
            children.append(
                _node(
                    f"Units  ({len(graph.units)})",
                    children=_grouped_leaves(graph.units.values()),
                )
            )
        if graph.heroes:
            children.append(
                _node(
                    f"Heroes  ({len(graph.heroes)})",
                    children=_grouped_leaves(graph.heroes.values()),
                )
            )
        label = graph.display if graph.display else graph.name
        if graph.side:
            label += f"  [{graph.side}]"
        nodes.append(_node(label, children=children))
    return nodes


class ObjectBrowser(QWidget):
    """A separate window, floating above the main window, with the All-objects tree and
    the By-faction drill-down, driving the main window's two unit slots from clicks."""

    def __init__(self, browser) -> None:
        # A Tool window floats above its parent (the main window) only - not above other
        # applications - and is hidden/minimized along with it.
        super().__init__(browser, Qt.WindowType.Tool)
        self._browser = browser
        self.setWindowTitle("Object Browser")
        self.setWindowIcon(QIcon(str(resource_path(ICON_FILE, __file__))))
        self.resize(720, 760)
        # The faction graphs come from the main window's shared cache (built once per load,
        # on a worker) the first time the By-faction tab is shown.
        self._faction_nodes: list[dict] | None = None
        self._faction_loading = False
        self._pending_focus: str | None = None  # a faction display name to open on build

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        hint = QLabel("Double-click loads as Unit 1, right-click loads as Unit 2.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.tabs = QTabWidget()
        self.tree = self._make_tree()
        self.faction_tree_widget = self._make_tree()
        self.tabs.addTab(self.tree, "All objects")
        self.tabs.addTab(self.faction_tree_widget, "By faction")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        # Buttons act on the selected leaf, mirroring the double-/right-click shortcuts.
        buttons = QHBoxLayout()
        self.unit1_button = QPushButton("Load as Unit 1")
        self.unit1_button.clicked.connect(lambda: self._load_selected(slot=1))
        self.unit2_button = QPushButton("Load as Unit 2")
        self.unit2_button.clicked.connect(lambda: self._load_selected(slot=2))
        buttons.addWidget(self.unit1_button)
        buttons.addWidget(self.unit2_button)
        layout.addLayout(buttons)

        self.rebuild()
        self._update_buttons()

    def _make_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setIndentation(tree.indentation() // 2)  # tighter nesting
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.itemDoubleClicked.connect(self._on_double_click)
        tree.customContextMenuRequested.connect(lambda pos, t=tree: self._on_right_click(t, pos))
        tree.currentItemChanged.connect(self._update_buttons)
        return tree

    def rebuild(self) -> None:
        """(Re)build both trees from the main window's current game, leaving every group
        collapsed. The faction view resets to lazy: it rebuilds when its tab is next
        shown, so a reload never pays for graphs nobody is looking at."""
        self.tree.clear()
        self._faction_nodes = None
        self._faction_loading = False
        self.faction_tree_widget.clear()
        game = self._browser.game
        if game is None:
            for tree in (self.tree, self.faction_tree_widget):
                self._placeholder(tree, "Load a source in the main window first.")
            return

        groups = group_objects(game)
        for side in _ordered_keys(groups):
            side_item = QTreeWidgetItem([side])
            self.tree.addTopLevelItem(side_item)
            for sorting in _ordered_keys(groups[side]):
                leaves = groups[side][sorting]
                sort_item = QTreeWidgetItem([f"{sorting}  ({len(leaves)})"])
                side_item.addChild(sort_item)
                for name, label in leaves:
                    leaf = QTreeWidgetItem([label])
                    leaf.setData(0, Qt.ItemDataRole.UserRole, name)
                    leaf.setToolTip(0, name)
                    sort_item.addChild(leaf)
        self.tree.collapseAll()

        self._placeholder(self.faction_tree_widget, "Open this tab to build the faction view.")
        self._ensure_faction_tree()

    @staticmethod
    def _placeholder(tree: QTreeWidget, text: str) -> None:
        item = QTreeWidgetItem([text])
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        tree.addTopLevelItem(item)

    def _on_tab_changed(self, _index: int) -> None:
        self._ensure_faction_tree()
        self._update_buttons()

    def _ensure_faction_tree(self) -> None:
        """Fill the faction view from the main window's shared graph cache the first time
        the By-faction tab is shown for the current game (built on a worker when cold)."""
        if self.tabs.currentWidget() is not self.faction_tree_widget:
            return
        if self._faction_nodes is not None or self._faction_loading:
            return
        if self._browser.game is None:
            return
        self._faction_loading = True
        self.faction_tree_widget.clear()
        self._placeholder(self.faction_tree_widget, "Building the faction view…")
        self._browser.ensure_faction_graphs(
            lambda graphs: self._on_faction_tree(faction_tree(graphs)),
            self._on_faction_tree_failed,
        )

    def focus_faction(self, display: str) -> None:
        """Open the By-faction tab on the faction labeled `display`, expanding its node -
        deferred until the tree is built when the cache is still cold."""
        self._pending_focus = display
        self.tabs.setCurrentWidget(self.faction_tree_widget)  # triggers the lazy build
        self._apply_pending_focus()

    def _apply_pending_focus(self) -> None:
        if self._pending_focus is None or self._faction_nodes is None:
            return
        target = self._pending_focus.casefold()
        self._pending_focus = None
        for index in range(self.faction_tree_widget.topLevelItemCount()):
            item = self.faction_tree_widget.topLevelItem(index)
            if item.text(0).casefold().startswith(target):
                item.setExpanded(True)
                self.faction_tree_widget.setCurrentItem(item)
                self.faction_tree_widget.scrollToItem(item)
                break

    def _on_faction_tree(self, nodes: list[dict]) -> None:
        self._faction_loading = False
        self._faction_nodes = nodes
        self.faction_tree_widget.clear()
        if not nodes:
            self._placeholder(self.faction_tree_widget, "No playable factions in this data.")
            return
        for node in nodes:
            self.faction_tree_widget.addTopLevelItem(self._make_item(node))
        self.faction_tree_widget.collapseAll()
        self._apply_pending_focus()

    def _on_faction_tree_failed(self, message: str) -> None:
        self._faction_loading = False
        self.faction_tree_widget.clear()
        self._placeholder(self.faction_tree_widget, f"Faction view failed - {message}")

    def _make_item(self, node: dict) -> QTreeWidgetItem:
        item = QTreeWidgetItem([node["label"]])
        if node["object"]:
            item.setData(0, Qt.ItemDataRole.UserRole, node["object"])
        if node["tooltip"]:
            item.setToolTip(0, node["tooltip"])
        for child in node["children"]:
            item.addChild(self._make_item(child))
        return item

    def _active_tree(self) -> QTreeWidget:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, QTreeWidget) else self.tree

    @staticmethod
    def _object_name(item: QTreeWidgetItem | None) -> str | None:
        """The raw object name stored on a leaf, or None for a group header."""
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        """Load a double-clicked object into the primary slot (group headers toggle)."""
        name = self._object_name(item)
        if name:
            self._browser.show_object(name)

    def _on_right_click(self, tree: QTreeWidget, pos) -> None:
        """Load the right-clicked object into the comparison slot."""
        name = self._object_name(tree.itemAt(pos))
        if name:
            self._browser.compare_object(name)

    def _update_buttons(self, *_args) -> None:
        """Enable the load buttons only when a selectable object (a leaf) is selected."""
        enabled = self._object_name(self._active_tree().currentItem()) is not None
        self.unit1_button.setEnabled(enabled)
        self.unit2_button.setEnabled(enabled)

    def _load_selected(self, *, slot: int) -> None:
        """Load the currently selected leaf into Unit 1 or Unit 2 (no-op on a group)."""
        name = self._object_name(self._active_tree().currentItem())
        if not name:
            return
        if slot == 1:
            self._browser.show_object(name)
        else:
            self._browser.compare_object(name)
