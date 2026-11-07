"""Execute native dispatcher, per-type cleanup and actual command-button rebuild caves."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sage_patch import UpgradeModuleConflictsPatch, UpgradeModuleRemovalPatch
from sage_patch import addresses as ad
from sage_patch.__main__ import main
from sage_patch.patches.commandbar import commandset_button_upgrade as cb
from sage_patch.registry import PATCHES
from sage_patch.sagepatch import generate_from_patches, rebuild
from sage_patch.utils import file_offset


def reference() -> bytes:
    path = Path(__file__).resolve().parents[2] / "tools/BFME-FILES/game.dat.backup"
    if not path.exists():
        pytest.skip("RotWK reference backup unavailable")
    return path.read_bytes()


def test_registration_cli_and_manifest(tmp_path: Path) -> None:
    name = "upgrade-module-conflicts"
    assert PATCHES[name] is UpgradeModuleConflictsPatch
    generated, unknown = generate_from_patches([name])
    assert unknown == []
    assert [p.name for p in generated.patches] == ["upgrade-module-conflicts"]
    from sage_ini.engine import AppliedPatch, Engine  # noqa: PLC0415

    patches, problems = rebuild(Engine(patches=(AppliedPatch(name),)))
    assert problems == [] and isinstance(patches[0], UpgradeModuleConflictsPatch)
    source, output = tmp_path / "stock.dat", tmp_path / "patched.dat"
    source.write_bytes(reference())
    assert main(["apply", name, "--in", str(source), "--out", str(output)]) == 0
    assert main(["verify", name, str(output)]) == 0
    assert source.read_bytes() == reference()


@pytest.mark.parametrize("reverse", [False, True])
def test_real_binary_composition_with_removal_and_buttons(reverse: bool) -> None:
    data = bytearray(reference())
    patches = [
        UpgradeModuleConflictsPatch(),
        UpgradeModuleRemovalPatch(),
        cb.CommandSetButtonUpgradePatch(),
    ]
    for patch in reversed(patches) if reverse else patches:
        patch.apply(data)
    assert all(not patch.verify(data) for patch in patches)


@pytest.mark.parametrize(
    "va", [*ad.OBJECT_CREATION_UPGRADE_CONFLICT_ANCHORS, ad.OBJECT_CREATION_UPGRADE_CONFLICT_CALL]
)
def test_creation_fingerprints_are_checked_before_mutation(va: int) -> None:
    data = bytearray(reference())
    data[file_offset(data, va)] ^= 1
    before = bytes(data)
    with pytest.raises(ValueError, match="unexpected build"):
        UpgradeModuleConflictsPatch().apply(data)
    assert data == before


class NativeWorld:
    """Native upgrade objects/masks; mock only external pools, UI, strings and production."""

    def __init__(self, *, buttons: bool = False, reverse: bool = False, removal: bool = False):
        pytest.importorskip("unicorn")
        pytest.importorskip("pefile")
        from .save_machine import Machine  # noqa: PLC0415

        data = bytearray(reference())
        patches = [UpgradeModuleConflictsPatch()]
        if buttons:
            patches.append(cb.CommandSetButtonUpgradePatch())
        if removal:
            patches.append(UpgradeModuleRemovalPatch())
        for patch in reversed(patches) if reverse else patches:
            patch.apply(data)
        assert all(not p.verify(data) for p in patches)
        self.m = m = Machine(bytes(data))
        self.obj, self.player, self.template = m.alloc(0x600), m.alloc(0x900), m.alloc(0x100)
        m.write32(self.obj + 4, self.template)
        self.field(self.template + 0x70, "BaseSet")
        self.modules = []
        self.events = []
        self.pool = {"Modifier_Test"}
        self.sets, self.set_names = {}, {}
        self.buttons = {"Command_A": 0xAAAA, "Command_B": 0xBBBB}
        self.new_set("BaseSet", {0: 0x1111})
        m.write32(cb.THE_COMMAND_SET_STORE, m.alloc(0x80))
        m.write32(cb.SELECTION_UI, m.alloc(0x80))
        m.stub(0x68B678, lambda x: x.ret(value=self.player))
        m.stub(0x797BEF, lambda x: x.ret(value=0))  # no related-object upgrade source
        m.stub(ad.UPGRADE_MASK_INIT, self.zero_mask)
        m.stub(0x444DB3, self.copy_mask)
        m.stub(0x8D28F1, lambda x: x.ret())
        m.stub(0x8D28F9, lambda x: x.ret())
        m.stub(0x8D286F, lambda x: x.ret(4))
        m.stub(0x9F3A3C, lambda x: x.ret(4))  # cosmetic UpgradeFX
        m.stub(0x68F259, self.remove_modifier)
        m.stub(0x68F1A8, self.add_modifier)
        m.stub(0x401E64, lambda x: x.ret(value=int(not self.text(x.reg("ecx")))))
        m.stub(0x4065AA, lambda x: x.ret(4, int(self.text(x.reg("ecx")) != self.text(x.arg(0)))))
        m.stub(0x4374E0, self.set_string)
        m.stub(cb.ASCII_STRING_SET, self.set_string)
        m.stub(cb.ASCII_STRING_ASSIGN, self.assign_string)
        m.stub(0x435F30, self.assign_string)
        m.stub(cb.ASCII_STRING_DTOR, lambda x: x.ret())
        m.stub(cb.ASCII_STRING_CONCAT_CSTR, self.concat_string)
        m.stub(cb.ASCII_STRING_CONCAT_CHAR, self.concat_char)
        m.stub(cb.SET_COMMAND_SET_STRING_OVERRIDE, self.set_override)
        m.stub(cb.FIND_COMMAND_SET, self.find_set)
        m.stub(cb.NEW_COMMAND_SET, self.create_set)
        m.stub(cb.FIND_COMMAND_BUTTON, lambda x: x.ret(4, self.buttons.get(self.text(x.arg(0)), 0)))
        m.stub(cb.CLEAR_COMMAND_BUTTONS, lambda x: (self.sets[x.reg("ecx")].clear(), x.ret()))
        m.stub(cb.GET_COMMAND_BUTTON, lambda x: x.ret(4, self.sets[x.reg("ecx")].get(x.arg(0), 0)))
        m.stub(cb.SET_COMMAND_BUTTON, self.set_button)
        m.stub(cb.UI_DESELECT, lambda x: x.ret(4))
        m.stub(cb.UI_RESELECT, lambda x: x.ret(4))

    def string(self, text):
        raw = text.encode() + b"\0"
        return self.m.alloc(8 + len(raw), struct.pack("<IHH", 1, len(raw) - 1, len(raw)) + raw)

    def cstr(self, address):
        out = bytearray()
        while (b := bytes(self.m.uc.mem_read(address + len(out), 1))) != b"\0":
            out.extend(b)
        return out.decode()

    def text(self, slot):
        pointer = self.m.read32(slot)
        return self.cstr(pointer + 8) if pointer else ""

    def field(self, slot, text):
        self.m.write32(slot, self.string(text) if text else 0)

    def zero_mask(self, m):
        m.uc.mem_write(m.reg("ecx"), bytes(0x90))
        m.ret(value=m.reg("ecx"))

    def copy_mask(self, m):
        m.uc.mem_write(m.reg("ecx"), bytes(m.uc.mem_read(m.arg(0), 0x90)))
        m.ret(4, m.reg("ecx"))

    def set_string(self, m):
        self.field(m.reg("ecx"), self.cstr(m.arg(0)))
        m.ret(4, m.reg("ecx"))

    def assign_string(self, m):
        self.field(m.reg("ecx"), self.text(m.arg(0)))
        m.ret(4, m.reg("ecx"))

    def concat_string(self, m):
        self.field(m.reg("ecx"), self.text(m.reg("ecx")) + self.cstr(m.arg(0)))
        m.ret(4, m.reg("ecx"))

    def concat_char(self, m):
        self.field(m.reg("ecx"), self.text(m.reg("ecx")) + chr(m.arg(0)))
        m.ret(4, m.reg("ecx"))

    def set_override(self, m):
        self.field(self.obj + 0x43C, self.text(m.arg(0)))
        self.events.append(("command-set", self.text(m.arg(0))))
        m.ret(4)

    def remove_modifier(self, m):
        name = self.text(m.arg(0))
        self.pool.discard(name)
        self.events.append(("remove-modifier", name))
        m.ret(4)

    def add_modifier(self, m):
        name = self.text(m.arg(0))
        self.pool.add(name)
        self.events.append(("add-modifier", name))
        m.ret(8)

    def new_set(self, name, buttons=None):
        ptr = self.m.alloc(0x100)
        self.sets[ptr] = buttons or {}
        self.set_names[name] = ptr
        return ptr

    def find_set(self, m):
        m.ret(4, self.set_names.get(self.text(m.arg(0)), 0))

    def create_set(self, m):
        assert m.arg(1) == 1
        m.ret(8, self.new_set(self.text(m.arg(0))))

    def set_button(self, m):
        self.sets[m.reg("ecx")][m.arg(1)] = m.arg(0)
        m.ret(8)

    def module(
        self, kind, *, trigger=1, conflict=2, all_conflicts=False, permanent=False, overlay=""
    ):
        m = self.m
        module, md = m.alloc(0x60), m.alloc(0x200)
        if kind == "creation":
            m.write32(module, ad.OBJECT_CREATION_UPGRADE_MUX_VTABLE)
            m.write32(module + 8, 0xC6E21C)
            m.write32(module + 0x14, 0xC6E160)
            m.write32(module + 0x18, 0xC6E150)
            m.write32(module + 0xC, md)
            m.write32(module + 0x10, self.obj)
            m.write32(module + 0x28, 1000)
            m.uc.mem_write(module + 0x2C, b"\x01")
            iface, member, mask, modes = module, module + 8, 0x10, 0x13C
            m.write32(md + 0x160, 0xFFFFFFFF)
        else:
            m.write32(module, 0xC6F448 if kind == "modifier" else cb.MODULE_VTABLE)
            m.write32(module + 0xC, 0xC6DC98)
            m.write32(module + 0x10, 0xC6F400 if kind == "modifier" else 0xC6DEF8)
            m.write32(module + 4, md)
            m.write32(module + 8, self.obj)
            iface, member, mask, modes = module + 0x10, module, 8, 0x134
            self.field(md + 0x138, "Modifier_Test" if kind == "modifier" else "AppliedSet")
            if overlay:
                self.field(md + cb.COMMAND_SET_OFFSET, "")
                self.field(md + cb.COMMAND_BUTTONS_OFFSET, overlay)
        m.write32(md + mask, trigger)
        m.write32(md + mask + 0x90, conflict)
        m.uc.mem_write(md + modes + 1, bytes([all_conflicts]))
        m.uc.mem_write(md + modes + 2, bytes([permanent]))
        m.uc.mem_write(iface + 4, b"\x01")
        self.modules.append(member)
        array = m.alloc(4 * (len(self.modules) + 1))
        for n, ptr in enumerate(self.modules):
            m.write32(array + 4 * n, ptr)
        m.write32(self.obj + 0x24C, array)
        return iface, md

    def dispatch(self, held):
        self.m.write32(self.player + 0x14C, held)
        self.m.call(ad.OBJECT_DISPATCH_UPGRADES, ecx=self.obj)
        assert not self.m.faults


@pytest.mark.parametrize("permanent", [False, True])
@pytest.mark.parametrize("removal", [False, True])
def test_native_attribute_modifier_cleanup_and_reactivation(permanent: bool, removal: bool) -> None:
    w = NativeWorld(removal=removal)
    iface, _md = w.module("modifier", permanent=permanent)
    w.dispatch(3)
    assert bytes(w.m.uc.mem_read(iface + 4, 1)) == b"\0"
    assert w.pool == ({"Modifier_Test"} if permanent else set())
    assert w.events.count(("remove-modifier", "Modifier_Test")) == int(not permanent)
    if not permanent:
        w.dispatch(1)
        w.dispatch(1)
        assert w.pool == {"Modifier_Test"}
        assert w.events.count(("add-modifier", "Modifier_Test")) == 1


@pytest.mark.parametrize("destroy,watcher", [(False, True), (True, False), (True, True)])
def test_native_object_creation_cancel_spawn_policy_and_no_upgrade_undo(
    destroy: bool, watcher: bool
) -> None:
    w = NativeWorld()
    m = w.m
    iface, md = w.module("creation")
    m.uc.mem_write(md + 0x15C, bytes([destroy]))
    m.write32(w.obj + 0x28C, 0x20)  # a previously granted OBJECT upgrade
    m.write32(0xDE9864, 1)  # initialized SlaveWatcher name key
    m.write32(0xDE9860, 123)
    slave, child = m.alloc(0x40), m.alloc(0x100)
    m.stub(0x68BDA5, lambda x: x.ret(4, slave if watcher else 0))
    m.stub(0xA0605D, lambda x: x.ret(value=77))
    m.stub(0x449681, lambda x: x.ret(4, child))
    m.stub(0x698EC3, lambda x: (w.events.append(("kill", x.reg("ecx"))), x.ret(8)))
    m.stub(0x69388B, lambda x: (w.events.append(("grant", x.arg(0))), x.ret(4)))
    m.stub(0x691438, lambda x: (w.events.append(("remove-upgrade", x.arg(0))), x.ret(4)))
    w.dispatch(3)
    assert bytes(m.uc.mem_read(iface + 4, 1)) == b"\0"
    assert bytes(m.uc.mem_read(iface + 0x2C, 1)) == b"\0"
    assert m.read32(iface + 0x28) == 0x3FFFFFFF
    assert w.events == ([("kill", child)] if destroy and watcher else [])
    assert m.read32(w.obj + 0x28C) == 0x20  # no automatic reversal of GrantUpgrade


@pytest.mark.parametrize(
    "all_conflicts,mask,held,active",
    [(False, 6, 3, False), (True, 6, 3, True), (True, 6, 7, False), (True, 0, 1, True)],
)
def test_native_creation_post_check_obeys_all_any_and_empty_masks(
    all_conflicts, mask, held, active
):
    w = NativeWorld()
    iface, _ = w.module("creation", conflict=mask, all_conflicts=all_conflicts)
    w.dispatch(held)
    assert bool(w.m.uc.mem_read(iface + 4, 1)[0]) == active
    assert bool(w.m.uc.mem_read(iface + 0x2C, 1)[0]) == active


def test_native_plain_commandset_restores_template_override() -> None:
    w = NativeWorld()
    iface, _ = w.module("commandset")
    w.field(w.obj + 0x43C, "AppliedSet")
    w.dispatch(3)
    assert w.text(w.obj + 0x43C) == ""
    assert bytes(w.m.uc.mem_read(iface + 4, 1)) == b"\0"
    assert w.events.count(("command-set", "")) == 1


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("removal", [False, True])
def test_command_button_union_removes_only_conflicting_module_and_restores_it(reverse, removal):
    w = NativeWorld(buttons=True, reverse=reverse, removal=removal)
    a, _ = w.module("commandset", trigger=1, conflict=2, overlay="Command_A:3")
    b, _ = w.module("commandset", trigger=8, conflict=4, overlay="Command_B:4")
    w.dispatch(9)
    assert w.sets[w.set_names[w.text(w.obj + 0x43C)]] == {0: 0x1111, 3: 0xAAAA, 4: 0xBBBB}
    w.dispatch(11)
    assert bytes(w.m.uc.mem_read(a + 4, 1)) == b"\0"
    assert bytes(w.m.uc.mem_read(b + 4, 1)) == b"\x01"
    assert w.text(w.obj + 0x43C) == "BaseSet+Command_B:4"
    assert w.sets[w.set_names[w.text(w.obj + 0x43C)]] == {0: 0x1111, 4: 0xBBBB}
    w.dispatch(9)
    assert w.sets[w.set_names[w.text(w.obj + 0x43C)]] == {0: 0x1111, 3: 0xAAAA, 4: 0xBBBB}


@pytest.mark.parametrize("production,accept", [(False, False), (True, False), (True, True)])
def test_object_creation_building_production_queue_retry_and_upgrade_actions(production, accept):
    w = NativeWorld()
    m = w.m
    iface, md = w.module("creation")
    logic = m.alloc(0x80)
    m.write32(ad.THE_GAME_LOGIC, logic)
    m.write32(logic + 0x40, 10)
    m.write32(iface + 0x28, 0)
    m.uc.mem_write(md + 0x170, b"\x01")
    self_tpl = m.alloc(0x80)
    self_prod, self_vtable = m.alloc(0x80), m.alloc(0x40)
    m.write32(self_prod, self_vtable)
    self_grant, self_remove = m.alloc(0x20), m.alloc(0x20)
    w.field(md + 0x148, "Spawn_Test")
    w.field(md + 0x144, "Grant_Test")
    w.field(md + 0x140, "Remove_Test")
    m.write32(md + 8, m.alloc(0x20))  # configured UpgradeObject OCL
    m.write32(w.obj + 0x28C, 0x40)
    m.stub(0x6D1305, lambda x: x.ret(4, self_tpl))
    m.stub(
        ad.OBJECT_GET_PRODUCTION_UPDATE_INTERFACE,
        lambda x: x.ret(4, self_prod if production else 0),
    )

    def prepare(x):
        assert [x.arg(i) for i in (0, 1, 3)] == [0xFFFFFFFF, 0, 1]
        x.ret(16, 99)

    def queue(x):
        assert [x.arg(i) for i in range(3)] == [self_tpl, 0xFFFFFFFF, 99]
        w.events.append(("queue", accept))
        x.ret(12, int(accept))

    def lookup(x):
        x.ret(4, {"Grant_Test": self_grant, "Remove_Test": self_remove}.get(w.text(x.arg(0)), 0))

    def grant(x):
        assert x.arg(0) == self_grant
        m.write32(w.obj + 0x28C, m.read32(w.obj + 0x28C) | 0x20)
        w.events.append(("grant", self_grant))
        x.ret(4)

    def remove(x):
        assert x.arg(0) == self_remove
        m.write32(w.obj + 0x28C, m.read32(w.obj + 0x28C) & ~0x40)
        w.events.append(("remove", self_remove))
        x.ret(4)

    m.write32(self_vtable + 8, m.stub(None, prepare))
    m.write32(self_vtable + 0x20, m.stub(None, queue))
    m.stub(0x66F5E5, lookup)
    m.stub(0x69388B, grant)
    m.stub(0x691438, remove)
    m.stub(0x5F0126, lambda x: (w.events.append(("ocl", None)), x.ret(12)))
    result = m.call(0x8B8464, ecx=iface + 0x18)
    assert not m.faults
    retry = production and not accept
    assert result == (1 if retry else 0x3FFFFFFF)
    assert w.events == (
        ([("queue", accept)] if production else [])
        + ([] if retry else [("grant", self_grant), ("remove", self_remove)])
    )
    assert m.read32(w.obj + 0x28C) == (0x40 if retry else 0x20)
