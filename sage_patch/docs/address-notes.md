# Address notes

The reasoning behind the constants in [`../addresses/`](../addresses/__init__.py): how each address
was found, what holds at it, and what to watch for when hooking it. Kept here so each comment
in the source stays short. Sections are named after the constant each note sits above, in
file order.

## `LOGIC_CRC_SHROUD_XFER`

`mov eax, [TheShroudManager]` inside the CRC producer at `0x00625886`, where the shroud manager
is xfer'd into the frame checksum like every other logic subsystem.

**This is the anchor for the claim the whole patch rests on**: fog of war is already part of the
sync hash on this build, so a client whose *shroud state* diverges already desyncs, and
attestation is aimed at the remaining hole - a client whose shroud state agrees because only its
code was changed. The contribution is guarded by `-xShroudCRC` (`0x00DE87BF`), which excludes it;
absent that flag it is always included.

## `DESYNC_DECLARE`

The `GameLogic` method that declares this client out of sync and raises the `GUI:DesyncTitle` /
`GUI:DesyncText` box, and the byte it latches on the way - see `docs/desync-detection.md`.

The latch is what an external observer watches: zero from `GameLogic`'s field initialisers
(`0x0063027D`) for the life of a match, 1 from `0x00629106` the moment the declaration happens,
and never cleared in between. So a poller sampling at the logic rate cannot step over the edge,
which a pulse would let it do. Static only: the transition has not yet been seen in a live match.

## `DESYNC_FILE_WRITER`

The other path: a per-client-frame self-check that recomputes this client's CRC, compares it
against a caller-supplied value and appends `"Desync detected on frame %d ..."` to
`CLIENT_DESYNC_<name>.txt`. **It never runs on a retail build.** Its gate has exactly one writer,
at `0x007BA6D3`, inside the orphaned command-line region `docs/headless.md` section 5 documents -
the `-verifyClientCRC` handler, which no dispatch table names. Recorded so the next reader knows
the file exists in the code and not on disk, rather than waiting for one to appear.

## `NET_CRC_INTERVAL`

`NetCRCInterval` - the cadence of the `MSG_LOGIC_CRC` (`0x44A`) heartbeat, and therefore the
resolution of every out-of-sync answer this engine can give. See `docs/desync-debug.md` section
2. The engine's own name for it, from the flag reporter's `NetCRCInterval: %d` line at
`0x00BFDCE4`.

Its only writer is `0x007BA6F5`, in the orphaned command-line region `docs/headless.md` section 5
documents, so on a retail build the shipped 100 is the only value it ever holds. Three live
readers, which is what makes changing the initialiser sufficient rather than a hook:
the `GameInfo` constructor seeds `+0xC` from it unclamped, the skirmish start re-seeds the same
field through a `min(x, 100)` clamp - so *lowering* it passes through every path - and the
recorder copies it into the replay header block that `sage_replay` reads back as `crc_interval`.

## `DESYNC_FOCUS_FRAME`

The desync **focus frame**: `-1` when unset, else a frame number that overrides the interval
entirely - per-frame heartbeats across the window ending on it (`0x0062E736`, from
`target - [TheNetwork+0xC18] - 2` inclusive), and silence on every other frame. See
`docs/desync-debug.md` section 3.

Six live readers; only the heartbeat gate and `0x006290E7` have been read. Its handler
(`0x007BA690`) is separate from the one that arms the declaration filter below, so the frame can
be set on its own.

## `CRC_LITE_FLAG`

`-liteCRC`, and the reason the nine `-x<Subsystem>CRC` exclusion flags (`0x00DE87BC` through
`0x00DE87C4`, `0x00DE87C8`, `CRC_EXCLUDE_SHROUD_FLAG` among them) are inert on a retail build:
each subsystem's contribution is included when *either* this is set or its own exclusion is
clear, and the plain emitter path sets this for the duration of the call (`0x0062E7E8`, cleared
at `0x0062E7F6`). So
the exclusions are only consulted on the `-deepCRC` route above. See `docs/desync-debug.md`
section 5.

## `THE_PARTITION_MANAGER`

`ThePartitionManager` and `TheShroudManager`, the two subsystems holding visibility state.

⚠ **`THE_PARTITION_MANAGER` used to read `0x00DE4358`, which is `TheShroudManager`.** The old
value came from reading the registration block as "the object built immediately after the name
string is pushed"; the block actually pushes each name *after* storing the object it names, so
that reading was one slot late. The decisive instruction is the `setName` call site, which
reloads the global it is about to name:

    0x0062CEB3  mov [0x00DE4354], eax      ; store the object
    0x0062CECB  push 0x00BFDC08            ; "ThePartitionManager"
    0x0062CED5  mov ecx, [0x00DE4354]      ; <- names the object stored above
    0x0062CEDB  call 0x0046EC7F            ; setName

Both are now **confirmed live** rather than statically: each object holds its own name as an
`AsciiString` at `+0x08`, and reading it back gives `ThePartitionManager` at `0x00DE4354` and
`TheShroudManager` at `0x00DE4358` (`TheTaintManager` and `TheCollisionManager` follow at
`0x00DE435C` and `0x00DE4360`). Nothing consumed the wrong value, so this corrects a
declaration rather than a behaviour.

## `THE_GAME_INFO`

The lobby description of the game being played - map, seed, slots, factions - and the source
`RecorderClass::startRecording` builds a replay header's metadata string from.

`TheGameInfo` is whichever flavour is live (`LANGameInfo`, the GameSpy one, or the skirmish
one); `TheSkirmishGameInfo` is the skirmish menu's own, and the skirmish setup screen assigns
it to both (`0x006309BF` is `TheGameInfo = TheSkirmishGameInfo`). Reading the first and
falling back to the second is what lets a cave name the map without reproducing
`startRecording`'s three-way branch on the network session object.

## `GAME_INFO_PARSE`

`ParseAsciiStringToGameInfo(GameInfo *, AsciiString, bool keepNames)` - `__cdecl`, the caller
pops twelve bytes, and the string arrives **by value** and is destroyed by the callee. It is the
inverse of the replay header's `GameInfoToAsciiString` (`0x008023C1`): replay playback
(`0x0077F280`) and the skirmish lobby's `Skirmish.ini` load (`0x00821D2E`, into
`TheSkirmishGameInfo`) both call it. It parses into eight local slots and commits nothing
unless every one of `M MC MS SD GSID GT SI GR S` was seen and every slot token parsed, so a
rejected string leaves the target untouched. `keepNames` false lets an `H` slot with no name
keep the one the target already holds.

## `GAME_SLOT_IS_OCCUPIED`

`GameSlot::m_isOccupied`, and the setter that writes it. Nonzero means the seat is **in this
game**: `GameSlot::isOccupied` (`0x008009B1`) is `m_state in {2..6} and m_isOccupied != 0`, and
`GameLogic::buildSidesFromGameInfo` skips any slot it answers no for, so such a seat gets no
side and no player. Measured live in a War of the Ring battle 2026-09-06: 1 on the two seats
fighting it, 0 on the third human, who was consequently never named, never seated, and fell
through to `PlyrCivilian`. Some other start path sets it on all eight slots at once
(`0x006277A4`), so 1 is an ordinary value for it to hold.

## `THE_TERRAIN_LOGIC`

The four id-space stores. `sage_live.utils.resolve` reconstructs these spaces from ini;
reading the engine's own tables instead is the alternative, and two of the four are now read
that way.

`TheUpgradeCenter` settled the upgrade `+3` (order_space_map OPEN 4: three engine-registered
veterancy upgrades ahead of the ini's first) and is what `sage_live.backends.memory` names
upgrade bits with. `TheThingFactory` has the same shape - list head at `+0x0C`, count at
`+0x10`, and `ThingTemplate+0x494` for `next` - and `sage_live.backends.memory.thing_order`
walks it, so a policy can name a template with no ini load. Both are derived in
`docs/live-object-model.md` sections 3b and 3c.

`TheSpecialPowerStore` is walked too, and is the reason to check the *shape* before assuming
one: it is a `std::vector` (`{begin, end, capacity}` at `+0x0C`), not a linked list, which is
why a list walk found nothing there. Its 1,566 names agree with the ini reconstruction
position by position on every entry. `TheScienceStore` has the same vector shape and exactly
the 263 entries the ini defines, but its elements are separately allocated at *different
sizes*, so no fixed offset names them and it is still unwalked.
`TheTerrainLogic`, registered at `0x0062D0C9` beside its own name string (`0x00BFDBD0`), and
the vtable slot holding `Real getGroundHeight(Real x, Real y, Coord3D *normal)` - `__thiscall`,
returning in `st0`, cleaning its own twelve bytes of arguments. Read the shape off
`Object::getHeightAboveTerrain` (`0x0070BC6E`), which is that call and one `fsubr`.

## `GAME_LOGIC_UPDATE`

`GameLogic::update` - the per-logic-frame callback on the logic thread.

It is **virtual**, dispatched through the vtable slot below, so it has no `call rel32`
xrefs and cannot be found by following calls. Anything hooking it should assert the slot
still names it: a hook on a function nothing dispatches to installs perfectly, never fires,
and is indistinguishable from a working patch.

## `OBJECT_ID`

`Object::m_id`. Measured, not inferred: for **386 of 386** live objects in the recorded match
`tests/sage_live/fixtures/match.snapshot.gz`, the dword here equals the id `TheGameLogic`'s
object table carries beside the `Object*`, and no other offset in the first `0x400` bytes
matched more than a handful. See `docs/live-object-model.md` section 2.

⚠ **The id space is not dense.** 382 of those 386 sat at `slot == id`; four engine-reserved
objects held ids `99999996`..`99999999` at slots 4403-4406. Anything indexing an array by this
value must fold or bound it - see `patches/experimental/hero_mana.py`, which masks it.

## `OBJECT_PRODUCER_ID`

The **second** `ObjectID` on an object, immediately after its own, and the engine's fallback
answer to "which horde does this belong to": `resolveAttackTarget` (`0x00668167`) looks it up
through `GameLogic::findObjectByID` when `m_containedBy` is null, and treats the result as
this object's horde if it is `KINDOF HORDE`. In the Generals-lineage layout that field is
`m_producerID` - who made me - which fits what the fallback is for and is why an object that
has *left* its horde still resolves back to it. Not measured live; see
`docs/horde-formation-orphans.md` section 6.

Corroborated statically from a second, unrelated consumer: on a structure standing on a build
plot this field is the **plot**, written by the build path (`0x00857AEA`) and by the plot's own
first-update adopt scan (`0x008584C7`), and read by `GettingBuiltBehavior::onDelete`
(`0x0085757F`) to free that plot when the structure goes away. Two producers and one consumer
that all mean "who made me" is about as far as this can be taken without a debugger; see
`docs/foundation-rebind.md` section 2.1.

## `OBJECT_GET_HEIGHT_ABOVE_TERRAIN`

`Object::m_status`, the `ObjectStatusMaskType` bitset - 4 dwords, so 128 slots for the 106
names this build defines. Recovered from the one helper every test site goes through,
`Object::testStatus(bit)` at `0x0044DDEC`, whose body is
`and eax, [esi + edx*4 + 0x94]` with `edx = bit >> 5`.

The bit numbering is the name table's index order, corroborated by the call sites rather than
assumed: 91 of them push a literal bit, and all 39 distinct values name a status that makes
sense where it is used - `HORDE_MEMBER` (38) in the horde target resolver, `IS_LEAVING_FACTORY`
(90) in the stance module's wait, `UNDER_CONSTRUCTION` (2) thirteen times.
`Object::getHeightAboveTerrain` - the whole function is one `getGroundHeight` call and an
`fsubr`, so its 28 bytes pin `THE_TERRAIN_LOGIC`, the vtable slot and the calling convention at
once: the two floats and the NULL normal go on the stack, the answer comes back in `st0`, and
the `ret` that follows adds nothing to `esp`. Anything calling ground height through a cave
anchors here rather than asserting a `.data` slot whose contents only exist at runtime.

## `GET_FINAL_OVERRIDE`

The activation path, end to end, as `docs/hero-mana.md` derives it:

  order/UI -> Object::doSpecialPower*  -> SpecialPowerStore::canUseSpecialPower  (the predicate)
                                       -> Object::getSpecialPowerModule          (the module)
                                       -> module vtable +0x2c / +0x30 / +0x34    (the effect)

## `ABILITY_TRIGGER`

Where an ability *actually fires*, and the reason the charge cannot sit on the click.

A BFME hero ability is a pair: a `SpecialPowerModule` "starter" and a `…SpecialAbilityUpdate`
that takes the timing (approach to `StartAbilityRange`, `UnpackTime` wind-up, then the effect).
With `UpdateModuleStartsAttack = Yes` the starter does not perform the power at all, so
`Object::doSpecialPower*` is never even reached - measured live: casting Gandalf's Word of
Power produced zero records at those three sites.

`0x00854DF7` is the update's tick, a virtual through vtable `0x00C769EC`. `ebp` is the
interface `this` (`mov ebp, ecx`), **not** a frame pointer, so the module reaches back at
negative offsets. At `0x00855042` an unpack countdown has just hit zero and the engine pays
`UnitCost` - the same instant a mana cost is owed.

## `DO_SPECIAL_POWER_SITES`

The three `Object::doSpecialPower*` variants. Each resolves the module then dispatches through
it; the tuple is `(window VA, window bytes, VA just past the window)`. The window is the
`mov ecx, <module>` + `call [vtable+slot]` pair (variant 3 also carries the third argument's
`push`), which is the last point at which an activation can still be refused.

⚠ Each variant guards its `canUseSpecialPower` call with a caller-supplied bool
(`cmp byte ptr [ebp+0x14], 0`), so a caller can ask for the power to fire *without* the
predicate. That is why the charge has to re-check rather than trust the gate.

## `SPECIAL_POWER_NOTIFY_TRIGGERED_AND_PLAY_INITIATE_AUDIO`

`SpecialPowerTemplate`: `0x88` bytes, id at `+0x14`, `UnitCost`/`UnitCostDeathType` the last
two fields. The ctor zeroes both at `0x007B2007`/`0x007B200D`, so there is no padding to hide
a new field in and the struct has to grow.
RotWK 2.01, SHA256 948bac5ed89e33c605ac8b7e5c901e4b2554d953bc35b4ca3be4d7ff7c46cbd8.
Verified against game.dat.backup and the MusicSkriptParameter disassembly, 2026-09-09.
These are VAs. The CALL returns the final template in EAX; a pending push 0 at
0x89718B belongs to the later AudioEvent constructor, NOT to this no-argument call.

## `SPM_SCRIPT_MUSIC_PUSH`

thiscall, ret 24: (AsciiString* name, fadeOut, noFadeIn, count, flag*, level).
Resolves the music name (+0x12C), constructs AudioEvent, tags the local player,
sets count, and calls +0x84. An empty flag skips all ScriptEngine flag work.
The level is written into AudioEvent +0x78 at 0x7C0F34. The push consumer
0x45D313 indexes channel*2 + level; the Resume consumer 0x457EBF only returns
to a lower level when the requested level equals the current one. Use level 1,
reserving level 0 for normal scripting. A level-0 push cannot be undone by Resume(0, 1).

## `SPECIAL_POWER_FIELD_TABLE`

The `SpecialPower` INI field-parse table: 24 entries of
`{const char *name, ParseFn, void *userData, UnsignedInt offset}`, an all-zero terminator, and
**no slack after it** - `0x00DA6168` is live data. Exactly two references, both bare imm32
operands one byte into their instruction: `mov eax, imm32` (the `getFieldParse` accessor) and
`push imm32` (the parse call). Two is the smallest repoint of any table this package moves;
`production-condition` has sixteen.

## `CAN_DO_SPECIAL_POWER_AT_LOCATION`

The two targeted-cast predicates, both `__thiscall` on `TheActionManager`, each a chain of
sub-validators ending in one shared refuse arm. The UI cursor, the AI group routines and the
special-ability modules all call these, so a gate inside them reaches every caster.
`...AtLocation(Object *caster, Coord3D *where, cmdSource, SpecialPowerTemplate *, ?, cmdOptions,
Bool checkSource)` is `ret 0x1c`; `...AtObject(Object *caster, Object *target, cmdSource,
SpecialPowerTemplate *, cmdOptions, Bool checkSource)` is `ret 0x18`, keeps an `ebp` frame
throughout, and never writes its `target` (`[ebp+0xc]`) or template (`[ebp+0x14]`)
argument. See `docs/forbidden-upgrade-filter.md`.

## `OBJECT_FIELD_TABLE`

The `Object` INI field-parse table - the one an `Object` block is parsed through, writing into
a `ThingTemplate`. 191 entries of the same 16-byte shape, all-zero terminator at `0x00DA49E8`,
and **five** references, each a bare imm32 one byte into its instruction.

There is **no interior reference**. A byte scan reports one at `0x007162A4` pointing at entry
127, but disassembly says `0x007162A4` is `call 0x723CEE`, whose `E8` opcode plus the
first three bytes of its displacement happen to spell `0x00DA45E8`. A false positive, so the
table relocates as a unit.

## `THING_TEMPLATE_COPY_FROM`

`ThingTemplate::copyFrom(source)` - `__thiscall`, one stack argument, `ret 4`, copying field by
field. `ThingFactory::newOverride` allocates a default-constructed template and calls it, which
is the **only** way a `ThingTemplate` is ever duplicated: the other allocation
(`ThingFactory::newTemplate`) builds a fresh one that is then parsed. Both are `push 0x650`,
and those two are the only `push 0x650` sites in the image.

Anything keyed on a `ThingTemplate*` has to ride this call, or an INI override block silently
loses whatever the base template carried.

## `DESCRIPTION_SPECIAL_POWER_CASE`

The ControlBar's button-description builder, at its `UnitCost` case.

The whole routine is a switch on the `CommandButton`'s GUI command (`+0x14`); case `0x18` is
the special-power one, and its body reads `UnitCost` off the button's `SpecialPowerTemplate`
(`+0x44`) and appends one formatted line. `..._CASE` is the five-byte `cmp ecx, 0x18` /
`jne <done>` pair that guards it, `..._BODY` the instruction just past that pair, and
`..._DONE` the label the whole case falls out to.

## `DESCRIPTION_RANK_APPEND`

The same builder's **hero revive / recruit** case, at the point its rank line is handed over.

That case resolves the hero's `ThingTemplate` through `TheThingFactory::findTemplate` (so `esi`
is the template, not the button), appends an `APT:RankLabel` line describing the hero's level,
and then folds the accumulated line at `ebp-0x2c` into the description at `ebp-0x18`. The
window named here is that fold - `lea ecx, [ebp-0x18]` plus the `call` - which is the last
moment another line can join the same batch.

`edi` is the function's zero throughout (`xor edi, edi` in its prologue), which is what the
middle argument of a formatted line wants.

## `DESCRIPTION_PURCHASED_RUN`

The same builder's **"you already have this upgrade"** case, where it hands the message over.

The case is reached when `Player::hasUpgradeComplete` answers yes for the button's `Upgrade`
(`CommandButton+0x24`) and the GUI command is one of the three upgrade kinds. It fetches the
button's own `PurchasedLabel` (`CommandButton+0x70`), or `TOOLTIP:AlreadyUpgradedDefault` when
that is empty, and **assigns** the result over the description at `ebp-0x18` - which is what
throws away the `DescriptLabel` text fetched earlier at `0x00807DCF`.

`..._ASSIGN` is the nine-byte `lea ecx, [ebp-0x18]` / `push eax` / `call <operator=>` window,
`..._RESUME` the temporary's destructor immediately after it, and `..._RUN` the whole case
(the `add esi, 0x70` that names the field, both fetch arms, and the window) for fingerprinting.
`eax` holds the fetched `UnicodeString *` at `..._ASSIGN` on both arms.

## `DESCRIPTION_BLOCKED_RUN`

The sibling case, immediately before it: **"a conflicting upgrade"** / **"a prerequisite
upgrade you do not have"**. Same shape, one field along (`ConflictingLabel` and
`LacksPrerequisiteLabel` share `CommandButton+0x74`/`+0x78`, reached as `esi + 0x78`), two
default keys instead of one, and the same assignment over the description.

Note the window's first byte is the `push eax` rather than the `lea` - the two sites emit the
argument and the `this` in opposite order - so the two are not interchangeable.

## `DESCRIPTION_PLAYER_EBP_OFFSET`

That `Object`'s controlling `Player`, in the same frame - and **never null**, which is the
useful part: `0x00807AD4` seeds the slot from `ThePlayerList` (`0x00DE4928`) and only then
overwrites it with `getControllingPlayer` when there *is* an object. So a per-player value is
answerable even for a button with nothing selected behind it.

Both this and `DESCRIPTION_OBJECT_EBP_OFFSET` are written **once**, in the prologue, and
by nothing else in the function - unlike the button's `ThingTemplate` slot at `ebp-0x4c` and
(on one path) its `UpgradeTemplate` slot at `ebp-0x24`, both of which later cases reuse as
scratch. That is what makes these two safe to read from a hook at the end of the function.

## `DESCRIPTION_BUTTON_CAPTURE`

The description builder's prologue, at the instruction that loads the `CommandButton`.

`esi` is the builder's `this` here and `[esi+0xc]` is the button - but `esi` does **not** hold
the `this` at the end of the function: three cases reassign it (`0x00808426`, `0x00808654`,
`0x0080867A`), so a hook that runs after the switch cannot recover the button from it. This is
where a patch that needs the button later takes a copy, because the path through here is
unconditional: everything above it is straight-line from the function's entry, and the null
button check (`0x00807AFF`) is the instruction immediately *after* the window.

The window is the two instructions `mov [ebp-0x3c], edi` / `mov ecx, [esi+0xc]`; the resume
point is the `cmp ecx, edi` that tests what the second one loaded.

## `DESCRIPTION_TAIL`

The same builder's **tail**: the first instruction past the point where every case has finished.

The whole switch converges on `0x008086AA`, and between there and the tooltip record's
constructor at `0x008086E5` the only thing written is the hint slot at `ebp-0x48`. So the
description at `ebp-0x18` is **final** here, which makes this the one site where a line can be
appended and be genuinely last - the per-case sites cannot promise that, because the
`CONTROLBAR:Requirements` and `TOOLTIP:BuildDisabled` folds run after several of them.

`0x008086AA` and `0x008086AB` are both branch targets and this is not, and the four bytes it
encodes appear as an imm32 nowhere in the image, so no jump table reaches it either. The window
is the single `mov ecx, [0x00DE4A70]` that begins the hint block.

## `THE_GAME_TEXT`

How the engine builds one `<label>: <number>` line. Twelve sites share the idiom, so it is
stable: fetch the localized label through `TheGameText`'s vtable `+0x44` with the caller's three
already-pushed arguments, then format it into the buffer the builder keeps at `ebp-0x28`, then
drop all three.

⚠ **`UNICODE_STRING_CONCAT` does not concatenate - it replaces.** The name is kept because three
patches import it, but `0x00ADF7E0` forwards to `0x00437120`, which `vswprintf`s into a `0x4000`
scratch buffer and finishes with `UnicodeString::set` (`0x00436B20`) - so the destination's
previous contents are gone. The twelve engine sites conceal this perfectly, because each formats
into a slot it is the only writer of. A patch that formats into a slot something else has
already written **deletes that text**, and neither `verify` nor a disassembly of the cave can
see it. To add a line to an existing string, format into a temporary and join it with
`UNICODE_STRING_APPEND`, which is what the builder's own rank case does at `0x008085C4`.

The three arguments are pushed *by the caller* as `(label key, 0, value)` and cleaned by the
`add esp, 0xc` at the end, which is what makes the block copyable into a cave: it is
stack-neutral and needs only `ebp` to still be the builder's frame.

## `CONTROL_BAR_UNIT_COST_CALL`

The ControlBar's command-availability evaluator, at its `UnitCost` test. `ecx` holds the
`SpecialPowerTemplate` and `ebx` the `Object`; the `call` named here is the
`getFinalOverride` immediately before `cmp [eax+0x80], 0`. `..._UNAVAILABLE` is the tail the
existing `unitCost > members` branch jumps to (`xor eax, eax`), at the same stack depth.

The ControlBar does **not** call `canUseSpecialPower`, which is why greying a button is a
separate edit from gating the activation.

## `CLEAR_GAME_DATA`

`MSG_CLEAR_GAME_DATA` - the message that ends a recording. `sage_replay` reads the chunk it
produces as `Bfme2OrderType.EndOfRecording`.

**It has thirteen emitters, not one.** `GameLogic::clearGameData` (`0x00625E36`) is only the
one a mid-match quit takes; a game that *finishes* reaches the score screen and ends through
a different site entirely (the 0x9C5088 / 0x91xxxx window code), and there are eleven more.
So there is no single place upstream to hook - the funnel is downstream, at the consumer.

## `RECORDER_RECORDED_MODES`

The `MSG_NEW_GAME` game modes the stock recorder accepts, and the one it does not. The mode
is the message's argument 0; the emitters that name a constant cover 0..7, and the two the
recorder keeps are the network ones - every replay in the corpus carries mode 1 in its
header tail. The skirmish setup screen (`Skirmish.apt`, the start handler at `0x009287D9`
that also allocates `TheSkirmishGameInfo`) emits **2**, as does the command-line map launch
at `0x0063CB7B` on the branch that builds a `SkirmishGameInfo` - which is why a skirmish is
not recorded. Derived in `docs/skirmish-replay.md`.

## `RECORDER_MODE`

`RecorderClass`. `m_mode` is `RECORD` / `PLAYBACK` / `NONE` (0/1/2 - the constructor seeds
`NONE`, `startRecording` zeroes it and `startPlayback` writes 1), and `m_file` is the `FILE*`
it both writes recordings to and reads playbacks from - so `m_mode == RECORD` is what tells
a live recording apart from a replay being watched, and both must hold before anything
writes to that handle.

`writeToFile` is the engine's own chunk writer, and the format it lays down is what
`sage_replay.ReplayChunk` parses: `fwrite` of the logic frame, the message type and the
message's player number, then a unique-argument-type count, one `(type, count)` pair each,
and the values.

## `RECORDER_GAME_MODE`

`RecorderClass::m_gameMode` - the `MSG_NEW_GAME` mode a recording was started for, or the one
read back out of a header during playback (`startPlayback` freads into it at `0x0077F788`).

**Do not read this from inside `startRecording`.** `updateRecord` stores the mode here
(`0x0077F923`) and immediately passes it on (`0x0077F965`), but `startRecording`'s first act
is `reset()` (vtable `+0x24`, `0x0077D86C`), which tail-jumps to `0x0077D7C1` and writes the
sentinel **9** over it at `0x0077D7D2` - 40 bytes before the file is even named. A cave inside
`startRecording` that asks this field what kind of game it is gets 9, always. Confirmed on a
live skirmish: the field read 9 while the header the same call wrote carried mode 2.

The mode is still `startRecording`'s own second argument, which is the value it writes into
the header, so that is what a cave in there should read. See `START_RECORDING_MODE_ARG`.

## `START_RECORDING`

`RecorderClass::startRecording(Int arg1, Int gameMode, Int arg2, Int arg3)` - thiscall, four
stack arguments, `ret 0x10`. It runs on a normal `ebp` frame (the SEH prologue at its entry
establishes one), and writes all four arguments into the header's trailing block at
`0x0077EFBB`+ - which is where `sage_replay` reads them back as the last four words of
`unknown_tail`. So `[ebp+0x0C]` inside it *is* the mode the replay will claim it was recorded
at, by construction rather than by a second lookup that can go stale.

## `RECORDER_NEW_GAME_BRANCH`

`RecorderClass::updateRecord`'s `MSG_NEW_GAME` branch - the whole of the engine's decision to
record, and `startRecording`'s only caller:

    cmp  eax, 0x1E                  ; 0x0077F8D1  message type
    jne  <not a new game>
    push ebp / mov ecx, esi
    call 0x00710C9E                 ; getArgument(0) -> the game mode
    mov  eax, [eax]
    cmp  eax, 4    ; je <skip>      ; the shell map
    cmp  eax, 7    ; je <skip>
    cmp  [TheGameLogic+0x114], 3    ; je <skip>
    xor  ebx, ebx / inc ebx         ; ebx = 1, the default arg1
    cmp  eax, ebx  ; je <record>    ; mode 1
    cmp  eax, 5                     ; 0x0077F910  <- the whitelist tail, 9 bytes
    jne  <skip>                     ; 0x0077F9DD
    <record>                        ; 0x0077F919

The nine bytes at `..._MODE_GATE` are the only thing between a skirmish and a recording: the
4/7 rejects above are redundant against the whitelist, and `TheGameLogic+0x114` is 3 for any
game started from the shell (`0x00779F20` sets it there and nothing else writes it outside a
savegame load). `..._BRANCH_BYTES` is the 63-byte run from the message-type compare down to
the gate: a bare `cmp eax, 5` says nothing about which comparison it is, and that context
does.

## `RECORDER_LAST_REPLAY_NAME`

`RecorderClass::startRecording`'s call to the helper that names the file. The helper is
`TheGameText->fetch("GUI:LastReplay")` with a `00000000` fallback, so every recording is
written to `<UserDataDir>\Replays\Last Replay.BfME2Replay` and overwrites the previous one.

It has a second caller (`0x00817E49`, the replay menu reconstructing that exact name to find
the entry), so the *call site* is the patchable thing, not the helper. It is cdecl with one
argument - the uninitialised `UnicodeString` storage to construct into - and returns it in
`eax`; `..._CALL_BYTES` sits at offset 4 of the surrounding fingerprint.

## `RECORDER_END_BRANCH`

`RecorderClass::updateRecord`'s `MSG_CLEAR_GAME_DATA` branch - the one place every ending
converges on, whichever of the thirteen emitters appended the message. It reads:

    cmp  eax, 0x1D                  ; 0x0077F977
    jne  <ordinary order>
    cmp  [edi+0x10], ebp            ; m_file != NULL
    je   <nothing to write>
    or   dword [0xDA570C], -1
    push esi                        ; the GameMessage *
    mov  ecx, edi
    call 0x0077D8FC                 ; 0x0077F98B  writeToFile(msg)  <- the hook site
    mov  ecx, edi
    call 0x0077D8C8                 ; stopRecording() - closes the file

Hooking the `writeToFile` call is what puts a cave *between* the last order and the end
marker, with `m_file` already proven non-NULL by the branch above and the file still open.
It is the last moment anything can be appended to a recording.

`..._END_BRANCH_BYTES` is the 20-byte fingerprint from the `cmp eax, 0x1D` through the
`mov ecx, edi` that sets up the call: it pins the message id, the file test and the register
the recorder is in, so a build whose layout moved fails instead of hooking a bare call.

## `RECORDER_END_STOP_CALL`

The branch's *second* call - `stopRecording`, two instructions past the `writeToFile` one.
A cave here runs after the `0x1D` end marker has been written and before the file is closed,
which is the second and last such moment; `replay-annotations` takes it precisely because
`replay-outcome` owns the first (composing rule 2 - two patches must not edit one site).

`..._SETUP_BYTES` is the `mov ecx, edi` that loads the recorder for the call. Together with
`RECORDER_END_BRANCH_BYTES` (which stops one byte short of the `writeToFile` call, so it stays
valid whether or not `replay-outcome` has rewritten those five bytes) it pins the site without
reading a byte any other patch may have changed.

## `IS_MULTIPLAYER_GAME`

Two siblings that answer "is this a game the observer machinery applies to". Both are
thiscall on `TheGameLogic` and return a bool in `al`; they differ only in whether skirmish
counts. Derived in `docs/observer-switch.md`.

    IS_MULTIPLAYER_GAME              `m_gameMode` in {1, 5} - the two network flavours.
    IS_MULTIPLAYER_OR_ITS_REPLAY     that, or a *playback* whose recorded mode is 1 or 5.
    IS_MULTIPLAYER_OR_SKIRMISH...    that, plus live mode 2 and a recorded mode of 2.

The last one is the predicate `docs/skirmish-replay.md` §3 cites as proof the engine already
anticipates a mode-2 recording; it has 31 callers. The middle one has **exactly one**, the
observer bar's visibility gate below.

## `OBSERVER_BAR_GATE_CALL`

The palantir's per-frame decision to show or hide the observer bar - the APT clip holding
`ObserverStuff/NextPlayerBttn` and `PriorPlayerBttn`, the only UI that reaches
`PlayerList::observeNextPlayer`:

    mov  ecx, [TheGameLogic]         ; 0x006D7809
    test ecx, ecx ; je <hide>
    call 0x0062541E                  ; 0x006D7813  multiplayer, or a replay of one?
    test al, al   ; je <hide>
    mov  ecx, [ThePlayerList]
    call 0x006A87F5                  ; is the local player an observer (or defeated)?
    test al, al   ; je <hide>
    mov  bl, 1 / jmp / xor bl, bl    ; the answer
    <compare against the cached bit at Palantir+0x7E>
    call 0x008003F6                  ; SetObserverStuffState("_show")
    jmp
    call 0x0080041A                  ; SetObserverStuffState("_hide")

`..._FINGERPRINT` is that whole 66-byte run, with `..._BYTES` at offset 10 of it. A bare
`call` says nothing about which one it is; the two predicates around it and the two APT
thunks below it do.

## `PLAYER_LIST_LOCAL_IS_NOT_ACTIVE`

`PlayerList::localPlayerIsNotActive` (`mov ecx, [this+0x10]` - the local player - then
`!Player::isPlayerActive`, which is `!m_isObserver && !m_isDefeated`). The second half of the
gate above, and the *only* other test `PlayerList::observeNextPlayer` makes beyond
`GameLogic::isInGame` (`0x00441B60`: mode not in {4, 7, 9}). Neither cares about skirmish.

It has 12 callers, so it is never to be widened in place - a patch that wants a different
answer for one of them retargets that one `call`. See `CONTROL_BAR_CLICK_GATE_CALL`.

## `CONTROL_BAR_PROCESS_COMMAND_UI`

`ControlBar::processCommandUI(GameWindow *, GadgetGameMessage)` - thiscall on `TheControlBar`,
`ret 8` - where a command-button click enters the engine. Reached from the window system
callback bound to the name `"ControlBarSystem"` (`0x0080406B`, through the thunk at
`0x0071C4EA`), which is the whole of the 33-slot command grid: the palantir's chrome is APT,
the grid is not. Derived in `docs/observer-command-range.md`.

    call 0x0072979C                  ; 0x00941BB1  the window's CommandButton
    pop  ecx / mov esi, eax          ; 0x00941BB7  esi = the button, live to the end
    ...
    test esi, esi ; je <discard>     ; 0x00941BC8
    mov  ecx, [ThePlayerList]        ; 0x00941BCC
    call 0x006A87F5                  ; 0x00941BD2  is the local player an observer/defeated?
    test al, al ; jne <discard>      ; 0x00941BD7  <- every observer click dies here
    cmp  [esp+0x14], 0x400B          ; 0x00941BDB  the two bools the executor takes

The gate is anchored either side of the `call` rather than across it, so the fingerprints stay
valid once the call is retargeted. `..._BUTTON_LOAD` pins where `esi` comes from, which nothing
else would catch: a cave reading `[esi+0x14]` off a different pointer simply reads garbage.

## `CONTROL_BAR_CLICK_ARGUMENT_BUILD`

The rest of the dispatch, from the discard test to the executor call. It is the reason a patch
that answers the gate itself has to zero the *whole* of `eax` rather than just `al`: the two
`Bool` arguments are built with `sete al` / `setne al` and pushed as dwords, and the stock
predicate leaves `eax` at a clean 0 or 1 (`neg al; sbb eax, eax; inc eax`). A replacement that
writes only `al` would push whatever the window virtual at `0x00941BBD` left in the top three
bytes.

    mov   ecx, ebx                   ; 0x00941BE3  TheControlBar
    sete  al                         ; 0x00941BE5  message == 0x400B
    cmp   [esp+0x14], 0x4009         ; 0x00941BE8
    mov   [esi+0xC4], edi            ; 0x00941BF0  the button remembers its window
    push  eax / setne al / push eax  ; 0x00941BF6  the two bools, as dwords
    push  esi / call 0x00940435      ; 0x00941BFB  the button, into the click executor

## `CONTROL_BAR_COMMAND_DISPATCH`

The click executor's dispatch on `CommandButton+0x14`, and the two tables it dispatches
through - an MSVC two-level switch, so the handler for command `T` is
`jump_table[index_table[T - 1]]`:

    mov   ecx, [esi+0x14]            ; the GUICOMMAND
    lea   edx, [ecx-1] ; cmp edx, 0x3b ; ja <unhandled>
    movzx edx, byte [0x00941B63 + edx]
    jmp   dword [0x00941AC3 + edx*4]

Reading the pair back is how a patch proves the two paging commands are 55 and 56 in *this*
binary rather than trusting the name table's ordering.

## `AI_GROUP_DO_OBJECT_UPGRADE`

The two paging handlers the tables above must reach. `PUSH` takes `&button->m_range`
(`CommandButton+0x22C`) and appends it to the stack at `ControlBar+0x2B0`; `POP` drops the top
8-byte record. Both end in `switchToContext(current, current)` - a redraw, and nothing else.
`ControlBar::populateMultiSelect`'s per-drawable merge - `thiscall(Drawable *, Bool first)`,
`ret 8`. Called once per selected drawable from `0x009448A9`, with `first` set for the first one
only. The `first` pass installs that unit's `CommandSet` into the 33 slots (each button needing
`OK_FOR_MULTI_SELECT`, tested at `0x009445DA`); every later pass **intersects**, and the loop at
`0x009446CA` is the whole of that rule.

Three frame slots survive the loop: `[ebp-4]` the `ControlBar`, `[ebp-8]` this drawable's
`CommandSet`, and `[ebp-0x14]` its `Object` - stored at `0x00944556`, with the
`je 0x00944754` two instructions later proving it is non-NULL everywhere the loop runs.
`AIGroup::doObjectUpgrade(UpgradeTemplate *)` - `thiscall`, the logic-side end of an
`OBJECT_UPGRADE` click on a selection. `MSG(0x415)` carries an object id of **zero**, meaning the
issuing player's whole selection, so this is where one click reaches many units.

`ebx` holds the message's upgrade for the whole member loop and `[ebp+8]` keeps the original
argument untouched, which is what lets a hook rewrite `ebx` per member and still re-derive the
message's own upgrade on the next pass. The per-member gate below it is
`canAffordAndLegal` / `Object::hasUpgrade` / `Object::canAcceptUpgrade` - and **none of them ask
which `CommandSet` the clicked button came from**.

## `CONTROL_BAR_MERGE_SLOT`

The merge's verdict, and the three arms it dispatches to. `edi` is this object's button for the
slot, `eax` the button already installed there, `esi` the slot's window, `cl` the flag saying one
of the two is `ATTACK_MOVE` (GUI command 0xA, the stock exemption). Eight bytes, four whole
instructions:

    0094472e  cmp  edi, eax        ; the comparison is **pointer identity**, nothing weaker
    00944730  je   0x94474a        ;   same button -> keep the slot
    00944732  test cl, cl
    00944734  jne  0x94474a        ;   ATTACK_MOVE involved -> keep the slot
    00944736  <clear the slot and hide the window>

So two units whose sets name *different* buttons at one index lose that slot for the whole
selection - it is hidden, not greyed, which is why a mixed selection shows an empty socket rather
than a disabled icon.

`edx` is dead across the loop and `cl` is dead past its own test, which is what leaves a cave
room to work without saving anything.

## `CONTROL_BAR_MERGE_RESET`

The merge's three continuations. `HIDE` is the stock refusal - `[esi+0x84] = NULL` then
`winHide(TRUE)`. `KEEP` is the loop's own `inc ebx` / `add esi, 4`. `INSTALL` is the arm the
empty-slot case takes, and it is reusable from anywhere **provided `eax` is zero**: it stores
`edi` into `[esi+0x84]`, then `winHide(eax)` - so a non-zero `eax` would hide the window it
means to show.
`populateMultiSelect`'s reset and its first-object install, the two other sites the merge rule
needs. `0x00944509` clears `[win+0x84]` on all 33 slots and has **exactly one caller** - the
`call` at `0x00944853`, inside the multi-select arm - which makes that call the one place a
per-populate scratch area can be zeroed. `ecx` is the `ControlBar` across it, so a shim must
preserve it.

## `CONTROL_BAR_MERGE_INSTALL_FIRST`

The first object's install, in the `first == 1` loop: `mov [edi+0x84], ebx` with `edi` the
slot's window pointer, `ebx` the button and `esi` zero. Six bytes, one whole instruction.

⚠ **The flags are live across it.** `cmp ecx, esi` two bytes earlier is what the `je` at the
resume point reads, and `ecx` - the window - is live too, all the way to the `winHide` at
`0x009445F4`. A shim has to restore both.

The slot index in that loop is `[ebp+8]`: the `Drawable` argument slot, reused as the counter
(`mov [ebp+8], ebx` at `0x009445B7`, `inc dword [ebp+8]` at `0x009446B5`). `[ebp-0x14]` still
holds the `Object`.

## `CONTROL_BAR_RANGE_FETCH`

`ControlBar::populate`'s single-object path, and the one place it reads the visible range the
handlers above maintain. `CONTROL_BAR_RANGE_FETCH` is eleven bytes - three whole instructions
plus the `call` - that load the top `{start, count}` record into the frame:

    00943e11  lea  eax, [ebp-0x48]          ; &range
    00943e14  push eax
    00943e15  mov  ecx, ebx                 ; the ControlBar
    00943e17  call 0x0071cf0a               ; getVisibleRange(&range)

`0x00943DF4` jumps to the first byte, and nothing branches into the other ten, which is what
makes the whole span replaceable. Derived in `docs/push-visible-command-range.md`.

## `VICTORY_CONDITIONS_VTABLE`

`VictoryConditions` - the subsystem that decides who is out and who has won. Derived in
`docs/replay-outcome.md`; `sizeof` is 0x94 and the vtable is the one its constructor
installs.

`m_players` is a compacted list: `addPlayer` walks `ThePlayerList` at game start and keeps
only the real playable sides, so an index here is *not* a `ThePlayerList` index. A player is
named by its own `PLAYER_INDEX` instead, which is what the engine stamps into every replay
chunk, so a chunk written from here is attributable exactly as a real order is.

`m_isDefeated[i]` is a latch: `VictoryConditions::update` sets it once, on the frame the
player is first found defeated, and never clears it. The two vtable predicates are the
engine's own answers, teams included, and both are already called every frame by the stock
UI - so calling them again costs nothing new.

## `PLAYER_INDEX`

`Player`. `m_playerIndex` is the number the engine writes into every replay chunk: the
`GameMessage` constructor at 0x710C36 fills the message's player field from
`ThePlayerList->getLocalPlayer()->m_playerIndex`, and `RecorderClass::writeToFile` copies
that field straight out. `m_defeatedFrame` is stamped by `VictoryConditions::update` on the
transition, `m_isDefeated` is the player's own hard flag (a quit, or nothing left that
`MP_COUNT_FOR_VICTORY` counts), and `m_isObserver` marks a slot that plays no side.

## `PLAYER_SCORE_KEEPER`

`ScoreKeeper`, embedded in `Player` (not a pointer) - the score-screen counters, which no
replay has ever carried. Derived in `docs/replay-annotations.md` §2.

The base is pinned twice over: 107 `lea reg, [reg+0x3DC]` sites hand that address to the
method block at 0x0079DB00-0x0079DD00, and `PLAYER_SCORE_KEEPER + SCORE_KEEPER_END_FRAME`
is exactly `PLAYER_DEFEAT_FRAME` - the field `replay-outcome` already reads and has
runtime-verified, so the two readings check each other.

## `VIEW_GET_LOCATION_VTABLE_SLOT`

`View::getLocation(ViewLocation *)` and `View::setLocation(const ViewLocation *)`, the pair
the camera-bookmark hotkeys use. Both are `__thiscall` taking one pointer, and the callee
cleans the argument (`ret 4`) - the engine's own call sites push and never adjust `esp`.

The pair, and the struct's size, come from the bookmark handler reading its slot array with a
32-byte stride: `0x0083B294` saves the live camera into slot *n* through `+0x170`, and
`0x0083B420` restores slot *n* through `+0x174`, both addressing `[base + n*32]`.

## `VIEW_POSITION_OFFSET`

`View::m_pos` - the camera's look-at point on the terrain, and the one field of a placement
that can be written on its own. `setLocation` copies a `ViewLocation`'s three position floats
here with `lea edi,[ebx+0x0C]` and three MOVSDs (`0x0065E995`), and `getLocation` reads them
back from `[esi+0x0C]` (`0x0065E942`).

**Writing these twelve bytes moves the camera by itself**, without the recompute `setLocation`
calls afterwards - measured live against a running match, at 160 writes a second. That matters
because `setLocation` is otherwise the only way in and it always writes all four scalars, one
of which it cannot write correctly: `zoom` is read from `+0x124` and written to `+0x128`, so
handing a captured location straight back still moved the live zoom from 1.281116 to 1.234136,
after which the client restored it over about 0.6 seconds. Asking for the reported zoom is
refused identically, so there is no value that makes `setLocation` a no-op.

## `CAN_MAKE_UNIT`

`BuildAssistant::canMakeUnit(Object *producer, const ThingTemplate *what, int reviveIndex)` -
the one gate the AI consults before deciding a producer may make something. It is virtual, at
the vtable slot below, and `BUILD_ASSISTANT_VTABLE` is the class's vtable (from the constructor
`TheBuildAssistant` is registered with), so a patch can assert the slot still names it.

It walks the producer's `CommandSet` and branches on whether a revive index was passed. The
labels below are the four points inside it that `patches/ai_revive_gate.py` needs; they are
derived in `docs/ai-revive-gate.md`.

## `CAN_MAKE_UNIT_PRODUCTION_GATE`

`BuildAssistant`'s **other** gate, vtable slot `+0x64`. It is the one every producer-facing
consumer asks - the ControlBar's button availability, `ProductionUpdate::queueCreateUnit`,
the script and AI production paths, 14 call sites in all - and it reaches `canMakeUnit`
through a *virtual self-call* on its own `this`, which is why a scan for a
`TheBuildAssistant` global load followed by `call [reg+0x68]` cannot see it.

So it is the edge that puts `canMakeUnit` on the player's path, and the return address it
leaves on the stack is how `patches/ai_revive_gate.py` tells the AI's own queries apart from
everyone else's. Anchoring the call rather than naming the return address means a build whose
layout moved fails loudly instead of comparing against a stale constant.

## `GUICOMMAND_PUSH_VISIBLE_COMMAND_RANGE`

The two paging commands, entries 55 and 56 of that same table. Neither issues a `GameMessage`:
`PUSH` appends the button's `CommandRangeStart`/`CommandRangeCount` pair to a stack on the
ControlBar and `POP` drops the top one, and both then re-run `switchToContext` to redraw. So
they are the only two GUI commands that change nothing but which slice of a `CommandSet` is on
screen - which is what makes them safe to hand an observer. Derived in
`docs/observer-command-range.md`.

## `AI_PRODUCER_PICKER`

The `SkirmishAI` producer picker, and the construction check that is missing from it.
Derived in `docs/ai-construction-gate.md`.

RotWK ships **two** AIs. The Generals/BFME1-lineage `AIPlayer::findFactory` at 0x008F5347 does
test `UNDER_CONSTRUCTION` (at 0x008F53A2) before it asks `canMakeUnit` - but a skirmish match
runs the BFME2-era `SkirmishAI` subsystem, whose own producer index and picker live in the
0x0096xxxx-0x009Exxxx region and consult no status at all. The picker below is where the AI
chooses which of its buildings will make a thing, for units and for hero revives alike.

## `ARMY_DEFINITION_FIELD_TABLE`

`HeroBuildOrder`, and the skirmish AI's hero builder that spends a purse against it. Derived in
`docs/ai-hero-build-delay.md`.

The keyword is row 29 of the `ArmyDefinition` field table and stores a plain
`std::vector<AsciiString>` of names; the builder copies that vector wholesale and picks an entry
out of it at random. There is no clock anywhere on the path, which is why the AI empties its
purse into whichever hero it happened to draw as soon as it can afford one.

## `REBUILD_HOLE_SET_POSITION`

`push [esi+0x74]` - the tail of `onDie`, where the fresh hole is told what to put back: the
dying object's `ThingTemplate` (`[esi+4]`) and id. Anchoring it proves the function being
edited is the one that arms the rebuild, not merely one that spawns an object.
The eleven bytes in `onDie` that place the fresh hole: `lea eax, [esi+0x38]` / `push eax` /
`mov ecx, edi` / `call OBJECT_SET_POSITION`, giving the hole the *dying* object's live position.
For a structure killed mid-rebuild that position has already left the terrain, so the hole is
buried. No branch or dword in the image reaches any byte of the run, so all eleven are
replaceable in place. `RESUME` is the next instruction, the angle copy.

## `REQUEST_UNIQUE_UNIT_ID`

`ProductionUpdateInterface::requestUniqueUnitID()` - the mint for the `ProductionID` that
names one queued production. `ProductionUpdate` is its only implementer: the address below
appears in exactly one vtable slot in the image, the one named here.

The interface is a secondary base of the `ProductionUpdate` module, at module `+0x20`, so
`this` is the interface subobject and the counter it advances is module `+0x30`. The
constructor (`0x008A17D8`) seeds that counter to 1 and nothing but this function reads or
writes it - which is what makes it replaceable. Derived in `docs/unique-production-id.md`.

## `PRODUCTION_UPDATE_VTABLE`

The module's *primary* vtable, written at `module+0x00` by the constructor
(`0x008A1819`: `mov dword [esi], 0xc67ef4`). A vtable address is unique to its class, so
this is how a reader outside the process identifies which of an object's behaviour modules
is the `ProductionUpdate` - without calling the engine's own `getProductionUpdateInterface`,
which it cannot. Used by `sage_live.backends.memory` to read production state; see
`docs/production-model-condition.md` §5.

## `INI_PARSE_STRING_LIST`

`INI::parseAsciiStringVector`, the parser behind every whitespace-separated **list of names**:
it erases the `std::vector<AsciiString>` at `store` (`{begin, end, capacity}`, four bytes an
element) and appends one entry per token, macros expanded. `HeroBuildOrder`,
`OffensiveBuildings` and `ScavangedResourceBuildings` all name it, which is why a patch wanting
a richer token syntax for one of them repoints that field's **row** rather than this function.
Nothing here resolves a name, so the vector holds text until a consumer looks it up.

## `TERRAIN_RESOURCE_MODULE_DATA_CTOR`

The module on a claimed resource spot: it wakes every `IncomeInterval`, deposits an income, and
hands the same number to the building's `ExperienceTracker`. Derived in
`docs/terrain-resource-exp.md`.

`ModuleData` is 0x24 bytes holding eight fields. Two `Bool`s sit at +0x14/+0x15 and the next
field is a 4-byte `KindOfFilter` that has to start aligned at +0x18, so **+0x16 and +0x17 are
padding**: nothing reads them and the constructor never writes them.

## `TERRAIN_RESOURCE_INCOME_GATE`

The three sites a **negative** `MaxIncome` has to get past, in the order `update` reaches them.
Derived in `docs/maintenance-cost.md`; nothing here is a new field, because `INI::parseInt`
already accepts a minus sign - `INI::scanInt` is an `sscanf("%d")` - so a negative parses today
and is thrown away at run time instead.

`..._INCOME_GATE` is `jle 0x0088573C`, taken when the income *before* inflation comes out <= 0.
It is the whole of why a negative does nothing today, and the one edit that needs no cave: the
condition wants to be "== 0" rather than "<= 0", which is `0F 8E` -> `0F 84` in place, the same
six bytes and the same target.

## `TERRAIN_RESOURCE_INCOME_FLOAT_EBP`

The slot the income lives in as a **float** between the inflation multiply and the floor:
`fstp dword [ebp-0x20]` at 0x00885692 writes it, and the `fld`/`fistp` two instructions later
turn it into the `ebx` the floor tests. It is the same `ebp-0x20` that held
`&ResourceModifierObjectFilter` earlier in the function, reused - see `AUTO_DEPOSIT_FILTER_EBP`.

Worth a name because the float **keeps a sign the integer loses**: an inflation multiplier of
zero turns a charge into an integer 0, but IEEE gives `-5.0f * 0.0f` the value `-0.0f`, whose
sign bit a `test` on the raw dword reads directly.

## `PLAYER_TEMPLATE_NAME_KEY`

`PlayerTemplate` members. `+0x10` is the `NameKeyType` of the block name, and it is the only
**stable** identity a template has: templates live in a `std::vector<PlayerTemplate>` at
`PlayerTemplateStore+0x0C` with stride `0x1DC`, are parsed into a *stack temporary* and then
copied in, so every pointer a parse callback sees is transient.
`PlayerTemplateStore::findPlayerTemplate` (`0x005FCA2E`) walks that vector comparing exactly
this dword, which is what proves it survives the copy.

## `PLAYER_COMMAND_POINTS_CAP`

The rest of the command-point block, as `Player::getCommandPointsAvailable` combines them:
`cap = min(+0x64 base + +0x6C bonus + <filtered extras>, +0x70 hard)`. The extras are a
vector at `+0x80`/`+0x84` whose entries carry an `ObjectFilter`, so evaluating them means
calling the engine - a reader that copies only the flat fields gets a **lower bound** on the
real ceiling, which is why all four are recorded rather than a computed total.
Confirmed live 2026-08-16: a fresh Angmar seat read used 120 / base 500 / bonus 0 / hard 1500.

## `PLAYER_ADD_COMMAND_POINTS_FOR_OBJECT`

The command-point accounting an object performs as it is gained, lost and modified, and the
leak in it - see `docs/command-point-leak.md`. The two `Player` wrappers pick their counter by
`ThingTemplate.CommandPointBonus` (`+0x62C`): positive goes to the cap bonus (`Player+0x6C`)
via `0x006A7C3E`/`0x006A7C51`, everything else to points-in-use via `0x006A7FDA`/`0x006A7FEB`.
`0x006A7C01` values a cap-granting object as its template bonus **plus** every live
`COMMAND_POINT_BONUS` attribute modifier (type 24), which is why applying a modifier has to
re-do the accounting at all.

## `OBJECT_APPLY_MODIFIER_LIST`

`Object::applyModifierList`, the single door all 32 attribute-modifier call sites go through.
It subtracts the object's cap contribution at `0x0068F225`, applies, and re-adds at
`0x0068F243` - but `0x0068F23A` returns FALSE without re-adding when the apply is refused,
which permanently deletes that object's contribution from `Player+0x6C`. `0x0068F2A0` is the
removal counterpart and is correctly symmetric. The refusals live in
`ModifierHolder::applyModifierList`; `ModifierList+0xD2`/`+0xD3` are
`ReplaceInCategoryIfLongest` and `IgnoreIfAnticategoryActive`, and a `Duration` of 0 becomes
expiry `0x3FFFFFFF` at `0x00805B39`, so a permanent list outlasts and refuses every shorter
one sharing its `Category`.

## `PLAYER_RESOURCES`

The player's spendable resource balance, and the spellbook point pair (`+0x24` is the
spendable balance, `+0x1C` the lifetime total - only the former falls when a power is bought).

**`+0x94` is not derivable from the `ScoreKeeper`'s money fields.** Measured live 2026-08-16
over 130 frames: `+0x94` tracked `starting purse + ScoreKeeper.money_earned` exactly, while
`money_spent` sat unchanged at 5000 from before the first order with `units_built` still 0 -
so `money_spent` carries a setup charge that was never deducted from the balance, and only
`+0x94` says what a player could actually afford.

`Player+0x3E0` is deliberately absent: it is lifetime income and reads **byte-identical** to
`ScoreKeeper+0x04` on every sample, so recording it would duplicate a field.

## `PLAYER_GRANT_UPGRADE`

`__thiscall(UpgradeTemplate *, 2, 0)`, `ret 0xC` - the engine's own "this player has completed
this upgrade" path, which sets the bit in `PLAYER_COMPLETED_UPGRADE_MASK` *and* runs whatever
the upgrade does on completion. `LIVING_WORLD_BATTLE_SETUP` restores a saved mask by driving it
rather than writing the bitset: `UPGRADE_FIRST_SET` turns the mask into a template, this grants
it, and the caller clears the bit and goes round again (`0x008126E5`-`0x0081271C`). That loop is
the reference for replaying a mask onto a player without half-applying anything.

## `PLAYER_LIST_GET_LOCAL_PLAYER`

`PlayerList::getLocalPlayer` - thiscall, no arguments. The palantir's own refresh
(`0x006D577C`) reaches the displayed player through it, so a HUD-side read matches.

**It is not a plain getter.** When `m_local` is not active - an observer, or a defeated
player - it returns `ControlBar+0x218`, the player being observed, and only falls back to
`m_local` when there is none (`0x006A8850`). That redirect is what makes the whole command bar
evaluate against the watched seat during a replay; see `docs/observer-command-range.md` §5.1.

## `AUTO_DEPOSIT_SCALE`

`AutoDepositUpdate::update` (`0x008854D3`) - the tick income path, and the *only* reader of
`PlayerTemplate.ResourceModifierValues` in the whole image.

`..._SCALE` is where the finished inflation multiplier stops being written and starts being
used: `[ebp-0x1C]` holds it, nothing touches it between here and the `fmul` at `0x00885685`,
and the window is `mov eax, [ebp-0x18]` / `fild dword ptr [eax+0xC]` - six bytes.
`esi` is the controlling `Player` and `edi` the depositing `Object` throughout.

`..._FILTER_EBP` holds `&template->ResourceModifierObjectFilter` **only until `0x00885672`**,
where a `fistp` reuses the slot for the rounded amount. A hook at `..._SCALE` is before that.

## `PLAYER_FOR_EACH_TEAM_OBJECT`

`Player::forEachTeamObject(fn, ctx)` - thiscall, `ret 8`, walks the team list at `Player+0x34C`
and stops early if `fn` returns 0. Pure: it writes nothing and takes no lock, so a HUD-side
read of the same count the deposit computes is safe.

`..._COUNT_CALLBACK` is the engine's own per-object counter, `cdecl (Object*, void *ctx)` with
`ctx = { ObjectFilter* filter; Int count; }`. It skips objects failing `testStatus(2)` and
counts those the filter accepts - calling `allow(object, NULL)`, a **null player**, where the
gate three instructions earlier passes the real one. Reusing it rather than writing a second
counter is what makes a readout agree with the deposit by construction.

## `ACTIVE_BODY_ATTEMPT_HEALING`

The healing path, per `docs/healing-received-modifier.md`. `ActiveBody::attemptHealing` is body
vtable slot `+0x04` and is shared by nine body vtables; `InactiveBody` has its own, which
discards the heal. Every heal in the engine becomes a `DamageInfo` of type 7 and reaches it,
including the six sites that build one inline rather than going through
`OBJECT_ATTEMPT_HEALING` (thiscall, `ret 8`, `(Real amount, Object *source)`).

`..._AMOUNT_FSTP` is the `fstp dword [ebp-4]` storing what `Armor::adjustDamage` returned - the
only place the amount exists, five bytes with the `fldz` after it and nothing branching into
them, which is why `healing-received` hooks exactly there. The healed object is in `edi` across
it, and the engine's own `<= 0` test at `..._AMOUNT_TEST` sits below, so a zero multiplier
skips the health change, the observers and the `out` store together.

## `OBJECT_HAS_MODIFIER`

The two per-type modifier queries on `Object`, both thiscall. `hasModifier(type, Real *out,
ctx)` is `ret 0xC` and **sums**; `getModifierMultiplier(type, Real *out, ctx, flag)` is
`ret 0x10` and **multiplies**, seeding `*out` to 1.0 at `0x0080500F` - but returning at its own
holder guard without writing through `out` at all when the object has never been modified,
which is why every call site seeds the slot itself. Additive versus multiplicative is the
caller's choice, not the type's.

## `PALANTIR_RESOURCE_MULTIPLIER`

The palantir's **resource-multiplier** readout - a slot that already exists, is already
refreshed every frame, and is already blank in a skirmish.

The text builder at `0x00800844` takes one **float** and blanks itself at exactly `1.0f`
(`ucomiss` against `FLOAT_ONE`, then `L" "` at `0x00BD16E4`); anything else it formats with
`L"x%g"` (`0x00C4E5BC`) and pushes to `TheAptPlayer::setValue("APT:PalantirResourceMultiplier",
…)`. The `.csf` entry of that name is a design-time placeholder as usual - Edain's reads `x23`.

The refresh at `0x006D577C` feeds it the War-of-the-Ring region bonus (`0x006E1F2F`, capped by
`GameData.ResourceMultiplierLimit`) and otherwise **exactly `1.0f`**, at the window below.
Replacing that constant load is therefore the whole of a readout: everything downstream - the
`ucomiss` change filter against the cached float at `palantir+0x18`, the builder, the blanking
rule - is untouched.

The window is `movss xmm0, [FLOAT_ONE]` / `jmp 0x006D5A69`, thirteen bytes. All three branches
into it (`0x006D5997`, `0x006D59A0`, `0x006D59A7`) target its **first** byte, so nothing lands
inside and a five-byte `jmp` plus padding is safe.

## `PLAYER_MONEY`

`Player::m_money`, the `Money` subobject both income modules address as `lea ecx, [player+0x90]`
before the deposit, and `Money::m_amount` inside it.

⚠ **The amount is unsigned, and `deposit` does not check.** `Money::deposit` is
`add [this+4], amount` with no clamp, while `withdraw` compares with `cmova` - an *unsigned*
compare. So a "negative deposit" is not a charge that happens to be written oddly: it rolls the
balance through zero to about four billion gold. Anything charging a player goes through
`MONEY_WITHDRAW`, which clamps to what is there and returns what it took.

## `GUI_LOSE_CASH`

The engine's own "you lost gold" floating text, at `0x008C6980` where a transfer pays one
player and charges another: `GUI:LoseCash` in red at the payer, `GUI:AddCash` in green at the
receiver, both lifted above the object by a constant. Reusing the pair is what keeps a charge
looking like something the game already does.

`..._RISE` is the float added to the object's `z` (30.0f; the `AddCash` site uses 20.0f), and
the color is `ARGB`. `IN_GAME_UI_ADD_FLOATING_TEXT` is `TheInGameUI`'s vtable slot for
`addFloatingText(UnicodeString*, Coord3D*, Color)` - callee-cleaned, `ret 0xC`.

## `AUTO_DEPOSIT_MODULE_DATA_CTOR`

`AutoDepositUpdate` - the "this structure pays you on a timer" module, and the one the
second-resource grant rides on. Derived in `docs/second-resource.md`.

**Not** the module `AUTO_DEPOSIT_SCALE` above names: that constant sits inside
`TerrainResourceBehavior::update` (`0x008854D3`), the *other* income module, which is the only
reader of `PlayerTemplate.ResourceModifierValues`. The two are easy to confuse and the fields
read alike; the discriminator is the `ModuleData`, reached as `[ebp-0x18]` there and as
`[esi-0x0C]` here.

`ModuleData` is 0x24 bytes holding eight fields ending with two `Bool`s at +0x20/+0x21, so
**+0x22 and +0x23 are alignment padding**: no field names them and the constructor never
writes them. The two `Bool` stores at `..._CTOR_BOOLS` are six bytes for what `mov [esi+0x20],
ebx` does in three with `ebx` already zero - and that one dword store clears the padding too,
so the new field's default costs no bytes at all.

## `AUTO_DEPOSIT_DEPOSIT`

The deposit inside `AutoDepositUpdate::update`, as a whole five-byte `call` - so the hook
displaces one complete instruction and needs no padding.

`esi` is the module (its `ModuleData` at `[esi-0x0C]`) and `edi` the controlling `Player`,
both callee-saved across the deposit. `edi` stops being the player at the resume address,
where it is reloaded with the depositing object's `ExperienceTracker`.

## `AUTO_DEPOSIT_PAY`

The two sites a **negative** `DepositAmount` has to get past. Unlike `TerrainResourceBehavior`
this module clamps the amount nowhere - `cvttss2si`, the region bonus at `0x006AA858` and the
rounding helper at `0x00A3CFA4` all carry a sign through, and the floating `+N` text is already
gated on `DepositAmount > 0` at `0x0089DD52`. Only the deposit itself and the experience grant
need an edit.

`..._PAY` is `lea ecx, [edi+0x90]`, the money pointer, chosen over the `call` five bytes later
for one reason: `second-resource` owns that call. `edi` is the controlling `Player`, `[esi-8]`
the depositing `Object`, `eax` and `[esp]` the signed amount. `..._PAY_RESUME` is the
`mov [ebp-0x14], eax` between the two, so a positive amount rejoins *above* the call and
whatever occupies it still runs.

## `AUTO_DEPOSIT_TRUNCATE`

Where `AutoDepositUpdate::update`'s amount stops being a float: `cvttss2si eax, [ebp-0x14]`,
after `UpgradeBonusPercent` (0x0089DC83) and the difficulty handicap (0x0089DCD2) and before the
War-of-the-Ring region bonus (0x0089DCE5) and the final rounding. Derived in
`docs/auto-deposit-inflation.md`.

**Five bytes holding exactly one instruction**, so a detour needs no padding. The window's first
byte is a branch target - `je 0x0089DCDD` at 0x0089DCB7, the no-handicap path - which is what a
detour wants: both paths converge on it and both get scaled. Nothing lands in its interior, and
no byte of it appears as an imm32 anywhere in the image; `scripts/scan_branches.py` is what
establishes that, by decoding a branch at every byte offset rather than sweeping linearly.

`edi` is the controlling `Player` and `[esi-8]` the depositing `Object` here, and `eax` is the
only register the resume point needs.

## `PLAYER_TEMPLATE_BLOCK_KEY_EARLY`

The `PlayerTemplate` block's name key, one instruction *before*
`PLAYER_TEMPLATE_BLOCK_KEY` - `eax` already holds the key and the window is the six bytes of
`mov ecx, [PlayerTemplateStore]`.

Two hooks are needed here rather than one because a template's per-block key is the only
identity a field callback can file against, and `command-point-upkeep` already owns the
instruction pair at `PLAYER_TEMPLATE_BLOCK_KEY`. The two windows do not overlap and neither
reads what the other writes: both only copy `eax`.

## `PLAYER_INIT`

`Player::init(PlayerTemplate *)` - the one place a player's purse is seeded from its faction,
and therefore the one place a second pool has to be seeded and cleared.

`PlayerList`'s own reset (`0x006A8916`) calls it on **all twenty slots** with a NULL template,
and the money block is inside the `template != NULL` branch - so a hook placed at the money
block would never clear an unused slot. `..._ENTRY` is past the SEH prologue and before that
branch, with `ecx` still the `Player` and `[ebp+8]` the template, so one hook both clears and
seeds. Four callers, none of them a per-frame path.

## `PALANTIR_RESOURCES`

The palantir's resource text, built and pushed to the movie in one place - the same shape as
`PALANTIR_COMMAND_POINTS`, and the reason a second number needs no `.apt` edit.

`0x006D56E1` takes the amount as its only argument, formats `"%d"` (`0x00BD4194`, **8-bit**)
into an `AsciiString` and hands it to `TheAptPlayer::setValue("APT:PalantirResources", …)`
through the widening wrapper at `0x00625071`. A negative amount takes a `" "` placeholder
(`0x00BD343C`) instead. So the movie's own text is overwritten every refresh and a mod's `.csf`
entry of that name is a design-time placeholder, exactly as for the command-point readout.

The window is `cmp [ebp+8], 0` / `mov [ebp-4], 1` - eleven bytes, sitting *before* the first
vararg push, which is the only place a second one fits. `[ebp-4]` is the SEH state marking the
`AsciiString` at `[ebp-0x10]` constructed, so a hook has to keep writing it on every path.

## `PALANTIR_RESOURCES_CACHE`

The refresh's change filter, in the palantir update at `0x006D577C`.

`edi` is the local player's gold (or -1 when there is no playable local player) and `[esi+0xC]`
the last value pushed; the text call only happens when they differ. **A second number has to
widen that filter or it goes stale**, because a game where gold is momentarily flat still moves
the second pool. `cmp edi, [esi+0xC]` / `je` is exactly five bytes.

## `THING_TEMPLATE_ID`

`ThingTemplate+0x5E8`, and why a second build cost cannot live there.

The idea document costs the 2-byte gap between `CampnessValue` (an `Int` at +0x5E4) and
`BuildCost` (a `UInt16` at +0x5EA) as possibly-free storage. **It is not.** It is the
template's engine-assigned id: a dedicated setter at `0x006CFBC7`, a down-counting global
allocator at `0x00DA18E4`, ~15 readers, and the ControlBar pushes it into build orders
(`0x00940948`). An override *swaps* ids so the new template inherits the old one's identity.

That is the second apparent hole in a template that turned out to be a real member - see
`PlayerTemplate+0x34` in `docs/second-resource.md` §1.2 - and it is why `BuildCost2` is keyed
in a cave rather than stored on the template.

## `THING_TEMPLATE_COPY_ID`

The id copy **inside** `ThingTemplate::copyFrom`, where `eax` is the source template and `ebx`
the destination. Anything keyed on a `ThingTemplate *` has to ride this, or an INI override
block silently loses whatever the base template carried.

`hero-mana` rides the same copy from the outside, by retargeting its **call site**
(`THING_TEMPLATE_COPY_CALL`). This is the body, so the two do not share a byte - and hooking
the body also covers any caller that is not that one call.

## `BUILD_GATE_AFFORD`

The one affordability comparison every human production path shares, inside `BuildAssistant`'s
`+0x64` gate (`0x00793ECB`).

`esi` is the `Player` (`+0x94` is its gold), `eax` the cost `calcCostToBuild` just returned
(`0x0073C25F`), `ebx` gold plus the allowance the frame computed, and `[ebp+0xC]` the
`ThingTemplate` being priced. The window is `cmp eax, ebx` / `jbe <affordable>` / `push 2` -
six bytes - and **2 is the engine's own "not enough money" code**, so refusing here reuses the
refusal message and the button tint that already exist.

## `TOOLTIP_COST_BUILD`

The two `TOOLTIP:Cost` lines in the ControlBar's description builder that price a
`ThingTemplate` - a unit or structure to build, and a hero to revive or recruit.

`TOOLTIP:Cost` (`0x00C4F028`) has four call sites; these are the two where the thing being
priced is a template in a known register, and they are exactly the two `BuildCost2` applies to.
The other two price a science and a per-frame float.

Every site shares one shape: three pushes, `TheGameText`'s vtable `+0x44` formats the localized
line into `eax`, then the line is concatenated onto the description at `ebp-0x28`. The window
named here is `push eax` / `lea eax, [ebp-0x28]` / `push eax` - five bytes, sitting **after**
the line exists and **before** it is handed over, which is the one place a suffix can join it.

## `COMMAND_BUTTON_AUTO_ABILITY`

`AutoAbility`, the last `Bool` before the `KindOfFlags` at +0x110, and **the three bytes after
it are alignment padding**: no field in the table names +0x10D..+0x10F, the constructor never
writes them, and the `memset(this+0x110, 0, 0x1C)` that follows starts past them.

That is what makes the new field's default free. The constructor's `mov byte [esi+0x10C], bl`
becomes `mov dword [esi+0x10C], ebx` - **one byte changed, six for six** - and since `ebx` is
the zero the whole constructor stores from (it is `xor ebx, ebx` at 0x0075D52A and is what
`RequireLevel` is defaulted with six bytes earlier), the dword store leaves `AutoAbility` at
`No` and clears the padding on the way past.

+0x103, the other apparent hole, is **not** one: the constructor zeroes it explicitly and
`CommandButton::getBorderType` (`0x0075CBA5`) returns border type 5 when it is set.

## `COMMAND_BUTTON_TRIGGER_WHEN_READY`

`TriggerWhenReady`, the `Bool` at +0x12C, and **the three bytes after it are alignment padding**
- the second hole of the same shape as `AutoAbility`'s. No field in the table names
+0x12D..+0x12F: `PresetRange` is the `Real` at +0x130, and the constructor's
`memset(this+0x110, 0, 0x1C)` stops at +0x12B, one byte short of `TriggerWhenReady` itself.

The constructor defaults it with `mov byte [esi+0x12C], bl`, six bytes at
`COMMAND_BUTTON_CTOR_TRIGGER_WHEN_READY`. Widening that to `mov dword [esi+0x12C], ebx`
is **one byte changed, six for six**, and `ebx` is the zero the whole constructor stores from
(`xor ebx, ebx` at 0x0075D52A; the dword store `mov [esi+0x2DC], ebx` at 0x0075D72B is the proof
all four bytes of it are zero, not just `bl`). So the widened store leaves `TriggerWhenReady` at
`No` and clears the padding on the way past, which is what makes a field parked there free to
default without a constructor hook at all.

## `BUILD_GATE_COMMAND_POINTS`

The command-point verdict inside `BuildAssistant`'s `+0x64` gate
(`CAN_MAKE_UNIT_PRODUCTION_GATE`), eight bytes: `test al, al` / `jne <ok>` / `push 7` /
`jmp <carry the code out>`. It is the **last** refusal in the gate and it sits below the money
one (`BUILD_GATE_AFFORD`, 24 bytes earlier, which `second-resource` takes), so the two do not
share a byte.

Both branches arrive here: `0x00793FED` jumps into the call at `0x00794023` with the revive's
template, so hooking the verdict covers `UNIT_BUILD` and `REVIVE` at once.

## `PRODUCTION_UPDATE_COMMAND_POINT_STALL`

Where the **stock** engine already holds a queue that has outrun the command-point cap, and
the reason this patch needs no second half. Neither address is patched; they are named so the
claim can be checked.

`PRODUCTION_UPDATE_COMMAND_POINT_STALL` is inside `ProductionUpdate::update`: for a head entry
of kind 1 (unit) or 3 (revive) it asks `COMMAND_POINTS_HAS_ENOUGH` about the entry's own
template and, when the answer is no, plays EVA message 0x0B for the local player and returns
**before** the block at `0x008A1EBC` that adds this frame's progress to `entry+0x1C`. The
queue simply does not advance.

`PRODUCTION_UPDATE_REVIVE_COMMAND_POINT_DELAY` is the revive-side equivalent, called from the
top of `update` (`0x008A1C10`): it walks the queue and, for every kind-3 entry the player
cannot afford, increments that hero's revive start frame (`ReviveMgr` entry +0xA8) - pushing
the completion out by one frame for as long as the cap holds.

## `PRODUCTION_UPDATE_PICK_ENTRY`

**The production queue's per-frame entry picker.**

Derived in `docs/hero-recruit-parallel.md`. `ProductionUpdate` keeps units, upgrades and hero
revives in one doubly-linked list appended at the tail (`PRODUCTION_QUEUE_APPEND`), and
`ProductionUpdate::update` advances exactly one entry per frame - whichever
`PRODUCTION_UPDATE_PICK_ENTRY` hands back. So queue order is press order and the picker is the
whole of the scheduling policy.

## `ASCII_STRING_SET`

**The shell's campaign start.**

Derived in `docs/campaign-select.md`. `AptMainMenu` registers a string-keyed callback map at
`this+0x21C` in its constructor (`0x0091CA80` onwards, one ~85-byte block per command); the
APT movie reaches those callbacks through `_root.GameCode(func, params)`, which is
`geturl2("FSCommand:AptMainMenu::" + func, params)`.

## `MAIN_MENU_CAMPAIGN_HANDLER`

The callback itself, whole (35 bytes, `thiscall`, `ret 4`, one `const char *` argument):

    mov  eax, [esp+4]              ; the FSCommand's params string
    mov  [ecx+0x288], 9            ; MAIN_MENU_PHASE_LEAVING
    mov  [ecx+0x28C], 0Dh          ; MAIN_MENU_CAMPAIGN_SELECTION_ID
    mov  al, [eax]                 ; **only the first byte is kept**
    mov  [ecx+0x2A8], al           ; 'E' / 'M' / 'H', from "Easy" / "Medium" / "Hard"
    ret  4

The whole of `campaign-select` follows from line four: the params string is a `const char *`
the engine already has in hand and already dereferences, and it throws away everything after
the first character.

## `CAMPAIGN_NAME_STATIC`

The function-local `static AsciiString` that case 13's start thunk (`0x0091BE64`) passes to
`startLinearCampaign` (`0x0091B1D2`, which resolves it through `TheCampaignManager` and does
nothing if the name is unknown), and the MSVC magic-static guard beside it:

    0091BE96  test byte ptr [0x00DEA360], 1   ; the guard
    0091BE9D  push esi
    0091BE9E  mov  esi, 0x00DEA35C            ; the static - loaded unconditionally
    0091BEA3  jne  0x0091BECA                 ; already initialised -> straight to the start

The initialisation the `jne` skips is the *only* place the hardcoded `ANGMAR_CAMPAIGN` string
reaches the static, and it runs at most once per process. Filling the static and setting the
guard before the thunk runs therefore substitutes the campaign name without touching the thunk,
the jump table or the callback registry.

## `BATTLE_SCHOOL_COMMAND`

**The Battle School command, and the shell services its exit needs.**

Derived in `docs/battle-school.md`. ROTWK still registers `AptMainMenu::BattleSchool` and its
handler is complete; what EA dropped is `AptMainMenu::TutorialExit`, the mirror command that
reverses the sound fade on the way out. `battle-school` supplies the missing half through the
surviving command's unused `params` argument rather than by registering a second one.

## `BATTLE_SCHOOL_HANDLER`

The handler, whole (169 bytes, `thiscall`, `ret 4`, one `const char *` argument it never
reads). It marks the shell as movie-owned, fades the shell audio out through the
`MainMenuToBattleSchool` transition, and persists `FlashTutorial = 0` so the menu stops
blinking the button:

    0091B54D  mov  eax, [SHELL] ; je ...
    0091B55C  mov  byte ptr [eax+0x5D], 1     ; SHELL_MOVIE_ACTIVE
    0091B567  push 0x00C7CE28                 ; BATTLE_SCHOOL_TRANSITION_NAME
    0091B571  mov  ecx, [WINDOW_TRANSITIONS_HANDLER] ; call WINDOW_TRANSITION_SET_GROUP
    0091B586  call 0x0075D9B1                 ; stop shell audio
    0091B593  push 0x00C7CE18                 ; "FlashTutorial" -> 0, written to preferences
    0091B5CE  mov  byte ptr [esi+0x281], bl   ; MAIN_MENU_BLINK_FLAG

The first five bytes are the SEH prologue's cookie load, `mov eax, 0xBA9A56` - which is what
makes a five-byte detour clean: the cave re-emits them and jumps back to the `call` at
`BATTLE_SCHOOL_HANDLER + 5` with the stack exactly as the stock entry left it.

## `CLI_TABLE`

**The command line, and the two instructions that give it its length.**

`game.dat` parses argv against a table of `{const char *name, int (*handler)(char **argSlot,
int remaining)}`. The dispatcher compares with `_strnicmp` and requires equal length, rewrites
a leading `0x96` (a Word en-dash) to `-` first, and adds each handler's return value to the
argument index - so a handler returns how many arguments it consumed, 1 for a flag and 2 for
one that takes a value. Only `eax`, `ecx` and `edx` are free inside one.

The table's address and its length reach the dispatcher from a single call site, as a
register load and a pushed constant. That is what makes the table extensible in six bytes:
repoint `CLI_TABLE_REF` at a copy with more rows and raise the count. `push imm8` reaches 127
entries, so the count edit keeps its length and nothing shifts.

Derived in `docs/headless.md` §1.

## `THE_DISPLAY`

**The per-frame draw.**

`TheDisplay`, and the one call that draws a frame. `GameClient::update` reaches the display
twice: `update` through vtable `+0x28` at `0x00648838`, then `draw` through `+0x30` eleven
bytes later. Suppressing the second is what makes a headless run cheap; the first is left
alone, because everything downstream of the display's own update is state, not pixels.

`THE_DISPLAY` has 540 references in `.text`, essentially none of them null-checked, which is
why a headless mode here suppresses drawing rather than removing the display.

## `GLOBAL_DATA`

**`TheWritableGlobalData`, and the two frame-rate fields.**

The pointer, and the pair of `GameData` fields that cap the loop. Both are ordinary INI fields
(the field-parse table at `0x00BFF580` maps `UseFPSLimit` to `+0x26` and
`FramesPerSecondLimit` to `+0x28`) and both are read live - `0x0063A01B` copies `+0x26` into
the loop's own global, and `0x0062C6FF` already writes the pair at runtime.

The command line is parsed *after* `GlobalData`'s INI is loaded (`0x0063AFA4` registers and
loads it, `0x0063AFB2` parses argv), so a handler writing these fields wins over the tree.

## `GLOBAL_DATA_ASSET_PROFILE`

The asset-load profiler's switch, which is a `GlobalData` field only in the sense that it lives
in the struct: it is absent from the field-parse table, no command-line handler reaches it, and
the constructor is its only writer (`0x00643A79`, storing zero). Its three readers are
`0x0062ECD4`, `0x006314E2` and `0x0063160B`. Writable at run time, so a live session can toggle
it in a binary the `asset-load-profile` patch has defaulted on. Derived in
`docs/asset-demand-load.md`.

## `GAME_DATA_BOOL_PARSER`

**`GameData`'s LivingWorldCampaignOverrride, and the two parsers.**

A `GameData` field-table row is `{const char *name, parse_fn, user_data, offset}`. Two of the
parsers matter here, both identified by the fields that already use them: `0x0042E558` is the
`Bool` parser (`Windowed`, `AudioOn`, `ShellMapOn`), and ends in `mov byte ptr [ecx], al`;
`0x0042EE5E` is the `AsciiString` parser, which `ShellMapName` uses.

`LivingWorldCampaignOverrride` (the engine's own spelling) names a `LivingWorldCampaign` to start
by name. Its row declares the **Bool** parser while `GlobalData+0x8C` is an `AsciiString` in
every code path - the constructor stores a pointer there (`0x00642AA3`), the campaign selector
calls `AsciiString::isEmpty` on it (`0x007B96E4`), and the orphaned command-line handler at
`0x007BAA28` sets it with `AsciiString::set`. Setting it in INI writes one byte over the pointer.

Derived in `docs/living-world-campaign.md`.

## `LIVING_WORLD_BATTLE_END`

The War of the Ring battle boundary: how a living-world army becomes units on a map, and what
comes back. Derived in `docs/living-campaign/hero-permadeath.md`.

An army's force container is `army+0x78`: `+0x1C` army id, `+0x2C` phase, `+0x40` the record
vector, `+0x60` `SurvivalThreshhold`. A record is `0xD8` bytes and is the same object an
`ArmyEntry` parses into, so the INI field offsets below are also the runtime ones.

## `ACT_VERB_TABLE`

The campaign Act, and the verb table that fills it. Derived in
`docs/living-campaign/merge-player-army.md`.

`sizeof(Act)` is `0xB8` - a vtable, the act's name, fourteen 12-byte per-verb vectors,
`JumpToAct`'s string at `+0x50` and `EndAct`'s bool at `+0xB4`, leaving three padding bytes. No
new verb can add a per-act list; records for one have to live in the patch's own cave.

## `KINDOF_DEAD_SLOTS`

The two `KindOf` slots that are dead on both sides - never written anywhere in Edain's ini tree
and never read by the engine, so one can be repointed to a new token for the cost of a single
dword instead of relocating `KINDOF_NAME_TABLE`. Established by decoding every instruction in
the image that touches the mask byte and reading its immediate; `template + 0x109` is busy
(`INFANTRY`, `CAVALRY`, `MONSTER`, `MACHINE`, `AIRCRAFT`, `DOZER`, `SWARM_DOZER` are all
tested) but bit `0x20` appears in none of its 151 references.
Capstone prints small immediates in decimal - a scan keyed on `0x` operands wrongly reports
`MONSTER` and `NO_GARRISON` as dead.

## `PALANTIR_SCREEN_CHOICE_CALL`

**The Palantir's objectives button, and which screen it opens.**

The button does not show or hide: it pushes **one of three movies**, and
`IS_MULTIPLAYER_OR_SKIRMISH_OR_ITS_REPLAY` (`0x00625456`, above) is asked **twice** on the way -
once to pick the handler, then again inside the handler it picked.

The outer question runs in the button's own callback (`0x006D40C9`) and, identically, in the
hotkey dispatch (`0x0081FFAA`):

    006d40d2  call 0x00625456
    006d40d9  je   0x006D40E2
    006d40db  call 0x00914EF0      ; pushes "PlayerTribute.apt" unconditionally
    006d40e2  call 0x008E8843      ; asks again, below

and the inner one is inside `0x008E8843`:

    008e8958  call 0x00625456
    008e8961  test al, al
    008e8968  je   0x008E8972
    008e896b  push 0x00C18C2C      ; "PlayerStatus.apt"  - the player/enemy list
    008e8972  push 0x00C18C5C      ; "Objectives.apt"

Every term of that predicate is a game-type test; none of them consults the map. A War of the
Ring battle is skirmish-mode, so the outer question already routes it to the tribute screen and
`0x008E8843` never runs - which is why the campaign maps show the resource-transfer screen where
objectives belong. Redirecting only the inner call changes nothing outside the linear campaign.

Not to be confused with `0x006D7873`, which gates the button's **flash** on whether the living
world is active (its helper targets the APT function `FlashObjectivesButton`). That one changes
no screen. Derived in `docs/objectives-in-any-map.md`.

## `DEBUG_CRASH_MESSAGE_EBP`

`Debug::crash(int mode)` - `__thiscall` on the `Debug` singleton (`0x00DC62C0`), the function
that formats the crash text, shows the message box and raises. Its three frame slots below are
everything the exception record is missing.

`..._MESSAGE_EBP` is the formatted crash text: allocated at `0x0043A91E` and filled with the
current error record's expression, file and line followed by `..._TAG_EBP`'s literal. It is a
heap pointer, so it is readable offline only in a dump that carries the heap.
`..._TAG_EBP` is one of two `.rdata` literals chosen at `DEBUG_CRASH_TAG_STORE` by `mode`, and
`..._MODE_EBP` is `mode` itself - 1 for an assertion, anything else for an error.

## `WRITE_MINI_DUMP_CALL_FILTER`

The `call writeMiniDump` **inside the unhandled-exception filter** `0x0043D610` (the
`SetUnhandledExceptionFilter` target, installed at `0x00437EB3` via the `push 0x43D610` at
`0x00437EA6`). `esi` holds the `EXCEPTION_POINTERS` and `dl` the `fulldump` flag, both already
pushed; the call returns to a `add esp, 8` at `0x0043D753` that cleans them. This is the site
every observed `0x04560123` shutdown dump was written from, and the one `quiet-exit` redirects
through its `m_quitting` gate. The image's other `call writeMiniDump` (`0x0043818B`, in a
wrapper with no static callers) is left alone.

## `ATTACK_NUGGET_VTABLES`

The nuggets whose presence makes a weapon able to attack a victim, as `{name: vtable}`.

**An allowlist, because the engine's own damage getters do not answer this question.**
`NUGGET_VTBL_DEALS_DAMAGE` is not a reliable reading of "this nugget hurts the target":
`AttributeModifierNugget`, `ParalyzeNugget`, `FireLogicNugget` and `EmotionWeaponNugget` all
return `mov al,1` from it and none of them is a reason to attack, while `HordeAttackNugget`,
`SlaveAttackNugget`, `DamageFieldNugget` and `GrabNugget` return false from both it and
`NUGGET_VTBL_SUBWEAPON` and every one of them is. Nothing in the vtable separates the two
groups, so they are named.

Order is irrelevant to the answer; this is the order the list was specified in.

## `SCENARIO_IS_FACTION_ENABLED`

`Scenario::isFactionEnabled(AsciiString side)` - walks the `DisabledFactions` vector comparing
`side` (a `PlayerTemplate` *name*, `FactionMen` and so on, which is why the INI entries carry
the `Faction` prefix) against each entry and answers `al = 0` on a hit. `__thiscall`, `ret 4`:
the argument comes **by value and is destroyed by the callee**, which is what the `AsciiString`
destructor at its tail does. It takes no player, which is the whole reason `DisabledFactions`
can only be scenario-wide.

## `SCENARIO_FACTION_CALL_SITES`

`(call VA, its stock bytes, the ebp displacement holding the lobby slot index)` for **every**
`call SCENARIO_IS_FACTION_ENABLED` in the image - there are exactly four, all inside the
multiplayer game-setup screen, and each already has the slot it is asking about in a local that
is live and unwritten at the call. In order: the start-game gate that raises
`GUI:DisabledFaction`; the historical-scenario pass that rejects a duplicate or disabled pick;
the pass that resolves a slot left on Random; and the one that fills a slot's faction combo box,
greying and disabling the entries it refuses.

## `DEPLOY_STYLE_TARGETED_COMMAND_OFFSETS`

The subset of those that name something the `READY_TO_MOVE` arm can resolve on its own: an
attack-object command (`+0x595`, with the `ObjectID` at `+0x584`) and an attack-position one
(`+0x596`, with the `Coord3D` at `+0x588`). `+0x594` is deliberately absent - it means
"attack-ish, no explicit target" (guard, attack-move, hunt), and its arm resolves a target only
through the mood picker and the tracked id, both of which come back empty for a unit attacking
out of its guard machine. That is the case `deploy-before-attack` has to answer for.

## `AI_CURRENT_VICTIM`

`AIUpdateInterface::getCurrentVictim` - `m_currentVictimID` at `this+0x40`, resolved to an
`Object*` (NULL when there is none). `__thiscall`, no arguments, 71 callers. The id is written by
the setter at 0x006682B1, which every attack path in the AI goes through - 27 call sites across
the idle, move, guard, approach and pursue states - and cleared both by `setCurrentVictim(NULL)`
and by the victim's own death (0x00668280), so it cannot name a dead object. This is the one
field that sees an attack however the engine started it.

## `AI_COMMAND_OBJECT_EBP`

`AICommandParms::m_obj`, the command's target `Object*`, at `+0x14` - written by
`AICommandParmsStorage::reconstitute` (0x0075315B) from the stored `ObjectID` through
`GameLogic::findObjectByID`, with no null check, so an id whose object has been removed
arrives here as NULL. The struct travels by value, so in the frame of the transfer check
below it is `[ebp+0x1c]`: `+0x8` for the return address and saved `ebp`, `+0x8` more for the
`Coord3D` at struct offset `+0x8`.

## `SCRIPT_DEBUG_FLAG_HANDLER`

The script debug window, engine side. `-scriptDebug2` and `-scriptDebugLite` both set
`SCRIPT_DEBUG_USE_LITE_DLL`, so both load `DebugWindowLite.dll`; the handle `LoadLibraryA`
returns is kept in `SCRIPT_DEBUG_MODULE`. `SCRIPT_DEBUG_SUPPRESS` is what separates the two
flags - only `-scriptDebugLite` sets it, and it is tested at the head of both the append
wrapper and the adjust-variable wrapper, each of which then does nothing. Derived in
`docs/script-debug-window.md`; the cost this names lives in the DLL, not here.

## `GAME_ENGINE_INIT`

The `-mod` pipeline, and the INI loads that run before it. `GAME_ENGINE_INIT` registers
`TheSubsystemLegend`, loads `Data\INI\Default\SubsystemLegendExpansion1.ini`, then registers
`TheWritableGlobalData` at `GAME_ENGINE_INIT_GLOBAL_DATA_CALL` - which reaches
`SUBSYSTEM_INIT`, the legend loader in `GLOBAL_DATA_VTABLE` slot `+8`, and so `INI_LOAD`s
`Data\INI\GameData.ini`. Only afterwards, at `GAME_ENGINE_INIT_MOD_CALL`, does
`COMMAND_LINE_PARSE_AND_MOUNT_MODS` run `COMMAND_LINE_PARSE` over the 16-entry
`COMMAND_LINE_STARTUP_TABLE` and mount what `-mod` named. Derived in `docs/mod-load-order.md`.

## `GAME_MAIN`

`GameMain(int argc, char **argv)` - `WinMain` calls it at `0x00402CB9` with its own argument
count and the array it built - pushes both again, calls `GameEngine::init` through vtable slot
`+0x38` and tail-jumps into `execute`. It has no frame of its own, so from inside `init` its
return address sits at `[ebp+0x10]` and its arguments at `[ebp+0x14]` and `[ebp+0x18]`, and
nothing between `WinMain` and the end of `init` writes them. `init`'s own `[ebp+8]` and
`[ebp+0xC]` are no substitute past `GAME_ENGINE_INIT_MOD_CALL`: the function reuses both as
scratch (`[ebp+0xC]` from `0x0063AFD3`, `[ebp+8]` from `0x0063BA88`, last at `0x0063CB66`), so
at `COMMAND_LINE_SKIRMISH_SETUP` they hold stack addresses. The `ebp` displacements below are
from `init`'s frame. The CRT builds `argv` (`__getmainargs`), so a quoted argument arrives whole.

## `COMMAND_LINE_MOD_HANDLER_TARGET`

Where the `-mod` handler ends: `AsciiString::operator=` writing the finished absolute path into
whichever `GlobalData` field `_stat` selected. `COMMAND_LINE_MOD_HANDLER_TARGET` is the tail
that picks between the two fields and pushes the source, so at the store `ecx` is the
destination - which is what says whether this `-mod` named a directory or an archive - and
`[esp+4]` is the string. A second `-mod` reaches the same store and overwrites the first.
Derived in `docs/multi-mod.md`.

## `GLOBAL_DATA_MOD_DIR`

Where `-mod` lands. The handler stores an absolute path into one of two `GlobalData`
`AsciiString`s depending on what `_stat` says it is - a directory into `GLOBAL_DATA_MOD_DIR`,
a file into `GLOBAL_DATA_MOD_BIG` - and `MOD_MOUNT_DIRECTORY` is what turns the directory form
on: it copies the path to `MOD_DIRECTORY`, raises `MOD_PREFER_LOCAL_FLAG` and mounts every
`*.BIG` beneath it. Those last two globals are the whole of the file system's mod awareness;
`-preferLocalFiles` raises the same flag with an empty directory.

## `ASSET_CACHE_LOAD`

How the asset cache finds its `asset.dat`, which is not a `TheFileSystem` lookup at all.
`ASSET_CACHE_LOAD` is the loader `W3DDisplay::init` calls with `m_modDir`, `m_modBIG` and a
flag by value; it `fopen`s `<m_modBIG>\asset.dat`, then `<m_modDir>\asset.dat`, then plain
`asset.dat` in the working directory, handing each open file to `ASSET_CACHE_READ_FILE`. So
only the **last** `-mod` is ever consulted, whatever else is mounted.

`ASSET_CACHE_MOD_BIG_TEST` is the `mov eax, [ebp+0xc]` / `test eax, eax` pair that opens the
first of those three attempts, and `ASSET_CACHE_MOD_BIG_BRANCH` the `je` that reads the flags
it sets - which is why a stand-in in front of it has to end on that same pair.

Precedence inside the cache is **first-wins**: `ASSET_CACHE_REGISTER_GATE` lowercases each
asset name and skips the whole registration when `ASSET_CACHE_HAS_ASSET` already knows it, so
the earlier a file is read the higher it ranks. Derived in `docs/multi-mod.md`.

## `ASSET_DAT_NAME`

The `asset.dat` file name and the `fopen` mode the third attempt uses, both already in
`.rdata` as NUL-terminated narrow strings, and the two CRT slots a cave needs to reach them.
`ASSET_CACHE_WORKING_DIR_ATTEMPT` is that whole third attempt - `fclose` on the previous file,
then `fopen("asset.dat", "rb")` - which is the one window that pins both slots and both
strings at once, and so is the anchor to read rather than the slots themselves: an import
table is filled at load time and says nothing on disk.

## `GAME_LOGIC_START_NEW_GAME`

The mid-session map swap, as `LivingWorldLogic::startCampaign` performs it at `0x006B532B`.
Both are `__thiscall` on `THE_GAME_LOGIC`: `GAME_LOGIC_START_NEW_GAME` stages the mode and
promotes `GLOBAL_DATA_STAGED_MAP` over `GLOBAL_DATA_ACTIVE_MAP` (clearing the staged copy),
then `GAME_LOGIC_LOAD_MAP` tears the session down and rebuilds it, reaching the world builder
`GAME_LOGIC_BUILD_WORLD` at `0x0063157B`. Naming the destination means formatting
`MAP_PATH_FORMAT` ("maps\%s\%s.map") with `ASCII_STRING_FORMAT`. Derived in
`docs/map-transition.md`.

## `THE_SCRIPT_ENGINE`

`TheScriptEngine` and the two name-keyed maps holding the state a map script accumulates.
Counters and timers share one map - a timer is a counter record with `SCRIPT_COUNTER_IS_TIMER`
set. Two further sibling maps at `+0x191B8` and `+0x191C4` are name-to-id tables that have not
been told apart yet. All four are `std::map`: the mapped value sits at `STD_MAP_NODE_VALUE`
inside the node, iteration walks `[map + 8]` until it returns to the header, and
`STD_MAP_ITERATOR_INCREMENT` is the step.

## `SCRIPT_COUNTER_VALUE`

A counter record, at `STD_MAP_NODE_VALUE` inside its node. `SCRIPT_COUNTER_IS_TIMER` gates the
countdown at `SCRIPT_ENGINE_TIMER_TICK_SITE`, which decrements `SCRIPT_COUNTER_VALUE` by one per
tick and stops at -1 - so a timer holds ticks *remaining* and never references the frame
counter. `SCRIPT_COUNTER_IS_SECONDS` only records that the value was authored in seconds;
the conversion (`SCRIPT_TIMER_FRAMES_PER_MS * SCRIPT_TIMER_MS_PER_SECOND` = 5 per second,
agreeing with `LOGIC_FRAMES_PER_SECOND`) happens once at write time.

## `THING_FACTORY_NEW_OBJECT`

Making an object and dressing it to match one that no longer exists - the sequence
`RebuildHoleBehavior::onDie` runs at `0x00889B14`. `THING_FACTORY_NEW_OBJECT` is `__thiscall` on
`THE_THING_FACTORY` and takes **four** stack arguments (`ret 0x10`): the template, the owning
`Team`, a pointer to a zeroed `OBJECT_STATUS_DWORDS`-wide status mask, and a fourth passed as 0
at every site read so far. It forwards to `GAME_LOGIC_CREATE_OBJECT` on `THE_GAME_LOGIC`.
Objects are created onto a `Team` (`OBJECT_TEAM`), not a `Player`. Veterancy needs no separate
call: it rides `OBJECT_UPGRADE_MASK` as three engine-registered upgrades at indices 0, 1 and 2
(`docs/live-object-model.md`), so rank and purchased upgrades are one field.
Derived in `docs/map-transition.md`.

## `SCRIPT_ACTIONS_CREATE_UNIT_REVIVAL_ENTRY`

`ScriptActions::createUnitRevivalEntry(AsciiString *player, AsciiString *unit, int level)` -
the body behind `CREATE_UNIT_REVIVAL_ENTRY` (595) and `..._AT_LEVEL` (597), which passes -1 for
"no level". It resolves the player through `SCRIPT_ENGINE_PLAYER_NAME_TO_INDEX` and
`PLAYER_LIST_PLAYER_FROM_INDEX` (which takes a *pointer* to the index), then appends to the
hero ledger at `PLAYER_HERO_LEDGER_OFFSET`. That ledger dies with the player on a map swap, but
this call rebuilds an entry from nothing but the three values a snapshot would hold.

## `SCRIPT_ENGINE_SCOPE`

Counter and flag keys are **scoped**. `SCRIPT_ENGINE_SCOPED_KEY` composes the lookup key through
`SCRIPT_KEY_COMPOSE(out, name, scope)`, taking the scope from `SCRIPT_ENGINE_SCOPE` - the script
player currently being evaluated, empty for globals, and the same string the save chunk records.
A name containing `/` overrides it, so `Player_1/MyCounter` is an explicit cross-scope reference.
Anything writing counters from outside a script must set `SCRIPT_ENGINE_SCOPE` first or it will
create a second, unrelated symbol.

## `SCRIPT_ENGINE_RUN_SCRIPT`

How a script runs. Every execution - the per-frame walk and both call-subroutine paths - reaches
`SCRIPT_ENGINE_RUN_SCRIPT(Script *, AsciiString *name)` (`__thiscall`, `ret 8`), which checks
`SCRIPT_IS_DUE`, reschedules, and dispatches. `SCRIPT_ENGINE_RUN_SCRIPT_NODES(list, node,
validate)` walks one script chain, skipping subroutines; `SCRIPT_ENGINE_RUN_GROUP_NODES(list,
node)` recurses through groups. `SCRIPT_ENGINE_CALL_SUBROUTINE` is the by-name entry the
call-subroutine actions use. `SCRIPT_ENGINE_CURRENT_PLAYER` is the `Player *` being evaluated,
whose AI difficulty wins over `SCRIPT_ENGINE_DIFFICULTY` in the due check.

## `FRAME_DISPATCHER`

The script debugger's pause, derived in `docs/script-debugger.md` §1. The frame dispatcher
runs the client phase (render, camera, input), then asks `SCRIPT_DEBUG_PAUSED` - `thiscall` on
`TheScriptEngine`, plain `ret`, returning `al` - and on true skips the sub-frame advance and the
logic phase. So a pause freezes the simulation and nothing else. The predicate is true only
while `DebugWindowLite.dll` is loaded and its `CanAppContinue` (polled into
`SCRIPT_DEBUG_CAN_CONTINUE` by `SCRIPT_DEBUG_POLL_CONTINUE` just before) said no, so a debugger
without the DLL redirects `FRAME_DISPATCHER_PAUSE_CALL` instead. `SCRIPT_DEBUG_RUN_FAST` is the
`RunAppFast` query the main loop uses to skip rendering - not a pause. `SCRIPT_DEBUG_IS_PAUSED`
is the engine's own "either predicate" query for the rest of the game.

## `SCRIPT_DEBUG_RUN_SCRIPT_LOG`

What a script trace hooks, derived in `docs/script-debugger.md` §2.1. `executeScript` calls the
run-script logger - `cdecl (AsciiString *key, Bool isTrue, Bool pause)` - at the four sites of
`SCRIPT_EXECUTE_LOG_CALLS`, each just before it runs a **non-empty** action list, with the
`Script *` in `esi` and `TheScriptEngine` in `edi` at every one. The sequential path never logs;
it evaluates at `SCRIPT_SEQUENTIAL_EVALUATE_CALL` (`edi` the `Script *`) and queues the true
actions when that says yes. `SCRIPT_ENGINE_EVALUATE` is `thiscall (Script *, 0, 0)`, `ret 0xC`,
answering in `al`; `SCRIPT_ENGINE_RUN_ACTIONS` is `thiscall (ScriptAction *list, Script *,
AsciiString *)`. `SCRIPT_ENGINE_CURRENT_OBJECT` is the team member a team script is running for.

## `SCRIPT_SCOPE_ENTER`

How the per-frame driver (`0x0060CDAA`..) puts a player's scripts in scope, which is what a
script run from outside it has to repeat. `SCRIPT_SCOPE_ENTER` is the constructor of a 12-byte
guard - `thiscall (AsciiString *target, AsciiString *value)`, `ret 8` - that saves `target`
and copies `value` in; `SCRIPT_SCOPE_LEAVE` (`thiscall`, `ret`) copies it back. The value is the
player's name: `NAME_KEY_TO_NAME` (`thiscall` on `THE_NAME_KEY_GENERATOR`, `ret 4`) of the
player's name key at `PLAYER_NAME_KEY`, returning an `AsciiString *`.

## `OBJECT_TO_ARMY_RECORD`

`Object::toArmyRecord(record)` - thiscall on the **Object**, `ret 4`, no living-world state
involved. It fills the same `0xD8` record an `ArmyEntry` parses into: the template name,
`Quantity = 1`, a `0x90`-byte state block and the upgrade list, then copies `Object+0x480` to
`record+0xD0`. `OBJECT_WRITE_ARMY_RECORD_STATE` is the inner half, and it resolves a horde to
its member template rather than writing the horde object itself. `HERO_LEDGER_TO_RECORD` is the
exact mirror for a dead hero's ledger entry, which is why a revived hero keeps the level and
upgrades he died with.

`ARMY_RECORD_CREATE_OBJECT` is the exact inverse and is equally free of living-world state:
thiscall on the record, one argument (the receiving `Player`), returning the new `Object`. It
resolves the template through `ARMY_ENTRY_FIND_TEMPLATE`, creates through
`THING_FACTORY_NEW_OBJECT` onto `PLAYER_DEFAULT_TEAM`, applies `ARMY_RECORD_HEALTH` to the body,
copies `ARMY_RECORD_UPGRADE_LIST` onto `OBJECT_UPGRADE_MASK` (so veterancy rides along), and
pushes the same upgrade list into the object's contain so **horde members** are dressed too.

`ARMY_RECORD_SPAWN` is the loop above it - thiscall on a pointer to the record, `ret 0x10`,
creating `Quantity` copies. It is the layer that pulls in living-world state, resolving the
`Player` from an army id at `record+0x1C`; calling `ARMY_RECORD_CREATE_OBJECT` directly with a
`Player` skips that entirely. `LIVING_WORLD_ARMY_DEPLOY` above *both* is army- and battle-bound
and is not reusable.

## `SPECIAL_POWER_READY_FRAME`

A special power's cooldown, on the power interface. `SPECIAL_POWER_READY_FRAME` is an **absolute
logic frame**, written as `frame + duration` by `SPECIAL_POWER_START_RECHARGE` and compared
against `TheGameLogic`'s frame on demand rather than counted down (`docs/recharge-rescale.md`).
That makes it the opposite of a script timer, which holds ticks *remaining*
(`SCRIPT_COUNTER_VALUE`): anything that restarts the frame counter must rebase this and must not
touch the other. `docs/recharge-rescale.md` §168 has the engine's own after-the-fact adjustment.

## `GLOBAL_DATA_SHELL_MAP`

`GameData`'s `ShellMapName`, row 248 of the field table (`GAME_DATA_SHELL_MAP_NAME_ROW`), an
`AsciiString` defaulting to the full path `Maps\ShellMap1\ShellMap1.map` written by
`GlobalData`'s constructor at `0x0064306B`. Same shape as `GLOBAL_DATA_ACTIVE_MAP`, which is
what makes copying one onto the other a valid way to ask for the shell map: posting
`MSG_NEW_GAME` with the shell's mode does **not** select the shell map by itself - the loader
reads the active map name, so without this the engine reloads whatever is already running.

## `LIFETIME_ALLOC`

`LifetimeUpdate`, the `ToggleMountedSpecialAbilityUpdate` whose swap and retire it borrows,
and the `UpdateModule` contract both sit on. Derived in `docs/lifetime-extend-upgrade.md` and
`docs/lifetime-transform.md`; read by `patches/lifetime_fields.py`, which imports them under
shorter local names.
`LifetimeUpdate::newModuleData`'s `push esi` / `push 0x18` / `call operator new`, and the
`pop ecx` that cleans the argument, which is where the cave rejoins. Eight bytes for a
`jmp rel32` and three of padding.

## `MAP_CACHE_FIELD_TABLE`

The `MapCache` INI block, the `MapMetaData` it parses into, and the lobby map list that
turns that entry into a row. Derived in `docs/map-list-symbols.md`; read by
`patches/map_list_symbols.py`, which imports them under shorter local names.
The `MapCache` field-parse table: 24 rows of `{name, parseFn, userData, offset}` and a NULL
terminator. `offset` is into the parse-time temporary, not into the `MapMetaData` the entry
ends up as - `parseMapCacheDefinition` copies the one into the other field by field.

## `MAP_LIST_COMPARE_KEY`

The map-list comparator's third delta, `a->key - b->key`, and the two instructions
interleaved with it: `mov eax, [ebx+0xF4]` / `mov ecx, [ebp-0x10]` / `sub eax, [edi+0xF4]`
/ `mov ecx, [ecx]`, seventeen contiguous bytes. This arm is what makes `+0xF4` a sort key at
all, and it compares the **whole** dword - so a sort that is to ignore part of the key has to
mask both operands here. `ebx` and `edi` are the two entries, `[ebp-0x10]` the sort
functor, and `edx` is free (the stock code zeroes it four bytes past the resume point).

## `PASSIVE_AREA_EFFECT_CONSTRUCTION_GATE`

The gate that keeps this module quiet while its object is being **built** - including the
rebuild out of rubble, which is a `GettingBuiltBehavior` with `RebuildTimeSeconds`. It returns
the ordinary `PingDelay` sleep, and it sits *above* the dead test, so this module already
resumes when a rebuild finishes rather than when it starts::

    00887e45  mov  ecx, ebx              ; the Object
    00887e47  call 0x0068c3e6            ; Object::getGettingBuiltBehavior -> iface or NULL
    00887e4c  test eax, eax
    00887e4e  je   0x00887e6b            ;   none -> the status-bit fallback
    00887e50  mov  edx, [eax]
    00887e52  mov  ecx, eax
    00887e54  call [edx+0x2c]            ;   isStillBuilding()
    00887e57  test al, al
    00887e59  jne  0x00887ebe            ; yes -> the ordinary sleep

`passive-aura-revive` transcribes this into its cave to give `AttributeModifierAuraUpdate`, which
has no gate of its own, the same behaviour - so both are anchored rather than merely read.

## `ATTRIBUTE_MODIFIER_AURA_GATES`

The whole gate block the patch rewrites, twenty-four bytes::

    0089f441  test byte [esi+0x458], 1   ; effectively dead?
    0089f448  push edi
    0089f449  mov  edi, [ecx-0xc]        ; the ModuleData
    0089f44c  mov  [ebp-0x14], ecx       ; `this`, read back further down the update
    0089f44f  je   0x0089f459            ;   not dead -> the scan
    0089f451  cmp  byte [edi+0x16a], bl  ; RunWhileDead (`ebx` is 0 from 0x0089F43F)
    0089f457  je   0x0089f474            ;   dead and No -> UPDATE_SLEEP_FOREVER

The `push` and the two loads are displaced with the gates because the cave has to re-emit them
before it can test anything, and nothing in the update branches into these bytes.

## `ATTRIBUTE_MODIFIER_AURA_SCAN`

Where the gate falls through to when `RunWhileDead = Yes`, and where the cave sends that case
unchanged: the next gate, `mov eax, [esi+0x11c]`, and then the scan.

**`ecx` must still be `this` when this address is reached.** Ten instructions on, at
`0x0089F469`, the update does `add ecx, 0x10` / `mov eax, [ecx]` / `call [eax]` - the
`UpgradeMux::isAlreadyUpgraded` test - off whatever `ecx` holds, because stock nothing between
the `__thiscall` prologue and there touches it. Anything that calls out before jumping here has
to reload it from `ATTRIBUTE_MODIFIER_AURA_THIS_EBP_OFFSET` first; a `__thiscall` callee
leaves its own `this` in `ecx`, so the read lands ten bytes into the wrong module and calls
through whatever is there.

## `ATTRIBUTE_MODIFIER_AURA_DEAD_SLEEP`

`mov eax, 0x3FFFFFFF` - `UPDATE_SLEEP_FOREVER`. **The patch leaves this stock**, because the
dead arm is not its only reader: the `UpgradeMux::isAlreadyUpgraded` test four instructions
above falls into it too, and for an aura still waiting on its `TriggeredBy` upgrade sleeping
forever is correct - `giveSelfUpgrade` (`0x00855388`) wakes it through this module's
`upgradeImplementation` (`0x008554D6`, a bare `setWakeFrame`). Rewriting it in place would put
every un-triggered aura in the game back on a `RefreshDelay` poll.

## `AUTO_HEAL_UPDATE`

`AutoHealBehavior::update` - slot 0 of the module's `UpdateModule` sub-object, whose vtable is
`AUTO_HEAL_UPDATE_VTABLE`. `this` is the sub-object at module `+0x10`, so the body opens by
reaching back past it: `[this-0xc]` is the `ModuleData` (kept in `ebx` for the whole function),
`[this-0x8]` the `Object`, and `this-0x10` - the module base - is stashed in the frame slot
`AUTO_HEAL_MODULE_BASE_SLOT`. The same `this-0x10` idiom as `LifetimeUpdate` and both aura
modules.

## `AUTO_HEAL_RESPAWN_MEMBER_FIXUP`

The `__thiscall` helper the stock respawn calls on the newly spawned member (`0x00855D80`), with
no arguments and a plain `ret`. It reaches a virtual base through the vbtable at `Object+0x68`,
calls that base's vtable `+0x10`, and hands a non-NULL answer to `0x00B4F410`, which unlinks a
node from a doubly-linked list and frees it. What the node is has not been established; the cave
makes the call because the stock respawn makes it, and one of its ten callers is the engine's own
change-of-owner path at `0x0068DAAE`.

## `AUTO_HEAL_ANCHORS`

Everything the patch reads and does not rewrite. The constructor's vtable store, the vtable slot
and the module-name string identify the function; the prologue names the `ModuleData` register
and the module-base slot; the `AffectsContained` gate and the contain fetch say what `edi` holds
at the hook, and the list destructor abuts it; the delay computation and the write-back say where
the respawn timestamp lives; the respawn block is what the cave transcribes; and the four
routines are the ones it calls.

## `HOT_KEY_TRANSLATOR_MODIFIER_GATE`

The hotkey layer: where a letter typed in game finds a CommandButton, and where a modified
key press is thrown away before it gets there. Derived in `docs/spellbook-hotkeys.md`.

`HOT_KEY_TRANSLATOR_MODIFIER_GATE` is the whole of the stock rule. `esi` carries the modifier
mask in the same vocabulary the `CommandMap` block's `Modifiers` keyword parses (CTRL `0x4`,
SHIFT `0x10`, ALT `0x40`), and `[ebp-0x10]` is the flag handed on to the matched button:

    0075b11d  cmp esi, ebx           ; no modifier at all -> take the key
    0075b11f  je  0x0075b12a
    0075b121  cmp byte [ebp-0x10], bl
    0075b124  je  0x0075b1ac         ; Ctrl or Alt held -> discard the key press

Thirteen bytes, ending exactly on `..._PROCEED`, with no inbound branch into them other than
the `je` being replaced. So Ctrl+letter is dead space in the stock build, which is what makes
it claimable without taking a combination away from anything.

## `HOT_KEY_EXECUTE`

`HotKeyManager::executeHotKey(AsciiString *key, Bool flag)` - `__thiscall`, `ret 8`, `al` set
when the key was consumed. `..._HOOK` is five bytes *past* its game-state gates (a running
game, `TheInGameUI+0x15`/`+0x16` and its vtable `+0x17c`), which is where an addition wants to
sit: the gates have already run and `ebp` is set up, so the arguments are addressable.

    0075af43  push esi              ; the three displaced bytes, re-emitted by the cave
    0075af44  push edi
    0075af45  push [ebp+8]

`ebx` holds the `HotKeyManager` from `0x0075AF06` onwards and both exits below restore it, so
a cave entered here must preserve `esi`/`edi` itself and may leave `ebx` alone.

## `CONTROL_BAR_DO_COMMAND`

`ControlBar::doCommand(CommandButton *, Bool, Bool)` - `__thiscall` on `THE_COMMAND_SET_STORE`
(the ControlBar and the command-set store are the same singleton), `ret 0xC`. This is where a
click lands once the window it came from has been resolved away, so everything a click does -
the targeting cursor, the sounds, `CommandTrigger` - happens here and not in the caller.

Command 0x26 `SPELL_BOOK` is one of the three the selection requirement at `0x00940462` exempts,
which is why a spellbook button fires with nothing selected. Both `Bool`s are read as bytes.

## `CONTROL_BAR_GET_COMMAND_AVAILABILITY`

`ControlBar::getCommandAvailability(CommandButton *, Object *, Int, Real *out, Int)` -
`__thiscall` on `THE_COMMAND_SET_STORE`, `ret 0x14`, answering a small enum and filling `out`
with the button's recharge fraction. Derived in `docs/spellbook-hotkeys.md` §7.

**1 and 2 are the only answers that mean "a click on this does something."** Two independent
sites say so: `doCommand`'s own selection path tests exactly those two
(`CONTROL_BAR_AVAILABILITY_TEST`), and the spellbook bar's update maps them to the only
two movie states it then marks clickable, sending 0, 4, 6 and 7 to a greyed state and skipping
the slot entirely on 3. A no-local-player call returns 3 (`0x0094276B`).

Nothing on the `SPELL_BOOK` path asks it. The bar's buttons are greyed inside the APT movie,
so a disabled one never reaches the engine and the engine never needed the check.

## `CONSTRUCTION_INITIAL_HEALTH_CALLS`

The four places the engine drives a structure's health to exactly **one hit point** because it
is about to be built, as `{call VA: the whole sequence's VA}`. All four are byte-for-byte the
same shape - `push 0` (the `DamageInfo`), `call [vtable+0x10]` (`getHealth`),
`fsubr [FLOAT_ONE]`, `push ecx` to reserve the float slot, `fstp [esp]`, then
`call [vtable+0x84]` (`internalChangeHealth`) - so the hooked call always sees `ecx` = the
body, `[esp+4]` = the delta and `[esp+8]` = a NULL `DamageInfo`.

`0x0079541F` is `BuildAssistant`'s: health, then `Object+0x288 = 0`, then `UNDER_CONSTRUCTION`.
`0x00858975` is `GettingBuiltBehavior`'s rebuild, and `0x008AD88E` the builder placing a
foundation; both set `Object+0x288 = 0` and `AWAITING_CONSTRUCTION` around it. `0x0088D59E` is
the `DozerAIUpdate` helper that restarts a build, which sets `UNDER_CONSTRUCTION` at
`0x0088D616`.

## `PERF_SCOPE_CTOR`

The engine's **named render-scope class**, and the whole of `perf-stage-readout`'s surface.
Thirty `PerfScope` objects are constructed and destroyed per drawn frame, each naming a stage -
`UpdateShadowMap`, `RenderTerrain`, `MeshDX8Render` and twenty-five more - and each opening a
PIX event around it. Derived in `docs/perf-stage-readout.md`.

`PERF_SCOPE_CTOR` is `PerfScope::PerfScope(const char *name, const char *category, int colour)`,
`__thiscall` with `ecx` the object. **The name arrives as a `.rdata` pointer here and nowhere
after**: the constructor's first act is to `strncpy` it into the object, so by the time
`PERF_BEGIN_EVENT` sees it the pointer is a stack address shared by every scope in the same
function. That is why the hook is on the constructor rather than on the D3DPERF wrapper.

## `SPELLBOOK_AI_TYPE_NAMES`

The skirmish AI's spellbook target pickers, and `AI_SPELLBOOK_REBUILD`'s in particular. Derived
in `docs/ai-rebuild-gate.md`.

`SpecialPowerAIType` (row 1 of the `AISpecialPowerUpdate` field table, offset 0xC) parses to a
plain index into the name table below, and a factory switches on that index to build one
behaviour object per type. Each behaviour's vtable slot 7 is its own target picker, so the
chain name -> index -> case -> constructor -> vtable -> slot is what identifies a picker. Every
link of it is asserted as bytes, and the links between them are decoded rather than written
down, so a build that moved any one of them fails to apply.
