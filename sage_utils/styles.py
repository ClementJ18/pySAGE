"""Qt stylesheet themes shared by the SAGE front ends: one template filled from a
dark and a light colour palette."""

import sys
from pathlib import Path
from string import Template

__all__ = ["DARK", "DARK_STYLE", "LIGHT", "LIGHT_STYLE", "palette"]

# Resolves under `sys._MEIPASS` in a PyInstaller build, like the other bundled assets.
_ASSETS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"

# Squared and ruled: no rounded corners anywhere, a rule under every card heading, a double rule
# under table headers and dock titles, and tabs and the active tool marked by an underline
# rather than a box.
_THEME = Template("""
QWidget { background: $bg; color: $text; font-size: 14px; }
/* Labels/checkboxes are transparent so they show the card behind them, not the
   window background painted by the QWidget rule above. */
QLabel, QCheckBox, QRadioButton { background: transparent; }
/* The indicators are drawn here rather than by the platform style: under a stylesheet the native
   checked box or radio button loses its outline and is hard to tell from an unchecked one. */
QCheckBox::indicator {
    width: 14px; height: 14px; border: 1px solid $muted; background: $surface;
}
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }
QCheckBox::indicator:disabled { background: $control; border-color: $border; }
QCheckBox::indicator:checked:disabled { background: $primaryDisabled; border-color: $border; }
/* A radio button is a ring; checked, it gets the accent ring and a starlight dot inside it. */
QRadioButton::indicator {
    width: 14px; height: 14px; border: 1px solid $muted; border-radius: 8px;
    background: $surface;
}
QRadioButton::indicator:hover { border-color: $accent; }
QRadioButton::indicator:checked {
    border: 2px solid $accent; width: 12px; height: 12px;
    background: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5,
        stop: 0 $radioDot, stop: 0.55 $radioDot, stop: 0.6 $surface, stop: 1 $surface);
}
QRadioButton::indicator:disabled { background: $control; border-color: $border; }
QRadioButton::indicator:checked:disabled {
    border-color: $border;
    background: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5,
        stop: 0 $primaryDisabled, stop: 0.55 $primaryDisabled,
        stop: 0.6 $control, stop: 1 $control);
}
/* The selection colours are set explicitly: without them Qt falls back to the desktop
   palette for highlighted text, which on a light theme renders white on white and makes a
   selected value unreadable. An editable QComboBox draws through this same rule. */
QLineEdit {
    background: $surface; border: 1px solid $border;
    padding: 8px 10px; font-size: 15px;
    selection-background-color: $accent; selection-color: $accentInk;
}
QLineEdit:focus { border-color: $focus; }
QScrollArea { border: none; }
QFrame#card { background: $surface; border: 1px solid $cardEdge; }
QLabel#h2 {
    color: $rubric; font-family: $headFont; font-size: 12px; font-weight: 600;
    border-bottom: 1px solid $border; padding-bottom: 4px;
}
QLabel#objName { font-family: $headFont; font-size: 22px; font-weight: 600; }
QLabel#objType, QLabel#muted { color: $muted; font-size: 12px; }
QLabel#conditions { color: $rubric; font-size: 12px; }
QLabel#colhead { color: $muted; font-size: 11px; font-weight: 600; }
QLabel#scalarPct { color: $rubric; }
QLabel#better { color: $better; }
QLabel#worse { color: $worse; }
QComboBox { background: $control; border: 1px solid $border; padding: 5px 8px; }
QComboBox:focus { border-color: $focus; }
/* The drop-down is drawn flat inside the box, its arrow the tree's open arrow. */
QComboBox::drop-down { border: none; background: transparent; width: 28px; }
QComboBox::down-arrow { image: url("$branchOpen"); width: 14px; height: 14px; }
/* An editable combo embeds its own line edit; name it too rather than rely on inheritance. */
QComboBox QLineEdit {
    selection-background-color: $accent; selection-color: $accentInk;
}
QComboBox QAbstractItemView {
    background: $surface; border: 1px solid $border;
    selection-background-color: $accent; selection-color: $accentInk;
}
QPushButton { background: $control; border: 1px solid $border; padding: 6px 12px; }
QPushButton:hover { border-color: $text; }
QPushButton:disabled { color: $disabledText; }
QPushButton#primary {
    background: $primary; color: $primaryInk; border: 1px solid $primaryEdge; font-weight: 600;
}
QPushButton#primary:disabled { background: $primaryDisabled; color: $muted; border: none; }
QPushButton#closePanel {
    background: transparent; border: none; color: $muted; font-size: 16px; padding: 0;
}
QPushButton#closePanel:hover { color: $worse; }
QPushButton#sectionHeader {
    background: transparent; border: none; padding: 2px 0;
    text-align: left; color: $rubric; font-family: $headFont; font-size: 12px; font-weight: 600;
}
QPushButton#sectionHeader:hover { color: $accent; }
QListWidget { background: $surface; border: 1px solid $border; padding: 4px; }
QListWidget::item { padding: 4px 6px; }
QListWidget::item:selected { background: $selection; color: $text; }
QTreeWidget { background: $surface; border: 1px solid $border; padding: 4px; }
/* Highlight the whole selected row (branch included), not just a narrow bar. */
QTreeWidget::item { padding: 4px 6px; }
QTreeWidget::item:selected,
QTreeWidget::branch:selected { background: $accent; color: $accentInk; font-weight: 600; }
/* Styling ::branch drops the platform's expand arrows, and Qt's fallback ones vanish into the
   accent fill of a selected row, so the arrows are drawn here: muted, or in the accent's ink
   when selected. */
QTreeWidget::branch:has-children:closed { image: url("$branchClosed"); }
QTreeWidget::branch:has-children:open { image: url("$branchOpen"); }
QTreeWidget::branch:has-children:closed:selected { image: url("$branchClosedSelected"); }
QTreeWidget::branch:has-children:open:selected { image: url("$branchOpenSelected"); }
/* Tables (QTableWidget and plain QTableViews alike) keep their gridlines, so every cell reads
   against its row and column. The table's own selection colours are set too: without them a
   selected row is painted in the platform highlight under the item rule's translucent wash. */
QTableView {
    background: $surface; border: 1px solid $border;
    gridline-color: $border;
    selection-background-color: $selection; selection-color: $text;
}
QTableView::item:selected { background: $selection; color: $text; }
/* Header sections default to Qt's native palette (white bar in dark mode) unless themed here.
   A double rule sets the headers off from the data: under the column heads, and to the right of
   the row heads. Between sections run the same hairlines as the gridlines, so a head lines up
   with its row or column. */
QHeaderView { background: $surface; }
QHeaderView::section {
    background: $surface; color: $muted; border: none;
    padding: 6px 8px; font-family: $headFont; font-weight: 600;
}
QHeaderView::section:horizontal {
    border-bottom: 3px double $accent; border-right: 1px solid $border;
}
QHeaderView::section:vertical {
    border-bottom: 1px solid $border; border-right: 3px double $accent;
}
QTableCornerButton::section {
    background: $surface; border: none;
    border-bottom: 3px double $accent; border-right: 3px double $accent;
}
/* Tabs default to Qt's native palette (white bars in dark mode) unless themed here. They are
   underlined titles over a pane that is only a rule. */
QTabWidget::pane { background: $surface; border: none; border-top: 1px solid $border; top: -1px; }
QTabBar::tab {
    background: transparent; color: $muted;
    border: none; border-bottom: 2px solid transparent;
    padding: 7px 14px; margin-right: 6px; font-family: $headFont; font-size: 15px;
}
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $rubric; }
QTabBar::tab:hover { color: $accent; }
/* Dock title bars: without these the float and close buttons keep the platform's black glyphs,
   which vanish on the dark theme. */
QDockWidget {
    titlebar-close-icon: url("$dockClose");
    titlebar-normal-icon: url("$dockFloat");
}
QDockWidget::title {
    background: $bg; color: $text; font-family: $headFont;
    padding: 6px 8px; border-bottom: 3px double $border; text-align: left;
}
QDockWidget::close-button, QDockWidget::float-button {
    background: transparent; border: none; padding: 1px;
}
QDockWidget::close-button:hover, QDockWidget::float-button:hover { background: $border; }
QDockWidget::close-button:pressed, QDockWidget::float-button:pressed { background: $muted; }
/* Tool buttons: a checked one (the active tool, a lock) is underlined here, because the platform
   style's sunken look does not show under a stylesheet on the dark theme. */
QToolBar { background: $bg; border: none; spacing: 2px; padding: 2px; }
QToolButton {
    background: transparent; border: 1px solid transparent; padding: 3px 7px;
}
QToolButton:hover { background: $control; border-color: $border; }
QToolButton:checked {
    background: transparent; border: none; border-bottom: 2px solid $rubric; color: $text;
}
QToolButton:pressed { background: $border; }
QToolButton:disabled { color: $disabledText; }
QMenuBar { background: $bg; }
QMenuBar::item { padding: 4px 10px; background: transparent; }
QMenuBar::item:selected { background: $selection; }
/* Menus are drawn by the stylesheet so a checkable item (a View toggle, an exclusive choice) gets
   a full-size box like QCheckBox's: left to the platform style it is squeezed into a sliver.
   Styling the items also takes over their hover colour, so that is set here too. */
QMenu { background: $surface; border: 1px solid $text; padding: 4px; }
QMenu::item { padding: 5px 28px 5px 32px; background: transparent; }
QMenu::item:selected { background: $selection; color: $text; }
QMenu::item:disabled { color: $disabledText; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }
QMenu::indicator {
    width: 14px; height: 14px; left: 9px; border: 1px solid $muted; background: $surface;
}
QMenu::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }
QMenu::indicator:disabled { border-color: $border; background: $control; }
""")

# Ithildin: the moon-letters on the Doors of Durin, thin silver-blue lines on night stone. The
# dark palette is `webtheme.STEEL`, so the desktop apps match the HTML pages the tools generate;
# the light one is mithril grey with lapis ink. `rubric` colours headings, emphasis and the
# underline of a selected tab or tool, `focus` the ring on a focused field, and `primary` is a
# gradient. `canvas` is behind a map or model view, a step darker than `bg` so the toolbars and
# docks around it read as separate.
DARK = {
    "bg": "#0d1219",
    "canvas": "#05080c",
    "text": "#dce5f0",
    "surface": "#161e28",
    "border": "#33445a",
    "cardEdge": "#2a3a4e",
    "accent": "#7ea9d6",
    "accentInk": "#0d1219",
    "rubric": "#9fc0e4",
    "focus": "#cde3fb",
    "radioDot": "#cde3fb",
    "primary": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #9cc0e6, stop:1 #7ea9d6)",
    "primaryEdge": "#9cc0e6",
    "primaryInk": "#0d1219",
    "muted": "#8393a6",
    "control": "#1e2835",
    "better": "#63bb95",
    "worse": "#e2705e",
    "disabledText": "#55657a",
    "primaryDisabled": "#2b3d52",
    "selection": "rgba(126, 169, 214, 0.18)",
}
LIGHT = {
    "bg": "#e8edf3",
    "canvas": "#d3dbe5",
    "text": "#18222e",
    "surface": "#f8fafc",
    "border": "#c6d1de",
    "cardEdge": "#d3dce7",
    "accent": "#2f5f98",
    "accentInk": "#f8fafc",
    "rubric": "#2f5f98",
    "focus": "#2f5f98",
    "radioDot": "#2f5f98",
    "primary": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3a6dab, stop:1 #2f5f98)",
    "primaryEdge": "#2a5589",
    "primaryInk": "#ffffff",
    "muted": "#566577",
    "control": "#edf1f6",
    "better": "#24795a",
    "worse": "#b8432f",
    "disabledText": "#a3afbd",
    "primaryDisabled": "#c4d3e6",
    "selection": "rgba(47, 95, 152, 0.13)",
}


def palette(dark: bool) -> dict[str, str]:
    """The dark or light theme's colours, for a widget that paints its own rather than taking
    them from the stylesheet (a map view's background, an OpenGL clear colour)."""
    return DARK if dark else LIGHT


# Titles, section heads, tabs, table headers and dock titles; everything else keeps the platform
# font, because a stylesheet font-family would override a font a widget sets in code (a
# monospace editor).
_HEAD_FONT = "Constantia, Georgia, serif"


def _glyphs(theme: str) -> dict[str, str]:
    """The stylesheet's glyphs in the theme's colours: the dock buttons in its text colour, the
    tree arrows muted, and the check mark and a selected row's arrows in the accent's ink."""
    names = {
        "check": "check",
        "dockClose": "dock_close",
        "dockFloat": "dock_float",
        "branchClosed": "branch_closed",
        "branchOpen": "branch_open",
        "branchClosedSelected": "branch_closed_selected",
        "branchOpenSelected": "branch_open_selected",
    }
    return {key: (_ASSETS / f"{name}_{theme}.svg").as_posix() for key, name in names.items()}


DARK_STYLE = _THEME.substitute(DARK, headFont=_HEAD_FONT, **_glyphs("dark"))
LIGHT_STYLE = _THEME.substitute(LIGHT, headFont=_HEAD_FONT, **_glyphs("light"))
