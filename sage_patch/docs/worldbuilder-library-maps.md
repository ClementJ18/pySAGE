# Library maps, inherited scripts and what overrides them

How a player's library maps reach its script tree, why a row reads `(imported)` or `(overridden)`,
and what it takes to override an inherited script. Recovered statically from the stock RotWK
`Worldbuilder.exe` (ImageBase `0x400000`) with `pefile` + `capstone`, and checked against the
library maps Edain ships (`Libraries\ki gondor\ki gondor.map` and the maps it chains to).

**This targets `Worldbuilder.exe`.** The classes it names (`ScriptList`, `ScriptSetBase`) are
GameEngine code shared with `game.dat`, whose copies of these strings the release build drops.
`sage_worldbuilder/libraries.py` is the reimplementation.

## 1. Where the scripts come from

Each player carries a list of library maps in the map's `LibraryMapLists` chunk, stored as
`Libraries\<name>\<name>.map`. `SidesList::linkLibraryMaps` (`0x00A88720`, `ret 0x18`) walks that
list **from the last entry to the first**. For each one:

1. `LibraryMapCache::getSides(name)` (`0x00A8B920`) reads the library map, cached per name. It
   warns `Library map "%s" has %d player(s). Discarding all but the first two players.` when the
   library has more than two - Edain's have twenty, so this fires for all of them.
2. `getSideInfo(1)` - **side 1 only**, whatever the map's own player list says. That is where a
   library keeps its scripts; side 0 is left empty.
3. It recurses on that side's *own* library list first (`+0x54` of the side info), so the chains
   are followed to the end before the library that named them contributes.
4. `ScriptList::mergeUnder` (`0x00AA61E0`) adds the library's items on top of what the walk has
   collected so far: it swaps the two lists (`0x00AA76F0`), marks what it now holds inherited
   (`0x00AA6890`, the per-container loop at `0x00AB3FA0`), and adds the other list's items over
   that. So a library added later wins, and the walk being backwards, **the first library in the
   player's list wins** - over the ones after it, and over the chains it opens.

Once every library has been collected, `0x00A88310` runs the same `mergeUnder` one last time with
the player's own list as the receiver: the collected library items go in, are marked inherited,
and the player's own items are added over them.

Teams follow in the same function: a library team is copied with `teamLibraryMapName` set to the
library it came from, which is what makes the Teams dialog's Library / Imported / Overridden
columns, and what makes `Renaming of imported teams is not allowed`.

## 2. The name slots

`ScriptList` holds two name-keyed sets, `ScriptSetBase<ScriptGroup>` at `+0x0C` and
`ScriptSetBase<Script>` at `+0x2C`, so a group and a script may share a name without clashing.
Each entry is `0x14` bytes:

| offset | field |
|---|---|
| `+0x00` / `+0x04` | next / previous entry id (the free and used chains) |
| `+0x08` | the name, the key the set is indexed by |
| `+0x0C` | `inherited`: 1 when the definition holding the name came from a library |
| `+0x0E` | `version`: bumped every time the name is (re)allocated |
| `+0x10` | the definition chain (`firstElementNode`) |

A reference to a script or group (`{ list, entryId, version }`) carries the version it was made
with, which is how the two display predicates work:

| function | address | meaning |
|---|---|---|
| `ScriptList::isCurrent` | `0x00AA6040` (groups: `0x00AA5C50`) | `entry.version == ref.version` - this reference is the definition that holds the name |
| `ScriptList::isInherited` | `0x00AA60A0` (groups: `0x00AA5CB0`) | `!isCurrent(ref) \|\| entry.inherited` |

`TreeScriptItem::makeText` (`0x005CC390`; groups `0x005C9260`) appends ` (overridden)` when
`isCurrent` is false and ` (imported)` when it is true and the entry is inherited, and
`updateIcon` (`0x005CB8A0`) picks the icon the same way: `+2` subroutine, `+4` inactive, `+6`
imported, `+12` overridden.

## 3. What overriding is

`ScriptSetBase::allocateEntry` (groups `0x00AB4630`, scripts `0x00AB5FB0`) is the whole rule:

- If the name is free, it takes a fresh entry, sets the key and `version = 0`.
- If the name is taken, it is allowed **only when that entry's `inherited` byte is set**;
  otherwise it fails with `Attempting to override non-overridable script "%s".` and returns -1.
  A name the map itself defines cannot be redefined.
- Either way it ends with `entry.version += 1; entry.inherited = 0`, so the new definition holds
  the name and is the map's.

Since §1 puts the libraries in first and marks them inherited, and the player's own items are
allocated over them, **the map's own script always wins over a library's of the same name**, and
among libraries the first one in the player's list wins. `SidesList::discardOverriddenScriptsAndTeams`
(`0x00A880A0`, per-list `0x00AA6910`) then drops every reference that is no longer current.

## 4. Overriding from the editor

There is no Override command in the Scripts dialog. `doEdit` and `doDelete` refuse an inherited
item outright (`You cannot edit an inherited script`, `Cannot delete scripts inherited from library
maps`), and so do drag-and-drop (`ScriptList::takeScripts`) - an imported row is read-only.

The one route is **Copy**. `duplicate` (`0x005C06A0`) asks whether the name is free or held only
by an inherited entry (`0x005C0870`, which returns the entry's `inherited` byte, or true when the
name is unknown):

- **held only by a library** - the copy **keeps the name**, and by §3 it takes that name for the
  map. Copy is the override.
- **held by the map** - the copy is renamed by the `__N` generator first, so a map-owned script is
  never silently replaced.

`sage_worldbuilder` exposes that as its own Override button (`sage_worldbuilder.libraries.override`)
rather than through Copy, and rebuilds the path as well: a library group the map does not have is
recreated to hold the copy, which by §3 takes that group's name too.
