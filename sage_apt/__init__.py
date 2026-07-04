"""Tooling for SAGE `.apt` UI movies (the engine's Flash-derived menu/HUD format).

An APT ships as a binary pair — `.apt` (structure, characters, ActionScript bytecode)
plus `.const` (constant pool). `sage_apt.aptfile` converts the pair to an editable XML
form and compiles the XML back; `sage_apt.viewer` renders the XML to a self-contained
HTML/SVG page; `sage_apt.editor` serves a browser editor over it. The `sage-apt` CLI
fronts all three.
"""

from sage_apt.aptfile import AptError, apt_to_xml, xml_to_apt
from sage_apt.viewer import render_viewer_html, write_viewer_html

__all__ = [
    "AptError",
    "apt_to_xml",
    "render_viewer_html",
    "write_viewer_html",
    "xml_to_apt",
]
