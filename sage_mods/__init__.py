"""Patch- and mod-specific overlays over the engine-generic SAGE packages.

Each subpackage holds the names, paths, and conventions of one BFME mod or patch
(`sage_mods.edain` for the Edain mod). The generic core (`sage_utils`, `sage_ini`,
`sage_map`, ...) stays engine-neutral; anything that hard-codes a mod's flag names,
folder layout, or CommandButton conventions lives here.
"""
