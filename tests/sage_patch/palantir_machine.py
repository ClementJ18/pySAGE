"""Emulated engine services for native SpecialPower presentation regression tests."""

import struct

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
from unicorn import x86_const as x86

BASE = 0x400000


class World:
    def __init__(
        self,
        image,
        matched=False,
        update_starts=False,
        movie=True,
        disabled=False,
        valid_upgrade=True,
        override=False,
        present=None,
    ):
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        for start, size in [
            (0, 0x1000),
            (BASE, 0xB00000),
            (0x1000000, 0x10000),
            (0x2000000, 0x20000),
            (0x3000000, 0x10000),
        ]:
            self.uc.mem_map(start, size)
        self.uc.mem_write(BASE, image)
        self.module, self.data, self.obj, self.template, self.player = (
            0x2000000,
            0x2001000,
            0x2002000,
            0x2003000,
            0x2004000,
        )
        self.behaviors, self.behavior, self.update, self.vtable = (
            0x2005000,
            0x2006000,
            0x2007000,
            0x2008000,
        )
        self.pos, self.string, self.upgrade = 0x2009000, 0x200A000, 0x200B000
        self.final_template = self.template + 0x200 if override else self.template
        self.uc.mem_write(self.pos, struct.pack("<3f", 70, 80, 90))
        self.uc.mem_write(self.obj + 0x38, struct.pack("<3f", 10, 20, 30))
        self.uc.mem_write(self.string, struct.pack("<IHH", 1, 4, 30) + b"ProbeMovie\0")
        self.put(self.module + 4, self.data)
        self.put(self.module + 8, self.obj)
        self.put(self.module + 0x10, self.vtable + 0x200)
        self.put(self.data + 8, self.template)
        self.uc.mem_write(self.data + 0xC, bytes([update_starts]))
        self.put(self.obj + 0x74, 77)
        self.put(self.obj + 0x24C, self.behaviors)
        self.put(self.template + 4, self.final_template if override else 0)
        self.put(self.final_template + 0x5C, self.string if movie else 0)
        self.put(self.final_template + 0x1C, 1)
        self.put(self.player + 0x54, 3)
        self.put(self.behaviors, self.behavior if (matched if present is None else present) else 0)
        self.put(self.behavior + 0xC, self.vtable)
        self.put(self.vtable + 0x64, 0x1000100)
        self.put(self.update, self.vtable + 0x100)
        self.put(self.vtable + 0x100, 0x1000140)
        self.put(self.vtable + 0x100 + 0x1C, 0x1000120)
        self.put(self.vtable + 0x100 + 8, 0x1000160)
        self.put(self.vtable + 0x200 + 0x3C, 0x1000180)
        self.put(0xDE42FC, self.player + 0x500)
        self.put(self.player + 0x500, self.vtable + 0x300)
        self.put(self.vtable + 0x300 + 0x64, 0x10001A0)
        self.put(self.upgrade + 4, 0)
        self.put(self.data + 0x7C, self.behaviors + 0x100)
        self.put(self.data + 0x80, self.behaviors + 0x104)
        self.put(self.behaviors + 0x100, self.string)
        self.events = []
        self.audio = {}
        self.disabled = disabled
        self.valid_upgrade = valid_upgrade
        self.stub_trigger = True
        self.stop_at = None
        self.handlers = {
            0x1000100: (0, lambda: self.update),
            0x1000120: (4, lambda: int(matched)),
            0x1000140: (20, lambda: self.event("update-intent", self.arg(0))),
            0x1000160: (0, lambda: 0),
            0x1000180: (4, lambda: self.event("recharge", self.arg(0))),
            0x10001A0: (4, self.add_audio),
            0x9325B4: (0, lambda: int(self.disabled)),
            0x44DDEC: (4, lambda: 0),
            0x435F30: (4, self.copy_string),
            0x435D50: (0, lambda: 0),
            0x6D5397: (8, lambda: self.event("movie-request", self.get(self.arg(0)))),
            0x4B1B5A: (0, lambda: self.event("initiate-fx", self.arg(0))),
            0x70E013: (0, lambda: 0),
            0x68B678: (0, lambda: self.player),
            0x759986: (12, lambda: self.event("script-notify", self.arg(0))),
            0x6DA95E: (8, self.audio_ctor),
            0x6DA6A7: (4, lambda: self.event("sound-object-id", self.arg(0))),
            0x6DA67E: (4, self.set_pos),
            0x66ECE1: (4, lambda: self.event("sound-player-index", self.arg(0))),
            0x6DABCB: (0, lambda: 0),
            0x4BB893: (4, self.copy_vector),
            0x66F5E5: (4, lambda: self.upgrade if self.valid_upgrade else 0),
            0x6AEE22: (12, lambda: self.event("grant-upgrade", self.arg(0))),
            0x42C978: (0, lambda: 0),
            0x8C7393: (0, lambda: 0),
        }
        self.uc.hook_add(UC_HOOK_CODE, self.hook)

    def put(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def get(self, a):
        return struct.unpack("<I", self.uc.mem_read(a, 4))[0]

    def arg(self, i):
        return self.get(self.uc.reg_read(x86.UC_X86_REG_ESP) + 4 + i * 4)

    def event(self, name, value):
        self.events.append((name, value))
        return 0

    def copy_string(self):
        a = self.uc.reg_read(x86.UC_X86_REG_ECX)
        self.put(a, self.get(self.arg(0)))
        return a

    def copy_vector(self):
        a = self.uc.reg_read(x86.UC_X86_REG_ECX)
        self.uc.mem_write(a, bytes(self.uc.mem_read(self.arg(0), 12)))
        return a

    def audio_ctor(self):
        a = self.uc.reg_read(x86.UC_X86_REG_ECX)
        self.audio[a] = {"field": hex(self.arg(0) - self.final_template), "position": None}
        return a

    def set_pos(self):
        a = self.uc.reg_read(x86.UC_X86_REG_ECX)
        self.audio[a]["position"] = struct.unpack("<3f", self.uc.mem_read(self.arg(0), 12))
        return 0

    def add_audio(self):
        self.events.append(("audio-request", dict(self.audio[self.arg(0)])))
        return 0

    def hook(self, uc, address, size, _):
        if address in (0x1000000, self.stop_at):
            uc.emu_stop()
            return
        if address == 0x897987 and self.stub_trigger:
            self.event("trigger-location", self.arg(0))
            cleanup, value = 4, 0
        elif address in self.handlers:
            cleanup, f = self.handlers[address]
            value = f()
        else:
            return
        esp = uc.reg_read(x86.UC_X86_REG_ESP)
        uc.reg_write(x86.UC_X86_REG_EAX, value or 0)
        uc.reg_write(x86.UC_X86_REG_ESP, esp + 4 + cleanup)
        uc.reg_write(x86.UC_X86_REG_EIP, self.get(esp))

    def run(self, target, args, interface=False, stop_at=None):
        self.stop_at = stop_at
        stack = 0x300F000
        self.put(stack, 0x1000000)
        for i, v in enumerate(args):
            self.put(stack + 4 + 4 * i, v)
        initial = {
            x86.UC_X86_REG_EBX: 0x11112222,
            x86.UC_X86_REG_ESI: 0x33334444,
            x86.UC_X86_REG_EDI: 0x55556666,
            x86.UC_X86_REG_EBP: 0x77778888,
        }
        for r, v in initial.items():
            self.uc.reg_write(r, v)
        self.uc.reg_write(x86.UC_X86_REG_ESP, stack)
        self.uc.reg_write(x86.UC_X86_REG_ECX, self.module + (0x10 if interface else 0))
        self.uc.emu_start(target, 0x1000000 + 1, count=20000)
        assert self.uc.reg_read(x86.UC_X86_REG_EIP) == (stop_at or 0x1000000), hex(
            self.uc.reg_read(x86.UC_X86_REG_EIP)
        )
        if stop_at is None:
            assert self.uc.reg_read(x86.UC_X86_REG_ESP) == stack + 4 + 4 * len(args)
            assert self.get(0) == 0, "SEH head not restored"
            for r, v in initial.items():
                assert self.uc.reg_read(r) == v, (r, self.uc.reg_read(r), v)
        return self.events
