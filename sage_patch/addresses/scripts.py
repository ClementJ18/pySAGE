"""The script engine: scripts, counters, flags, actions, and the script debugger."""

from __future__ import annotations

__all__ = [
    "CONDITION_ENABLED",
    "CONDITION_INVERTED",
    "CONDITION_NEXT",
    "CONDITION_PARAM_COUNT",
    "CONDITION_TYPE",
    "FRAME_DISPATCHER",
    "FRAME_DISPATCHER_PAUSE_CALL",
    "FRAME_DISPATCHER_PAUSE_CALL_BYTES",
    "OR_CONDITION_CONDITIONS",
    "OR_CONDITION_NEXT",
    "SCRIPT_ACTIONS_CREATE_UNIT_REVIVAL_ENTRY",
    "SCRIPT_ACTIONS_EXECUTE_ACTION",
    "SCRIPT_ACTION_ENABLED",
    "SCRIPT_ACTION_EPILOGUE",
    "SCRIPT_ACTION_GET_PARAMETER",
    "SCRIPT_ACTION_JUMP_TABLE",
    "SCRIPT_ACTION_PARAM_ARRAY",
    "SCRIPT_ACTION_PARAM_COUNT",
    "SCRIPT_ACTION_TEAM_TO_ARMY",
    "SCRIPT_ACTION_TEAM_TO_ARMY_ID",
    "SCRIPT_ACTION_TYPE",
    "SCRIPT_ACTIVE",
    "SCRIPT_AUTHORED_ACTIVE",
    "SCRIPT_CONDITIONS",
    "SCRIPT_COUNTER_IS_SECONDS",
    "SCRIPT_COUNTER_IS_TIMER",
    "SCRIPT_COUNTER_VALUE",
    "SCRIPT_DEBUG_ADJUST_VARIABLE",
    "SCRIPT_DEBUG_APPEND_MESSAGE",
    "SCRIPT_DEBUG_CAN_CONTINUE",
    "SCRIPT_DEBUG_FLAG_HANDLER",
    "SCRIPT_DEBUG_IS_PAUSED",
    "SCRIPT_DEBUG_LITE_FLAG_HANDLER",
    "SCRIPT_DEBUG_MODULE",
    "SCRIPT_DEBUG_PAUSED",
    "SCRIPT_DEBUG_POLL_CONTINUE",
    "SCRIPT_DEBUG_RUN_FAST",
    "SCRIPT_DEBUG_RUN_SCRIPT_LOG",
    "SCRIPT_DEBUG_SUPPRESS",
    "SCRIPT_DEBUG_USE_LITE_DLL",
    "SCRIPT_DELAY_SECONDS",
    "SCRIPT_EASY",
    "SCRIPT_ENGINE_BIND_OBJECT_NAME",
    "SCRIPT_ENGINE_CALL_SUBROUTINE",
    "SCRIPT_ENGINE_COUNTER_MAP",
    "SCRIPT_ENGINE_CURRENT_OBJECT",
    "SCRIPT_ENGINE_CURRENT_PLAYER",
    "SCRIPT_ENGINE_DIFFICULTY",
    "SCRIPT_ENGINE_EVALUATE",
    "SCRIPT_ENGINE_EVALUATE_CONDITION",
    "SCRIPT_ENGINE_EVALUATE_ENTRY_BYTES",
    "SCRIPT_ENGINE_EVALUATE_RESUME",
    "SCRIPT_ENGINE_EXECUTE_SCRIPT",
    "SCRIPT_ENGINE_EXECUTE_SEQUENTIAL",
    "SCRIPT_ENGINE_FIND_FLAG",
    "SCRIPT_ENGINE_FIND_OR_CREATE_COUNTER",
    "SCRIPT_ENGINE_FIND_OR_CREATE_FLAG",
    "SCRIPT_ENGINE_FLAG_MAP",
    "SCRIPT_ENGINE_NAMED_OBJECT_MAP",
    "SCRIPT_ENGINE_PLAYER_NAME_TO_INDEX",
    "SCRIPT_ENGINE_RUN_ACTIONS",
    "SCRIPT_ENGINE_RUN_GROUP_NODES",
    "SCRIPT_ENGINE_RUN_SCRIPT",
    "SCRIPT_ENGINE_RUN_SCRIPT_NODES",
    "SCRIPT_ENGINE_SCOPE",
    "SCRIPT_ENGINE_SCOPED_KEY",
    "SCRIPT_ENGINE_SET_COUNTER",
    "SCRIPT_ENGINE_SET_FLAG",
    "SCRIPT_ENGINE_SET_TIMER",
    "SCRIPT_ENGINE_TIMER_TICK_SITE",
    "SCRIPT_EVALUATE_CONDITION_CALL",
    "SCRIPT_EVALUATE_CONDITION_CALL_BYTES",
    "SCRIPT_EXECUTE_LOG_CALLS",
    "SCRIPT_FALSE_ACTIONS",
    "SCRIPT_GROUP_ACTIVE",
    "SCRIPT_GROUP_GROUPS",
    "SCRIPT_GROUP_SCRIPTS",
    "SCRIPT_GROUP_SUBROUTINE",
    "SCRIPT_HARD",
    "SCRIPT_IS_DUE",
    "SCRIPT_KEY_COMPOSE",
    "SCRIPT_LIST_ENTRY_GENERATION",
    "SCRIPT_LIST_ENTRY_NAME",
    "SCRIPT_LIST_ENTRY_OBJECTS",
    "SCRIPT_LIST_ENTRY_SIZE",
    "SCRIPT_LIST_GROUPS",
    "SCRIPT_LIST_GROUP_ENTRIES",
    "SCRIPT_LIST_SCRIPTS",
    "SCRIPT_LIST_SCRIPT_ENTRIES",
    "SCRIPT_NEXT_FRAME",
    "SCRIPT_NODE_GENERATION",
    "SCRIPT_NODE_INDEX",
    "SCRIPT_NODE_NEXT",
    "SCRIPT_NORMAL",
    "SCRIPT_ONE_SHOT",
    "SCRIPT_PARAMETER_INT",
    "SCRIPT_PARAMETER_NUMBER",
    "SCRIPT_PARAMETER_STRING",
    "SCRIPT_PARAMETER_TYPE",
    "SCRIPT_SCOPE_ENTER",
    "SCRIPT_SCOPE_GUARD_SIZE",
    "SCRIPT_SCOPE_LEAVE",
    "SCRIPT_SEQUENTIAL",
    "SCRIPT_SEQUENTIAL_EVALUATE_CALL",
    "SCRIPT_SEQUENTIAL_EVALUATE_CALL_BYTES",
    "SCRIPT_SUBROUTINE",
    "SCRIPT_TIMER_FRAMES_PER_MS",
    "SCRIPT_TIMER_MS_PER_SECOND",
    "SCRIPT_TRUE_ACTIONS",
    "THE_SCRIPT_ENGINE",
]

#: Script action 514, live: resolves a team by name through `TheTeamFactory` and assigns every
#: object on it to the battle's primary army. Distinct from the dead
#: `*_ASSIMILATE_WITH_ARMY_BY_NAME` trio (ids 540-542) in
#: `docs/living-campaign/dead-script-actions.md`.
SCRIPT_ACTION_TEAM_TO_ARMY = 0x007C409F
SCRIPT_ACTION_TEAM_TO_ARMY_ID = 514
#: The script debug window, engine side: both `-scriptDebug` flags load `DebugWindowLite.dll`; only
#: `-scriptDebugLite` sets `SCRIPT_DEBUG_SUPPRESS`.
SCRIPT_DEBUG_FLAG_HANDLER = 0x007BA1D4
SCRIPT_DEBUG_LITE_FLAG_HANDLER = 0x007BA1FB
SCRIPT_DEBUG_USE_LITE_DLL = 0x00DE87BA
SCRIPT_DEBUG_SUPPRESS = 0x00DE87B8
SCRIPT_DEBUG_MODULE = 0x00DE3B98
#: The engine's `AppendMessage` wrapper, with 87 direct callers across the script engine. It
#: resolves the export **by name on every message** (`GetProcAddress` at `0x00604DAD`, and again
#: at `0x00604FE8` for the pause variant) before formatting the frame-number prefix and calling
#: it. Real overhead, and not where the stutter is.
SCRIPT_DEBUG_APPEND_MESSAGE = 0x00604D85
SCRIPT_DEBUG_ADJUST_VARIABLE = 0x00605021
#: `ScriptActions::executeAction` and its 600-case jump table. A table entry that *is*
#: `SCRIPT_ACTION_EPILOGUE` is a stub - the action exists in WorldBuilder and does nothing, which
#: is what makes one repointable to a cave. Case bodies end with `jmp SCRIPT_ACTION_EPILOGUE`,
#: with `esi` holding the action and `edi` the `ScriptActions` object.
SCRIPT_ACTIONS_EXECUTE_ACTION = 0x007CAFA5
SCRIPT_ACTION_JUMP_TABLE = 0x007CF857
SCRIPT_ACTION_EPILOGUE = 0x007CF846
#: `ScriptAction::getParameter(int)` - `__thiscall`, `ret 4`, bounds-checked against
#: `SCRIPT_ACTION_PARAM_COUNT`, returning the `Parameter *` or NULL. Live case bodies inline it as
#: `[action + SCRIPT_ACTION_PARAM_ARRAY + i*4]`. `SCRIPT_ACTION_ENABLED` clear makes the
#: dispatcher skip the action outright.
SCRIPT_ACTION_GET_PARAMETER = 0x00602EFB
SCRIPT_ACTION_TYPE = 0x4
SCRIPT_ACTION_PARAM_COUNT = 0x8
SCRIPT_ACTION_PARAM_ARRAY = 0xC
SCRIPT_ACTION_ENABLED = 0x41
#: `Parameter`. The type tag is compared against `0x10` for a `Coord3D` at `0x007B3305`; the
#: numeric slot is what the timer path reads as a float; the string slot is an `AsciiString`,
#: so its characters start at `[param + SCRIPT_PARAMETER_STRING] + 8`.
SCRIPT_PARAMETER_TYPE = 0x0
SCRIPT_PARAMETER_NUMBER = 0xC
SCRIPT_PARAMETER_STRING = 0x10
#: `TheScriptEngine` and its name-keyed `std::map`s of counters (a timer is a counter) and flags.
THE_SCRIPT_ENGINE = 0x00DE3BAC
SCRIPT_ENGINE_COUNTER_MAP = 0x191A0
SCRIPT_ENGINE_FLAG_MAP = 0x191AC
#: Lookup-or-create by name, `__thiscall` on `THE_SCRIPT_ENGINE`, taking an `AsciiString` by value
#: and returning the record. These are the cheap way to write script state from a cave - the
#: `SET_*` entry points below all take a whole `ScriptAction` and read the name out of parameter 0.
SCRIPT_ENGINE_FIND_OR_CREATE_COUNTER = 0x0060817A
SCRIPT_ENGINE_FIND_OR_CREATE_FLAG = 0x006082CF
SCRIPT_ENGINE_FIND_FLAG = 0x00608249
#: The stage-1 script action implementations, reached from the chain at `0x0060C211` before it
#: delegates to `SCRIPT_ACTIONS_EXECUTE_ACTION`: `SET_FLAG` (1), `SET_COUNTER` (2) and `SET_TIMER`
#: (6) among 32 ids the script engine handles itself.
SCRIPT_ENGINE_SET_COUNTER = 0x00608D0B
SCRIPT_ENGINE_SET_FLAG = 0x00608FCC
SCRIPT_ENGINE_SET_TIMER = 0x00609092
#: A counter record. A timer holds ticks remaining, decremented once per tick and stopping at -1.
SCRIPT_COUNTER_VALUE = 0x0
SCRIPT_COUNTER_IS_TIMER = 0x4
SCRIPT_COUNTER_IS_SECONDS = 0x5
SCRIPT_ENGINE_TIMER_TICK_SITE = 0x0060CD4B
SCRIPT_TIMER_FRAMES_PER_MS = 0x00D9F610
SCRIPT_TIMER_MS_PER_SECOND = 0x00BD4388
#: `ScriptActions::createUnitRevivalEntry(player, unit, level)`: rebuilds a hero-ledger entry from
#: the three values a snapshot holds.
SCRIPT_ACTIONS_CREATE_UNIT_REVIVAL_ENTRY = 0x007C6D8E
SCRIPT_ENGINE_PLAYER_NAME_TO_INDEX = 0x00758F7C
#: `ScriptEngine::bindObjectName(AsciiString *, Object *)` - the script `unitName` binding, whose
#: string lives at `OBJECT_SCRIPT_NAME` on the object. `SCRIPT_ENGINE_NAMED_OBJECT_MAP` is the
#: sibling map it most likely writes; the only walker that types that map's value as an object id
#: is dead code, so treat the identification as unconfirmed.
SCRIPT_ENGINE_BIND_OBJECT_NAME = 0x00759467
SCRIPT_ENGINE_NAMED_OBJECT_MAP = 0x191B8
#: Counter and flag keys are scoped by the script player being evaluated; anything writing counters
#: from outside a script must set `SCRIPT_ENGINE_SCOPE` first.
SCRIPT_ENGINE_SCOPE = 0x1A20C
SCRIPT_ENGINE_SCOPED_KEY = 0x00604043
SCRIPT_KEY_COMPOSE = 0x0072C43C
#: The integer slot of a script `Parameter`, beside `SCRIPT_PARAMETER_NUMBER` (real) and
#: `SCRIPT_PARAMETER_STRING`. `CREATE_UNIT_REVIVAL_ENTRY_AT_LEVEL` reads its level from here.
SCRIPT_PARAMETER_INT = 0x8
#: A `ScriptList` is two node chains (top-level groups, top-level scripts) over two name-keyed
#: pools. A node is `{next, entry index, generation}`; the entry, `SCRIPT_LIST_ENTRY_SIZE` bytes in
#: the pool's array, holds the **name** and a chain of objects whose first one, plus 4, is the
#: current `ScriptGroup *` / `Script *` (`0x007B5379`, `0x007B53D8`). A node whose generation no
#: longer matches its entry's is stale, and the engine's walk skips it (`0x007B53EF`).
SCRIPT_LIST_GROUPS = 0x04
SCRIPT_LIST_SCRIPTS = 0x08
SCRIPT_LIST_GROUP_ENTRIES = 0x18
SCRIPT_LIST_SCRIPT_ENTRIES = 0x38
SCRIPT_LIST_ENTRY_SIZE = 0x14
SCRIPT_LIST_ENTRY_NAME = 0x08
SCRIPT_LIST_ENTRY_GENERATION = 0x0E
SCRIPT_LIST_ENTRY_OBJECTS = 0x10
SCRIPT_NODE_NEXT = 0x00
SCRIPT_NODE_INDEX = 0x04
SCRIPT_NODE_GENERATION = 0x08
#: `ScriptGroup`: its own child-group and script node chains (groups nest), then two flags. An
#: inactive group skips its scripts **and** its child groups; a subroutine group only runs when
#: called.
SCRIPT_GROUP_GROUPS = 0x04
SCRIPT_GROUP_SCRIPTS = 0x08
SCRIPT_GROUP_ACTIVE = 0x0C
SCRIPT_GROUP_SUBROUTINE = 0x0D
#: `Script`, from the chunk reader `0x007B83CC` and writer `0x007B63E8`. `SCRIPT_AUTHORED_ACTIVE`
#: is the flag as the map wrote it; `SCRIPT_ACTIVE` is the live copy the due check reads and a
#: one-shot clears. `SCRIPT_SEQUENTIAL` is the first byte of the fire-actions-sequentially block,
#: and selects `SCRIPT_ENGINE_EXECUTE_SEQUENTIAL` over `SCRIPT_ENGINE_EXECUTE_SCRIPT`.
#: `SCRIPT_DELAY_SECONDS` becomes `SCRIPT_NEXT_FRAME = frame + seconds * LOGIC_RATE` each run.
SCRIPT_SEQUENTIAL = 0x10
SCRIPT_DELAY_SECONDS = 0x20
SCRIPT_AUTHORED_ACTIVE = 0x28
SCRIPT_ONE_SHOT = 0x29
SCRIPT_SUBROUTINE = 0x2A
SCRIPT_EASY = 0x2B
SCRIPT_NORMAL = 0x2C
SCRIPT_HARD = 0x2D
SCRIPT_CONDITIONS = 0x30
SCRIPT_TRUE_ACTIONS = 0x34
SCRIPT_FALSE_ACTIONS = 0x38
SCRIPT_NEXT_FRAME = 0x3C
SCRIPT_ACTIVE = 0x40
#: How a script runs: every execution reaches `SCRIPT_ENGINE_RUN_SCRIPT(Script *, name)`.
SCRIPT_ENGINE_RUN_SCRIPT = 0x0060A15C
SCRIPT_ENGINE_RUN_SCRIPT_NODES = 0x0060A377
SCRIPT_ENGINE_RUN_GROUP_NODES = 0x0060BCE5
SCRIPT_ENGINE_CALL_SUBROUTINE = 0x0060BD42
SCRIPT_ENGINE_EXECUTE_SCRIPT = 0x006099DC
SCRIPT_ENGINE_EXECUTE_SEQUENTIAL = 0x00609C3A
SCRIPT_IS_DUE = 0x00603878
SCRIPT_ENGINE_CURRENT_PLAYER = 0x1A230
SCRIPT_ENGINE_DIFFICULTY = 0x1A5C4
#: The script debugger's pause (`docs/script-debugger.md` section 1): skipping the logic phase
#: freezes the simulation and nothing else.
FRAME_DISPATCHER = 0x006325A0
FRAME_DISPATCHER_PAUSE_CALL = 0x006325C4
FRAME_DISPATCHER_PAUSE_CALL_BYTES = bytes.fromhex("e8890efdff")
SCRIPT_DEBUG_PAUSED = 0x00603452
SCRIPT_DEBUG_POLL_CONTINUE = 0x00604189
SCRIPT_DEBUG_CAN_CONTINUE = 0x00DE3B9C
SCRIPT_DEBUG_RUN_FAST = 0x00603491
SCRIPT_DEBUG_IS_PAUSED = 0x00441E23
#: What a script trace hooks (`docs/script-debugger.md` section 2.1): the run-script logger's four
#: call sites, with the `Script *` in `esi`.
SCRIPT_DEBUG_RUN_SCRIPT_LOG = 0x00604F1C
SCRIPT_EXECUTE_LOG_CALLS = {
    0x00609AE7: bytes.fromhex("e830b4ffff"),  # true actions, per team member
    0x00609B37: bytes.fromhex("e8e0b3ffff"),  # false actions, per team member
    0x00609BB5: bytes.fromhex("e862b3ffff"),  # true actions
    0x00609BF4: bytes.fromhex("e823b3ffff"),  # false actions
}
SCRIPT_SEQUENTIAL_EVALUATE_CALL = 0x00609C55
SCRIPT_SEQUENTIAL_EVALUATE_CALL_BYTES = bytes.fromhex("e8b5f6ffff")
SCRIPT_ENGINE_EVALUATE = 0x0060930F
#: Inside `SCRIPT_ENGINE_EVALUATE`: the clauses are a chain of `OrCondition`s from
#: `SCRIPT_CONDITIONS`, each a chain of `Condition`s ANDed together. A disabled condition is skipped
#: and so counts as passed; the first one that fails ends its clause, and the first clause that
#: passes ends the evaluation. Every enabled condition is judged by the one call at
#: `SCRIPT_EVALUATE_CONDITION_CALL` to `SCRIPT_ENGINE_EVALUATE_CONDITION(Condition *)`
#: (`__thiscall` on the engine, `ret 4`, verdict in `al`), which is where a "why not" trace hooks.
#: The entry is a whole 5-byte `mov eax, imm32` (the SEH frame's handler), so it can become a `jmp`
#: that counts evaluations and resumes at `SCRIPT_ENGINE_EVALUATE_RESUME`.
SCRIPT_ENGINE_EVALUATE_ENTRY_BYTES = bytes.fromhex("b8760fb800")
SCRIPT_ENGINE_EVALUATE_RESUME = 0x00609314
SCRIPT_ENGINE_EVALUATE_CONDITION = 0x006092A9
SCRIPT_EVALUATE_CONDITION_CALL = 0x00609395
SCRIPT_EVALUATE_CONDITION_CALL_BYTES = bytes.fromhex("e80fffffff")
#: `OrCondition` and `Condition`, from the chunk writer `0x007B4DEA` and the walk above. The
#: condition type is the map's own content type (0 false, 1 counter, 2 flag, 3 true, 4 timer
#: expired, then the `ScriptConditions` table). The inversion flag is not read on the counter,
#: flag and timer paths of `SCRIPT_ENGINE_EVALUATE_CONDITION`.
OR_CONDITION_NEXT = 0x04
OR_CONDITION_CONDITIONS = 0x08
CONDITION_TYPE = 0x04
CONDITION_PARAM_COUNT = 0x08
CONDITION_NEXT = 0x3C
CONDITION_ENABLED = 0x4C
CONDITION_INVERTED = 0x4D
SCRIPT_ENGINE_RUN_ACTIONS = 0x0060C1C9
SCRIPT_ENGINE_CURRENT_OBJECT = 0x1A218
#: How the per-frame driver puts a player's scripts in scope - what a script run from outside it has
#: to repeat.
SCRIPT_SCOPE_ENTER = 0x00604243
SCRIPT_SCOPE_LEAVE = 0x0060428D
SCRIPT_SCOPE_GUARD_SIZE = 0x0C
