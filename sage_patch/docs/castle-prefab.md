# Script and CommandButton-selected castle prefabs

`castle-prefab` targets RotWK 2.01 `game.dat` (2.01.2614.37001); `castle-prefab-wb`
targets its independent `Worldbuilder.exe`. Both are experimental: binary application,
verification and emulated cave execution are checked, but in-game acceptance, multiplayer
and replay tests are still required. No CommandButton or control-bar change is part of this patch.

## Script syntax and authoring

Apply `castle-prefab` to the game and, when authoring map actions in the retail editor,
`castle-prefab-wb` to WorldBuilder. The editor offers both actions under Base, beside the retail unpack actions.
Install the same game patch and mod data on every multiplayer peer.

```lua
ExecuteAction("NAMED_BASE_UNPACK_PREFAB", "CastleFlag", "CastleReference", "GondorCastle")
ExecuteAction("NAMED_BASE_UNPACK_PREFAB_FREE", "CastleFlag", "CastleReference", "GondorCastle")
```

The registered arguments are UNIT_NAME (14), NAMED_REFERENCE (54), TEXT_STRING (10).
For custom ScriptEditor catalogues use `types: [14, 54, 10]` and a third type name of
`TEXT_STRING`. Type 2 is SCRIPT_NAME in the engine, although some external catalogues label
it STRING. The runtime also accepts type 2 for the third argument because it uses the same
AsciiString field; existing maps authored with `[14, 54, 2]` do not need rewriting for this
compatibility change. Other parameter kinds are rejected before stock unpack is called.
The second parameter has precisely the stock reference-name meaning; an empty string leaves
reference registration to the stock helper. The third is the **registered castle prefab name**,
not a faction, Object/ThingTemplate, filesystem path or arbitrary `.bse` filename. The example
name is illustrative: use a prefab actually registered and available in your mod/map.
The engine still performs its ordinary prefab lookup and member creation. This patch does not
load or register BSE files. Missing names, unavailable BSE content, malformed prefab data or
templates requiring unavailable member objects can fail, produce incomplete castles or crash;
phase 1 does not validate a prefab's contents before starting the unpack.

Actions 381 (`NAMED_BASE_UNPACK`) and 493 (`NAMED_BASE_UNPACK_FREE`) remain unchanged.
Both new actions call the same retail helper. The paid action retains its faction's ownership,
requirements, affordability, resource accounting and timing. The free action retains the retail
FREE helper's immediate/free behavior. **Only the prefab/BSE selection is overridden.** Choosing
a larger or smaller prefab does not change any cost or requirement: those still come from the
normal `CastleToUnpackForFaction` entry of the controlling player's faction. This is not an
independent castle-variant definition with its own gameplay rules.

The game initializer registers both names and their parameter descriptors, so Lua's template
lookup and action construction receive three parameters. The engine's normal later template
key pass handles map-name keys. The optional editor patch registers the same descriptors in
the editor's table. `sage_worldbuilder/script_templates.json` remains the **stock extraction**;
pySAGE's separate script-editor catalogue does not automatically show these patched templates.
Maps containing them require the patched game and editor, including when reopening/resaving.

## Troubleshooting installation and authoring

Changing a ScriptEditor catalogue does not install engine hooks or update an existing map's
parameter tags automatically. Check the saved action has ID 227/343, three arguments and
Enabled=1. The third argument may be 10 (canonical) or 2 (compatible). The paid action can
still be rejected by stock ownership, requirements or affordability checks; FREE retains the
stock instant/free behavior and is a useful diagnostic in a synchronized test script.

Rebuild from the original game/editor binaries after patch-code changes. Do not apply the
patch again on top of its old cave: the exact-byte guards deliberately reject that. Ensure
the launcher actually uses the rebuilt game.dat and the editor shortcut opens the rebuilt
Worldbuilder.exe. Verify each generated file with its corresponding patch verifier. The
WorldBuilder action appears in Base only after the updated editor patch is installed; the
older registration used Unit_/Castle. Its absence from Base alone did not prove the old patch
was missing. The stock catalogue JSON remains an extraction of the unpatched editor.

## Why IDs 227 and 343

The dispatcher has 600 fixed entries, bounded by `cmp eax,0x257` at `0x007CAFCA`.
The template owner also has fixed action records at `this+0x20+id*0x80`, with conditions
immediately following. Lua and map parsing scan that bounded catalogue. Extending only the
jump table cannot add a working action; expanding the arrays requires tracing allocations,
construction/destruction, template lookup, key generation, parsing and both editor copies.
That expansion is outside phase 1.

There are 66 stage-two stubs, but 32 are implemented by the ScriptEngine's first dispatch
stage. Nineteen further actions have gutted bodies rather than stub entries. Reusing an
arbitrary apparently broken action can therefore remove functioning behavior or collide with
an existing map name/parameter contract. The experimental `map-transition` already owns 540.

The stock template extraction leaves 227, 343, 382 and 480 unregistered. Binary inspection
confirms 227, 343 and 382 dispatch straight to `0x007CF846`; 480 dispatches to `0x007CF05B`,
so it is **not** a safe empty slot. Use 227 and 343, registering new names and three-argument
descriptors there instead of relabeling an existing live action. Neither is handled by the
stage-one script-flow chain. Leave 382 available for another extension.

This follows the existing cave allocation and guarded jump-table replacement pattern.
Both claimed table words must still equal the stock epilogue or installation fails before
allocation. The registration hooks and all runtime hooks also require exact original bytes.
External mods may claim these IDs without changing these particular binary words; that
conflict is not discoverable automatically. Reserve the pair in the mod's action-ID policy
and do not use old maps with unknown actions bearing these IDs.

## State and lifetime

1. A valid new action resolves its target with the retail Parameter-to-Object lookup, interns
   its template using the engine's NameKeyGenerator, and establishes pending state containing
   Object*, NameKey and the target Parameter*. Invalid parameter counts/types, null pointers,
   missing objects and empty prefab names are no-ops.
2. It calls the stock helper. Ownership, unpackability and affordability rejection cannot
   create a persistent override because those checks precede the hooked StartUnpack call.
3. At that call, only the same Object*, target Parameter* and Behavior owner can latch the key.
   The side table records Behavior*, NameKey, Object* and ObjectID. It holds up to 256
   simultaneously pending unpack operations. A full table declines the new unpack instead of
   silently selecting the faction prefab; the stock helper can still assign the reference.
4. On helper return, pending state is cleared (or restored to an outer action's pending state
   under reentrancy). Persistent state survives a delayed unpack and every resolver call.
5. Resolver lookup requires Behavior, owner pointer and ObjectID agreement. No override takes
   the exact displaced stock instructions and continues through the original faction resolver.
6. The actual-unpack entry wrapper forwards its original argument and carries the original
   Behavior* as a hidden second stack argument. The common epilogue uses that identity to clear
   the table before replaying the original epilogue instructions. This also covers ordinary
   early exits. `ESI` cannot supply this identity: stock changes it to Object* and later a member
   address near `0x0079C110`; the stock local at `ebp-0x10` is reused as a byte flag.
7. The CastleBehavior destructor clears its own record as well, so destruction
   and normal object teardown cannot leave a pointer available for a later object allocation.

No player faction, faction map entry, cost resolver or prefab record is edited. Multiple
castles can retain distinct keys concurrently. A refused later script request preserves an
already-latched record. Abnormal SEH exceptions or a hook that bypasses normal entry/teardown
are not covered by the ordinary-return lifetime guarantee. Cancellation/reset paths that keep
the Behavior alive have not been fully traced; they may retain a stale override until actual
unpack or destruction. Do not assume a retail restart after such a cancellation resets it.

## Save/load, multiplayer and replay

The side table is gameplay state. **Phase 1 does not serialize it.** Saving/loading while a
custom unpack is delayed is unsupported: the resumed stock unpack can lose its chosen prefab,
or existing process state can survive differently depending on the load path. Do not rely on
such saves, including multiplayer save restoration. Save after the actual unpack has completed.
Destruction cleanup is not a save/load implementation; a serializer, cancellation audit and
load/reset hooks need separate RE before removing this restriction.

Only synchronized map scripts or otherwise synchronized simulation scripts may invoke these
actions. CommandButton selection uses the synchronized message extension below; live-bridge injection
is not part of this feature. Calling Lua
`ExecuteAction` locally from a debugger/tool is **not** synchronization. Every peer must
execute the same action in the same simulation order with identical registered prefab data;
NameKey allocation also depends on that order. Side-table state is not added to the stock
save format or CRC stream, so a missing entry may only become observable when it changes the
created world. Identical patches are necessary but do not establish multiplayer safety.
Replay playback likewise needs matching patch/data and synchronized original script execution.

## Verified addresses and patch composition

Address constants live in the existing `sage_patch.addresses` package (the repository's
successor to a monolithic `addresses.py`), exported through its normal domain modules.

| Address | Meaning |
| --- | --- |
| `0x007BED64` | stock named-base helper, Parameter*, reference string*, bool; ret 12 |
| `0x007BEDEE` | its StartUnpack call, after all stock checks |
| `0x0079C17D` | StartUnpack(bool, ThingTemplate*); ret 8 |
| `0x00799021` | Behavior prefab resolver |
| `0x00798F70` | stock ModuleData faction-to-prefab resolver |
| `0x0079B892`, `0x0079B918` | both prefab resolver calls in the unpack builders |
| `0x0079BE6A` | actual unpack; ret 4 |
| `0x0079C16D` | common actual-unpack SEH epilogue |
| `0x0079AAA7` | CastleBehavior destructor, reached by scalar deleting destructor `0x0079B865` |
| `0x0075A3D8` | resolve Object* from a unit Parameter*; ret 4 |
| `0x007CF857` | 600-word script-action jump table |
| `0x007D5270`, `0x007E478F` | game action-template initializer and final string-assignment call |
| `0x00FE0AF0`, `0x00FF336E` | independent editor initializer and final setter call |

Inspection on 2026-10-05 used the 11,346,944-byte game image and the 34,267,136-byte
editor image. The game initializer's stock byte range `0x007D5270..0x007E4798` hashes to
SHA256 `d4e20010d04ba3c4ce8724b77b91d1d9d0dcc72002aba8c0aeced6d9d23fbe89`.
The neighboring OpenBfme/OpenBfme2 source confirms the template record fields, Lua template
lookup and stock helper contract; target addresses and instructions were checked independently
in RotWK rather than transferred from those other builds.

The patch owns `.cstpre` and the editor patch `.cstprwb`, dynamically allocated in any order.
It does not overlap `castle-unpack-clearance`, `castle-unpack-buttons` or `map-transition`;
both composition orders are tested. The latter two remain separate optional patches, not
dependencies or changes installed by this feature. Other patches intercepting these entries,
the destructor, common epilogue, initializer's final setter or IDs 227/343 conflict and fail
the byte guards. Verifiers check the installed cave, hooks and unchanged stock anchors.

## Acceptance still needed

Test two differently selected castles concurrently, paid rejection for insufficient money,
wrong-owner calls, missing targets, normal faction fallback, both prefab member loops, instant
FREE unpack, destruction before delayed completion and table exhaustion. Verify resource
charges, requirements and timing against retail. Run a multiplayer match and replay with
identical scripted calls on all peers, and explicitly confirm the unsupported save/load case.
Passing x86 emulation and byte verification does not substitute for those engine/data tests.


## CommandButton CastlePrefab extension

Apply `CastlePrefabPatch()` (`castle-prefab`) **before**
`CastlePrefabCommandButtonPatch()` (`castle-prefab-commandbutton`). Both classes live in
`patches/experimental/castle_prefab.py`. The latter verifies the exact installed core before
writing; no implicit install, duplicate override table or replacement script action is created.
Rebuild previously patched binaries from the clean supported image with the current patches;
the shared core now exposes a common promotion routine. ScriptActions 227/343 continue to use
Pending → Persistent after their retail checks. Retail actions 381/493 stay untouched.

```ini
CommandButton Command_UnpackRohanLarge
    Command      = CASTLE_UNPACK
    CastlePrefab = RohanCastleLarge
End

CommandButton Command_UnpackFactionDefault
    Command = CASTLE_UNPACK
End
```

`CastlePrefab` selects a registered CastleTemplate/BSE name, not a file to load. It is only
meaningful with `Command = CASTLE_UNPACK`. Cost, prerequisites, ownership checks, timing and
other unpack rules remain those of the normal faction `CastleToUnpackForFaction` entry.
A missing/unavailable BSE still follows the engine's existing prefab lookup behavior; config
registration is not a content availability check. `CASTLE_UNPACK` without the parameter retains
the exact argumentless retail message path. `CASTLE_PACK` is unchanged.

`CASTLE_UNPACK_EXPLICIT_OBJECT` remains the separate retail ThingTemplate-based feature
(CommandType 0x32, message 0x43F). It is not BSE selection. Both the script and button prefab
paths keep `StartUnpack(false, nullptr)` for paid unpack; neither writes the one-shot
`CastleBehavior+0x98` explicit ObjectTemplate name, which bypasses BSE/faction iteration.

### Config and stable identifiers

The composable INI table mechanism copies every live CommandButton parser row unchanged and
adds only `CastlePrefab`, with offset/userData zero and a sidecar-only callback. No CommandButton
allocation, struct member or padding is changed. Other fields retain retail parser semantics.
The new callback accepts one printable ASCII token, 1..255 bytes, and rejects missing, empty,
non-ASCII, overlong or extra tokens without a fatal parser call. It replaces earlier config
transactionally with retail fallback on rejection. It stores `CommandButton* → prefabId` in
2048 fixed rows and `prefabId → NameKey + exact name` in 1024 fixed rows in `.cstcmd`.
Constructor cleanup removes recycled button identities; lookup scans past cleared holes.
Prefab registrations remain for the process lifetime, so repeated names reuse their NameKey.
Capacity exhaustion declines the extension. Invalid/collision/capacity counters occupy the
first three dwords of `.cstcmd` for debugging; no user-facing diagnostic is emitted by the engine.

The wire ID is FNV-1a/32 (offset basis `0x811C9DC5`, multiplier `0x01000193`, unsigned wrap)
over the token's bytes. Normalization removes surrounding INI whitespace; case is preserved to
match the engine's case-sensitive NameKey namespace. Zero is reserved. Different exact names
with the same ID quarantine that ID permanently (NameKey zero), disabling **both** names in
sender and receiver regardless of registration order. IDs do not depend on pointers, button
addresses, parser order or engine NameKey allocation. NameKeys are generated only at parse time,
never on the client-local sender path. Every peer must load matching config/data.

### Wire, receiver and synchronization evidence

An extended button creates exactly one normal `MSG_CASTLE_UNPACK` (0x43D) through the retail
`TheMessageStream` factory (global `0x00DE6398`, vtable `+0x48`). It appends two integer args
with `GameMessage::AppendIntegerArgument`:

1. `0x50534350`: fixed pySAGE CastlePrefab protocol magic, version 1.
2. The stable 32-bit prefab ID (the full bits, even if interpreted as a signed integer).

Stock buttons emit zero args. No pointer or NameKey is transmitted. After the retail validations
and affordability test succeed, the receiver requires argumentCount >= 2, INTEGER type on
both args and the exact magic. An unknown/zero/quarantined ID falls back to normal unpack;
extra arguments are ignored. A valid ID calls the **same core promotion routine** as the script
patch, recording Behavior, NameKey, owner pointer and ObjectID in `.cstpre`. No pending stage is
needed. If that 256-entry persistent table is full, the button falls back to retail. Shared
resolver, actual-unpack completion and destructor cleanup govern both request sources. The
stock failure branch is taken before any extension read or state change.

Direct RotWK evidence: generic `GetArgumentData` at `0x00710C9E`, typed `GetArgumentType` at
`0x00710CC0`, integer append at `0x007111E5`, and the typed copy constructor at `0x00712965`
iterate/copy the linked argument list. The retail 0x43F sender/receiver demonstrates integer
arguments on this same message mechanism. The supplied OpenBfme2 analysis corroborates generic
network and separate replay serialization over typed message arguments. This is architectural
corroboration, **not direct proof of RotWK's exact network/replay serializer loops**, and not an
end-to-end multiplayer/replay test. No OpenBfme2 code is modified. Identically patched clients,
matching INI/BSE content and in-game MP/replay validation are still required. The existing
save/load and CRC-side-table limitations above apply equally to button-created overrides.

### Exclusive byte windows and parser compatibility

| Written range (inclusive) | Original bytes | Behavior |
| --- | --- | --- |
| `0x00940AB6..0x00940ABA` | `68 3d 04 00 00` | UNPACK sender; stock resumes at `0x00940ABB`, extended exits at `0x00941ABB` |
| `0x0077C324..0x0077C329` | `0f 84 bc 0c 00 00` | Fail to `0x0077CFE6`; success resumes unchanged stock pushes/call at `0x0077C32A` |
| `0x0075D524..0x0075D529` | `8b f1 83 4e 0c ff` | Clear recycled sidecar identity and replay constructor instructions |
| `0x005DA706..0x005DA70A`, `0x005DA7B6..0x005DA7BA`, `0x005DA7D0..0x005DA7D4` | current live table reference | Point at copied live rows + CastlePrefab |

All hook windows and ABI/layout anchors are checked before allocation or writing. Guards include
the whole ordinary receiver case up to `TEST AL,AL`, its shared StartUnpack tail, the argument
helpers, factory path, constructor and the untouched 0x22 PACK / 0x32 EXPLICIT_OBJECT arms.
The 0x43F branch to `0x0077C32B` is never rewritten. A competing hook on the three exclusive
windows fails safely. Table extensions such as `command-point-cost`, `queue-ignore-cp` and
`multi-select-group` compose by copying the live rows; they can relocate the table again after
this patch, and verification locates CastlePrefab by name. A duplicate CastlePrefab row is a
conflict. Patches that restore a stock table instead of preserving live rows are incompatible.

This CommandButton field targets `game.dat` only. `castle-prefab-wb` registers the script
actions, not the new button field. Retail WorldBuilder cannot parse INI rows containing
`CastlePrefab`; keep such rows out of its input until an editor field-table twin is available.

Data-free structural and Unicorn tests cover config parsing without struct writes, deterministic
IDs and a real hash collision in both orders, stock and extended sender paths, malformed/unknown
payloads, retail failure branch and correct persistent promotion, register/stack preservation,
constructor identity reuse and the existing ScriptAction state machine. Before release, test
both buttons side by side, failed paid requests, delayed completion/destruction, two castles
with different prefabs, multiplayer on two matching clients and replay playback of those orders.
