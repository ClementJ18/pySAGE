# ROTWK `game.dat` patching

Reverse-engineering + binary-patch work on the ROTWK SAGE engine (build `2.01.2614.37001`). The
patches below are all engine-level — they apply to any ROTWK install of that build and benefit
every mod on it (Edain among them), not one in particular. All of them target `game.dat` except
two, which patch other binaries from the same install: `desert-weather-wb` patches
`Worldbuilder.exe`, and `standalone-launcher` patches the launcher shim `lotrbfme2ep1.exe`:

- **`commandset-limit`** raises the `CommandSet` button limit from its stock **33** to any **N** in
  34..127, plus the INI paging rule needed to surface the extra buttons, and widens the AI's
  set-walk to the same N. The shipped build uses **N = 64**.
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
  **Not yet runtime-verified in game.**
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
- **`desert-weather-wb`** is the authoring half of that, and the one patch here that targets
  **`Worldbuilder.exe`** rather than `game.dat`. Worldbuilder's map-settings weather dropdown is
  filled by a loop with a hardcoded member count, so `DESERT` never appears in it - and because
  the OK handler stores `CB_GETCURSEL` unvalidated, opening that dialog on a `DESERT` map and
  pressing OK writes `-1` back into the map and silently reverts it. The patch grows the same
  table and raises that one bound. Dropdown only: the editor *viewport* keeps drawing the
  non-`SAND` variant, which needs Worldbuilder's own model-condition table extended too.
- **`replay-outcome`** writes **each player's final victory/defeat state into the replay**, at
  the frame the recording ends - whether a player left or the game finished. A stock replay
  records inputs, not state, so no chunk says who won and
  [`sage_replay.winner`](../sage_replay/winner.py) has to infer it from who stopped issuing
  orders (and gives up entirely on elimination endings and on AI players). This adds one `0x7D0`
  chunk per player, written straight to the recorder's own file handle just before the `0x1D`
  end-of-recording marker. Client-local: nothing enters the simulation and nothing crosses the
  network, so it does **not** have to be on every peer. **Runtime-verified** on all three endings.
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
  companion to `skirmish-replay`, and independent of it. Client-local. **Not yet runtime-verified
  in game.**
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
- **`hero-mana`** gives special powers a **regenerating per-object cost** — `SpecialPower.ManaCost`
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

- **`second-resource`** gives every player a **second resource pool** alongside gold, granted per
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
  block runs after the check and is not covered. **Not yet runtime-verified in game.**
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
  same patched binary** and replays do not cross. **Not yet runtime-verified in game.**
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
  not play back on a stock build. **Not yet runtime-verified in game.**

- **`herobar`** adds a **`HEROBAR`** kindof: every instance of one `ThingTemplate` shares a single
  hero-bar slot, two different templates take two slots, and clicking a grouped slot selects the
  whole group. Different from `PORTER`, which collapses *every* porter into one slot whatever
  template it came from and clicks through them one at a time. It is cheap for two reasons. The
  kindof is free: `KindOfMaskType` is 224 bits with 222 named, so the new bit needs no
  `ThingTemplate` growth and no savegame change, and the table move is 14 references and 6 counts
  against `production-condition`'s 16 and 10. And the hero bar is already most of the way there -
  `slot+0x16` is a generic **"this slot is a group"** byte the click handler already dispatches on,
  and a group slot is drawn with the *same* ActionScript calls as a hero slot, so **no `.apt` edit
  is needed**. So the patch adds no drawing code at all: `HEROBAR` objects join the **hero** list
  the draw loop already walks, and three small detours around that loop clear a per-pass set of
  templates, send a duplicate to the engine's own "next node, no slot consumed" label, and mark the
  slot it did draw. The removal pair is not optional - the stock `onObjectRemoved` accepts only
  `HERO` and `PORTER`, so without it a dead `HEROBAR` object's node would sit on the list forever.
  **No count badge** (a group slot shows the representative's rank, not a member count) and the bar
  is still **16 slots**, so enough distinct groups push heroes off the end. **Not yet
  runtime-verified in game.**
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
  stock build. **Not yet runtime-verified in game.**
- **`campaign-select`** lets the main menu start **any `LinearCampaign`, by name**, instead of the
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
  cooldown and a dummy building. **Simulation state**, so it has to be on every peer. **Not yet
  runtime-verified in game.**
- **`standalone-launcher`** is the one patch here aimed at **`lotrbfme2ep1.exe`**, the launcher
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
- **`headless`** makes a run cheap enough to automate: it adds **`-headless`**, **`-renderEvery n`**,
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
  [`docs/headless.md`](docs/headless.md). **Not yet runtime-verified in game.**

Uses [pyBIG](..)/capstone/pefile and Ghidra headless.

## CLI

Bring your own `game.dat` (this repo ships the patch recipe, never the copyrighted binary):

```sh
sage-patch list                                  # the registered patches
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

# --pool is the fallback maximum in whole points, --regen the fallback refill in hundredths of a
# point per logic frame (30 == one point per second at 30fps); a SpecialPower may override both.
sage-patch apply hero-mana --pool 100 --regen 30 --in game.dat.backup --out game.dat
sage-patch verify hero-mana --pool 100 --regen 30 game.dat

# per-faction upkeep thresholds come from playertemplate.ini; --no-hud keeps the palantir's
# command-point text exactly as the stock engine draws it
sage-patch apply command-point-upkeep --in game.dat.backup --out game.dat
sage-patch verify command-point-upkeep game.dat

# a second currency: granted, shown and spent
sage-patch apply second-resource --in game.dat.backup --out game.dat
sage-patch verify second-resource game.dat

# one hero-bar slot per object type; --kindof renames the token from the default HEROBAR
sage-patch apply herobar --in game.dat.backup --out game.dat
sage-patch verify herobar game.dat

# the mechanic without the palantir bracket or the tooltip one
sage-patch apply second-resource --no-hud --in game.dat.backup --out game.dat

# rename only the skirmish recordings, leaving network ones (and Save Replay) as stock
sage-patch apply skirmish-replay --rename added --in game.dat.backup --out game.dat

sage-patch apply terrain-resource-exp --in game.dat.backup --out game.dat   # --keyword GiveNoXP
sage-patch verify terrain-resource-exp game.dat

# no parameters; --slots is read out of the image (33, or commandset-limit's N) unless pinned
sage-patch apply multi-execute-gate --in game.dat.backup --out game.dat
sage-patch verify multi-execute-gate game.dat

# a CommandButton field that lets an engine-pressed button queue past the command-point cap
sage-patch apply queue-ignore-cp --in game.dat.backup --out game.dat   # --keyword QueueIgnoreCP
sage-patch verify queue-ignore-cp game.dat

# a wider hero bar; the .apt must define Hero17..HeroN clips to match (see sage_apt)
sage-patch apply hero-bar-slots --count 21 --in game.dat.backup --out game.dat
sage-patch verify hero-bar-slots --count 21 game.dat

# hand a settlement plot from the building a ReplaceSelfUpgrade destroys to the one it creates
sage-patch apply foundation-rebind --in game.dat.backup --out game.dat  # no parameters
sage-patch verify foundation-rebind game.dat

# a command-line surface, and a game that does not draw
sage-patch apply headless --in game.dat.backup --out game.dat          # no parameters
sage-patch verify headless game.dat

# the launcher, not game.dat: no install-location lock on the token it hands the engine
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
commandset-limit   officialNecro  Raise the CommandSet button limit from 33 to N
cah-factions       officialNecro  Add mod sides + an 'All' token to the Create-A-Hero faction enum
...

$ sage-patch apply hero-mana --in game.dat.backup --out game.dat
applying patch: hero-mana (by officialNecro)
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
| [`patches/utils/`](patches/utils/) | the machinery more than one patch needs and none of them owns — the three global name tables and the primitives every table extension shares, the `KindOf` mask, and the income link |

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
