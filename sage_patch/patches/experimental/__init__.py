"""Patches that are built and verify but have not been played enough to trust.

Expect what `EXPERIMENTAL_WARNING` says: crashes, desyncs and save/replay incompatibility are all
possible. A patch here sets `Patch.experimental`, one outside does not, and a test checks both. To
graduate a patch once it has been played: move the module up into `sage_patch.patches`, drop the
attribute, and fix its import in `sage_patch.registry`.
"""
