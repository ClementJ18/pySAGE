"""Qt stylesheet themes shared by the SAGE front ends: one template filled from a
dark and a light colour palette."""

from string import Template

_THEME = Template("""
QWidget { background: $bg; color: $text; font-size: 14px; }
/* Labels/checkboxes are transparent so they show the card behind them, not the
   window background painted by the QWidget rule above. */
QLabel, QCheckBox { background: transparent; }
QLineEdit {
    background: $surface; border: 1px solid $border; border-radius: 6px;
    padding: 8px 10px; font-size: 15px;
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

DARK_STYLE = _THEME.substitute(DARK)
LIGHT_STYLE = _THEME.substitute(LIGHT)
