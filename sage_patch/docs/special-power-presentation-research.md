# PalantirMovie and InitiateAtLocationSound: BFME 2 and RotWK

The implementation in [special-power-palantir-movie.md](special-power-palantir-movie.md)
adds only the two movie paths described below. The sound fallback remains an
unimplemented proposal.

As of November 5, 2026, the observed `PalantirMovie` limitation is confirmed for
the investigated paths. `InitiateAtLocationSound`, however, depends on the
position passed to the trigger, rather than the presence of a
`SpecialAbilityUpdate`.

Evidence: source analysis and repeatable execution of original x86 code with
modeled engine services. The two movie additions are implemented as
`special-power-palantir-movie`. Actual movie or sound playback has not been
tested in game.

## Reference material and evidence limits

- Open-BFME-2: commit `a43e7c386a0ee706007f0b5d098a0570b98b1bf5`, in the existing
  `~/projects/Open-BFME-2` checkout. The relevant reconstructed functions are
  marked `matched` in `reverse/functions.csv`; they were not recompiled for
  this investigation.
- pySAGE: starting commit `d4872002fdd607a886c54b7573ee6686ec12109b`.
- Inspected binary: `tools/BFME-FILES/game.dat.backup`.
- SHA-256: `5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`.
- PE ImageBase: `0x00400000`; version resource: `2.1.2614.37001`.
- **BFME 2 addresses are RVAs; all RotWK addresses below are VAs.**
  RotWK mappings were derived from actual bytes, INI tables, constructors,
  vtables and calls, rather than a fixed address offset between the games.

The investigation loaded this binary read-only and executed its unchanged
original routines with Unicorn. The modeled engine services are retained for
patch regression tests in `tests/sage_patch/palantir_machine.py`. They model
movie and audio backends, upgrade services, string/vector copies and the queried
update interfaces. Original branches, position forwarding and normal function
returns execute as native x86. The OCL-at-location cases stop immediately after
the base-class call; OCL creation and subsequent update ticks are outside those
cases. Starter tests model the trigger as an observable call; the actual
notification/audio routine was executed separately in full.

## 1. The parameters belong to different phases

The shared RotWK INI table is at `0x00DA5FD8`. Its entries establish these fields:

| SpecialPower field | Offset in the final template | Invocation in the investigated path |
| --- | --- | --- |
| `PalantirMovie` | `+0x5C` | Intent dispatch to a matching update interface |
| `InitiateSound` | `+0x34` | Shared trigger notification, attached to the caster |
| `InitiateAtLocationSound` | `+0x38` | The same notification, additionally gated by `location != NULL` |

These are distinct from `Behavior` fields. `InitiateFX` is at `+0x44` in the
SpecialPower module data and shares the movie's `foundUpdate` branch.
`TriggerFX` is at `+0x48` and is processed by the actual trigger. The Behavior
also has its own `InitiateSound` field; that is not the template field at
`+0x34` investigated here.

### PalantirMovie

BFME 2: `SpecialPowerModuleRva0049466D.cpp`,
`SpecialPowerModule::initiateIntentToDoSpecialPower`, RVA `0x004946F3`.
RotWK: the corresponding identified function at `0x00897E87`.

The RotWK sequence is:

1. Walk the caster's Behavior list at `Object+0x24C`.
2. Query a SpecialPowerUpdate interface; its slot `+0x1C` must accept this
   power's template.
3. Pass the template, target object, target position, CommandOptions and
   waypoint to the matching interface's intent method.
4. Only after finding such an interface, request the movie, InitiateFX and
   the investigated initiation voice path.

The decisive original bytes are:

```text
00897F9C  837DF000      cmp dword [ebp-0x10], 0
00897FA0  0F84EC000000  je  00898092         ; no update: skip the whole block
...
00897FB2  E8F0EAFFFF    call 00896AA7       ; movie from final template, +0x5C
...
00897FD4  E8BED3E3FF    call 006D5397       ; existing client movie request
```

Getter `0x00896AA7` calls `GET_FINAL_OVERRIDE = 0x00688D3C` and copies field
`+0x5C`. An empty movie name skips the request. The client routine also has
its native status check (`0x006D4609`, status mask `7`); reaching the movie
request therefore does not guarantee visible playback.

The condition is more specific than having a SpecialAbilityUpdate: it requires
**a SpecialPowerUpdate interface matching this power**. An unrelated update on
the same object is insufficient. Conversely, this code does not require the
specific class name `SpecialAbilityUpdate`. The intent call returns no success
value that is checked here: the movie accompanies accepted initiation and does
not confirm that the ability's eventual effect occurred.

### PlayerUpgradeSpecialPower

BFME 2: `PlayerUpgradeSpecialPowerDoSpecialPower.cpp`, RVA `0x004C7CAD`.
RotWK: `0x008CC0CC`, identified through constructor `0x008CC022` and the
SpecialPower interface vtable `0x00C74D48`.

This override **never calls the base intent routine**. It checks Disabled,
starts the cooldown, processes the upgrade list and then directly calls
`triggerSpecialPower(NULL)`:

```text
008CC160  6A00        push 0
008CC162  8D4EF0      lea ecx, [esi-0x10]
008CC165  E81DB8FCFF  call 00897987
```

Consequently, the native movie request is missing even if a matching update
exists on the object. Attaching an update alone does not fix this override.
An unknown upgrade template exits before the trigger; a patch must preserve
that abort path.

### OCLSpecialPower

BFME 2: `OCLSpecialPower.cpp`, particularly `doSpecialPowerAtLocation`,
RVA `0x004C3365`.
RotWK: `0x008C75D8`; its base-class call at `0x008C75FC` reaches
`SpecialPowerModule::doSpecialPowerAtLocation` at `0x0089816C`.

The OCL location path reaches the intent routine described above, so its movie
is missing without a matching update. With `UpdateModuleStartsAttack = No`,
the base still invokes the trigger afterward and forwards the target position.
The location sound therefore **does not require an update** on this path.

OCL also has a specialized targetless override at `0x008C73EF`: it copies the
caster's position and uses the base location entry. Such an OCL can request
the location sound at the caster's position without an update as well.

## 2. InitiateAtLocationSound: NULL is the decisive difference

BFME 2: `SpecialPowerModuleTrigger.cpp`, `aboutToDoSpecialPower`,
RVA `0x004939AB`; RotWK: `0x0089713F`.

The existing `SPECIAL_POWER_NOTIFY_TRIGGERED_AND_PLAY_INITIATE_AUDIO` address
names this exact routine. Its caller is the shared trigger at `0x00897987`
(call at `0x0089799F`).

The script system is notified first. Next, `InitiateSound` from the final
template is attached to the caster's object ID. Only the second sound checks
the position:

```text
008971C6  395D08  cmp [ebp+8], ebx       ; ebx = 0
008971C9  7460    je  0089722B           ; NULL: do not construct a location sound
008971CB          ... final override ...
008971D4  83C038  add eax, 0x38         ; InitiateAtLocationSound
...
008971F0          call 006DA67E          ; set position
00897206          call 0066ECE1          ; set player index
0089721A          call [eax+0x64]        ; audio request
```

The following table describes the original, unpatched paths:

| Path | Movie | InitiateSound | InitiateAtLocationSound |
| --- | --- | --- | --- |
| PlayerUpgrade, normal successful execution | No request | Requested | No request: NULL trigger |
| OCL at location, no matching update, StartsAttack=No | No request | Requested | Requested at the target position |
| Targetless OCL, no matching update, StartsAttack=No | No request | Requested | Requested at the copied caster position |
| Targetless base, no matching update, StartsAttack=No | No request | Requested | No request: NULL |
| Base with object target, no matching update, StartsAttack=No | No request | Requested | Requested at the target object's position |
| Base with waypoints, StartsAttack=No | Only with a matching update | Requested | No request: the trigger discards the location |

Requested means the relevant trigger is reached; it does not guarantee audible
playback. Sound definitions, audio settings and the backend still apply.

`UpdateModuleStartsAttack = Yes` skips the immediate base trigger. The update
phase must take over execution. Even then, an update does not guarantee a
position: `SpecialAbilityUpdate::startPreparation` calls
`markSpecialPowerTriggered(0)` in BFME 2. The corresponding RotWK call sequence
at `0x00853E44` is also `mov edx,[eax]; push 0; mov ecx,eax; call [edx+0x38]`.
Vtable target `0x00897D25` forwards to the shared trigger. This is another
confirmed NULL path despite the presence of an update.

## 3. Small patch design

Movie requests and an optional caster-position sound fallback are independent
changes. Both can use the existing INI fields and native backends, without new
template fields, savegame data or ability states. Only the movie additions are
implemented in `special-power-palantir-movie`.

### A. Add the missing movie requests

1. In the intent routine's skipped `foundUpdate == NULL` branch, request the
   movie separately and then jump to the existing end. Limit this fallback to
   `UpdateModuleStartsAttack = No`, the direct starter path. When StartsAttack
   is Yes, a missing update should not show a movie suggesting an ability
   successfully started.
2. Wrap the successful PlayerUpgrade call at `0x008CC165`: request the movie,
   then invoke exactly the original trigger with its original NULL position.
   This site is after the Disabled and upgrade-abort paths.
3. Leave the existing movie request for matching updates unchanged.

A shared movie helper can use getter `0x00896AA7`, its native string copy and
the native destructor, check for an empty name and call `0x006D5397`. That
approach must release the extra string copy on every normal exit and preserve
flags, stack and registers live at the hook. The implemented helper instead
borrows the final template's string for the synchronous request, avoiding an
additional owned copy; the native client copies it before returning.

This adds exactly one movie request on each investigated missing path and no
second request on the working update path. Existing initiation timing is
preserved. Other derived SpecialPower classes that bypass the intent routine
are not automatically covered and need individual investigation.

**Do not simply remove the condition at `0x00897FA0`:** later code in the guarded
block dereferences the matching update. Without an update, that would access
NULL. Adding the movie must not also enable InitiateFX or voices without their
existing conditions.

### B. Optional caster-position sound when location is missing

Only inside `aboutToDoSpecialPower`, after the first sound:

```text
soundLocation = location
if soundLocation == NULL:
    soundLocation = caster position
execute the existing InitiateAtLocationSound branch with soundLocation
```

A detour at `0x008971C6` could replace **this audio routine's own argument copy**
with `Object+0x38` when NULL, then continue at `0x008971CB`. An existing position
would remain unchanged. The routine already sets the player index and calls
the existing audio backend.

Do not substitute this position in the enclosing `triggerSpecialPower` call:
that routine also uses its location parameter for ViewObject, TriggerFX and
range/effect processing. Changing it would affect more than presentation.

This fallback plays a missing-location sound **at the caster**, rather than
automatically at the originally clicked target. If an update discards its real
target position as NULL, playing audio at that original target would require
additional audio-only position forwarding from the update context. The intent
routine stores object targets at module `+0x2C`, but no general location target
coordinate, and does not reset that object ID for targetless calls. The ID is
therefore not a reliable substitute for a lost target position. Preserving the
original target would be a separate, larger change.

### Hook sites and fingerprints

| Purpose | RotWK VA | Original bytes | Continuation |
| --- | --- | --- | --- |
| Movie without matching update | `0x00897FA0` | `0F 84 EC 00 00 00` | Found: `0x00897FA6`; after fallback: `0x00898092` |
| PlayerUpgrade after successful upgrades | `0x008CC165` | `E8 1D B8 FC FF` | Wrapper calls original `0x00897987`, returns to `0x008CC16A` |
| Local location-sound fallback | `0x008971C6` | `39 5D 08 74 60` | Sound block `0x008971CB`; original NULL exit `0x0089722B` |

The complete design would change three windows totaling 16 existing `.text`
bytes, plus appended code and PE metadata. The implemented movie-only patch
uses the first two windows, totaling eleven bytes. The third remains a proposal.

The implementation follows existing sage-patch conventions: check original
bytes and context, allocate the cave with `allocate_section`, detect it through
`find_section`, stage `apply` on a copy, and check hooks and generated code in
`verify`. Preserve the original binary for recovery and reject hooks modified
by unknown patches.

## 4. Compatibility with existing patches

- `addresses/player.py` confirms `GET_FINAL_OVERRIDE`,
  `SPECIAL_POWER_NOTIFY_TRIGGERED_AND_PLAY_INITIATE_AUDIO` and the existing
  music hook `SPM_TRIGGER_HOOK = 0x0089718C`.
- `special-power-music` hooks the override call in the same audio routine,
  hence the trigger, independently of the missing movie call. The proposed
  sound detour is after that site and would not overwrite it.
- `trigger-recharge-list` changes the comparison at `0x00897A21`, outside the
  three proposed windows.
- `hero-mana` has its own availability, payment and update hooks; these do
  not warrant additional movie or sound requests.

The existing patches were applied to memory-only copies of the backup in
both orders:

```text
PASS hero-mana -> special-power-music -> trigger-recharge-list
PASS trigger-recharge-list -> special-power-music -> hero-mana
```

All three existing `verify` checks passed, and the three proposed hook windows
still contained their original bytes. This establishes available sites
relative to those patches; it is not a compatibility test of the proposed
sound fallback or a multiplayer test. The movie patch's own composition tests
are described in [special-power-palantir-movie.md](special-power-palantir-movie.md).

## 5. Validation

Run the implemented movie patch's regression tests from the pySAGE root:

```bash
.venv/bin/python -m pytest tests/sage_patch/test_special_power_palantir_movie.py
```

They check the generated cave and patched original routines. The list below
records the investigation of unpatched original paths using the same modeled
engine services.

That investigation passed **20/20 cases**:

- Four intent cases: no update, matching update, empty movie name and an
  overridden template.
- Three audio cases: NULL, target position and caster position; these read
  from an overridden template.
- Four PlayerUpgrade cases: without/with a matching update, Disabled and an
  unknown upgrade template. Only the two normal cases reach the NULL trigger;
  none reaches the movie routine.
- Four OCL-at-location cases: without/with a matching update, each with
  StartsAttack=No/Yes.
- One targetless OCL case with a copied caster position.
- One present but nonmatching update.
- Three base-class cases: targetless, object target and waypoints.

For routines that return fully, the engine model also checks the stack,
callee-saved registers and SEH chain restoration. The four OCL prefix cases
omit return validation because they intentionally stop before OCL creation.
These checks establish original control flow with controlled services; the
new caves are not executed by that original-path investigation.

The patch tests do execute the new cave and check duplicate movie requests,
trigger ordering and preserved caller state. Actual OCL and PlayerUpgrade
playback, animations, AI, replay, observer and multiplayer behavior still need
in-game acceptance testing.

## Relevant BFME 2 source files

Under `Code/GameEngine/Source/GameLogic/Object/`:

- `SpecialPower/SpecialPowerModuleRva0049466D.cpp`: update lookup and movie guard.
- `SpecialPower/SpecialPowerModuleDo.cpp`: positions in the four base entry points.
- `SpecialPower/PlayerUpgradeSpecialPowerDoSpecialPower.cpp`: direct NULL trigger.
- `SpecialPower/OCLSpecialPower.cpp`: location and targetless OCL entry points.
- `SpecialPower/SpecialPowerModuleTrigger.cpp`: both sounds and trigger side effects.
- `Update/SpecialAbilityUpdate.cpp`: `startPreparation` notifies the trigger with NULL.

Under `Code/GameEngine/Source/Common/RTS/`:

- `SpecialPowerStoreParseSpecialPowerDefinition.cpp`: original field mapping.

Under `Code/GameEngine/Include/GameLogic/Module/`:

- `SpecialPowerUpdateInterface.h`: update interface and template matching.
- `SpecialPowerModuleData.h`: Behavior fields, separate from template fields.
