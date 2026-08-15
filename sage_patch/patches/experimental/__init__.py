"""Patches that are built but **not settled**: unstable and largely untested.

Everything in here is finished code, not a sketch. The reverse engineering is written up in
`../../docs/`, the assembly is there, the patch applies to a clean `game.dat` and `sage-patch
verify` says the result carries it. What is missing is the part no static work can supply -
somebody playing the patched binary long enough, and across enough of what the patch touches, to
find out whether it does what the disassembly says it does. Some of these have had a session or
two; `hero-mana` has a known open defect written into its own doc. None has had enough.

That gap is not a formality. A patch is a reading of the machine code, and the tests are written
from the same reading, so a wrong reading passes both. Only the running game disagrees.

So the honest expectation for anything in this package is
:data:`~sage_patch.patcher.EXPERIMENTAL_WARNING`: crashes, desyncs and save/replay incompatibility
are all live possibilities, and the unpatched binary is worth keeping.

**Membership is the same fact as** :attr:`~sage_patch.patcher.Patch.experimental`. A patch here sets
that attribute, a patch outside here does not, and `TestExperimentalPatchesAreDeclared` fails on
either mismatch - because the directory is what a reader sees and the attribute is what `sage-patch
list` and `sage-patch apply` say to somebody who never opens the source, and a warning that depends
on which of the two you happened to look at is not a warning.

**Graduating a patch is a move, not an edit**: play it, then move the module up into
:mod:`sage_patch.patches`, drop the attribute, and fix the import in :mod:`sage_patch.registry`.
Nothing else about the patch changes, which is the point - the flag tracks what has been
*observed*, not what has been written.
"""
