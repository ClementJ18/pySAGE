# ObjectCreationUpgrade: parameter and rollback report

Checked against Open-BFME-2 commit `a43e7c386a0ee706007f0b5d098a0570b98b1bf5`
and `tools/BFME-FILES/game.dat.backup`, SHA-256
`5481de75b63e22483660ea8097478faef594f90b9ade7de893e092256ba68a26`.
RotWK addresses below are VAs, ImageBase `0x00400000`.

| Parameter | Default | Exact role in this RotWK version |
| --- | --- | --- |
| `DestroyWhenSold` | `No` | On native unupgrade/cleanup, look up the owner's `SlaveWatcherBehavior` and kill its tracked live object. It does not kill the owner, identify every previously spawned object, or reverse granted upgrades. It also applies when cleanup comes from a failed trigger/conflict, not only a sale. Missing watcher/target means no kill. `DeathAnimAndDuration` can then set a death model condition on that object. |
| `UpgradeObject` | none | An **ObjectCreationList reference**, not an Upgrade or Object name. It is parsed/resolved into ModuleData+0x08, but is inert in the inspected RotWK runtime: activation and delayed update never fire it. The small OCL-firing routine at `0x008B838D` has no direct callers or stored function-pointer references. Existing `sage_ini.model.behaviors.ObjectCreationUpgrade.stock_noops` independently records the same limitation. Use `ThingToSpawn` for an actual spawn. |
| `UseBuildingProduction` | `No` | Controls only how a nonempty `ThingToSpawn` is created. No: direct `BuildAssistant::buildObjectNow` with transformed Offset, owner orientation plus Angle, FadeInTime, watcher registration and owner callbacks. Yes: obtain the owner's ProductionUpdate interface, request a production token, and queue that unit template through it. This branch does not perform the direct-spawn offset/fade/watcher setup. |

`UseBuildingProduction = Yes` therefore needs a suitable `ProductionUpdate` on the owner.
If it rejects the queue request, the update returns its one-frame retry and does not yet execute
GrantUpgrade/RemoveUpgrade. If it accepts, those upgrade actions execute immediately after the
queue request, before this routine has seen any produced unit. If no production interface exists,
the spawn is skipped but the subsequent upgrade actions still run. The native cleanup has no
production-queue cancellation call and no newly produced unit ID from this branch.

The ordinary direct-spawn branch calls the native BuildAssistant; a failed direct creation
returns sleep-forever before the upgrade actions. Offset is transformed by the owner's transform;
it is not a fixed world-space coordinate. Actual asset creation, pathing and delivery were not
tested in a running game.

For later `ConflictsWith` conditions, native cleanup clears the executed flag, sets the delay
deadline to `0x3FFFFFFF` and clears the armed flag. This cancels pending delayed creation. A
previously created object remains unless the `DestroyWhenSold` watcher lookup finds it. Previously
executed `GrantUpgrade` and `RemoveUpgrade` actions on the **owner** are not reversed. `ThingToSpawn`
does not store a per-module list of created objects or an ownership record for granted upgrades.

The generalized [upgrade-module-conflicts](upgrade-module-conflicts.md) patch uses this native
ObjectCreation lifecycle, avoids calling it a second time from the generic conflict path, and
fixes the private evaluator's all-vs-any conflict test. It does not introduce arbitrary upgrade
undo or production cancellation.

Confirmed RotWK anchors:

- Field table `0x00C6E2F8`: UpgradeObject +0x08, ThingToSpawn +0x148,
  DestroyWhenSold +0x15C, UseBuildingProduction +0x170.
- UpgradeMux vtable `0x00C6E250`; arming `0x008B8281`; own condition/post-check
  `0x008B8329`; delayed update `0x008B8464`; cleanup `0x008B87C5`.
- Production branch `0x008B84BC`; production-interface lookup `0x0068C327`;
  queue interface slots +0x08 and +0x20; direct BuildAssistant slot +0x38 at `0x008B861E`.
- GrantUpgrade call `0x008B8727`; RemoveUpgrade call `0x008B8746`.

Primary BFME-2 sources:
`Code/GameEngine/Source/GameLogic/Object/Upgrade/ObjectCreationUpgrade.cpp`,
`ObjectCreationUpgradeModuleDataCtor.cpp`, `ObjectCreationUpgradeCtor.cpp`, and
`Code/GameEngine/Source/GameLogic/Object/Update/UpgradeMuxSlotOverrides.cpp`.
BFME-2 ModuleData offsets after the masks differ from RotWK by 0x20; they must not be copied
into RotWK hooks.

Tests in `tests/sage_patch/test_upgrade_module_conflicts.py` execute the patched native dispatcher,
cleanup and production-branch instructions against controlled external services. They confirm
pending cancellation, watcher/no-watcher policy, unchanged granted-upgrade bits, queue rejection,
acceptance and missing production interfaces. They do not constitute in-game asset/playback tests.
