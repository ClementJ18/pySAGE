"""`call-in-reinforcements`, executed.

The sibling file checks the fingerprint. This one runs the action body under Unicorn over the
synthetic stand-in, with a battle laid out in memory: `TheLivingWorldLogic` and `TheGameLogic`
globals, the battle bridge's army-id vector, and one roster per army. The by-name lookup and
`roster.callIn()` are answered in Python, so each case is an army in some state, in or out of the
battle, and the question is whether the cave hands its roster to `callIn` in state `READY` - and
leaves through the epilogue with the stack and the case-body registers as it found them.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import pytest

pytest.importorskip("unicorn", reason="the emulator harness needs unicorn")
pytest.importorskip("pefile", reason="the emulator harness maps the image with pefile")

from unicorn.x86_const import UC_X86_REG_ESP  # noqa: E402

from sage_patch.addresses import (  # noqa: E402
    LIVING_WORLD_ARMY_ROSTER_ID,
    LIVING_WORLD_ARMY_ROSTER_OFFSET,
    LIVING_WORLD_BATTLE_ARMY_IDS_BEGIN,
    LIVING_WORLD_BATTLE_ARMY_IDS_END,
    LIVING_WORLD_BATTLE_BRIDGE_OFFSET,
    LIVING_WORLD_FIND_ARMY_BY_NAME,
    LIVING_WORLD_ROSTER_CALL_IN,
    LIVING_WORLD_ROSTER_STATE,
    ROSTER_STATE_CALLED_IN,
    ROSTER_STATE_IN_BATTLE,
    ROSTER_STATE_READY,
    ROSTER_STATE_SUMMONING,
    ROSTER_STATE_WAITING,
    SCRIPT_ACTION_EPILOGUE,
    SCRIPT_ACTION_PARAM_ARRAY,
    SCRIPT_ACTION_PARAM_COUNT,
    SCRIPT_PARAMETER_STRING,
    THE_GAME_LOGIC,
    THE_LIVING_WORLD_LOGIC,
)
from sage_patch.patches.call_in_reinforcements import (  # noqa: E402
    SECTION_NAME,
    CallInReinforcementsPatch,
)
from sage_patch.utils import find_section  # noqa: E402

from .save_machine import Machine  # noqa: E402
from .synthetic import call_in_reinforcements_image  # noqa: E402

LIVING_WORLD_LOGIC = 0x0A0A0A0A
SCRIPT_ACTIONS = 0x0B0B0B0B


@pytest.fixture(scope="module")
def image() -> bytes:
    data = call_in_reinforcements_image()
    CallInReinforcementsPatch().apply(data)
    return bytes(data)


@dataclass
class Battle:
    """A living world with named armies, some of them in the battle being fought."""

    m: Machine
    armies: dict[str, int] = field(default_factory=dict)
    looked_up: list[str] = field(default_factory=list)
    #: `(roster, its state on entry)` for every `callIn` the cave made.
    called_in: list[tuple[int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        m = self.m
        self.action_va = find_section(m.image, SECTION_NAME)[0]
        self.logic = m.alloc(0x400, bytes(0x400))
        self.ids = m.alloc(0x100, bytes(0x100))
        self.in_battle = 0
        self._set_ids_end()
        m.ensure(THE_GAME_LOGIC)
        m.write32(THE_GAME_LOGIC, self.logic)
        m.ensure(THE_LIVING_WORLD_LOGIC)
        m.write32(THE_LIVING_WORLD_LOGIC, LIVING_WORLD_LOGIC)
        m.stub(LIVING_WORLD_FIND_ARMY_BY_NAME, self._find)
        m.stub(LIVING_WORLD_ROSTER_CALL_IN, self._call_in)
        m.stop_at(SCRIPT_ACTION_EPILOGUE)

    def _set_ids_end(self) -> None:
        bridge = self.logic + LIVING_WORLD_BATTLE_BRIDGE_OFFSET
        self.m.write32(bridge + LIVING_WORLD_BATTLE_ARMY_IDS_BEGIN, self.ids)
        self.m.write32(bridge + LIVING_WORLD_BATTLE_ARMY_IDS_END, self.ids + 4 * self.in_battle)

    def army(self, name: str, state: int, army_id: int, *, in_battle: bool = True) -> int:
        """Add an army; return its roster."""
        army = self.m.alloc(0x100, bytes(0x100))
        roster = self.m.alloc(0x100, bytes(0x100))
        self.m.write32(army + LIVING_WORLD_ARMY_ROSTER_OFFSET, roster)
        self.m.write32(roster + LIVING_WORLD_ARMY_ROSTER_ID, army_id)
        self.m.write32(roster + LIVING_WORLD_ROSTER_STATE, state)
        self.armies[name] = army
        if in_battle:
            self.m.write32(self.ids + 4 * self.in_battle, army_id)
            self.in_battle += 1
            self._set_ids_end()
        return roster

    def _find(self, m: Machine) -> None:
        assert m.reg("ecx") == LIVING_WORLD_LOGIC
        buffer = m.read32(m.arg(0))  # AsciiString* -> its buffer
        name = bytes(m.uc.mem_read(buffer + 8, 64)).split(b"\0")[0].decode()
        self.looked_up.append(name)
        m.ret(4, self.armies.get(name, 0))

    def _call_in(self, m: Machine) -> None:
        roster = m.reg("ecx")
        state = m.read32(roster + LIVING_WORLD_ROSTER_STATE)
        self.called_in.append((roster, state))
        if state == ROSTER_STATE_READY:
            m.write32(roster + LIVING_WORLD_ROSTER_STATE, ROSTER_STATE_CALLED_IN)
        m.ret(0)

    def action(self, name: str | None, *, params: int = 1, null_buffer: bool = False) -> int:
        """A ScriptAction whose parameter 0 holds `name`."""
        m = self.m
        param = m.alloc(0x40, bytes(0x40))
        if name is not None and not null_buffer:
            text = name.encode() + b"\0"
            buffer = m.alloc(8 + len(text), struct.pack("<IHH", 1, len(name), 0) + text)
            m.write32(param + SCRIPT_PARAMETER_STRING, buffer)
        action = m.alloc(0x60, bytes(0x60))
        m.write32(action + SCRIPT_ACTION_PARAM_COUNT, params)
        m.write32(action + SCRIPT_ACTION_PARAM_ARRAY, param if name is not None else 0)
        return action

    def run(self, action: int) -> None:
        """Enter the cave as the jump table does and run it to the epilogue."""
        m = self.m
        esp = 0x20000000 + 0x40000 - 0x1000
        m.write32(esp, 0xDEADBEEF)
        m.run(self.action_va, esp, esi=action, edi=SCRIPT_ACTIONS, ebx=0x1234, ebp=0x5678)
        assert m.stopped_at == SCRIPT_ACTION_EPILOGUE, f"stopped at {m.stopped_at}"
        assert m.uc.reg_read(UC_X86_REG_ESP) == esp, "the stack is not as the jump table left it"
        assert m.reg("esi") == action
        assert m.reg("edi") == SCRIPT_ACTIONS
        assert m.reg("ebx") == 0x1234
        assert m.reg("ebp") == 0x5678


@pytest.fixture
def battle(image: bytes) -> Battle:
    return Battle(Machine(image))


@pytest.mark.parametrize(
    "state", [ROSTER_STATE_WAITING, ROSTER_STATE_SUMMONING, ROSTER_STATE_READY]
)
def test_a_reinforcement_the_banner_still_offers_is_called_in(battle: Battle, state: int) -> None:
    roster = battle.army("AngmarRaiders", state, 7)
    battle.run(battle.action("AngmarRaiders"))
    assert battle.called_in == [(roster, ROSTER_STATE_READY)]
    assert battle.m.read32(roster + LIVING_WORLD_ROSTER_STATE) == ROSTER_STATE_CALLED_IN


@pytest.mark.parametrize("state", [ROSTER_STATE_IN_BATTLE, ROSTER_STATE_CALLED_IN, 5])
def test_an_army_already_fighting_is_left_alone(battle: Battle, state: int) -> None:
    roster = battle.army("AngmarRaiders", state, 7)
    battle.run(battle.action("AngmarRaiders"))
    assert battle.called_in == []
    assert battle.m.read32(roster + LIVING_WORLD_ROSTER_STATE) == state


def test_an_army_elsewhere_on_the_board_is_left_alone(battle: Battle) -> None:
    """It is `WAITING` too - the resting state - but deploying it would put it on the wrong map."""
    battle.army("Defenders", ROSTER_STATE_IN_BATTLE, 3)
    battle.army("SecondWave", ROSTER_STATE_WAITING, 4)
    roster = battle.army("FarAway", ROSTER_STATE_WAITING, 9, in_battle=False)
    battle.run(battle.action("FarAway"))
    assert battle.looked_up == ["FarAway"]
    assert battle.called_in == []
    assert battle.m.read32(roster + LIVING_WORLD_ROSTER_STATE) == ROSTER_STATE_WAITING


def test_the_army_is_found_anywhere_in_the_battle_list(battle: Battle) -> None:
    battle.army("Defenders", ROSTER_STATE_IN_BATTLE, 3)
    battle.army("SecondWave", ROSTER_STATE_WAITING, 4)
    last = battle.army("ThirdWave", ROSTER_STATE_WAITING, 5)
    battle.run(battle.action("ThirdWave"))
    assert battle.called_in == [(last, ROSTER_STATE_READY)]


def test_an_unknown_name_does_nothing(battle: Battle) -> None:
    battle.army("AngmarRaiders", ROSTER_STATE_WAITING, 7)
    battle.run(battle.action("Nobody"))
    assert battle.looked_up == ["Nobody"]
    assert battle.called_in == []


@pytest.mark.parametrize("null_buffer", [False, True], ids=["empty", "null"])
def test_an_empty_name_is_never_looked_up(battle: Battle, null_buffer: bool) -> None:
    """`AsciiString::compare` would match it against the first army with no ScriptingName."""
    battle.army("", ROSTER_STATE_WAITING, 7)
    battle.run(battle.action("", null_buffer=null_buffer))
    assert battle.looked_up == []
    assert battle.called_in == []


def test_an_action_without_its_parameter_does_nothing(battle: Battle) -> None:
    battle.army("AngmarRaiders", ROSTER_STATE_WAITING, 7)
    battle.run(battle.action("AngmarRaiders", params=0))
    battle.run(battle.action(None))
    assert battle.looked_up == []
    assert battle.called_in == []


def test_outside_a_living_world_session_nothing_is_touched(battle: Battle) -> None:
    battle.army("AngmarRaiders", ROSTER_STATE_WAITING, 7)
    battle.m.write32(THE_LIVING_WORLD_LOGIC, 0)
    battle.run(battle.action("AngmarRaiders"))
    assert battle.looked_up == []
    assert battle.called_in == []


def test_a_second_call_in_is_inert(battle: Battle) -> None:
    roster = battle.army("AngmarRaiders", ROSTER_STATE_WAITING, 7)
    battle.run(battle.action("AngmarRaiders"))
    battle.run(battle.action("AngmarRaiders"))
    assert battle.called_in == [(roster, ROSTER_STATE_READY)]
