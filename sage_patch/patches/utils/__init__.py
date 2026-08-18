"""Shared machinery for the patches in :mod:`sage_patch.patches`.

Nothing here is a :class:`~sage_patch.patcher.Patch`. These are the modules more than one patch
needs and none of them owns: the three global name tables and the primitives every table
extension shares, the INI field-parse tables that give a block a new keyword, the parser that
turns a one-token keyword into a list of them, the `KindOf` mask, and the null function pointer
that lets two income patches agree on a multiplier without either reading the other's bytes.

The rule that puts a module here rather than beside its caller is the composition contract in
:mod:`sage_patch.patcher`: a shared resource - a table, a count, an income factor - has exactly
one owner, and that owner reads the **live** image rather than stock constants, so two patches
touching the same resource compose in either order.
"""
