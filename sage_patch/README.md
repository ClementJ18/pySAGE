# ROTWK `game.dat` patching

Reverse-engineering + binary-patch work on the ROTWK SAGE engine (build `2.01.2614.37001`). The
patches below are all engine-level — they apply to any ROTWK install of that build and benefit
every mod on it (Edain among them), not one in particular. All of them target `game.dat` except
eleven, which patch other binaries from the same install. Ten patch `Worldbuilder.exe` —
`worldbuilder-mod`, `worldbuilder-label-assert`, `worldbuilder-silent-errors` and
`worldbuilder-object-typeahead`, plus the six **twins** that carry a game-side patch's INI surface
across to the editor: `desert-weather-wb`, `healing-received-wb`, `herobar-wb`,
`production-condition-wb`, `production-split-wb` and `science-prereqs-wb`. Each twin
lives in the same module as its game-side half. `standalone-launcher` patches the launcher shim
`lotrbfme2ep1.exe`.

Worldbuilder needs twins at all because it is an **assert-enabled build** — it prints
`_INTERNAL defined.` at startup — and keeps its *own* copies of the engine's name and field
tables. A token added to `game.dat` alone is unknown to the editor, and an unknown token in a mask
or lookup parse throws, which ends the editor's startup with exit code 0 and no dump.

> ### ⚠ Experimental patches
>
> Fourteen of the registered patches — **`hero-mana`**, **`second-resource`**,
> **`campaign-select`**, **`standalone-launcher`**, **`headless`**, **`recharge-rescale`**,
> **`live-bridge`**, **`living-world-override`**, **`cooldown-through-death`**,
> **`capture-the-flag`**, **`smart-rally`**, **`special-power-charges`**,
> **`render-rate`** and **`unit-plate-option`**
> — are **experimental: unstable and largely untested.** They live in
> [`patches/experimental/`](patches/experimental/), they are marked `exp`
> by `sage-patch list`, and `sage-patch apply` prints a warning before it touches a byte.
>
> What that means, precisely. The reverse engineering is written up, the assembly is there, the
> patch applies to a clean `game.dat` and `sage-patch verify` confirms the result carries it. What
> is missing is play — enough of it, across enough of what the patch touches, to know the
> disassembly was read right. Some have had a session or two (each one's doc says exactly how far
> it got; `hero-mana`'s and `smart-rally`'s each record a defect that is still open); none has had
> enough. A patch is a
> reading of the machine code and its tests are written from the same reading, so a wrong reading
> passes both — only the running game disagrees.
>
> Expect crashes, desyncs and save/replay incompatibility, **keep the unpatched binary**, and don't
> ship these in a mod release.
>
> The rest of the list is not thereby certified. Entries saying **Runtime-verified in game** are
> the ones observed doing what they claim; the others are merely not flagged.

- **`commandset-limit`** raises the `CommandSet` button limit from its stock **33** to any **N** in
  34..127, plus the INI paging rule needed to surface the extra buttons, and widens the AI's
  set-walk to the same N. The shipped build uses **N = 64**.
- **`commandset-button-upgrade`** lets `CommandSetUpgrade` add **individual command buttons** to
  whatever set an object already shows, instead of swapping the whole set for another one written
  out in INI. A new `CommandButtons` keyword takes a list of `CommandButton` names, each
  optionally pinned to a slot with `:N` and otherwise taking the lowest free one, and several
  such modules on one object **accumulate**. That is what removes the combinatorics: "this unit
  can buy any of four abilities" costs four modules rather than 16 hand-written `CommandSet`
  blocks naming every combination, and a fifth ability costs one more rather than doubling the
  file. The engine already does exactly this for Create-A-Hero (`0x00809FFB` builds a hero's set
  at runtime out of a base set plus a `(button, slot)` list), so the patch reuses that machinery
  rather than inventing it: on each change it rebuilds the union of every applied module from
  scratch, names the result after the base plus the tokens, and caches it in `TheCommandSetStore`
  under that name — which makes the operation idempotent, order-independent and identical on
  every peer. Removal works for free, because `Object::updateUpgradeModules` already resets and
  re-evaluates every upgrade module on every pass. An object carrying no `CommandButtons` module
  runs stock bytes, so the stock `CommandSet` keyword is untouched. Composes with
  `commandset-limit` in either order: the slot bound is read from that patch's own guard byte at
  **run time** rather than baked in. Logic-side, so **every peer needs the same binary**. See
  [`docs/commandset-button-upgrade.md`](docs/commandset-button-upgrade.md).
- **`cah-factions`** teaches the nine-name Create-A-Hero faction enum a caller-supplied list of mod
  sides plus an `All` token, so a `SubClass` can name them in `UsableFactions`.
- **`ai-revive-gate`** makes the AI evaluate a `REVIVE` command button's `NeededUpgrade` before
  recruiting or reviving through it. The engine checks that requirement for the player and for
  `UNIT_BUILD` buttons, but not on the AI's revive path — so hero slots disabled by an
  unobtainable upgrade are player-only restrictions today. The gate applies **only to callers that
  ask `canMakeUnit` directly**, which is only ever the AI's own choice of producer; the ControlBar
  and production come in through `BuildAssistant`'s `+0x64` gate and keep the stock answer.
- **`ai-construction-gate`** stops the skirmish AI queueing production out of a building that is
  **still going up**. "Under construction may not produce" is a real rule, stated in three places —
  the ControlBar, the legacy `AIPlayer::findFactory`, and `ProductionUpdate`'s exit step — and none
  of them is on the path a RotWK skirmish takes. The BFME2-era `SkirmishAI` subsystem has its own
  producer index (a structure enters it the frame its foundation is placed, hero revive slots
  included) and its own picker, which filters candidates on dead / has-a-`ProductionUpdate` /
  not-disabled / **idle** and stops there — and a construction site passes all four, emphatically
  including idle. The patch adds the missing `UNDER_CONSTRUCTION` test to that picker. Note this
  makes the AI **less bad, not less cheaty**, the opposite direction from `ai-revive-gate`: the
  queue takes the money and keeps ticking, but the finished unit is held at the door until the
  building completes, so the AI was paying to stall while a finished barracks next door looked
  equally attractive. AI-only for free — the picker is inside `SkirmishAI` and all six of its
  callers are AI, so unlike `ai-revive-gate` it needs no return-address discrimination. Only the
  picker's "pick one to use **now**" arm is gated; the "could this ever be made here" arm keeps the
  stock answer, because one caller *cancels* an order when that question comes back null.
  **Runtime-verified in game.**
- **`ai-flag-capture-gate`** stops the skirmish AI's flag-capture squads locking onto build
  plots they can never take. `AIFlagCaptureSquad` is one of the engine's *targetless* tactics: it
  builds a one-to-three-unit team named `TARGETLESS_FlagCaptureSquad_<n>_0` and sends it to stand
  on a capture flag. Its picker filters that map's `CAPTUREFLAG` objects on two things only — not
  already allied, and `KindOf CAPTUREFLAG` — then takes the **nearest**. It never asks whether the
  flag can be captured, and settlement / camp / fortress / economy plots are `CAPTUREFLAG` too. A
  plot somebody has claimed carries a structure, so the flag under it cannot be taken until that
  structure is destroyed — and the squad's only release condition is the flag turning allied, so
  there is no timeout. The units are given a plain move onto the flag's position, which is the
  centre of the building standing on it and therefore unreachable, and the move state holds
  `NO_AUTO_ACQUIRE`, which overrides their own `AutoAcquireEnemiesWhenIdle` — a battalion or two
  circling an enemy building for the rest of the match without ever attacking it. The patch adds
  one rejection to the picker: `KindOf BASE_SITE` **and** `ObjectStatus UNSELECTABLE`, which is a
  build plot that has already been claimed. `BASE_SITE` is asked first and on its own, because a
  plain `CaptureFlag` is recaptured by walking onto it whoever holds it and that is the tactic's
  real purpose. Free plots stay targets, so the AI keeps grabbing economy and expansion plots;
  enemy-held plots are already `AIFarmKillSquad`'s job, and it carries the structures on them in
  its own candidate list. AI-only for free — the picker is inside `SkirmishAI` and its one caller
  is the tactic's own update, so unlike `ai-revive-gate` it needs no return-address
  discrimination. Logic-side, so **every peer needs the same binary**. See
  [`docs/ai-flag-capture-gate.md`](docs/ai-flag-capture-gate.md).
- **`rebuild-hole-construction`** lets a structure destroyed **while it is being rebuilt** leave
  its rebuild hole behind again. A creep lair's loop hangs entirely off that hole: breaking the
  lair makes one, breaking the *hole* is what pays out treasure (the `CreateObjectDie` is on the
  hole, never on the lair), and left alone the hole puts the lair back and retires with DeathType
  `FADED` — which is what `DeathTypes = ALL -FADED` on every hole in the data exists to catch. The
  loop has one gap: `RebuildHoleExposeDie::onDie` refuses to create anything when the dying object
  is `UNDER_CONSTRUCTION`, and a lair rebuilt by a hole is `UNDER_CONSTRUCTION` for the whole time
  it rises — the engine's own babysitting loop is keyed on that exact bit. Kill it in that window
  and it is gone permanently: the old hole was destroyed the frame the rebuild began, no new one
  is made, and there is no treasure ever again. The patch erases the six-byte branch. The rule
  moves into the INI rather than disappearing — every die module opens with the shared filter that
  already evaluates `ExemptStatus` against live `ObjectStatus` bits, so
  `ExemptStatus = SOLD UNDER_CONSTRUCTION` restores the stock behaviour per object, which matters
  because the patch is global and reaches a faction's own lairs on their *first* build too.
  Logic-side, so **every peer needs the same binary**. **Not runtime-verified.** See
  [`docs/rebuild-hole-construction.md`](docs/rebuild-hole-construction.md).
- **`combo-horde-recruitment`** lets a horde built from **several `InitialPayload` lines** be
  recruited. A horde is filled by one of two mechanisms and its own `onObjectCreated` picks which:
  placed by a map it calls `createPayload`, which walks the whole payload list; produced by a
  building it returns at its second instruction, because `Object::m_producerID` is set, and the
  *building* fills it instead. That second path runs off a production queue entry, and an entry
  carries exactly **one `ThingTemplate` and one count** — it asks the horde for that template
  through contain-interface vtable slot `+0x24`, whose implementation answers **only when the
  payload list holds one entry** and returns the empty string otherwise. That call site is the
  getter's only caller in the image, so a combo horde's mix has nowhere to go: `findTemplate("")`
  fails, the entry is never re-aimed at the members, and it is freed having produced only the
  container. The patch replaces the six-byte producer read with a `call` into a cave that returns
  the same id unless the payload list holds two or more entries, in which case it returns `0` — so
  a combo horde falls through the untouched `test`/`jne` into `createPayload` and fills itself, the
  way a map-placed one always has. Single-payload hordes reach the branch with the identical value
  and keep the stock building-driven fill, exit sequencing included; the patch needs no keyword
  because the only data it can reach is data that is broken today. Logic-side, so **every peer
  needs the same binary**. **Not runtime-verified.** See
  [`docs/combo-horde-recruitment.md`](docs/combo-horde-recruitment.md).
- **`horde-exit-absorption`** stops a hero recruited **in parallel** with a battalion from being
  absorbed into it. `QueueProductionExitUpdate` — the door every production building pushes finished
  objects out of — remembers exactly **one** horde, in an `ObjectID` at module `+0x40`. It is written
  whenever the object leaving is `KINDOF HORDE`, and cleared only when a whole queue entry has been
  emitted; a battalion's entry is `Slots + 1` objects long, so the field names that battalion for the
  fourteen-odd frames its members take to come out. For every one of those frames the head of the
  same routine resolves that id and **unconditionally** binds whatever is leaving to it:
  `setProducer(horde)`, a formation-slot assignment, `setTeam(horde->m_team)` — and, further down,
  reads the same answer to decide this is not a lone unit, which is what denies the hero its own
  rally-point waypoint so it walks out of the door and is then dragged along by the battalion. Hero
  revives queue in parallel with units, so a hero finishing inside that window is caught by all of
  it. The patch redirects one five-byte `call` into a cave that asks the question the stock code
  never does — does this object belong in that horde? — by walking the horde's own unfilled slots for
  one whose declared payload template is equivalent to the object's, which is exactly the rule the
  slot assignment applies a few instructions later. A rejection hands back NULL, which is the "no
  battalion in the door" answer the engine already has a path for. A `KINDOF HERO` test would have
  been four bytes and wrong: `LothlorienRumil` fields Rumil and Orophin as a two-slot battalion, so
  that member really is a hero and really does belong. Logic-side, so **every peer needs the same
  binary**. **Not runtime-verified.** See
  [`docs/horde-exit-absorption.md`](docs/horde-exit-absorption.md).
- **`production-condition`** adds a **model condition** that is active while a structure's
  production queue is non-empty — training a unit *or* researching an upgrade. The stock engine
  has no such state: the `DOOR_n_*` conditions run *after* a unit completes, as the buffer during
  which it walks out, and `ModelConditionUpgrade` fires on an upgrade's completion. Two **opt-in**
  extras ride the same trigger: `--weapon-set-flag NAME` adds a `WeaponSetFlag`, so a
  `WeaponSet Conditions = NAME` block can give a producer a different loadout while it is busy,
  and `--locomotor-set NAME` adds a `LocomotorSetType`, so `Locomotor = NAME <template>` can give
  it a different locomotor. Both of those tables are read through their terminator rather than a
  count, so each costs a relocation and nothing else, and objects declaring neither are
  unaffected. The bit lives on the logic-side `Object` and is CRC'd, so **every peer must run the
  same patched binary** and replays do not cross.
- **`desert-weather`** adds a third global weather, **`DESERT`**, and a **`SAND`** model condition
  for it to drive - the pairing the engine already has for `SNOWY` → `SNOW`, and only for that one.
  A map carrying `weather = 2` (a plain `Integer` in its `WorldInfo` chunk, which is how the
  engine actually gets its weather - not `map.ini`) then sets `SAND` on every drawable the way a
  snowy map sets `SNOW`, and `WeatherTexture = DESERT …` works too. Note that `SAND` is **not** a
  stock model condition: the patch creates it, out of the same name table `production-condition`
  extends, so the two compose in either order.
- **`desert-weather-wb`** is the authoring half of that, and lives in the same module.
  Worldbuilder's map-settings weather dropdown is
  filled by a loop with a hardcoded member count, so `DESERT` never appears in it - and because
  the OK handler stores `CB_GETCURSEL` unvalidated, opening that dialog on a `DESERT` map and
  pressing OK writes `-1` back into the map and silently reverts it. The patch grows the same
  table and raises that one bound. Dropdown only: the editor *viewport* keeps drawing the
  non-`SAND` variant, which needs Worldbuilder's own model-condition table extended too.
- **`worldbuilder-mod`** gives **`Worldbuilder.exe`** the `-mod` switch the game has, so a mod's
  loose files load in the editor without being packed into a `.big` first. The editor already
  links the whole pipeline - the `-mod` table entry, `parseMod`, `ArchiveFileSystem::loadMods` -
  but all of it hangs off `GameEngine::init`, and Worldbuilder never constructs a `GameEngine`,
  so none of it runs. The patch calls the one function that arms a mod directory from
  Worldbuilder's own startup, just before it reads its first INI. **Pass a map before `-mod`**
  (`Worldbuilder.exe <some>.map -mod <dir>`): Worldbuilder is an MFC app, and MFC otherwise
  claims the bare mod path as a document to open and fails with `Access to … was denied`. Point
  `-mod` at the **subtree** being edited rather than a whole mod - a full one still kills the
  editor partway through startup, where the game handles the same tree fine. See
  [`docs/worldbuilder-mod.md`](docs/worldbuilder-mod.md).
- **`worldbuilder-object-typeahead`** puts a **type-ahead box above the object tree** in the dialog
  every script action's object argument opens - one class, `EditObjectParameter`, reached from two
  places, so it covers every script that names an object type. The tree holds every `ThingTemplate`
  in the game filed under its side and editor-sorting category, and opens with every folder
  collapsed. Each keystroke now selects the first item whose label matches - exact, then prefix,
  then substring, case-insensitively, leaves before folders - and clears the selection when nothing
  matches. `OnOK` is **not** patched: it still reads the selected item's text, so the dialog cannot
  write a name the stock one could not, and a typo falls into the stock "nothing selected" beep.
  The control is added to `IDD` 190 in place, within its stock 292 bytes; the behaviour is one
  extra `ON_EN_CHANGE` entry in a relocated `AFX_MSGMAP`, with no subclassing and no new imports.
  See [`docs/worldbuilder-object-typeahead.md`](docs/worldbuilder-object-typeahead.md).
- **`infantry-lighting`** decides **which kindofs get the map's infantry light environment**. A
  `.map` carries three light sets per time of day - terrain, objects, infantry - and the renderer
  picks the infantry one per render object from a flag set by a single `KindOf` test in the
  model-draw path: `test byte [tmpl+0x109], 5`, i.e. `INFANTRY | MONSTER` and nothing else. So a
  unit that is only `CAVALRY` is lit as scenery, alongside walls and rocks - and because the two
  sets differ almost exclusively in the sun's **ambient** (stock `map mp amon sul fortress`:
  `0.090, 0.071, 0.043` for objects against `0.290, 0.306, 0.290` for infantry, identical diffuse
  and direction), the symptom reads as "mounted units are too dark". The stock cure is to add
  `KINDOF_INFANTRY`, which also buys crush rules, `PATH_THROUGH_INFANTRY`, KindOf filters on
  weapons, armor and powers, and AI target selection. This rewrites the immediate instead: the
  default adds **`CAVALRY`**, `--kinds` names any of the eight kindofs in mask bits 8..15
  (resolved against the image's own name table, not a hardcoded list), and **`--all`** defuses the
  branch so every drawable takes the infantry environment. Nine bytes at each of two sites, no
  cave. Client-side render state only - nothing enters the logic frame or the CRC, so it does
  **not** have to be on every peer and replays cross both ways. Invisible on the maps whose two
  sets are identical, which is 80 of the 103 stock maps and 205 of Edain's 510. **Statically
  verified** - both sites hold their stock bytes in the real binary and apply/verify/detect
  round-trip against it - but **not yet observed in game**. See
  [`docs/infantry-lighting.md`](docs/infantry-lighting.md).
- **`replay-outcome`** writes **each player's final victory/defeat state into the replay**, at
  the frame the recording ends - whether a player left or the game finished. A stock replay
  records inputs, not state, so no chunk says who won and
  [`sage_replay.winner`](../sage_replay/winner.py) has to infer it from who stopped issuing
  orders (and gives up entirely on elimination endings and on AI players). This adds one `0x7D0`
  chunk per player, written straight to the recorder's own file handle just before the `0x1D`
  end-of-recording marker. Client-local: nothing enters the simulation and nothing crosses the
  network, so it does **not** have to be on every peer. **Runtime-verified** on all three endings.
- **`replay-annotations`** writes **each player's score-screen counters into the replay**: units
  and structures built, lost and destroyed, money earned and spent, and the army and base size at
  the closing frame. The engine keeps all of it in a `ScoreKeeper` embedded at `Player+0x3DC` and
  never records a byte of it, so a corpus can count what players *did* but not what it cost them.
  The two destroyed counters are `Int[20]` arrays indexed by the **victim's** `m_playerIndex`, so
  the record is a per-opponent **kill matrix** - in a team game, who actually fought whom. Hooks
  the *other* call of the branch `replay-outcome` hooks (`stopRecording` rather than
  `writeToFile`), so the two compose in either order; client-local, same as `replay-outcome`.
  **Verified statically** - the sites hold their stock bytes and apply/verify/detect round-trips
  against the real binary - but **not yet observed in a recording**. Read back
  with [`sage_replay.annotations`](../sage_replay/annotations.py) and folded into `aggregate`. See
  [`docs/replay-annotations.md`](docs/replay-annotations.md).
- **`skirmish-replay`** makes a **single-player skirmish record a replay**, which the stock engine
  never does, and gives each recording a **timestamp + map** name instead of overwriting
  `Last Replay`. `startRecording` has exactly one caller — the `MSG_NEW_GAME` branch of
  `RecorderClass::updateRecord` — and it whitelists the game mode against `{1, 5}`, the two
  network flavours; a skirmish emits **2** and falls off the end of the list. Everything
  downstream already works: `startRecording` has a complete non-network path that builds the
  header from `TheSkirmishGameInfo`, and the engine's own playback predicate already accepts a
  *recorded* mode of 2. So the patch replaces nine bytes of whitelist and retargets the call that
  names the file. **By default every recording is renamed**, not just skirmishes: the fixed name
  means each game overwrites the last, and a file every player has under the same name is what
  makes replays impossible to collect. That costs the replay menu's Save Replay button, which
  exists only to rescue the file before it is overwritten (`--rename added` keeps the stock
  behaviour for network games). Client-local, like `replay-outcome`. **Gate runtime-verified,
  naming re-test open.**
- **`observer-switch`** makes a **skirmish replay let you change seat** — next/prior player, and
  with it that player's vision, palantir and unlocked spellbook — which a network replay already
  does. The palantir shows the observer bar on two conditions, and the failing one whitelists the
  *recorded* game mode against `{1, 5}`; a skirmish records **2**, so the buttons never appear.
  Nothing downstream is gated: the observer seat is installed on the playback mode, and the switch
  itself re-runs the shroud manager for the new seat. The engine already ships the same predicate
  with mode 2 added, so the patch aims one `call` at it — five bytes, no cave. The natural
  companion to `skirmish-replay`, and independent of it. Client-local. **Runtime-verified in game.**
- **`unit-plate-option`** turns Edain's **unit plates into a player-side toggle** instead of a
  submod, by adding a **20th row to the shell Options screen**. `unit_plate.inc` puts a
  `W3DScriptedModelDraw` tagged `Module_UnitPlate` on 552 unit objects; the shipped game carries the
  draw module but not the model, so the disc is invisible until a submod drops `unit_plate.w3d`
  in — after which it is on forever, for everyone, at one extra render object per unit. Three hooks,
  one cave: the ladder's entry branch (`0x00920602`), where `AptOptions::InitGadgets` is an inlined
  chain of `stricmp`s with no table to extend, so the cave answers for its own gadget and hands
  every other name back; `AptOptions::Save`, spliced in front of the `UserPreferences::write` at
  `0x009204DC` because Save writes only six hardcoded keys; and the `ModelConditionState` `Model =`
  parser (`0x004C2266` — the only dword in the image pointing at it), which substitutes `None`
  unless the preference reads `yes`. The preference is read through a byte-for-byte clone of the
  engine's own `getAllHealthBars`; the row reads it fresh, the model gate once per launch and
  cached. The `off` state is not new behaviour — it is what ships today, and what
  `unit_plate_remover.inc` already produces on 78 child objects. `--model`, `--key` and `--gadget`
  make it work for any model/preference/row triple. **Needs a matching gadget in `Options.apt`**
  (`docs/options-menu-rows.md` §4) — without it the patch is inert, not harmful. Client-local.
  **Static only — not yet run in game.**
- **`observer-command-range`** lets an observer **work a command bar's paging buttons** —
  `PUSH_VISIBLE_COMMAND_RANGE` and `POP_VISIBLE_COMMAND_RANGE` — so what is being bought or
  researched on page two can be read while watching a replay, or after being defeated. Today the
  page is one click away and the click is discarded: `ControlBar::processCommandUI` asks
  `localPlayerIsNotActive` before it dispatches anything at all, and that is true for the length
  of any observed game. Everything else is already right — `getLocalPlayer` redirects to the
  *observed* player when the local seat is inactive, so the whole bar is evaluated against the
  player being watched, and both paging commands come out of the availability evaluator's default
  case as enabled. So the patch retargets that one `call` into a cave that answers "active" for
  those two commands and tail-calls the stock predicate for everything else — five bytes at the
  call site. Every other command stays refused, because the rest of them post `GameMessage`s.
  Client-local, and it needs nothing from the INI.
- **`skirmish-ai-fallback`** gives a faction a **working AI on a map that carries no
  `Skirmish<Faction>` side for it**. A map's sides are capped at 20 — `SidesList::addSide` refuses
  the 21st — so a mod past ten-odd factions runs out of room, and 63 of the 617 shipped maps are
  already full while 106 carry no skirmish side at all. What a faction with no side gets today is
  not a worse AI: `Player::initFromDict` falls into the arm that types it **0 = `PLAYER_HUMAN`**,
  so the slot is a human nobody is driving. The side supplies exactly two things — the `isSkirmish`
  flag that makes `setPlayerType` allocate an `AISkirmishPlayer`, and the faction's AI script
  library, which `prepareForMP` stamps onto the side from *that side's* `DefaultPlayerAIType` and
  `initFromDict` copies onto the player. The patch supplies both without a side: one hook routes a
  side-less AI down the same arm a matched one takes, the other writes the player's **own**
  `DefaultPlayerAIType` into its **own** side dict and calls the engine's single-side library
  loader on it — a stock routine with **zero callers** in the unpatched image. So the faction runs
  `ki <its own faction>`, not a borrowed one. Fallback only: where a `Skirmish<Faction>` side
  exists it still matches first and both hooks return untouched, and no map is edited. Two
  five-byte windows and a 110-byte cave; skirmish only, since the scan it hooks runs only for a
  dict carrying `playerIsSkirmish`. Logic state, so every peer of a game that reaches it needs the
  same binary. **Statically verified** — every anchor holds its stock bytes in the shipped
  `game.dat`, nothing branches into either window, and apply/verify/detect round-trips against it —
  but **not yet observed in game**. See
  [`docs/skirmish-ai-fallback.md`](docs/skirmish-ai-fallback.md).
- **`terrain-resource-exp`** adds a **`GiveNoXP`** boolean to `TerrainResourceBehavior`, so a
  resource spot can pay its owner without levelling its own building. The module hands the integer
  it just deposited to the building's `ExperienceTracker` on every income tick, and no INI field
  separates the two — while the sibling `AutoDepositUpdate` has shipped exactly this boolean, under
  exactly this name, since the stock build. The new field lands in `ModuleData+0x16`, alignment
  padding the constructor never wrote, so nothing grows. **Every peer must run the same patched
  binary**, and a mod using the keyword cannot run without it at all — an unknown field in a known
  block is an INI parse error, not a warning.
- **`unique-production-id`** mints the `ProductionID` **game-wide** instead of per building. The
  stock counter lives on the producer, so every building's first production is id 1 — and hero
  recruitment keys the player's revive bookkeeping on that id, so recruiting a hero from a second
  building while the first is still producing collides, and the click takes the money without
  starting anything.
- **`hero-mana`** ⚠**(experimental)** gives special powers a **regenerating per-object cost** — `SpecialPower.ManaCost`
  for the price of one activation, and `Object.ManaPool` / `Object.ManaRegen` for the caster's
  single pool that all of its abilities draw on. The stock `UnitCost` field cannot do
  this: all three sites that read it ask `Object+0x258` for the horde interface first and, when
  it is absent, branch to *the same label as "cost is zero"* — so on a lone hero `UnitCost` is
  not a weak mechanic, it is a **no-op**. The patch grows `SpecialPowerTemplate` `0x88 → 0x94`,
  relocates both the `SpecialPower` field-parse table (**two** references, the smallest repoint
  here) and the `Object` one (**five**, with no interior reference),
  and enforces the cost at `SpecialPowerStore::canUseSpecialPower` — the one predicate the
  player's UI, the AI and every activation path all share, so **the AI is gated for free**. The
  pool is *computed on read* from the logic frame rather than ticked, which is what lets it need
  no per-frame hook (avoiding a collision with `live-bridge`), no init hook, no destroy hook and
  no savegame change. A `ManaCost` line joins the stock `UnitCost` one in a button's description,
  from the `TOOLTIP:ManaCost` key and carrying **both the price and what the caster currently has**;
  a `ManaPool` line sits under a hero's level on its revive/recruit button. `ManaCost = 0`, the default, leaves a power exactly as it is today.

- **`second-resource`** ⚠**(experimental)** gives every player a **second resource pool** alongside gold, granted per
  tick by `AutoDepositUpdate.DepositAmount2` and seeded per faction by
  `PlayerTemplate.StartMoney2`, and shows it in brackets after the palantir's own number
  (`1000 (50)`), and lets an `Object.BuildCost2` price things in it — a priced button reads
  `Cost: 100 (25)` and is refused when the player is short. The
  counter is `UInt32 pool[20]` in the cave indexed by `Player::m_playerIndex` (no struct growth);
  the new `UInt16` lands in `ModuleData`'s alignment padding at `+0x22` and its default costs
  three bytes, because the constructor's two `Bool` stores collapse into one dword store that
  clears the padding too; and `StartMoney2` lives in a row table keyed by the template's
  `NameKeyType`, because `PlayerTemplate` has no hole (`+0x34` is the `Money` subobject's own
  `m_playerIndex`, not padding). The display needs **no `.apt` and no `.csf`**: like
  `APT:PalantirCommandPoints`, the resource text is formatted by the engine and pushed to the
  movie every refresh, so a second number is one more vararg on a call it already makes — plus
  widening the refresh's change filter, which otherwise leaves the bracket stale whenever gold
  sits still. `--no-hud` keeps the text stock. **Savegames are not supported** — a cave counter
  is not `Xfer`'d, so a load resets the pool. `BuildCost2` lives in the cave too, keyed by
  `ThingTemplate *`: the 2-byte gap at `+0x5E8` that looks free is the template's engine-assigned
  **id**, and the copy at `0x006D24AB` is field-by-field, so growing the struct would not even buy
  the copy — both routes need the same hook inside `copyFrom`. **The AI is out of scope by
  construction**: its unit variants leave `BuildCost2` at 0, and a cost of 0 short-circuits the
  shared gate before the pool is read. **Enforcement is not complete** — structure placement and
  upgrade research are refused correctly but not charged, and cancelling refunds no resource 2.
- **`maintenance-cost`** makes a **negative** `TerrainResourceBehavior.MaxIncome` or
  `AutoDepositUpdate.DepositAmount` **take** that much gold per tick instead of being discarded, so
  a structure can carry an upkeep. There is **no new INI keyword**: `INI::parseInt` is an
  `sscanf("%d")` whose error message reads *"Expected signed integer"*, so `MaxIncome = -5` already
  parses on a stock binary — it is the run-time paths that throw the sign away, at a
  `jle` past the deposit, at the engine's never-round-below-one-gold floor, and at
  `Money::deposit` itself. That last one is why the patch exists rather than being a data change:
  the balance is **unsigned** and `deposit` is an unclamped `add`, so a negative deposited is not a
  charge but about four billion gold. Every charge goes through `Money::withdraw` instead, which
  clamps to what the player actually has, returns what it took and credits `MoneySpent` rather than
  `MoneyEarned`. **A charge inherits whatever scales its module's income and computes nothing of
  its own**, so a `TerrainResourceBehavior` upkeep falls with the faction's
  `ResourceModifierValues` exactly as that spot's income does — stock arithmetic, not code this
  patch wrote — while an `AutoDepositUpdate` upkeep is flat, like its income, unless
  **`auto-deposit-inflation`** is applied too. It is drawn
  with the engine's own red **`GUI:LoseCash`** floating text, so **no `.csf` and no `.apt` edit**,
  and a charge tick grants **no experience** rather than negative experience. Nothing is destroyed
  or disabled for want of upkeep — a player who cannot pay simply pays what they have. Money is
  logic state, so **every peer must run the same patched binary**; and because there is no new
  keyword, a mod using it still **loads** on an unpatched one and silently does not charge. See
  [`docs/maintenance-cost.md`](docs/maintenance-cost.md).
- **`auto-deposit-inflation`** makes **`AutoDepositUpdate` obey the income inflation** the engine
  applies to `TerrainResourceBehavior` and to nothing else. `PlayerTemplate.ResourceModifierValues`
  — the per-building penalty every Edain faction sets — is read in exactly **one** place in the
  image, and it is the *other* income module; a structure paying through `AutoDepositUpdate` pays
  `DepositAmount` flat for ever. In Edain that is not a corner case: the resource spots are
  `TerrainResourceBehavior` and the **castle and camp keeps** are `AutoDepositUpdate`, so a keep's
  40 gold a tick is the one income a player's building count never touches. The hook is a single
  five-byte detour on `cvttss2si eax, [ebp-0x14]` — the instruction where the amount stops being a
  float, and the point both the handicap and no-handicap paths converge on — and the cave
  reproduces the engine's computation instruction for instruction, **including the
  `filter.allow(thisObject, player)` gate**, so a faction whose `ResourceModifierObjectFilter` does
  not accept its keeps is byte-for-byte unaffected. **No new INI field** — it reuses the two
  `PlayerTemplate` fields every faction already declares. **Applying it re-balances a mod on
  purpose**, and it costs one `Player::forEachTeamObject` walk per deposit tick, which is what the
  other module already spends on each of its own. With `maintenance-cost` it scales a **charge**
  by the same instruction that scales an income, which is the only way an `AutoDepositUpdate`
  upkeep becomes inflation-sensitive. See
  [`docs/auto-deposit-inflation.md`](docs/auto-deposit-inflation.md).
- **`command-point-upkeep`** makes a large army **cost a player income**: the more command points
  they have in the field, the less their resource buildings pay. Two new `PlayerTemplate` fields
  declare the curve per faction — `UpkeepCommandPointStep` (how many command points move a player
  one tier; **0, the default, is upkeep off**) and `UpkeepValues` (the percentage of income kept
  at each tier, the last entry held for everything past it). It is not a new mechanic so much as a
  second dial on an old one: `ResourceModifierValues` — the per-building "inflation" every Edain
  faction sets — is read in exactly **one** place, `AutoDepositUpdate::update`, which turns a
  *count* into a percentage and scales the deposit by it. Upkeep swaps the count for command
  points and multiplies the same slot, so the two stack and the engine's "never round income below
  1 gold" floor still applies. Only income the faction's own `ResourceModifierObjectFilter`
  accepts is taxed, because `AutoDepositUpdate` is *all* tick income and would otherwise catch
  captured neutral structures too. The per-faction rows live in the cave keyed by the template's
  `NameKeyType`, not by a pointer — a `PlayerTemplate` is parsed into a **stack temporary** before
  being copied into the store's vector — which is also what leaves **no savegame change and no
  init hook**. The `PlayerTemplate` field table has **one** reference, the smallest repoint here.
  The palantir's command-point readout gains the current loss: `500/1500 (-10%)`, produced by the
  engine's own formatter with a third vararg, so it needs no `.apt` and no `.csf`/`.str` edit
  (a mod's `APT:PalantirCommandPoints` string is a design-time placeholder the engine overwrites
  every refresh). `--no-hud` leaves the text stock.
- **`spell-store-upgrade`** selects a different purchase-science `CommandSet` from the **current
  player's completed upgrades**. A repeatable `PlayerTemplate` field declares each mapping as
  `PurchaseScienceCommandSetUpgrade = Upgrade_Name CommandSet_Name`; names are retained until use,
  then the upgrade is resolved, its `upgradeIndex` is tested against the player's 36-dword mask,
  and the first active mapping whose CommandSet exists wins. Unknown names and no active mapping
  fall through to the untouched stock selector. Only the call at `0x00822ACF` inside
  `AptSpellStore::initializeSpellSlots` is redirected; the shared selector at `0x0071F933` and all
  its other callers remain stock. Closing and reopening the SpellStore re-evaluates the table.
  Runtime selection and fallback have been verified in-game. The patch is intentionally scoped to the SpellStore callsite and composes with the existing PlayerTemplate field-table extension mechanism. The two helper ABIs remain reverse-engineered (HIGH confidence), so the implementation keeps explicit byte assertions, bounds checks, and stock fallback behavior. See  [`docs/spell-store-upgrade.md`](docs/spell-store-upgrade.md).
- **`science-prereqs`** lets **`PrerequisiteSciences` name a science defined later in the file**,
  so a mutually dependent pair (`C` needs `A or D`, `D` needs `B or C`) no longer has to be closed
  from `map.ini`. It is the smallest patch here — one `rel32` and a 16-byte cave — because
  `ScienceType` **is** the `NameKeyType`: `getScienceFromInternalName` computes the key *before* it
  checks the name is known, and `nameToKey` mints a key for a name it has not seen, so a forward
  reference and a backward one store the identical dword. Removing the check cannot produce a
  degraded value, and a key that never gets a definition is one no player can hold, so the group is
  simply unsatisfiable. By default the safety net stays: every name that did not resolve is
  recorded, and a detour immediately after the `initSubsystem` call that loads `TheScienceStore`
  re-checks the list and throws the engine's own message for the first one still missing — the same
  text a modder sees today, because this build's INI handler never adds file and line to begin
  with. `--no-report-missing` drops that half; `--all-keywords` widens the relaxation to every
  science-name keyword by repointing the shared thunk instead. A `map.ini` that defines a `Science`
  block runs after the check and is not covered. **Runtime-verified in game.**
- **`multi-execute-gate`** makes an **`OK_FOR_MULTI_EXECUTE` button respect each selected unit's own
  `EnableOnModelCondition` / `DisableOnModelCondition`**. Today it does not: the ControlBar lights
  the button if *any* member of the selection qualifies (reasonable), and the click then runs the
  ability on *every* member (not). The two rules never meet, because the click emits
  `MSG_DO_SPECIAL_POWER` with the button's `Options` word and an object id of **zero**, and zero
  means "the issuing player's whole selection" — so the logic side gets a `SpecialPowerTemplate` and
  never sees the `CommandButton` the masks live on. Its per-member gate does check required
  sciences, `UnitCost` and recharge; model conditions are simply not among the things it can ask
  about. This adds that one question to the two group loops, by recovering the button from the
  member itself through the engine's own object → command set → button walk — which reads the
  *effective* command set (the three per-object overrides ahead of the template's), so a mod that
  swaps sets at runtime still agrees with the button that was clicked. Two `rel32` and a
  `0xDB`-byte cave; the button stays `OK_FOR_MULTI_EXECUTE`, the loop still visits every member, and
  a member whose own button is disabled is skipped exactly as if it had failed the recharge check.
  This is what Edain's *Ambush of the Wood-elves* command-set swap works around, at the cost of the
  mass trigger. It changes which objects a logic-side order reaches, so **every peer must run the
  same patched binary** and replays do not cross. **Runtime-verified in game.**
- **`attack-requires-damage`** stops a unit **auto-acquiring or right-click-attacking a target it
  cannot damage**. Whether one object can attack another ends, for auto-acquire and for a
  right-click / attack order, in a routine that walks the weapon's nuggets and answers yes if
  **any** nugget's per-victim test accepts the target — with no regard for whether that nugget does
  anything worth attacking for. So a weapon whose only matching nugget is a knockback
  (`MetaImpactNugget`) or an `AttributeModifierNugget` reports itself able to attack something it
  does no damage to, and the unit walks up and "attacks" for nothing — a frequent bug report. The
  patch redirects the **one** `call` that is the attack-eligibility predicate's final answer into a
  cave that repeats the same nugget walk but counts a nugget only when it accepts the victim **and**
  is one of the eight kinds that are a reason to attack: `DamageNugget`, `ProjectileNugget`,
  `DOTNugget`, `DamageContainedNugget`, `DamageFieldNugget`, `GrabNugget`, `HordeAttackNugget`,
  `SlaveAttackNugget`. **A named list, because the engine's own damage getters answer this wrong in
  both directions** — `AttributeModifierNugget`, `ParalyzeNugget`, `FireLogicNugget` and
  `EmotionWeaponNugget` all report "deals direct damage", while `HordeAttackNugget` and
  `SlaveAttackNugget` report neither direct damage nor a sub-weapon and are exactly how their
  weapon hurts the target. Getting that last one wrong is not subtle: a horde acquires with a
  rangefinder weapon whose only nugget is a `HordeAttackNugget`, so excluding it stops **every horde
  in the game** attacking anything at all. **Firing is untouched**: the nugget-level valid-victim
  test the fire loop uses is a different, unhooked call, so a knockback still knocks back once the
  weapon is engaged on a legitimately damageable enemy — it just no longer causes the engagement on
  its own. **No INI change** — the filter is global and reads only data every weapon already has.
  Logic-side, so **every peer must run the same patched binary** and replays do not cross. See
  [`docs/attack-requires-damage.md`](docs/attack-requires-damage.md).
- **`spawn-union`** makes an object with several `SpawnBehavior`s use **all** of their spawns.
  `Object::getSpawnBehaviorInterface` walks the module list and returns on the **first** module that
  answers, so a structure with two of them orders only the first one's slaves to attack, asks only
  the first whether any slave can attack, and finds the closest slave only among the first — which
  is the whole of what `SPAWNS_ARE_THE_WEAPONS` means. The same getter carries a plain bug: a dying
  slave's death is reported to the first behavior alone, and `onSpawnDeath` returns having done
  nothing when the id is not in *its* list, so a second behavior's slaves die with no list removal,
  no live-count decrement and no respawn timer. Both spawn normally either way; spawning is each
  module's own update. The patch replaces the getter — one 5-byte `jmp` and a `0x4A7`-byte cave —
  with one that returns the stock answer for none and for one, and for two or more returns a
  **proxy** whose sixteen slots re-walk the list: `void` methods broadcast, predicates are OR'd
  (asking every behavior, no short-circuit), and `getClosestSlave` re-runs the distance comparison
  the stock implementation does internally, through the engine's own helper. Reentrancy is covered
  by a ring of eight proxies, since ordering slaves runs slave AI that comes back through the
  getter. **This one changes the simulation**, so it has to be on every peer and its replays will
  not play back on a stock build. **Runtime-verified in game.**

- **`trigger-recharge-list`** lets **`OnTriggerRechargeSpecialPower` name several special powers**
  instead of one, so a single ability can reset a whole set of cooldowns.
  `SpecialPowerTimerRefreshSpecialPower` is already a name-matched selector - it walks the object's
  modules and recharges the one whose `SpecialPowerTemplate` carries the name in that field - and
  the stock keyword is simply the singular of it: `INI::parseAsciiString` stores the **first** token
  on the line and the rest is never read, so `= A B` loads on a stock build and silently means `A`.
  The workaround does not exist either, because a second copy of the module needs its own
  `SpecialPowerTemplate` to be driven by and there is only one power being used. This is the
  cheapest patch of its kind here: the field is an `AsciiString`, one pointer to a refcounted
  buffer, so **a list of names is just a longer string** - no `sizeof(ModuleData)` to raise, no
  relocated field-parse table, no constructor or destructor shim. Two edits: the entry's parse
  function (4 bytes of `.rdata`) points at a cave routine that consumes every token on the line, and
  the walk's `AsciiString::compare` (5 bytes of `.text`) points at one that asks whether the
  candidate is *one of* those tokens, whole tokens only and case-sensitive exactly as the compare it
  replaces. A single name comes out byte-identical to stock, which is also what leaves the
  function's other comparison - the early-out when the field names the module's own power -
  correct without being touched. It changes which powers a logic-side activation recharges, so
  **every peer must run the same patched binary**, and a mod writing two names needs it or the
  second is dropped without a diagnostic. See
  [`docs/trigger-recharge-list.md`](docs/trigger-recharge-list.md). **Statically verified - not yet
  observed in game.**

- **`upgrade-grant-lists`** does the same for **`ObjectCreationUpgrade`'s `GrantUpgrade` and
  `RemoveUpgrade`**, so one upgrade can hand out a set and retire a set. Both keywords are
  `AsciiString`s parsed by the same one-token parser, and both are used in one block at the end of
  the module: `findUpgrade(&field)`, then `giveUpgrade` / `removeUpgrade` on the object, each
  behind its own `test eax,eax / je`. That guard is what makes the hook free - a cave that answers
  **NULL** turns the caller's own branch into a skip of the single-upgrade call it would otherwise
  make, so nothing is displaced and the stock path stays in the binary unexecuted. The extra work
  over its sibling is that `findUpgrade` wants an `AsciiString`, not a pointer into the middle of
  one: each token is copied into the cave routine's own frame to be NUL-terminated, bounded at 255
  characters, rather than NUL-ing the separator in the field's shared buffer. Grants still precede
  removals, `ThingToSpawn` - the third `AsciiString` in the same table - is deliberately left
  alone, and the table is located through the single `push imm32` that names it rather than by its
  address, so a patch that relocated it first is followed rather than bypassed. **Every peer must
  run the same patched binary**, and a mod writing two names needs it or the second is dropped
  without a diagnostic. See [`docs/upgrade-grant-lists.md`](docs/upgrade-grant-lists.md).
  **Statically verified - not yet observed in game.**

- **`herobar`** adds **two** kindofs that put an object on the hero bar **without making it
  a `HERO`** — nothing that asks "is this a hero" (armour, targeting, the AI, scripts) answers
  differently for either, and they differ only in how many slots the instances take.
  **`HEROBAR`** is a slot per object, drawn and clicked exactly like a hero's. **`HEROBAR_GROUP`**
  is a slot per *template*: every instance of one `ThingTemplate` shares a single slot, two
  different templates take two, the slot shows **how many members the group has** where a hero's
  shows its rank, and clicking it steps through those members **one at a time**, the way `PORTER`
  steps through porters — `PORTER` differs in collapsing *every* porter into one slot whatever
  template it came from. One application adds both, and a mod picks per template; `--kindof` and
  `--group-kindof` rename the tokens. It is cheap for two
  reasons. The kindofs are free: `KindOfMaskType` is 224 bits with 222 named, so the two new bits
  need no `ThingTemplate` growth and no savegame change, and the table move is 14 references and 6
  counts against `production-condition`'s 16 and 10. **They are also the last two** — nothing else
  can add a kindof to a binary carrying this patch. And the hero bar is already most of the way
  there - `slot+0x16` is a generic **"this slot is a group"** byte the click handler already
  dispatches on, and a group slot is drawn with the *same* ActionScript calls as a hero slot, so
  **no `.apt` edit is needed**. So the patch adds no drawing code at all: objects of either kindof
  join the **hero** list the draw loop already walks, and three small detours around that loop
  clear a per-pass set of templates, send a duplicate to the engine's own "next node, no slot
  consumed" label, and mark the slot it did draw. The membership hooks read either bit; only the
  draw loop narrows to `HEROBAR_GROUP`, which is the entire difference between the two. Stepping needs a cursor per group, which the bar object has no room for, so the
  patch keeps its own: 16 dwords in the cave, indexed by slot, holding the `ObjectID` it last
  selected there - an ID rather than a pointer, because a dead member has to read as "not found"
  rather than as a freed pointer. The badge is free by the same trick as the rest: the number a
  hero slot draws is a single local, filled *before* this patch's draw hook and read only after it,
  and written through the same text field the porter count uses - so writing the member count into
  that local is the whole feature, and the engine's own "has the number changed" test repaints the
  slot when the count moves. The removal pair is not optional for either kindof - the stock
  `onObjectRemoved` accepts only `HERO` and `PORTER`, so without it a dead object's node
  would sit on the list forever. Nor is the pair on the **select all heroes** button, which does
  not ask `HERO` at all: it walks the slot array and selects what it finds, so being on the bar
  was enough to be picked up by it. Two more detours, one on each of its passes, put back the
  question it never asked - `HERO` first, so a template that is a hero *and* on the bar still
  counts as one. Clicking a slot **twice in quick succession** centres the camera
  on the member the first click picked instead of advancing - the mouse button never reaches this
  hook (the movie calls the handler with the button's *name* as its only argument, and the APT
  runtime's event set is Flash's, with no right-button event), so a repeat click is the gesture.
  Its window is **`--jump-window`, 500 ms by default** (`0` turns the jump off), scaled to logic
  frames at runtime with the engine's own float. It is deliberately *not* the porter cycle's
  `SelectNearestBuilderCycleTimeOut`, which an earlier version borrowed: that is 3500 ms, a length
  that suits a porter round and not a double click, and the engine keeps it in a field past the
  slot array that `hero-bar-slots` moves.
  A seventh site, two bytes and no cave, stops a group inheriting the porter's *"select nearest
  unit"* tooltip: the hover handler dispatches on the same `slot+0x16` byte and read it as a flag.
  **A group of one shows `1`** (as a lone porter's slot does) and a veteran member's rank is no
  longer readable from the bar; and the bar is still **16 slots**, so enough distinct groups push
  heroes off the end.
  **Runtime-verified in game, except everything `HEROBAR_GROUP` does on a click or a hover.**
- **`hero-bar-slots`** raises the in-game **hero bar from its stock 16 slots to any N** in
  17..126 (the shipped build uses **21**). Adding `Hero17`+ clips to the movie
  achieves nothing on its own, and fails silently: the ctor registers `_OnBttnHeroSelect` for
  `Hero1`..`Hero16` only, and the draw loop `break`s before it ever names index 17, so the extra
  buttons stay in whatever state the movie parks them in. The ceiling looks like one constant and
  is **ten** — the draw ceiling and the cleanup back edge count from *one*, the other eight from
  zero, and one of them is the vector-ctor's element count, so raising the visible bound without
  it would run every loop off the end of a 16-element array. The array cannot grow where it is:
  `0x48 + 16*0x18` lands exactly on the iteration state that follows it. It moves anyway, because
  **every reference to that state is already a disp32** — so the block slides up by `(N-16)*0x18`
  and the class grows, in 27 same-length immediate rewrites, while the array stays at `+0x48` and
  its four disp8 addressing sites are never touched. **No cave and no assembly**: 38 immediates.
  Client-local, so it does not have to be on every peer and replays cross. The other half is an
  `.apt` edit, and it is the expensive one: on Edain the bar is drawn by **`FactionFrame.apt`**,
  *not* by the `InGameHeroSelect.apt` that ships beside it and is never loaded — the engine names
  slots through `%s/Hero%d/` against a path prefix, so no file name appears in the code and the
  right movie has to be identified from a running game. Both the `apt/` and `apt_widescreen/`
  variants need it, their grids differ, and the loose `_mod/apt/` folder is a source tree that no
  build step packs, so the two `.big`s must be repacked by hand. `docs/hero-bar-slots.md` §7 is
  the procedure. **Runtime-verified in game at N = 21.**
- **`queue-ignore-cp`** adds a **`QueueIgnoreCP`** boolean to `CommandButton`, so a button the
  *engine* presses — a `DoCommandUpgrade`'s `GetUpgradeCommandButtonName`, which is how a power or
  a research recruits a unit on an object's behalf — can queue its unit while the player is at the
  command-point cap. Stock, that press meets the same gate a click does, the cap answers **7**, and
  the whole feature is lost: the upgrade has already been granted and nothing will press the button
  again. **The other half of "queue it now, build it later" is already in the engine** and needed no
  patching: `ProductionUpdate::update` refuses to advance a head entry the player cannot afford in
  command points, and a sibling routine pushes a revive's completion frame out one frame per tick
  while the cap holds — so the unit sits at the head of the queue, charged, with the EVA cue firing,
  and starts building the moment points free up. The field lands in `CommandButton+0x10D`, alignment
  padding between `AutoAbility` and the `KindOfFlags`, so `sizeof` stays `0x2E0`; its default costs
  **one byte** (the constructor's `mov byte` becomes a `mov dword`); and the button's answer reaches
  the gate — which takes `(producer, what, reviveIndex)` and never sees a button — through a dword
  in the cave raised for exactly the length of one `queueCreateUnit` call, by wrapping the
  `UNIT_BUILD` and `REVIVE` cases of `Object::doCommandButton`. **The ControlBar is left stock**, so
  a *visible* button carrying the field is still drawn unavailable at the cap. **Every peer must
  run the same patched binary** — not for the flag, which is transient and identical on every peer
  executing the same order, but for the consequence: an unpatched client refuses a production a
  patched one accepts. And, as with `terrain-resource-exp`, the keyword is an INI parse error on a
  stock build. **Runtime-verified in game.**
- **`hero-recruit-parallel`** stops a hero being recruited from **freezing the production queued
  behind it**. A `ProductionUpdate` keeps units, upgrades and hero revives in one list appended at
  the tail, and `update` advances **exactly one entry per frame** — whichever its picker returns.
  The picker has four rules: a batch already part-produced, a `DOZER`, a revive whose clock has
  reached 1.0, and failing all three **the head, whatever it is**. Meanwhile a revive's clock is
  not the queue's at all: `queueCreateUnit` stamps the current logic frame into the hero's roster
  record at `Player+0x758`, and the entry finishes when `(now − start) / totalFrames >= 1.0`,
  whatever the queue is doing. Those two facts are the whole of the report: a hero queued *behind*
  other entries still finishes on time, because the third rule scans the list and returns a ready
  revive out of order — but a hero at the *head* is returned by the fourth rule every frame, fails
  the completion test, and `update` returns, so everything queued *after* it is frozen for the rest
  of the revive. The patch rewrites only the fourth rule: return the first entry that is **not** a
  revive, falling back to the head when the queue holds nothing but revives. That loses nothing —
  a ready hero is still caught one rule earlier, the command-point stall is separately applied to
  every revive in the queue wherever it sits, and the progress and completion a selected revive
  would get are dead for a revive anyway. **The hero's own revive time is untouched.** Seven bytes
  and a 37-byte cave. Logic-side, so **every peer needs the same binary**. **Not runtime-verified.**
  See [`docs/hero-recruit-parallel.md`](docs/hero-recruit-parallel.md).
- **`command-point-cost`** adds a **`CommandPointCost`** integer to `CommandButton`, so a special
  power or upgrade that **summons** units can be made unavailable while the player has fewer than
  that many command points free. Stock, command points gate *recruitment and nothing else*: the
  cost is a `ThingTemplate` field read by `hasEnoughCommandPoints` from inside the production gate,
  and a summon queues nothing, so it fires at 1500/1500 and the army it makes arrives outside the
  cap. **The refusal is the engine's own.** The ControlBar's availability evaluator already has a
  verdict for this — **7**, which it pushes at `0x00942F47` when the production gate answers "not
  enough command points" — and 7 greys the button and turns a click into
  `GUI:ErrorNoMoreCommandPoints` rather than an order. So the patch answers with that number rather
  than inventing a state, and "free" is the engine's own arithmetic:
  `getCommandPointCap() - Player+0x68`, called rather than read, because the cap is
  `min(base + CPObject bonus + terms, hard cap)` and reading any field short of that disagrees with
  what the engine gates on. The check sits at the **top** of the one evaluator every draw path and
  both click paths go through, not at its exit, and that is forced: `edi` is reloaded eleven times
  inside the function and the `[ebp+8]` argument slot is reused as scratch by four of the command
  cases, so by the time a verdict exists the button is unrecoverable — while nothing is lost by
  answering early, since every refusal the evaluator reaches on its own answers 3 whether it is
  reached or not. The field is an `UnsignedShort` at `CommandButton+0x10E`, the aligned word of the
  same three-byte alignment hole `queue-ignore-cp` takes a byte out of, parsed by the stock
  `INI::parseUnsignedShort` (`0..65535`, against a hard cap of 1500), so `sizeof` stays `0x2E0`;
  its default is a displaced `RequireLevel` store, one instruction *before* the one
  `queue-ignore-cp` widens, so the two compose in either order. **It gates the button, not the
  power**: nothing is charged or reserved, the summoned units still cost their own `CommandPoints`
  as they always did, and a script or the AI's own special-power evaluation is unaffected —
  the AI asks `canUseSpecialPower`, not the ControlBar. Client-side UI only, so it does **not** have
  to be on every peer for the simulation to agree; the keyword, as with `queue-ignore-cp`, is an INI
  parse error on a stock build. See
  [`docs/command-point-cost.md`](docs/command-point-cost.md).
- **`campaign-select`** ⚠**(experimental)** lets the main menu start **any `LinearCampaign`, by name**, instead of the
  two EA compiled in. The shipped `LinearCampaignExpansion1.ini` states the limit itself — *"campaign
  names are basically hard-coded into the game engine … They must be named ANGMAR_CAMPAIGN"* — and
  the binary agrees: each campaign button reaches a callback that differs from its sibling by one
  screen id, and each id reaches a thunk holding one string literal. **Only the name is hardcoded,
  though.** `startLinearCampaign` takes an `AsciiString *` and resolves it through
  `TheCampaignManager`, so every `LinearCampaign` block in the mod's INI is *already* reachable —
  the shell simply had no way to say which. Two facts make saying it cheap: the FSCommand callback
  is handed the movie's whole params string and keeps **only its first byte** (the difficulty
  letter), and the thunk's `AsciiString` is a function-local static behind an MSVC magic-static
  guard, so filling that static and setting the guard bit means the literal is never reached. The
  patch is therefore **one five-byte `jmp`** into a 129-byte cave — no jump-table relocation, no new
  FSCommand registration, no functor construction — and the movie sends
  `GameCode("Expansion1Campaign", "Hard:DWARVEN_CAMPAIGN")`. A params string with **no separator is
  left completely alone**, so a stock `.apt` keeps stock behaviour (`_DEMO` variant included), and
  `BonusCampaign` is untouched. Shell-only and **client-local**: it runs on a menu button press
  before a game exists, nothing enters the simulation and replays cross unpatched builds — same rule
  as `replay-outcome`. The other half is `.apt` work: the movie has to know the names.
  **Runtime-verified in game**: with two instructions inserted into `MainMenu.apt`'s difficulty
  sprite so the `Expansion1Campaign` button asks for `ANGMAR_BONUS_CAMPAIGN`, Solo Play → *An
  Unexpected Party* loaded **laketown** instead of the **Hobbiton** a stock engine can only ever
  give it. That run also put a `sage_apt` round-trip of a **shell** movie in front of the real game
  for the first time — `MainMenu.apt`, the file carrying the corpus's one unresolvable branch.
- **`foundation-rebind`** lets a **`ReplaceSelfUpgrade` keep the settlement plot** its building
  stands on, instead of freeing the flag between the destroy and the create. A plot's occupancy is
  one dword - the `ObjectID` at `FoundationAIUpdate+0x28`, shared with `CastleBehavior`, which
  derives from it - and `setBuiltOnObject` is the whole of the visual mechanic around it: non-zero
  hides the flag and fades it out over 10 frames, zero brings it back over 30. The flag returns not
  because anything is told the building *died* but because **`GettingBuiltBehavior::onDelete`
  actively frees the plot** it finds through `Object+0x78`, and `destroyObject` broadcasts
  `onDelete` to every module **inside the same call** - so the plot is free before the replacement
  exists. (A per-frame `findObjectByID(m_builtOnID)` poll agrees with it, and the plot's
  "what is standing on me" scan is **one-shot**, fired on its first update for map-placed
  structures, so nothing ever re-adopts.) The engine already re-points references from the old
  object to the new one in exactly this function - **for `WALL_HUB`, `WALL_UPGRADE` and
  `WALL_SEGMENT` only**; this adds plots. Two `call rel32` and a `0x12A`-byte cave: before the
  destroy, remember the plot and zero the link `onDelete` would follow; after the create, write the
  new id into the plot's occupant field **directly** rather than through the setter, which would
  reset the drawable's opacity and make the hidden flag blink. Every write is guarded by a proof of
  ownership, so a unit's producer - a barracks, which answers no foundation interface - is never
  touched. This is what Edain's Iron Hills vineyard works around with a hidden flag, a rebuild
  cooldown and a dummy building. **Simulation state**, so it has to be on every peer.
  **Runtime-verified in game.**
- **`standalone-launcher`** ⚠**(experimental)** is the one patch here aimed at **`lotrbfme2ep1.exe`**, the launcher
  shim, and it lets a **relocated install still hand the game a usable token**. Finding and
  starting `game.dat` needed no patch and never did — the shim `chdir`s into its own image
  directory (`argv[0]`, which the CRT seeds from the module path, not from the command line) and
  spawns from there, with the registry nowhere on that route. What is registry-bound runs *after*
  `CreateProcessA` returns: the launcher fills the `game2.dat` shared mapping the engine reads, and
  it does not hold that value — it **decrypts** it, under a Blowfish key built from
  `HKLM\<GameRegPath>\InstallPath` and the **volume serial number** of the drive that path names.
  Copy the folder to a stick, a container or a machine that never ran the EA installer and every
  input to that key is wrong, with nothing refusing: the game is simply handed the wrong plaintext.
  The patch replaces the key schedule and the decrypt with a `strcpy` from **`gi.dat`'s `G4`
  field** — the tenth and last, whose accessor has *zero* callers in the stock binary. 38 bytes in
  place, no cave. It is **not** a way to run a copy you do not have: the `.big` archives and
  `game.dat` are still required and unchanged, and the token gates nothing — the engine starts
  perfectly well without the shim. **The edit is the Edain mod's**, shipped in its install as the
  IDA difference file `lotrbfme2ep1.dif`; what is added here is the frame around it — the two
  `rel32`s re-derived from the function addresses rather than transcribed, nine anchor sites, and a
  test asserting `apply` reproduces the launcher Edain ships **byte for byte**.
- **`headless`** ⚠**(experimental)** makes a run cheap enough to automate: it adds **`-headless`**, **`-renderEvery n`**,
  **`-maxfps n`** and **`-uncapped`** to the command line, and suppresses the per-frame
  `Display::draw` when asked to. The command-line table is extensible in **six bytes** — the
  dispatcher takes it in `ebx` and its length as a `push imm8`, both at one call site, so a cave
  holding a copy of the stock 16 rows plus new ones is reachable without moving an instruction; the
  draw call is a single 11-byte site in `GameClient::update`. **It does not remove the display**:
  `TheDisplay` has 540 unguarded references, so the Direct3D device is still created and the assets
  still load — what stops is drawing. It also does not reimplement `-noshellmap` or `-noaudio`,
  which are stock and do more than set the flags they name; a headless run passes those too. Much
  of what a test rig needs is **already in the retail binary** and needed no patch at all —
  `-file <map>.map` starts a skirmish with no menu, `-file <replay>.rep` plays a replay, and
  `GameData UseFPSLimit` already uncaps the loop — which is what makes this patch small. See
  [`docs/headless.md`](docs/headless.md). **Runtime-verified in game.**
- **`production-split`** gives each of `PRODUCTION`'s meanings its own `ModifierList` keyword:
  **`PRODUCTION_MONEY`** (resource output), **`PRODUCTION_UNIT`**, **`PRODUCTION_UPGRADE`** and
  **`PRODUCTION_CONSTRUCTION`** — the last of which `PRODUCTION` never reached at all, because a
  structure going up advances in one place the modifier system was never wired to. The engine had
  already done the separating: type 13 is read at eight sites that fall into exactly those
  buckets, so five of the six hooks are **one extra factor at a call that already asks for it**,
  and the queue's two keywords come out of **one hook** reading the entry kind at `entry+0x04`.
  `PRODUCTION` is left alone, so the patch is a no-op until INI uses the new names. The only
  structural work is the modifier-type name table, which has no slack and is rebuilt in the cave.
  The AI's three valuation sites are opt-in (`--ai-sites`). **There is deliberately no
  `PRODUCTION_HERO`**: heroes are a third queue kind, but a hero's completion is decided by the
  player's hero ledger rather than by the queue accrual this patch hooks, so the keyword measured
  live as a progress bar that ran to 480% while the hero arrived on schedule. Kind 3 is handed
  back to the stock callee untouched. See
  [`docs/construction-speed-modifiers.md`](docs/construction-speed-modifiers.md). **Runtime-verified
  in game for the queue hook; the money and construction hooks are not.**
- **`healing-received`** adds **`HEALING_RECEIVED`**, a `ModifierList` keyword that multiplies
  **how much healing its target takes**, from any source — `25%` is a quarter, `200%` is double,
  `0%` is immune to healing. It is one five-byte `call` swap, because every heal in the engine
  becomes a `DamageInfo` of type 7 and funnels through a single `fstp` in
  `ActiveBody::attemptHealing` where the amount exists exactly once and the healed object is
  already in `edi`. The engine's own `<= 0` test sits below the hook, so a zero multiplier makes
  the whole tail disappear — no health change, no healing observers — rather than needing an arm
  of its own. Complementary to `AUTO_HEAL`, which is additive, read once and read on the *healer*.
  Nothing changes until INI uses the name. Shares the modifier-type name table with
  `production-split`; both read it live and compose in either order. See
  [`docs/healing-received-modifier.md`](docs/healing-received-modifier.md). **Statically verified;
  not yet runtime-verified.**

- **`large-group-bonus-filter`** lets a **`LargeGroupBonusUpdate` count objects that are not in a
  horde**. `HordeMemberFilter` is an ordinary `ObjectFilter` — nothing about its grammar is
  horde-specific — but it is **never evaluated against the object the scan returned**: it is only
  ever passed one level down, to that object's *contain* interface, which counts its own contained
  members against it. `Object::getContain` answers NULL for anything with no contain module, and the
  same test runs **twice** — in the partition filter the scan is given, and again in the accumulator
  — so a lone hero or a unit outside a horde is not merely uncounted, it is never even returned. A
  new `CountLooseObjects` boolean makes both gates put a container-less candidate to the filter
  directly, counting a match as one. The flag costs **no allocation**: `AlliesOnly` is written with a
  *byte* store, so `+0x19`..`+0x1b` is padding and `sizeof` stays `0x30`; the field table has
  **one** reference, the cheapest relocation here alongside `science-prereqs`; and the widened
  `allow` is reached by installing a 12-byte cave **copy** of the wrapper vtable rather than editing
  the stock one, so an unwidened module stays byte-identical. The source player relationship tokens
  need is not in a frame slot — gate 2 reads it from `ebx`, and gate 1 from the wrapper's own `+4`
  dword, which the engine zeroes and never reads. Two things it deliberately does **not** fix:
  `AlliesOnly` is parsed and read by nothing (the scan is hardcoded same-player in a partition
  filter shared with twelve other sites), and `FlagSubObjectNames` can only ever be *hidden* — the
  visibility byte it would be shown from is written once, to zero, in the constructor. **Every peer
  must run the same patched binary**, and the keyword is an INI parse error on a stock build.
  See [`docs/large-group-bonus-filter.md`](docs/large-group-bonus-filter.md).
  **Runtime-verified in game.**

- **`lifetime-fields`** adds three fields to `LifetimeUpdate`. **`ExtendedByUpgrades`** and
  **`UpgradeLifetimeBonus`** make gaining one of those upgrades push a summon's death **back by
  that many milliseconds**; **`ExpirationTemplate`** makes the module **turn the object into
  another one instead of killing it** when the time runs out. Each is armed by its own keyword,
  and a block declaring none of them runs stock bytes. The framing is the surprise: **there is no
  timer to extend**. `LifetimeUpdate` rolls one duration in its constructor, stores an absolute
  death frame and sleeps to it; `update` runs *once*, on that frame, and kills the object without
  ever reading the clock. So the extension itself is one `add` - and the whole cost of the patch is
  *noticing when to do it*, because the engine has no "an upgrade arrived" hook a non-upgrade
  module can subscribe to. The module therefore polls, and the engine already ships the shape of
  that **inside the function being hooked**: `update` opens with "if this object is a
  `THROWN_PROJECTILE`, come back next frame", which is how a rock in flight refuses to expire. The
  trigger is the mask going **empty → non-empty**, latched in a byte of instance padding, because
  an upgrade already held cannot be granted again - so a permanent player upgrade fires once per
  object (including on the first poll of one created while it is already held, which is what makes
  "this research makes every summon last 5 s longer" work) and an object-scoped one re-arms when
  something strips it. Five edits, and three of them cost almost nothing: `ModuleData` grows
  `0x18` → `0xac` for the mask and the bonus (**one hook**, because the `newModuleData` thunk is
  LifetimeUpdate's own, and it zeroes them there so the constructor keeps every store it had), the
  field table is rebuilt in the cave for its **one** reference, and the edge latch's default is a
  single opcode byte - the constructor's `mov byte [esi+0x28], al` widened to a dword, clearing
  tail padding the instance already carries. **No parse code and no arithmetic**: the mask row
  names the engine's own `parseUpgradeMask`, the bonus row names the duration parser `MinLifetime`
  and `MaxLifetime` already use (milliseconds in, frames out, scaled by the live logic rate), and
  the cave calls the engine's own `testForAny` against the object's completed mask and its
  player's, so "is it held" is answered exactly as `TriggeredBy` answers it. **The in-world timer
  follows for free**, which is not obvious and had to be established rather than hoped for: the bar
  over a summon is `(die - now) / (die - start)`, recomputed every frame from the live module, so
  an extension grows both terms and the bar jumps up and drains over the new total - whereas
  *pausing* the clock would freeze the numerator while the denominator kept growing, draining the
  bar over an object that is not dying. The honest cost: an object carrying the field **wakes every
  frame for its whole lifetime**; one that does not pays a single 36-dword scan on the frame it
  dies and is otherwise byte-identical. **Every peer must run the same patched binary** - this
  decides when objects die - and the keywords are an INI parse error on a stock build. Savegames
  need no version bump, at the price of one quirk: the edge latch is not xfer'd, so a still-held
  upgrade pays its bonus once more on the first poll after a load. See
  [`docs/lifetime-extend-upgrade.md`](docs/lifetime-extend-upgrade.md). **Runtime-verified in
  game.**

  **`ExpirationTemplate` is the same module's other half, and it costs almost nothing** because the
  transform already exists: `ToggleMountedSpecialAbilityUpdate`'s mount swap is a self-contained
  `__thiscall` that reads the `ModuleData` at `+0x04` and the `Object` at `+0x08` off the module it
  is called on, writes a success flag at `+0x8c`, and makes **no virtual call on it** - and of that
  `ModuleData` it reads only the template name at `0xd8` and the timer-sync vector behind it. So
  the `ModuleData` grows to `0xe8`, which is that module's own `sizeof`, the new row lands exactly
  where `MountedTemplate` lands, and the cave builds a module-shaped scratch **on the stack**,
  hands it the real pair and calls the stock swap and the stock retire. Health, experience, team,
  position, facing, selection and contained passengers move exactly as they do when a hero mounts,
  because it is the same code. The hook is `update`'s `ScoreKill` compare and the `push esi` behind
  it - five bytes of two whole instructions - rather than the kill twenty lines below, and that is
  not cosmetic: the `ScoreKill = No` arm calls `ScoreKeeper::addObjectBuilt(obj, -1)` and **so does
  the swap**, so a hook under it would walk the owner's "units built" down by one per transform.
  A refused swap (no such template, or a build the engine will not make) falls through to the stock
  death rather than leaving something immortal, and the retire is a `destroyObject`, not a kill -
  no `DeathType`, no death FX, no `SlowDeathBehavior`, nothing scored. What this replaces in mod
  data is a four-module contraption: a hidden `CommandButton` fired by a delayed upgrade, with a
  `LifetimeUpdate` a few seconds longer standing behind it as a backstop - and because the button
  is a special power it can be *refused*, at which point the backstop kills the unit instead of
  reverting it. Ability cooldowns are the one thing that does not carry across yet. See
  [`docs/lifetime-transform.md`](docs/lifetime-transform.md). **Not runtime-verified.**

- **`upgrade-description`** keeps a `CommandButton`'s **`DescriptLabel` visible after its upgrade is
  researched**, with *"this upgrade has already been researched"* appended **under** it instead of
  written **over** it. Stock, the description is simply gone the moment you own the thing it
  describes - which is the one moment a player most wants to re-read what it did. The cause is not
  a design decision but one call: the ControlBar's tooltip builder assembles the description in a
  single `UnicodeString` at `ebp-0x18` and adds every other status line to it with
  `UnicodeString::concat`, and this case alone reaches the **adjacent** method
  `UnicodeString::operator=`, which releases the buffer it is holding before taking the new one.
  So the fix is nine bytes of engine and a 0x41-byte cave: concatenate rather than assign, with the
  engine's own `L"\n"` in between and the engine's own *"is there anything to separate from"*
  guard - the null-pointer plus zero-length pair the `CONTROLBAR:Requirements` and
  `TOOLTIP:BuildDisabled` folds use twenty lines earlier - so a button carrying no `DescriptLabel`
  comes out **byte-identical to stock** rather than gaining a leading blank line. **No `.csf`, no
  `.apt`, no INI keyword**: the strings it joins are the two the engine had already fetched, the
  button's own `PurchasedLabel` or `TOOLTIP:AlreadyUpgradedDefault`. `--separator blank-line` puts
  a blank line between instead; `--also-blocked` gives the *conflicting upgrade* and *lacks
  prerequisite* messages the same treatment, which is the identical nine-byte shape one
  `CommandButton` field along. Deliberately **not** widened: a researched upgrade's tooltip still
  shows no cost line, because there is nothing left to buy. Client-local and read-only - nothing
  enters the simulation, so a patched and an unpatched client can play each other and replays
  cross, same rule as `replay-outcome`. See
  [`docs/upgrade-description.md`](docs/upgrade-description.md). **Runtime-verified in game.**
- **`recharge-rescale`** ⚠**(experimental)** makes a cooldown **already running** respond to a recharge modifier that
  arrives after the cast — a leadership aura, a temporary `RECHARGE_TIME` buff, the player
  finishing a `SpellRechargeModifierUpgrade` mid-match. Stock, none of those can touch it:
  `startPowerRecharge` computes the whole cooldown once, when the power fires, and stores an
  **absolute ready frame**, so a discount only ever pays off on the *next* cast. The fix is cheap
  for a reason that is not obvious until the layout is read: the module stores the cooldown
  **twice** — the ready frame at `interface+0x08`, and beside it the *length* of the cooldown that
  produced it, `max(1, ftol(ReloadTime * m))`, which exists to draw the button clock. That second
  field is the record of the multiplier baked in at cast time, so recomputing the stock formula now
  and comparing the two **integers** says whether anything has moved — exactly, with no tolerance
  to choose — and the patch needs **no per-module storage, no struct growth and no INI keyword**.
  When they differ it rescales the remainder, `remaining * frames_now / duration`, and stores the
  new duration. That is not an approximation of a per-frame rate, it **is** one: the stored
  remainder is the unscaled work times the multiplier, so a modifier held for part of a cooldown
  produces the same finish frame as integrating a rate over that interval, and "150% cooldown speed
  removes 1.5 seconds per second" falls out rather than being aimed at. The clock follows for free
  and **does not jump**, because numerator and denominator are scaled together — writing the ready
  frame alone, the tempting one-liner, would snap the pie forward when an aura landed and back when
  it expired. There is **nothing to tick**: a cooldown is an absolute frame, so nothing runs while
  it elapses and most special-power modules are not update modules at all — so the driver is a
  sweep of the logic's own object list, from the one `call` whose flags gate the frame counter
  (`0x0062E56A`), which is what keeps it in step across peers; `live-bridge` owns the *entry* of
  the same function and the two compose. Two things are left alone and both fail closed: the
  **second** `startPowerRecharge` at `0x00991500` (3 module vtables of 26) keeps no duration and so
  cannot say what it baked in, and `SharedSyncedTimer` powers keep their frame on the `Player`.
  Four bytes of `.text` and a 405-byte cave. **Simulation state**, so every peer needs the same
  binary and replays do not cross — but a **no-op on data that never moves a multiplier
  mid-cooldown**, since the rescale is gated on the stock formula's own answer. See
  [`docs/recharge-rescale.md`](docs/recharge-rescale.md).

- **`capture-the-flag`** ⚠**(experimental)** adds a **`ProximityCaptureUpdate`** behaviour that
  captures its own object for whichever player is **standing on it**, rather than for whoever
  right-clicked first. `ObjectFilter` says what counts, `Radius` how far, `TickRate` how often (in
  **milliseconds**, since it inherits a `Duration` reader), `TickAmount` how much of 100 a tick is
  worth, and `CaptureShare` what percentage of the units present a player needs to be the
  contender; `CountHordeMembers` counts a horde's members rather than the horde, which in BFME is
  the difference between a percentage that means something and one that scores a ten-man horde and
  a lone hero alike. A contender's progress rises, a rival's drives it down, at zero the claim
  passes over and at 100 the flag joins the contending units' team - **along with every
  `LINKED_TO_FLAG` object in the same radius**, which is how "capture the flag, get the shipyard"
  works: a `ShipWright` carries that kindof and not `CAPTURABLE`, so a flag is its only route and
  no map script is involved. Ownership goes
  through the engine's own `setTeam` with notifications **on**. **Known gap:** a captured
  structure keeps its neutral command set - the faction trigger a `CommandSetUpgrade` gates on is
  not re-evaluated for the new owner (doc §6.025). **A stock capture flag carries
  no capture logic at all** — it is a body, a die, an AI stub and a draw, and the capture lives on
  the *unit*, as a `SpecialAbilityUpdate` with a `PreparationTime` — so this adds a behaviour
  rather than replacing one, and the stock right-click path can stay alive beside it. No new art or
  strings: the shipped `CaptureFlag` already animates `START_CAPTURE`, `CANCEL_CAPTURE` and
  `CAPTURED`, which are exactly the three conditions the
  module sets. **It is `AutoFindHealingUpdate`, adopted**: that module is registered by the engine
  and used by nothing in any `.big` the install ships, and it is already a periodic-scan
  `UpdateModule` whose `ScanRate` and `ScanRange` sit at the two offsets wanted for `TickRate` and
  `Radius` — so the block is renamed with three `imm32`s and its behaviour changed with one dword in
  a vtable private to the class. **`AutoFindHealingUpdate` therefore stops existing.** Logic state,
  so **every peer must run the same patched binary** and replays do not cross; progress is an
  integer on a 0..100 scale and the share test an integer cross-multiply, so no float enters the
  comparison. Saves keep the flag's owner (that is `Object` state) but not a part-finished bar,
  which resets to zero identically on every peer. See
  [`docs/capture-the-flag.md`](docs/capture-the-flag.md).
- **`cooldown-through-death`** ⚠**(experimental)** carries a hero's **special-power cooldowns
  across a citadel revive**, under two new `SpecialPower` booleans:
  `PersistCooldownOnDeath = Yes` means a hero who dies halfway through a cooldown comes back
  halfway through it, and `CooldownTicksWhileDead = Yes` lets the cooldown keep *elapsing* while
  the hero is dead, so a long enough death clears it. Both default `No`, which is stock. **A hero
  has two ways back and only one of them loses anything**: `RespawnUpdate` respawning in place
  teleports *the object that died* to the keep, so its cooldowns were never lost, while the
  citadel revive builds a **brand-new** object through `TheThingFactory` and re-applies a snapshot
  taken at death — which is why the fix is not a gate to flip but one more field in a snapshot the
  engine already takes. Nothing in the engine clears a cooldown on death: `setReadyFrame` has four
  callers and they are three script actions and `HeroDie`, which clears the one power named on it.
  The two keywords live in **`SpecialPowerTemplate`'s interior padding** at `+0x5A`/`+0x5B`, so
  `sizeof` stays `0x88` and the three `operator new(0x88)` sites are untouched — three single-bit
  opcode widenings zero them in the constructor and carry them through a `DefaultSpecialPower`
  block. Two `call rel32` hooks (the revive-list add, the upgrade-mask restore), the field table
  rebuilt with two rows, and a cave that — alone in this package — **writes**: 1024 slots of
  banked `(readyFrame, duration, deathFrame)`, released by the restore that reads them and dropped
  wholesale when the logic clock goes backwards, which is how a new match or a savegame load stops
  inheriting the last one's. **Not in a savegame**: a save and load between the death and the
  revive loses the snapshot and the hero returns ready — stock behaviour, not a corrupt one. See
  [`docs/cooldown-through-death.md`](docs/cooldown-through-death.md).

- **`description-timers`** puts **how long a button's thing takes** at the bottom of its
  description: a special power's **cooldown** — its full length while the power is ready, the
  **time left** while it is recharging — a unit's or structure's **build time**, and an upgrade's
  **research time**. Every number is the engine's own, which is what makes "with the reduction
  applied" free rather than a second feature: the cooldown is
  `SpecialAbilityUpdate::startPowerRecharge`'s arithmetic transcribed instruction for instruction,
  so a `RECHARGE_TIME` aura that is up *right now* and a researched `SpellRechargeModifierUpgrade`
  are both in the figure; and the two build times are the same `calcTimeToBuild` pair
  `ProductionUpdate` asks for a queue entry's total, so the tooltip cannot disagree with what the
  game then does — the producer's `ProductionModifier` time multiplier is applied inside the call.
  The line goes at `0x008086AE`, the one instruction past the point where every case of the
  builder's switch has converged, which is what makes it genuinely **last** where a per-case site
  cannot be. The price of being that late is that `esi` no longer holds the builder's `this` —
  three cases reassign it — so a **second six-byte window** in the prologue copies the
  `CommandButton` into the cave; the builder has one caller and runs on hover, so the copy cannot
  go stale. **Silent unless the mod declares the string**: the engine's text fetch has an `exists`
  out-parameter all twelve stock callers pass `0` for, and passing a real one drops the whole line
  when the key is missing — so on a string table without `TOOLTIP:Cooldown`,
  `TOOLTIP:CooldownRemaining`, `TOOLTIP:BuildTime` and `TOOLTIP:ResearchTime` the tooltip is
  byte-identical to stock. Two limits stated rather than hidden: **the tooltip is built once per
  hover** (`0x00DE8998` latches and the same-request path returns early forever after), so the
  remaining cooldown is a snapshot taken when it appeared rather than a countdown; and hero revive
  buttons are **skipped**, because a hero's time comes off the player's ledger and not off its
  `ThingTemplate` — tested with the engine's own hero bit, so the failure is a missing line, never
  a wrong number. Client-local and read-only, so replays cross and peers need not match, same rule
  as `upgrade-description`. See
  [`docs/description-timers.md`](docs/description-timers.md). **Static only — not yet observed in
  a running game.**
- **`binary-attest`** folds a hash of the game's **own code** into the frame checksum, so a peer
  running a modified `game.dat` goes **out of sync** instead of playing. It exists because of what
  the RE found on the way: **fog of war is already in the sync hash** — the CRC producer at
  `0x00625886` xfers `TheShroudManager` like every other logic subsystem, gated only by the
  `-xShroudCRC` debug flag — so a maphack that writes revealer counts into the grid already
  desyncs. What that cannot reach is a cheat that changes no state at all: the fog byte at
  `ShroudImpl+0x68` is read at *lookup* time and clearing it leaves every shroud level
  byte-identical. Only the code differs, so only the code is left to attest. One hook at the
  `MSG_LOGIC_CRC` emitter's join (`0x0062E7FD`, where both producing paths converge) XORs an
  FNV-1a fold of `.text` plus the cave's own code into `edi` before it goes on the wire; the
  engine's existing `GameCRCMismatch` machinery does the rest, with no new message type. Computed
  once and cached, ~135 bytes of code. **Replay playback is exempt** (`TheRecorder` mode 1) so old
  recordings still play and `sage_verify` can follow one, and that exemption cannot conceal
  anything — a live client that skipped the mix would desync against its peers anyway. Because the
  image has no `.reloc`, the value is a property of the *file*: `expected_hash` recomputes it
  offline and `sage-verify attest` compares it with a running process. **Every peer must run the
  byte-identical binary** — that is the property being enforced. Honest limit: the hash is computed
  by the client it attests, so it raises the floor, not the ceiling, and it cannot see an external
  read-only overlay at all. See [`docs/binary-attest.md`](docs/binary-attest.md).
  **Runtime-verified in game.**
- **`crash-dump`** makes the minidump the engine already writes on every unhandled exception worth
  opening. The writer at `0x0043BE80` asks for `MiniDumpWithDataSegs` and passes **NULL for both
  the callback and the user-stream parameter**, and those two nulls are the whole problem: measured
  on six real dumps, **every engine singleton pointer is captured and nothing any of them points at
  is** — `TheGameLogic` reads a heap address that falls in no captured range — while **73% of each
  27 MB file is video-driver globals**, 20 MB of `nvd3dum.dll` and `igd9dxva32.dll`. One cave and
  two windows fix both halves at once. The eighteen bytes that push `MiniDumpWriteDump`'s last four
  arguments become a jump that pushes a **patch-owned dump type** — default `0x1b65`, the important
  bit being `WithPrivateReadWriteMemory`, which captures the SAGE heap without the mapped images —
  and a real `MINIDUMP_CALLBACK_INFORMATION`, whose routine clears `ModuleWriteDataSeg` for every
  module that is not `game.dat`. So the dump gets **more useful and smaller**: the module filter is
  what pays for the heap. The engine's own `fulldump` debug command still selects between the two
  profiles, both of which are parameters (`--dump-type`, `--deep-dump-type`) that `detect` reads
  back out of the cave. Separately, `Debug::crash` raises the engine's own `0x04560123` with **zero
  exception parameters** — four of the six observed dumps are that code, i.e. four dumps that
  record that an assert fired and not which one — so a second hook passes three: the formatted
  crash text, the `.rdata` literal that tags it as an assertion or an error, and the mode. The text
  is a heap pointer, which is why the two halves ship together. **The shipped 2003
  `dbghelp.dll` (6.3.0005.1) supports every bit used**, so nothing here needs it renamed out of the
  way. Client-local: no simulation, checksum, order stream or replay format is touched, and both
  hooks are reached only from code that runs after a crash. See
  [`docs/crash-dump.md`](docs/crash-dump.md), and
  [`docs/crash-dump-quality.md`](docs/crash-dump-quality.md) for the measurements behind it.
- **`quiet-exit`** stops the engine leaving a `.dmp` every time the game is closed. A benign
  `DEBUG_CRASH` assert trips on the shutdown path, raises the engine's own `0x04560123`, and the
  unhandled-exception filter at `0x0043D610` writes a minidump before the process dies — so a clean
  exit through the menu looks like a crash, and with `crash-dump` applied it is a **large** one. The
  filter's one `call writeMiniDump` (`0x0043D74E`) is redirected through a small cave that first
  reads `GameEngine::m_quitting` — the byte the main loop already checks to decide whether to keep
  running (`[TheGameEngine] + 0x10`). If the process is quitting, the dump is skipped; if it is not —
  a real fault mid-game — the call is made exactly as before, so **an actual crash still dumps**. The
  cave is `call`-ed in place of the original, tail-`jmp`s to `writeMiniDump` on the write path and
  `ret`s on the skip path, so the stack the filter's following `add esp, 8` sees is identical either
  way. Client-local: no simulation, checksum, order stream or replay format is touched, and the one
  site edited runs only after an unhandled exception. Composes with `crash-dump` — the two patches
  share the dump path but touch different bytes. **Static-verified**: it applies, verifies and
  disassembles as intended, and the redirect is confirmed against the real binary; the one thing only
  a live exit can settle is that `m_quitting` is already set when the shutdown assert fires — which is
  what it is set for. See [`docs/quiet-exit.md`](docs/quiet-exit.md).
- **`asset-load-profile`** turns on the **engine's own per-asset load timer**, which is a
  diagnostic and not a fix. The engine loads a model the first time something needs it, on the main
  thread, inside the frame — `AssetHandle::EnsureLoaded` (`0x00A32AD0`) falls through to a
  synchronous load at `0x00A37320` — which is where a mid-match hitch on a high-vertex model comes
  from, and the engine has always been able to say so: that function timestamps itself with
  `rdtsc` and a writer at its tail emits one CSV row per load,
  `frame,type,asset,tInit,tPreload,tLoad,tPostload,tTotal,recursion`, in milliseconds. The whole
  thing is gated on **one byte**, `GlobalData+0x123D` — which is not in the 457-row `GameData`
  field table, is not reachable from the sixteen-entry retail command-line table, and whose only
  writer is `GlobalData`'s constructor storing zero. So the switch exists, nothing can flip it, and
  this patch flips it: two adjacent byte stores in that constructor become one `mov word
  [esi+0x123C], 0x0100` plus three `nop`s, twelve bytes for twelve, leaving `+0x123C` at the zero
  the pair wrote and the uninitialised padding at `+0x123E` alone. The field stays a field, so a
  live session can turn it back off through `sage_live` without unpatching. Output lands in the
  process's working directory under the name the engine builds — `assetload <map>`, with no `.csv`
  extension, because nothing appends one. Client-local: peers need not agree on it, so one player
  can profile a match everyone else plays on stock binaries. Costs an `fopen`/`fprintf`/`fclose`
  per load, which lands after the timestamps — the columns stay honest, the felt hitch gets worse.
  See [`docs/asset-demand-load.md`](docs/asset-demand-load.md), which is also the scoping note for
  what to do about the hitch once it has been measured.
- **`wall-mesh-release`** makes a destroyed wall **give back the pathfinding data it registered**.
  A walkable wall registers three things in one function (`0x00935FAA`) and returns none of them:
  the walkable surface named by `RaisedWallMesh` claims a slot in the sixteen-entry table at
  `Pathfinder+0x60`, the two `RampMesh` ramps allocate a record each onto the list at
  `Pathfinder+0x5C`, and `WallBoundsMesh` marks a rectangle of cells. The ramps and the cells leak
  because their removal **re-asks the drawable for a mesh** — and a dying structure has changed
  model by the time the teardown reaches the pathfinder, so `RUBBLE` (no `P1`) and `POST_RUBBLE`
  (no model at all) mean every lookup answers "not found" and the bounds query's NULL **returns
  from the function** before one cell is unmarked. The walkable surface is worse and simpler: the
  claim and the list push have **exactly one caller each and both are on the add path**, so that
  leg is not a removal that fails, it is a removal that was never written — it leaks whatever the
  model does. The symptom is units walking on air over a wall that is gone, and fourteen slots
  never given back for the rest of the match (`Pathfinder::reset` is what eventually frees them,
  so the leak is bounded by the game, not the process). The patch makes the engine **remember what
  it registered** instead of re-deriving it: a ledger in the cave, keyed by `ObjectID`, filled by
  four hooks on the add path and consumed by one on the remove path. Stamping the id into the
  engine's own structures — the shape the RE document originally scoped — cannot work, because a
  layer slot is **shared between walls of equal height** and so cannot say which of its members is
  dying; and it is not needed, because `0x004BA693` hands the pathfinder an object *derived* from
  the queried sub-object and releases the sub-object itself, so what the slot holds is the
  pathfinder's own allocation and a pointer recorded at add time stays valid exactly as long as
  the registration does. **No engine structure grows and no savegame changes.** The surface is
  unlinked by that pointer and the slot handed back through the engine's own `0x00768AA7` — the
  inverse the document had recorded as *not yet located*, identified by `Pathfinder::reset` looping
  it over all sixteen slots — but only once the slot's list comes out empty, since a neighbour may
  still be standing on it. The ramps are unlinked by pointer rather than by the four-float geometry
  match `0x009356DF` does, which answers the same question without a mesh to ask it of. And the
  cells need **no new loop at all**: the four frame slots holding the rectangle are restored and
  control jumps to `0x0093682F`, the head of the stock unmark loop, which reads exactly those four
  and — unlike the *mark* branch one instruction earlier — dereferences no mesh. `Pathfinder::reset`
  drops the ledger at the one moment everything it describes stops existing, so a recycled
  `ObjectID` in the next match matches nothing. A wall with no ledger row is registered and removed
  exactly as it is today, which is also what a full table degrades to. **No INI keyword and no
  opt-in** — it changes what an existing wall block already does. Simulation state, so **every peer
  must run the same patched binary** and replays do not cross, the same rule as `spawn-union`. See
  [`docs/raised-wall-mesh-removal.md`](docs/raised-wall-mesh-removal.md).
- **`smart-rally`** (**experimental**) lets a structure's rally point **name a hero or a unit**
  instead of a spot on the ground, so units coming out of a barracks go where the target *is* rather
  than where it was standing when the order was given. The spend hook sits at the **head** of the
  release routine's walk-to-the-point arm, not its tail, so that a smart rally suppresses the
  exit-path call (`Object` vtable `+0x244`, `0x008A3D1D`) that arm opens with — the engine's own
  rally-at-object arm does not make it either, and making it *and* issuing an object order gives the
  unit a second destination that reasserts itself once it reaches the first. That is what walked
  produced units to the hero and then back to the spot the rally was set on. The `--guard` form
  additionally reads back the guarded `ObjectID` the engine records on success and **falls back to
  the move form** if the order did not take, so it can never leave a unit with no order at all. The order stream already describes this: `MSG_SET_RALLY_POINT`
  (`0x413`) carries **four** arguments and the fourth is the `ObjectID` of whatever was under the
  cursor, which the client fills in at `0x0081F5D8` — the handler at `0x0077A26C` resolves it, tests
  it for NULL to pick the global or single-producer arm, and then drops it. So no client edit, no
  new message, and **replays still parse byte-for-byte on a stock build**. The rally point itself is
  a `Coord3D` plus a flag on the `ExitInterface` and nothing more, so the patch grows
  `QueueProductionExitUpdate` from `0x44` to `0x48` bytes — its factory has exactly one allocation
  and its constructor exactly one caller — and keeps the target's id in the new dword. Four hooks
  fill it in: the handler records the id once the engine has accepted the point (behind a vtable
  check, because `getExitInterface` also answers with classes on which that offset is somebody
  else's field), the position setter zeroes it whenever a plain point is stored — which is what
  makes a ground click clear a standing target, and what covers the global arm the handler hook
  cannot see — and the release routine spends it, diverting the new unit to a target that is still
  alive and still allied (`Object::getRelationship == 2`, the same test the engine's own
  rally-target scan makes) and otherwise falling through to the stock instruction byte for byte. A
  fifth hook moves the **banner**: the ControlBar draws it at whatever `getRallyPoint` answers, from
  two sites holding the identical seven bytes, so both are redirected through one routine — reached
  by a `call` so its `ret` sorts out which — that answers with the target's live position instead.
  That half is client-side and read-only, and it keeps NULL meaning "destroy the marker" so a
  cleared rally point still puts the banner away. It changes *where* the banner is drawn, not how
  often it is redrawn, so it snaps to the target on the ControlBar's context refresh rather than
  gliding after a moving one. By
  default the unit is sent to the target's **current position**, the same call the stock arm makes
  with a different `Coord3D`; `--guard` issues `aiGuardObject` instead, so the units follow and
  defend. Note the engine already had a rally-at-object path — the `0x008A3AB4` scan for something
  to rally *into* — and it is **unreachable**: it demands `CanRallyToSlaughter`, which defaults to
  `No` and appears **zero times** in `ini.big`, `_patch201ini.big` or `__edain_data.big`, so nothing
  shipped can tell the difference between what these sites do today and what they do patched.
  **No INI keyword and no opt-in.** The new field is deliberately left out of the module's xfer, so
  the **save format does not change** — a rally target degrades to the stored position across a
  save/load. Simulation state, so **every peer must run the same patched binary**, the same rule as
  `production-condition`. See [`docs/smart-rally-points.md`](docs/smart-rally-points.md).
- **`banner-modifier`** adds **`BannerCarrierInflictsModifierOnDeath`** to `HordeContain`,
  naming a `ModifierList` the horde takes when its **banner carrier dies** - a bonus or a malus,
  applied to every surviving member and to the horde object, and lifted again when the horde gets
  a banner carrier back. The stock engine has one answer to a banner dying and it is
  all-or-nothing: `BannerCarrierDestroyHordeOnDeath` either kills the whole horde or does
  precisely nothing, so "the horde is shaken" is not expressible. Both halves are already written
  - `HordeContain` owns the routine that applies a named `ModifierList` to its members (the one
  behind the stock `AttributeModifiers`) and its exact inverse - so the patch is one field and the
  glue between them, at the join point of the `No` arm and at the one call that installs a banner
  carrier's id. The duration is the **`ModifierList`'s own**: the apply passes `-1`, which the
  engine reads as "use the block's `Duration`", and a block without one lasts until the horde is
  re-bannered (`--no-restore` keeps it forever instead). The awkward part is inheritance, not code:
  `AODHordeContainModuleData` **derives** from `HordeContainModuleData` and already occupies the
  space past its end, so the field goes past *both* layouts at `0x2CC` and all three
  `newModuleData` allocations in the family grow to the same `0x2D0` - one offset that is correct
  in every class sharing the code that reads it. `HorseHordeContain` and `AODHordeContain` inherit
  the keyword for free, because `buildFieldParse` chains. Simulation state, so **every peer must
  run the same patched binary**, and the keyword is an INI parse error on a stock build. See
  [`docs/banner-carrier-modifier.md`](docs/banner-carrier-modifier.md).
- **`detachable-rider-heal`** adds a **`HealOnDetach`** real to `DetachableRiderBody`, healing
  the mount by that many hit points at the moment its rider is knocked off. The stock module has
  one lever over what the riderless object is worth, `HealthPercentageWhenRiderDies`, and it is a
  percentage of the object's **maximum** health spent out of the health it happened to have - so
  "and give it 200 points back" is not expressible, and a flat grant is exactly the half that does
  not scale with the unit. The mechanism is one function: `DetachableRiderBody::attemptDamage`
  meets a killing blow by **rewriting the pending damage** so what lands leaves the object at that
  percentage, clearing the instant-kill flag, finding the `DetachableRiderUpdate` by name and
  calling it, and only then falling into `ActiveBody::attemptDamage` to apply the amount it wrote.
  The obvious cheap edit - subtract the grant from that amount - is wrong twice, which is why this
  patch does not: the amount is run through `Armor::adjustDamage` and a per-body scalar before it
  lands, so a "flat" number spent that way is worth a different count of hit points per attacker,
  and it is computed from the health the object had, so a grant folded into it can only give back
  health already lost. The hook instead reproduces the stock tail and grants the field afterwards
  through the engine's own `ActiveBody::internalChangeHealth` - the routine both `attemptDamage`
  and `attemptHealing` end at - which takes hit points rather than damage and carries the clamp to
  maximum health with it. It fires **only where the rider actually comes off**: the arm that finds
  no `DetachableRiderUpdate` keeps the stock bytes, and an object the damage left at zero health is
  left there, so the field tops a survivor up and never resurrects a corpse. The `ModuleData` has
  no padding to move into - its three fields end exactly at `sizeof` - so it grows from `0x1A0` to
  `0x1A4`, which costs one `push` (the class's only allocation) and a stub on its one constructor
  call to zero the new dword. Health is simulation state, so **every peer must run the same patched
  binary**, and the keyword is an INI parse error on a stock build. See
  [`docs/detachable-rider-heal.md`](docs/detachable-rider-heal.md).

- **`special-power-charges`** (**experimental**) gives a `SpecialPower` **charges**: `ChargeNumber = N` banks N casts
  behind `ReloadTimeBetweenCharge`, a short cooldown, and `ReloadTime` becomes the time to regain
  **one** charge - running from the moment the first charge goes missing, not from when the bank
  empties. `ReplenishAllChargesOnReloadTime = Yes` returns the whole bank at once instead. A power
  that does not set `ChargeNumber` is untouched. The trick that makes it cheap is that the engine's
  cooldown is an **absolute frame**, not a countdown: nothing ticks a special power while it
  recharges, so a charge bank does not need a per-frame driver either - the refill deadline is a
  second absolute frame and the count is recovered from it by integer division at the two moments
  anyone asks. **`isReady` is not patched**: with charges left `readyFrame` holds the short
  cooldown, with the bank empty it holds the refill deadline, so the ControlBar, both click arms,
  the AI and the button's pie clock all keep working untouched. **Which arm of `startPowerRecharge` counts as a use** is the whole
  story of the patch, and it took two runs in a real game to get right. That function means "arm
  the cooldown", which the engine does from **fourteen** places, so hooking it plainly made one
  cast empty the bank; hooking instead the one call that looks like the cast
  (`doSpecialPower`'s, on its own interface) missed every ability written with
  `UpdateModuleStartsAttack = Yes` beside a `WeaponFireSpecialAbilityUpdate`, which is how most
  targeted hero abilities in Edain are written. It now discriminates **on the caller**: the return
  address at `[ebp+4]` excludes the two arms that are provably not a use - the module constructor
  and the `OnTriggerRecharge` walk - and everything else is one, whichever module flavour drove
  it. `edi` already holds the refill interval the engine computed, so the short cooldown is that
  same ratio in integers and the patch runs no float of its own. Nothing that *clears* a cooldown is
  hooked either and none of it needs to be: an empty bank holds `readyFrame` at the deadline, so a
  reset is visible after the fact and hands a charge back. Nine bytes of `SpecialPowerTemplate`
  (which grows `0x88` -> `0x94`) and six of module padding that is neither read nor `Xfer`'d - so
  **charges do not survive a savegame**, which reloads at a full bank. The button description gains
  a charge readout once the mod declares `TOOLTIP:SpecialPowerCharges` (two `%d`) and
  `TOOLTIP:SpecialPowerChargesRecharging` (two `%d` and a `%.1f` of seconds); the tooltip is built
  once per hover, so the seconds are a snapshot. Charges gate whether a power fires, so **every peer
  must run the same patched binary** and replays do not cross. Spellbook spells are covered -
  a spellbook is an ordinary object and its spells ordinary `SpecialPowerModule` /
  `OCLSpecialPower` / `PlayerUpgradeSpecialPower` behaviours. See
  [`docs/special-power-charges.md`](docs/special-power-charges.md).
- **`render-rate`** ⚠**(experimental)** draws at **N frames per second instead of 30 without the simulation
  speeding up**. SAGE already simulates at 5 logic frames per second and draws at 30, keeps a sub-frame
  counter and hands the render path an interpolation alpha — what welds the two clocks back together is
  **one comparison**, the wrap that ends a logic frame written against a literal `6` rather than against the
  ratio the engine derives from the rates. Moving the client rate and that literal together is most of the
  patch, and a rendered drawable then takes **11 distinct interpolated positions per logic frame at 60
  against 5 at stock**: it is genuinely smoother, not merely faster. Two things break when it moves and
  both are fixed here. The once-per-logic-frame latch fires on a sub-frame that **never occurs** at 60, so
  every `previous = current` latch behind it stops and animations freeze — **one dword**, measured over 373
  client frames before it was believed. And `ParticleSystemManager::update` runs once per client frame from
  the draw path with lifetimes counted in *updates*, so every effect in the game ran at double speed; a
  0x28-byte cave stamps the manager with `clientFrame * 30 / clientRate` instead of the raw frame, measured
  live at **0.500 steps per client frame**. **The one INI change is not optional**: `FramesPerSecondLimit`
  in `GameData` must be set to the same N, or the pace loop targets 30 against a 60 fps binary and the
  **whole game runs at half speed** — no warning, no crash, just slow. This is **Edain's** binary's patch:
  the latch divisor it edits does not exist on stock SAGE, and the patch refuses a build whose predicate is
  not that shape rather than writing a dword into whatever lives there. **Single-player and replays only,
  and that is structural rather than a bug list.** The wrap counts *client* frames and the limiter is only a
  ceiling, so the logic rate is the frame rate a machine actually achieves divided by the ratio — invisible
  at stock, where every machine renders 30, and dominant at 60, where **each peer simulates at a speed set
  by its graphics performance**. Played online on 2026-08-23 with identical binaries on both sides: the host
  rendered 60 and stuttered for the whole match while a weaker peer that could not hold 60 ran slow, and it
  desynced. **The condition matters, though**: a client measured over a full 18.5-minute match on hardware
  that *does* hold 60 paced at a flat **5.000 Hz** with no stalls, so this mechanism explains a peer that
  drops frames and not a match between two that do not. Network play needs the wrap to end on elapsed
  milliseconds instead of a count of draws, which is a different patch. See
  [`docs/render-rate.md`](docs/render-rate.md) §9.9.

Uses [pyBIG](..)/capstone/pefile and Ghidra headless.

## CLI

Bring your own `game.dat` (this repo ships the patch recipe, never the copyrighted binary):

```sh
sage-patch list                                  # the registered patches; `exp` = experimental
sage-patch info commandset-limit                 # one patch: author, source, write-up,
                                                 # parameters, and the INI surface it adds
sage-patch info commandset-limit --file game.dat # ...and whether *this* binary carries it,
                                                 # with the parameters recovered from it
sage-patch apply commandset-limit --count 64 \
    --in game.dat.backup --out game.dat          # --in is read, never modified
sage-patch verify commandset-limit --count 64 game.dat   # exits non-zero on any mismatch

sage-patch apply cah-factions --sides Rohan,Lothlorien \
    --in game.dat.backup --out game.dat
sage-patch verify cah-factions --sides Rohan,Lothlorien game.dat

sage-patch apply ai-revive-gate --in game.dat.backup --out game.dat   # no parameters
sage-patch verify ai-revive-gate game.dat

sage-patch apply ai-construction-gate --in game.dat.backup --out game.dat   # no parameters
sage-patch verify ai-construction-gate game.dat

sage-patch apply ai-flag-capture-gate --in game.dat.backup --out game.dat   # no parameters
sage-patch verify ai-flag-capture-gate game.dat

sage-patch apply rebuild-hole-construction --in game.dat.backup --out game.dat   # no parameters
sage-patch verify rebuild-hole-construction game.dat

sage-patch apply horde-exit-absorption --in game.dat.backup --out game.dat   # no parameters
sage-patch verify horde-exit-absorption game.dat

sage-patch apply combo-horde-recruitment --in game.dat.backup --out game.dat    # no parameters
sage-patch verify combo-horde-recruitment game.dat

sage-patch apply production-condition --condition PRODUCING \
    --in game.dat.backup --out game.dat
sage-patch verify production-condition --condition PRODUCING game.dat

# the same patch with both optional halves; verify takes the arguments apply was given
sage-patch apply production-condition --condition PRODUCING \
    --weapon-set-flag PRODUCING --locomotor-set SET_PRODUCING \
    --in game.dat.backup --out game.dat

sage-patch apply unique-production-id --in game.dat.backup --out game.dat   # no parameters
sage-patch verify unique-production-id game.dat

sage-patch apply replay-outcome --in game.dat.backup --out game.dat         # no parameters
sage-patch verify replay-outcome game.dat

sage-patch apply skirmish-replay --in game.dat.backup --out game.dat  # --modes 2 --rename all
sage-patch verify skirmish-replay game.dat

# the other half of watching a skirmish replay: the next/prior player buttons
sage-patch apply observer-switch --in game.dat.backup --out game.dat        # no parameters
sage-patch verify observer-switch game.dat

sage-patch apply unit-plate-option --in game.dat.backup --out game.dat   # --model/--key/--gadget optional
sage-patch verify unit-plate-option game.dat

# every faction gets an AI on every map, running its own ki <faction> library
sage-patch apply skirmish-ai-fallback --in game.dat.backup --out game.dat   # no parameters
sage-patch verify skirmish-ai-fallback game.dat

# --pool is the fallback maximum in whole points, --regen the fallback refill in hundredths of a
# point per logic frame (30 == one point per second at 30fps); a SpecialPower may override both.
sage-patch apply hero-mana --pool 100 --regen 30 --in game.dat.backup --out game.dat
sage-patch verify hero-mana --pool 100 --regen 30 game.dat

# per-faction upkeep thresholds come from playertemplate.ini; --no-hud keeps the palantir's
# command-point text exactly as the stock engine draws it
sage-patch apply command-point-upkeep --in game.dat.backup --out game.dat
sage-patch verify command-point-upkeep game.dat

# spell-store CommandSets selected by completed PLAYER_UPGRADE mappings in PlayerTemplate INI
sage-patch apply spell-store-upgrade --in game.dat.backup --out game.dat
sage-patch verify spell-store-upgrade game.dat

# a second currency: granted, shown and spent
sage-patch apply second-resource --in game.dat.backup --out game.dat
sage-patch verify second-resource game.dat

# a structure that costs its owner gold per tick instead of paying it (negative MaxIncome /
# DepositAmount; no INI keyword to add, and no parameters here)
sage-patch apply maintenance-cost --in game.dat.backup --out game.dat
sage-patch verify maintenance-cost game.dat

# and, if that upkeep (and the keeps' own income) should fall with the faction's inflation
sage-patch apply auto-deposit-inflation --in game.dat.backup --out game.dat

# hero-bar slots for things that are not HEROes: HEROBAR (one per object) and
# HEROBAR_GROUP (one per template, clicking through its members one at a time)
sage-patch apply herobar --in game.dat.backup --out game.dat
sage-patch verify herobar game.dat

# rename either token
sage-patch apply herobar --kindof SOLOSLOT --group-kindof SHAREDSLOT --in game.dat.backup --out game.dat
sage-patch verify herobar --kindof SOLOSLOT --group-kindof SHAREDSLOT game.dat

# a snappier (or disabled, with 0) click-again-to-jump gesture on the group slots
sage-patch apply herobar --jump-window 300 --in game.dat.backup --out game.dat
sage-patch verify herobar --jump-window 300 game.dat

# the mechanic without the palantir bracket or the tooltip one
sage-patch apply second-resource --no-hud --in game.dat.backup --out game.dat

# rename only the skirmish recordings, leaving network ones (and Save Replay) as stock
sage-patch apply skirmish-replay --rename added --in game.dat.backup --out game.dat

sage-patch apply terrain-resource-exp --in game.dat.backup --out game.dat   # --keyword GiveNoXP
sage-patch verify terrain-resource-exp game.dat

# a mount healed by a flat number of hit points when its rider is knocked off
sage-patch apply detachable-rider-heal \
    --in game.dat.backup --out game.dat     # --keyword HealOnDetach
sage-patch verify detachable-rider-heal game.dat

# an upgrade pushes a summon's death back, and expiry can transform instead of killing
sage-patch apply lifetime-fields \
    --in game.dat.backup --out game.dat  # --keyword / --bonus-keyword / --template-keyword
sage-patch verify lifetime-fields game.dat

# let a LargeGroupBonusUpdate's HordeMemberFilter also match objects outside a horde
sage-patch apply large-group-bonus-filter \
    --in game.dat.backup --out game.dat        # --keyword CountLooseObjects
sage-patch verify large-group-bonus-filter game.dat

# no parameters; --slots is read out of the image (33, or commandset-limit's N) unless pinned
sage-patch apply multi-execute-gate --in game.dat.backup --out game.dat
sage-patch verify multi-execute-gate game.dat

# a CommandButton field that lets an engine-pressed button queue past the command-point cap
sage-patch apply queue-ignore-cp --in game.dat.backup --out game.dat   # --keyword QueueIgnoreCP
sage-patch verify queue-ignore-cp game.dat

# a CommandButton field that greys the button unless that many command points are free
sage-patch apply command-point-cost --in game.dat.backup --out game.dat  # --keyword CommandPointCost
sage-patch verify command-point-cost game.dat

# a wider hero bar; the .apt must define Hero17..HeroN clips to match (see sage_apt)
sage-patch apply hero-bar-slots --count 21 --in game.dat.backup --out game.dat
sage-patch verify hero-bar-slots --count 21 game.dat

# a cooldown / build time / research time line at the bottom of a button's description;
# --integer-seconds makes each key take a %d instead of a %.1f
sage-patch apply description-timers --in game.dat.backup --out game.dat
sage-patch verify description-timers game.dat

# keep an upgrade's description once it is researched, message appended under it
sage-patch apply upgrade-description --in game.dat.backup --out game.dat
sage-patch apply upgrade-description --separator blank-line --also-blocked \
    --in game.dat.backup --out game.dat
sage-patch verify upgrade-description game.dat

# hand a settlement plot from the building a ReplaceSelfUpgrade destroys to the one it creates
sage-patch apply foundation-rebind --in game.dat.backup --out game.dat  # no parameters
sage-patch verify foundation-rebind game.dat

# a command-line surface, and a game that does not draw
sage-patch apply headless --in game.dat.backup --out game.dat          # no parameters
sage-patch verify headless game.dat

# a cooldown already running responds to a recharge modifier granted after the cast
# EXPERIMENTAL - `apply` prints the warning before it writes; see the note at the top
sage-patch apply recharge-rescale --in game.dat.backup --out game.dat   # no parameters
sage-patch verify recharge-rescale game.dat

# a hero's cooldowns survive a citadel revive; --ticks-keyword names the second bool, the one
# that lets the cooldown keep elapsing while the hero is dead
# EXPERIMENTAL - `apply` prints the warning before it writes; see the note at the top
sage-patch apply cooldown-through-death --in game.dat.backup --out game.dat
sage-patch verify cooldown-through-death game.dat

# a crash .dmp that carries the heap and not the video driver's globals; --dump-type and
# --deep-dump-type are MINIDUMP_TYPE masks, the second selected by the `fulldump` debug command
sage-patch apply crash-dump --in game.dat.backup --out game.dat        # defaults 0x1b65 / 0x1b67
sage-patch verify crash-dump game.dat

# the launcher, not game.dat: no install-location lock on the token it hands the engine
# EXPERIMENTAL - `apply` prints the warning before it writes; see the note at the top
sage-patch apply standalone-launcher \
    --in lotrbfme2ep1.exe.backup --out lotrbfme2ep1.exe                # no parameters
sage-patch verify standalone-launcher lotrbfme2ep1.exe
```

`verify` re-derives the expected tables, the repointed references and every patched site from the
same parameters and checks them against the file — a structural, disassembler-free pass/fail.

## Credit

**Every patch here names an author. `list` has a column for it and `apply` prints it:**

```
$ sage-patch list
commandset-limit        officialNecro  Raise the CommandSet button limit from 33 to N
cah-factions            officialNecro  Add mod sides + an 'All' token to the Create-A-Hero enum
hero-mana          exp  officialNecro  Give special powers a regenerating per-object mana cost
...

$ sage-patch apply spawn-union --in game.dat.backup --out game.dat
applying patch: spawn-union (by officialNecro)
wrote game.dat
```

That line is not decoration. What makes a patch is not the assembly in `patches/` — it is knowing
that `0x0077F98B` is the call every ending converges on out of thirteen emitters, that the revive
gate counts buttons it never reads, that `SAND` is not a stock model condition and has to be
created before it can be driven. Weeks of disassembly go into a finished patch and **none of it is
visible in the diff afterwards**; the result reads like twenty lines of obvious code. Somebody did
that work, and the attribute is where this repository says who.

The patches in this package are engine-level: they apply to any ROTWK install of build
`2.01.2614.37001` and benefit every mod on it. They are meant to be used. What is asked in return
is attribution:

- **If you ship a patched `game.dat`, credit the patch authors** in whatever your mod uses for
  credits — a readme, a mod-page section, an in-game screen. The `applying patch:` lines from
  `apply` name everyone whose work went into the binary, so the build log is the roster; you do
  not have to read the source to find out.
- **Credit by patch, not by package.** A build that carries three patches by three people should
  name three people. This is why the author lives on the patch class rather than in one line at
  the top of the repo.
- **Carry the attribution downstream.** If your mod is forked, or your patched binary is
  redistributed as part of a pack, the credit travels with it.
- **A fix or an extension does not transfer authorship.** Add your own name beside the original
  author's rather than in place of it — the addresses were somebody else's work first.

For new patches, set `author` beside `name` on the class:

```python
class MyPatch(Patch):
    name = "my-patch"
    author = "yourNameHere"
    description = "What it changes, in one line"
```

It is not optional in practice: `tests/sage_patch/test_patching.py::TestEveryPatchIsAttributed`
fails the build for any registered patch that leaves it empty. The default is the empty string
rather than a name, so an unattributed patch prints `(author unrecorded)` and is caught, instead
of quietly crediting somebody else's work to whoever happened to be first in the file.

## Telling the linter what the engine now accepts

A patch that adds an INI field or a name-table token changes what *valid data* looks like, and
`sage_ini`'s model describes the stock engine — so on a patched game the mod's own data reads as
a pile of unknown attributes and unknown enum tokens. `sagepatch` closes that: it reads the binary
and writes the `.sagepatch` that `sage_ini` and `sage_lint` load (see
[`sage_ini/engine.py`](../sage_ini/engine.py)).

```sh
sage-patch sagepatch game.dat -o /path/to/mod/.sagepatch   # commit it beside .sagelint
sage-patch sagepatch game.dat                              # to stdout, to review first
sage-patch sagepatch game.dat --check /path/to/mod/.sagepatch   # non-zero if it has drifted
sage-patch sagepatch --patch hero-mana --patch commandset-limit  # by name, no binary
```

It reads the **binary**, not a list of names you type, because that is the only thing that knows
what was actually built: which patches are in it, at what count, under which keyword, and which
token landed on which bit. Two passes do it, and they cover for each other — each patch is offered
the image through `Patch.detect` (which recovers its parameters) and contributes its declared
`Patch.ini_surface`, while the name tables are read live so *any* token past the stock ones is
recorded with its real index, including ones added by a patch applied under a custom name or by a
patch this package has never heard of. The `--patch` form skips the binary for a project that
would rather not wire a path into CI, at the cost of describing every patch with its defaults.

`--check` is the drift guard: run it in CI, and a committed `.sagepatch` that no longer matches
the binary the team ships fails the build instead of silently mislinting.

## The patch framework

`apply_patches(game_dat, patches, output=None)` applies an ordered list of `Patch` subclasses to a
copy of the binary and writes the result (in-place if `output` is omitted). Each `Patch` verifies
the bytes it expects before writing, so a list either applies in full or raises without leaving a
half-patched file.

```python
from sage_patch import AiReviveGatePatch, apply_patches, CahFactionsPatch, CommandSetLimitPatch

apply_patches(
    "game.dat.backup",
    [
        CommandSetLimitPatch(count=64),
        CahFactionsPatch(sides=["Rohan", "Lothlorien"]),
        AiReviveGatePatch(),
    ],
    output="game.dat",
)
```

| module | what |
|--------|------|
| [`patcher.py`](patcher.py) | the `Patch` base class (`apply` / `verify` / CLI hooks) + `apply_patches` driver |
| [`cli.py`](cli.py) | the `sage-patch` console script (`apply` / `verify` / `list` / `sagepatch`) |
| [`sagepatch.py`](sagepatch.py) | reads a patched binary back as the `.sagepatch` describing the INI it accepts — patch detection plus a live read of every engine name table |
| [`registry.py`](registry.py) | the name→`Patch` map the CLI dispatches over; register a patch here to expose it |
| [`addresses.py`](addresses.py) | every address of the target build, in one place — the globals, the hooked functions and the labels inside them that the caves jump to |
| [`asm.py`](asm.py) | the tiny label-resolving x86 emitter the caves are written with |
| [`utils.py`](utils.py) | PE/byte helpers (`allocate_section`/`find_section` — the pair that makes caves order-independent — plus `apply_byte_patch`, `va_to_offset`, `image_base`, …) operating on an in-memory `bytearray` |
| [`patches/`](patches/) | every `Patch` lives here, one module per patch, and [`registry.py`](registry.py) names them all |
| [`patches/experimental/`](patches/experimental/) | the **unstable and largely untested** ones. Membership is the same fact as `Patch.experimental`, which is what makes `list` mark them `exp` and `apply_patches` log a warning; a test fails if the two disagree. Graduating one is a move plus dropping the attribute |
| [`patches/utils/`](patches/utils/) | the machinery more than one patch needs and none of them owns — the three global name tables and the primitives every table extension shares, the INI field-parse tables that give a block a new keyword, the `KindOf` mask, and the income link |

### Composing patches

**Any subset of the bundled patches applies in any order**, with one exception named below, and a
patch is only considered done when it holds that. `apply_patches` takes a list precisely so they
can be stacked:

```sh
sage-patch apply commandset-limit --count 64 --in game.dat.backup --out game.dat
sage-patch apply cah-factions --sides Rohan,Lothlorien --in game.dat --out game.dat
```

Three rules make that work, in decreasing order of how mechanically they hold:

| rule | enforced by | if broken |
|---|---|---|
| Allocate a cave with `allocate_section` (never a fixed RVA) and find it again with `find_section` | the helper — a patch that uses it cannot get this wrong | the section table comes out unsorted when another patch's cave is already present |
| Do not edit bytes another patch edits | not prevented, but `apply_byte_patch` asserts the original bytes first | the second patch to reach the site **raises**; nothing is silently corrupted |
| Do not derive your output from bytes another patch rewrites | nothing — this is the one the framework cannot catch | both orders "succeed" and disagree; declare the dependency in the docstring instead |

No bundled patch touches another's bytes or reads what another writes, and all three allocate their
cave the same way — so any order produces binaries that differ only in which cave landed first
(and therefore in the pointers to it), all verifying clean.

The one pair worth naming: `commandset-limit` and `ai-revive-gate` both edit
`BuildAssistant::canMakeUnit` — the hook at `0x7950ce` (6 bytes) and the AI scan bound at
`0x7950e2` (4 bytes), 20 bytes apart, no intersection. `ai-revive-gate`'s cave jumps only to
`0x79502a`, `0x7950dc` and `0x7950df`, all below the bound, so neither reads what the other writes.
[`tests/sage_patch/test_ai_revive_gate.py`](../tests/sage_patch/test_ai_revive_gate.py) asserts
both halves of that.

**The exception is `multi-execute-gate`, which must be applied after `commandset-limit`.** Its
`slots` defaults to reading the `CommandSet` bound out of the image, which is `33` until
`commandset-limit` raises it. The other order corrupts nothing — a button past the bound is not
found and that member takes the stock path — but `verify` reports the disagreement and `detect`
answers "not patched". Pin `slots` explicitly to apply them the other way round.

Placement being computed rather than hardcoded costs nothing: on an unpatched image
`next_section_rva` returns exactly `0xAD3000`, so a lone `commandset-limit` build puts `.cmdext`
at the same RVA a fixed placement would have chosen.

> **Why 127 and not more.** Six patch sites encode the limit as a *signed 8-bit* immediate
> (`6a NN` push, `83 fa NN` / `83 fb NN` / `83 7d f8 NN` cmp). At 128 the byte `0x80` decodes as
> `-128`, and one of those pushes supplies `rep stosd`'s counter — the constructor would zero ~4
> billion dwords. Going higher means re-encoding those six as imm32 (3 bytes longer apiece), which
> no longer fits in place and needs relocated code, not a byte patch.

Tests live in [`tests/sage_patch/test_patching.py`](../tests/sage_patch/test_patching.py) and
[`tests/sage_patch/test_ai_revive_gate.py`](../tests/sage_patch/test_ai_revive_gate.py), including
a byte-identity check that `count=64` reproduces the shipped `game.dat`.

## Module reference

```sh
python scripts/module_defaults.py game.dat \
    --json docs/module-reference.json \
    --markdown docs/module-reference.md \
    --enums docs/ini-types.json         # needs your own game.dat
python scripts/build_wiki.py            # -> build/wiki/index.html, no game.dat needed
```

A field's type is its parse function, and those are identified from what the code does:
the constant a real is scaled by (`pi/180` is degrees in, radians out), the range the
parser complains about (`expected > 0`), the name array a token is resolved against, the
field table a nested block hands to the INI reader.

Block types are found the same way. The loader dispatches a block on `{keyword, parser}`
pairs in the data sections; a candidate is kept only when its parser really does hand a
field table to the INI reader, which is what makes it a block type rather than a string
that happens to sit next to a function pointer. Where the parser also allocates and
constructs its instance, the same constant tracking recovers that block's defaults.

The site is a build artefact and is not committed; the JSON it reads is.

## Reproduce the build

```sh
cd engine
OUT=game.dat python patch.py   # clean game.dat.backup -> N=64 game.dat  (COUNT=N for another limit)
python verify.py && python finalcheck.py
```
