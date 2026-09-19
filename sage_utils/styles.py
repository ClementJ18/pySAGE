"""Qt stylesheet themes shared by the SAGE front ends: one template filled from a
dark and a light colour palette."""

import sys
from pathlib import Path
from string import Template

# Resolves under `sys._MEIPASS` in a PyInstaller build, like the other bundled assets.
_ASSETS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"

_THEME = Template("""
QWidget { background: $bg; color: $text; font-size: 14px; }
/* Labels/checkboxes are transparent so they show the card behind them, not the
   window background painted by the QWidget rule above. */
QLabel, QCheckBox, QRadioButton { background: transparent; }
/* The indicators are drawn here rather than by the platform style: under a stylesheet the native
   checked box or radio button loses its outline and is hard to tell from an unchecked one. */
QCheckBox::indicator {
    width: 14px; height: 14px; border: 1px solid $muted; border-radius: 4px;
    background: $surface;
}
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }
QCheckBox::indicator:disabled { background: $control; border-color: $border; }
QCheckBox::indicator:checked:disabled { background: $primaryDisabled; border-color: $border; }
/* A radio button is a ring; checked, it gets the accent ring and an accent dot inside it. */
QRadioButton::indicator {
    width: 14px; height: 14px; border: 1px solid $muted; border-radius: 8px;
    background: $surface;
}
QRadioButton::indicator:hover { border-color: $accent; }
QRadioButton::indicator:checked {
    border: 2px solid $accent; width: 12px; height: 12px;
    background: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5,
        stop: 0 $accent, stop: 0.55 $accent, stop: 0.6 $surface, stop: 1 $surface);
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
    background: $surface; border: 1px solid $border; border-radius: 6px;
    padding: 8px 10px; font-size: 15px;
    selection-background-color: $accent; selection-color: $accentInk;
}
QLineEdit:focus { border-color: $accent; }
QScrollArea { border: none; }
QFrame#card {
    background: $surface; border: 1px solid $border; border-radius: 8px;
}
QLabel#h2 { color: $muted; font-size: 11px; font-weight: 600; }
QLabel#objName { font-size: 20px; font-weight: 600; }
QLabel#objType, QLabel#muted { color: $muted; font-size: 12px; }
QLabel#conditions { color: $accent; font-size: 12px; }
QLabel#colhead { color: $muted; font-size: 11px; font-weight: 600; }
QLabel#scalarPct { color: $accent; }
QLabel#better { color: $better; }
QLabel#worse { color: $worse; }
QComboBox {
    background: $control; border: 1px solid $border; border-radius: 6px;
    padding: 5px 8px;
}
QComboBox:focus { border-color: $accent; }
/* An editable combo embeds its own line edit; name it too rather than rely on inheritance. */
QComboBox QLineEdit {
    selection-background-color: $accent; selection-color: $accentInk;
}
QComboBox QAbstractItemView {
    background: $surface; border: 1px solid $border;
    selection-background-color: $accent; selection-color: $accentInk;
}
QPushButton {
    background: $control; border: 1px solid $border; border-radius: 6px;
    padding: 6px 12px;
}
QPushButton:hover { border-color: $accent; }
QPushButton:disabled { color: $disabledText; }
QPushButton#primary { background: $primary; color: $primaryInk; border: none; font-weight: 600; }
QPushButton#primary:disabled { background: $primaryDisabled; color: $muted; }
QPushButton#closePanel {
    background: transparent; border: none; color: $muted; font-size: 16px; padding: 0;
}
QPushButton#closePanel:hover { color: $worse; }
QPushButton#sectionHeader {
    background: transparent; border: none; padding: 2px 0;
    text-align: left; color: $muted; font-size: 11px; font-weight: 600;
}
QPushButton#sectionHeader:hover { color: $accent; }
QListWidget {
    background: $surface; border: 1px solid $border; border-radius: 6px;
    padding: 4px;
}
QListWidget::item { padding: 4px 6px; border-radius: 4px; }
QListWidget::item:selected { background: $selection; color: $text; }
QTreeWidget {
    background: $surface; border: 1px solid $border; border-radius: 6px;
    padding: 4px;
}
/* Highlight the whole selected row (branch included), not just a narrow bar. */
QTreeWidget::item { padding: 4px 6px; }
QTreeWidget::item:selected,
QTreeWidget::branch:selected { background: $accent; color: $accentInk; }
QTableWidget {
    background: $surface; border: 1px solid $border; border-radius: 6px;
    gridline-color: $border;
}
QTableWidget::item:selected { background: $selection; color: $text; }
/* Header sections default to Qt's native palette (white bar in dark mode) unless themed here. */
QHeaderView::section {
    background: $control; color: $muted;
    border: none; border-bottom: 1px solid $border; border-right: 1px solid $border;
    padding: 6px 8px; font-weight: 600;
}
QTableCornerButton::section { background: $control; border: none; }
/* Tabs default to Qt's native palette (white bars in dark mode) unless themed here. */
QTabWidget::pane {
    background: $surface; border: 1px solid $border; border-radius: 8px; top: -1px;
}
QTabBar::tab {
    background: $control; color: $muted;
    border: 1px solid $border; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
    padding: 6px 14px; margin-right: 2px;
}
QTabBar::tab:selected { background: $surface; color: $text; }
QTabBar::tab:hover { color: $accent; }
/* Dock title bars: without these the float and close buttons keep the platform's black glyphs,
   which vanish on the dark theme. */
QDockWidget {
    titlebar-close-icon: url("$dockClose");
    titlebar-normal-icon: url("$dockFloat");
}
QDockWidget::title {
    background: $control; color: $text;
    padding: 5px 6px; border-bottom: 1px solid $border; text-align: left;
}
QDockWidget::close-button, QDockWidget::float-button {
    background: transparent; border: none; border-radius: 4px; padding: 1px;
}
QDockWidget::close-button:hover, QDockWidget::float-button:hover { background: $border; }
QDockWidget::close-button:pressed, QDockWidget::float-button:pressed { background: $muted; }
/* Tool buttons: a checked one (the active tool, a lock) is marked here, because the platform
   style's sunken look does not show under a stylesheet on the dark theme. */
QToolBar { background: $bg; border: none; spacing: 2px; padding: 2px; }
QToolButton {
    background: transparent; border: 1px solid transparent; border-radius: 5px;
    padding: 3px 7px;
}
QToolButton:hover { background: $control; border-color: $border; }
QToolButton:checked { background: $selection; border-color: $accent; color: $text; }
QToolButton:pressed { background: $border; }
QToolButton:disabled { color: $disabledText; }
/* Menus are drawn by the stylesheet so a checkable item (a View toggle, an exclusive choice) gets
   a full-size box like QCheckBox's: left to the platform style it is squeezed into a sliver.
   Styling the items also takes over their hover colour, so that is set here too. */
QMenu { background: $surface; border: 1px solid $border; padding: 4px; }
QMenu::item { padding: 5px 28px 5px 32px; border-radius: 4px; background: transparent; }
QMenu::item:selected { background: $selection; color: $text; }
QMenu::item:disabled { color: $disabledText; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }
QMenu::indicator {
    width: 14px; height: 14px; left: 9px;
    border: 1px solid $muted; border-radius: 4px; background: $surface;
}
QMenu::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }
QMenu::indicator:disabled { border-color: $border; background: $control; }
""")

DARK = {
    "bg": "#1d1f23",
    "text": "#e6e6e6",
    "surface": "#26292e",
    "border": "#3a3f47",
    "accent": "#d8a657",
    "accentInk": "#1d1f23",
    "primary": "#d8a657",
    "primaryInk": "#1d1f23",
    "muted": "#9aa0a8",
    "control": "#2f333a",
    "better": "#a9d977",
    "worse": "#e06c75",
    "disabledText": "#6b7079",
    "primaryDisabled": "#5a5237",
    "selection": "rgba(216, 166, 87, 0.22)",
}
LIGHT = {
    "bg": "#f3f4f6",
    "text": "#1d2024",
    "surface": "#ffffff",
    "border": "#d4d8de",
    "accent": "#c08a2e",
    "accentInk": "#1d2024",
    "primary": "#b07a1f",
    "primaryInk": "#ffffff",
    "muted": "#6b7079",
    "control": "#eceef1",
    "better": "#2f8f3f",
    "worse": "#c0392b",
    "disabledText": "#aeb3ba",
    "primaryDisabled": "#e7d6b3",
    "selection": "rgba(192, 138, 46, 0.25)",
}

# The check mark is dark ink, which reads on the accent fill of both themes.
_CHECK = (_ASSETS / "check.svg").as_posix()


def _dock_icons(theme: str) -> dict[str, str]:
    """The dock title bar glyphs drawn in the theme's text colour."""
    return {
        "dockClose": (_ASSETS / f"dock_close_{theme}.svg").as_posix(),
        "dockFloat": (_ASSETS / f"dock_float_{theme}.svg").as_posix(),
    }


DARK_STYLE = _THEME.substitute(DARK, check=_CHECK, **_dock_icons("dark"))
LIGHT_STYLE = _THEME.substitute(LIGHT, check=_CHECK, **_dock_icons("light"))
