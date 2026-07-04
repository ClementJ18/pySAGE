"""ActionScript bytecode reading/writing for the APT format."""

import struct
from xml.etree import ElementTree as ET

# Opcode constants
ACTION_END = 0x00
ACTION_NEXTFRAME = 0x04
ACTION_PREVFRAME = 0x05
ACTION_PLAY = 0x06
ACTION_STOP = 0x07
ACTION_TOGGLEQUALITY = 0x08
ACTION_STOPSOUNDS = 0x09
ACTION_ADD = 0x0A
ACTION_SUBTRACT = 0x0B
ACTION_MULTIPLY = 0x0C
ACTION_DIVIDE = 0x0D
ACTION_EQUAL = 0x0E
ACTION_LESSTHAN = 0x0F
ACTION_LOGICALAND = 0x10
ACTION_LOGICALOR = 0x11
ACTION_LOGICALNOT = 0x12
ACTION_STRINGEQ = 0x13
ACTION_STRINGLENGTH = 0x14
ACTION_SUBSTRING = 0x15
ACTION_POP = 0x17
ACTION_INT = 0x18
ACTION_GETVARIABLE = 0x1C
ACTION_SETVARIABLE = 0x1D
ACTION_SETTARGETEXPRESSION = 0x20
ACTION_STRINGCONCAT = 0x21
ACTION_GETPROPERTY = 0x22
ACTION_SETPROPERTY = 0x23
ACTION_DUPLICATECLIP = 0x24
ACTION_REMOVECLIP = 0x25
ACTION_TRACE = 0x26
ACTION_STARTDRAGMOVIE = 0x27
ACTION_STOPDRAGMOVIE = 0x28
ACTION_STRINGCOMPARE = 0x29
ACTION_THROW = 0x2A
ACTION_CASTOP = 0x2B
ACTION_IMPLEMENTSOP = 0x2C
ACTION_RANDOM = 0x30
ACTION_MBLENGTH = 0x31
ACTION_ORD = 0x32
ACTION_CHR = 0x33
ACTION_GETTIMER = 0x34
ACTION_MBSUBSTRING = 0x35
ACTION_MBORD = 0x36
ACTION_MBCHR = 0x37
ACTION_DELETE = 0x3A
ACTION_DELETE2 = 0x3B
ACTION_DEFINELOCAL = 0x3C
ACTION_CALLFUNCTION = 0x3D
ACTION_RETURN = 0x3E
ACTION_MODULO = 0x3F
ACTION_NEW = 0x40
ACTION_VAR = 0x41
ACTION_INITARRAY = 0x42
ACTION_INITOBJECT = 0x43
ACTION_TYPEOF = 0x44
ACTION_TARGETPATH = 0x45
ACTION_ENUMERATE = 0x46
ACTION_NEWADD = 0x47
ACTION_NEWLESSTHAN = 0x48
ACTION_NEWEQUALS = 0x49
ACTION_TONUMBER = 0x4A
ACTION_TOSTRING = 0x4B
ACTION_DUP = 0x4C
ACTION_SWAP = 0x4D
ACTION_GETMEMBER = 0x4E
ACTION_SETMEMBER = 0x4F
ACTION_INCREMENT = 0x50
ACTION_DECREMENT = 0x51
ACTION_CALLMETHOD = 0x52
ACTION_NEWMETHOD = 0x53
ACTION_INSTANCEOF = 0x54
ACTION_ENUM2 = 0x55
EA_ACTION56 = 0x56
EA_ACTION58 = 0x58
EA_PUSHZERO = 0x59
EA_PUSHONE = 0x5A
EA_CALLFUNCTIONPOP = 0x5B
EA_CALLFUNCTION = 0x5C
EA_CALLMETHODPOP = 0x5D
EA_CALLMETHOD = 0x5E
ACTION_BITWISEAND = 0x60
ACTION_BITWISEOR = 0x61
ACTION_BITWISEXOR = 0x62
ACTION_SHIFTLEFT = 0x63
ACTION_SHIFTRIGHT = 0x64
ACTION_SHIFTRIGHT2 = 0x65
ACTION_STRICTEQ = 0x66
ACTION_GREATER = 0x67
ACTION_STRINGGREATER = 0x68
ACTION_EXTENDS = 0x69
EA_PUSHTHIS = 0x70
EA_PUSHGLOBAL = 0x71
EA_ZEROVARIABLE = 0x72
EA_PUSHTRUE = 0x73
EA_PUSHFALSE = 0x74
EA_PUSHNULL = 0x75
EA_PUSHUNDEFINED = 0x76
EA_ACTION77 = 0x77
ACTION_SETREGISTER = 0x87
ACTION_CONSTANTPOOL = 0x88
ACTION_GOTOFRAME = 0x81
ACTION_GETURL = 0x83
ACTION_WAITFORFRAME = 0x8A
ACTION_SETTARGET = 0x8B
ACTION_GOTOLABEL = 0x8C
ACTION_WAITFORFRAMEEXPRESSION = 0x8D
ACTION_DEFINEFUNCTION2 = 0x8E
ACTION_TRY = 0x8F
ACTION_WITH = 0x94
ACTION_PUSHDATA = 0x96
ACTION_BRANCHALWAYS = 0x99
ACTION_GETURL2 = 0x9A
ACTION_DEFINEFUNCTION = 0x9B
ACTION_BRANCHIFTRUE = 0x9D
ACTION_CALLFRAME = 0x9E
ACTION_GOTOEXPRESSION = 0x9F
EA_PUSHSTRING = 0xA1
EA_PUSHCONSTANT = 0xA2
EA_PUSHWORDCONSTANT = 0xA3
EA_GETSTRINGVAR = 0xA4
EA_GETSTRINGMEMBER = 0xA5
EA_SETSTRINGVAR = 0xA6
EA_SETSTRINGMEMBER = 0xA7
EA_PUSHVALUEOFVAR = 0xAE
EA_GETNAMEDMEMBER = 0xAF
EA_CALLNAMEDFUNCTIONPOP = 0xB0
EA_CALLNAMEDFUNCTION = 0xB1
EA_CALLNAMEDMETHODPOP = 0xB2
EA_CALLNAMEDMETHOD = 0xB3
EA_PUSHFLOAT = 0xB4
EA_PUSHBYTE = 0xB5
EA_PUSHSHORT = 0xB6
EA_PUSHLONG = 0xB7
EA_BRANCHIFFALSE = 0xB8
EA_PUSHREGISTER = 0xB9


# ActionBytes (used during XML→binary write)


class ActionBytes:
    """Accumulates action bytecode and associated relocation info."""

    def __init__(self):
        self.actionbytecount = 0
        self.buf = bytearray()
        self.constantcount = 0
        self.constants = []  # list of uint32 indices into const pool
        self.stringcount = 0
        self.actionstrings = []  # [{'offset': int, 'string': str}]
        self.pushdatacount = 0
        self.actionpushdatas = []  # [{'offset': int, 'count': int, 'data': [uint32]}]
        self.definefunction2count = 0
        # [{'offset': int, 'argumentcount': int, 'arguments': [{'reg','name'}]}]
        self.actiondefinefunction2s = []
        self.definefunctioncount = 0
        # [{'offset': int, 'argumentcount': int, 'arguments': [str]}]
        self.actiondefinefunctions = []
        # Branch resolution: label -> instruction start byte offset, and the branch
        # operand fields awaiting a signed delta once every label position is known.
        self.labelpositions = {}
        self.branchfixups = []  # [{'operand_offset': int, 'target': str}]

    def _write_byte(self, v):
        self.buf.append(v & 0xFF)
        self.actionbytecount += 1

    def _write_uint32(self, v):
        self.buf.extend(struct.pack("<I", v & 0xFFFFFFFF))
        self.actionbytecount += 4

    def _write_int32(self, v):
        self.buf.extend(struct.pack("<i", v))
        self.actionbytecount += 4

    def _write_uint16(self, v):
        self.buf.extend(struct.pack("<H", v & 0xFFFF))
        self.actionbytecount += 2

    def _write_float(self, v):
        self.buf.extend(struct.pack("<f", v))
        self.actionbytecount += 4

    def _align(self):
        pad = (4 - (self.actionbytecount % 4)) % 4
        for _ in range(pad):
            self._write_byte(0)

    def add_action(self, opcode):
        self._write_byte(opcode)

    def add_int_action(self, opcode, value):
        self._write_byte(opcode)
        self._align()
        self._write_int32(value)

    def add_string_action(self, opcode, string):
        self._write_byte(opcode)
        self._align()
        self.actionstrings.append({"offset": self.actionbytecount, "string": string})
        self.stringcount += 1
        self._write_uint32(0)  # pointer placeholder

    def add_byte_action(self, opcode, number):
        self._write_byte(opcode)
        self._write_byte(number & 0xFF)

    def add_short_action(self, opcode, number):
        self._write_byte(opcode)
        self._write_uint16(number)

    def add_float_action(self, opcode, number):
        self._write_byte(opcode)
        self._write_float(number)

    def add_long_action(self, opcode, number):
        self._write_byte(opcode)
        self._write_uint32(number)

    def add_url_action(self, opcode, str1, str2):
        self._write_byte(opcode)
        self._align()
        self.actionstrings.append({"offset": self.actionbytecount, "string": str1})
        self.stringcount += 1
        self._write_uint32(0)
        self.actionstrings.append({"offset": self.actionbytecount, "string": str2})
        self.stringcount += 1
        self._write_uint32(0)

    def add_constant_pool_action(self, opcode, constantcount):
        self._write_byte(opcode)
        self._align()
        self._write_uint32(constantcount)
        self._write_uint32(0)  # constants_ptr placeholder, patched at write time

    def add_definefunction2_action(self, opcode, pd, flags, size, name):
        self._write_byte(opcode)
        self._align()
        # name pointer (string relocation)
        self.actionstrings.append({"offset": self.actionbytecount, "string": name})
        self.stringcount += 1
        self._write_uint32(0)
        self._write_uint32(pd["argumentcount"])
        self._write_uint32(flags)
        pd["offset"] = self.actionbytecount
        self._write_uint32(0)  # arguments pointer placeholder
        pd["size_offset"] = self.actionbytecount
        self._write_uint32(size)
        self._write_uint32(0x98765432)
        self._write_uint32(0x12345678)

    def add_definefunction_action(self, opcode, pd, size, name):
        self._write_byte(opcode)
        self._align()
        self.actionstrings.append({"offset": self.actionbytecount, "string": name})
        self.stringcount += 1
        self._write_uint32(0)
        self._write_uint32(pd["argumentcount"])
        pd["offset"] = self.actionbytecount
        self._write_uint32(0)  # arguments pointer placeholder
        pd["size_offset"] = self.actionbytecount
        self._write_uint32(size)
        self._write_uint32(0x98765432)
        self._write_uint32(0x12345678)

    def add_branch_target_action(self, opcode, target):
        """Emit a branch whose operand will be resolved from a label, not a literal
        offset. The 4-byte operand is a placeholder patched by `resolve_branches`."""
        self._write_byte(opcode)
        self._align()
        self.branchfixups.append({"operand_offset": self.actionbytecount, "target": target})
        self._write_int32(0)

    def resolve_branches(self):
        """Patch every label-based branch operand with the signed byte delta.

        The destination is relative to the byte right after the 4-byte operand
        field (the confirmed corpus semantics), so the stored delta is
        `label_position - (operand_offset + 4)`."""
        for fx in self.branchfixups:
            target = fx["target"]
            if target not in self.labelpositions:
                raise ValueError(
                    f"branch target label {target!r} has no matching anchor instruction"
                )
            delta = self.labelpositions[target] - (fx["operand_offset"] + 4)
            struct.pack_into("<i", self.buf, fx["operand_offset"], delta)

    def add_pushdata_action(self, opcode, pd):
        self._write_byte(opcode)
        self._align()
        self._write_uint32(pd["count"])
        pd["offset"] = self.actionbytecount
        self._write_uint32(0)  # pushdata pointer placeholder


# Reading: binary → XML


def _read_cstring(buf, offset):
    end = offset
    while end < len(buf) and buf[end] != 0:
        end += 1
    return buf[offset:end].decode("latin-1", errors="replace")


def _align_offset(a):
    return (a + 3) & ~3


def apt_process_actions(parent_elem, a, aptbuffer, const_data):
    """Walk binary action bytes starting at offset `a`, appending XML children to parent_elem.

    A definefunction[2] body spans from just after its header (`df_ptr`) to
    `df_ptr + size`. Bodies are tracked on a stack so a function defined inside
    another function's body is nested under it rather than flattened to the top
    level; this keeps the `<body>` element equal to the byte span the size field
    describes, which the compiler relies on to recompute that size.

    Branches (`branchalways`/`branchiftrue`/`branchiffalse`) carry a signed byte
    offset relative to the byte right after their 4-byte operand field. Each is
    resolved to a `target` label matching an `anchor` attribute on the destination
    instruction (labels shared when branches coincide, numbered in byte order) so an
    edit that shifts byte counts stays consistent; the raw `offset` is emitted too
    as a legacy fallback. A branch whose destination falls outside the block or off
    an instruction boundary keeps only its `offset`.
    """
    scopes = []  # stack of [body_node, end_offset] for the open function bodies
    pos_map = {}  # instruction start byte offset -> its XML element (flat across scopes)
    branches = []  # [(branch_element, destination_byte_offset)]

    def insert(node):
        (scopes[-1][0] if scopes else parent_elem).append(node)
        pos_map[op_pos] = node

    while True:
        op_pos = a
        opcode = aptbuffer[a]
        a += 1

        if opcode == ACTION_BRANCHALWAYS:
            a = _align_offset(a)
            off = struct.unpack_from("<i", aptbuffer, a)[0]
            a += 4
            n = ET.Element("branchalways")
            n.set("offset", str(off))
            insert(n)
            branches.append((n, a + off))
        elif opcode == ACTION_BRANCHIFTRUE:
            a = _align_offset(a)
            off = struct.unpack_from("<i", aptbuffer, a)[0]
            a += 4
            n = ET.Element("branchiftrue")
            n.set("offset", str(off))
            insert(n)
            branches.append((n, a + off))
        elif opcode == EA_BRANCHIFFALSE:
            a = _align_offset(a)
            off = struct.unpack_from("<i", aptbuffer, a)[0]
            a += 4
            n = ET.Element("branchiffalse")
            n.set("offset", str(off))
            insert(n)
            branches.append((n, a + off))
        elif opcode == ACTION_GOTOFRAME:
            a = _align_offset(a)
            n = ET.Element("gotoframe")
            n.set("frame", str(struct.unpack_from("<i", aptbuffer, a)[0]))
            a += 4
            insert(n)
        elif opcode == ACTION_SETREGISTER:
            a = _align_offset(a)
            n = ET.Element("setregister")
            n.set("reg", str(struct.unpack_from("<i", aptbuffer, a)[0]))
            a += 4
            insert(n)
        elif opcode == ACTION_WITH:
            a = _align_offset(a)
            n = ET.Element("with")
            n.set("pos", str(struct.unpack_from("<i", aptbuffer, a)[0]))
            a += 4
            insert(n)
        elif opcode == ACTION_GOTOEXPRESSION:
            a = _align_offset(a)
            n = ET.Element("gotoexpression")
            n.set("pos", str(struct.unpack_from("<i", aptbuffer, a)[0]))
            a += 4
            insert(n)
        elif opcode == ACTION_GETURL:
            a = _align_offset(a)
            s1_off = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            s2_off = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            n = ET.Element("geturl")
            n.set("str1", _read_cstring(aptbuffer, s1_off))
            n.set("str2", _read_cstring(aptbuffer, s2_off))
            insert(n)
        elif opcode == ACTION_CONSTANTPOOL:
            a = _align_offset(a)
            count = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            cpd_off = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            n = ET.Element("constantpool")
            for i in range(count):
                idx = struct.unpack_from("<I", aptbuffer, cpd_off + i * 4)[0]
                n2 = ET.SubElement(n, "constant")
                n2.set("id", str(i))
                if idx < len(const_data["items"]):
                    item = const_data["items"][idx]
                    if item["type"] == 4:
                        n2.set("integer", str(item["value"]))
                    else:
                        n2.set("string", item["value"] or "")
            insert(n)
        elif opcode == ACTION_PUSHDATA:
            a = _align_offset(a)
            count = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            pid_off = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            n = ET.Element("pushdata")
            for i in range(count):
                idx = struct.unpack_from("<I", aptbuffer, pid_off + i * 4)[0]
                n2 = ET.SubElement(n, "data")
                n2.set("id", str(idx))
                if idx < len(const_data["items"]):
                    item = const_data["items"][idx]
                    if item["type"] == 4:
                        n2.set("integer", str(item["value"]))
                    else:
                        n2.set("string", item["value"] or "")
            insert(n)
        elif opcode == ACTION_DEFINEFUNCTION2:
            a = _align_offset(a)
            name_off = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            count = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            flags = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            args_off = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            size = struct.unpack_from("<I", aptbuffer, a)[0]
            n = ET.Element("definefunction2")
            n.set("name", _read_cstring(aptbuffer, name_off))
            n.set("flags", str(flags))
            n.set("size", str(size))
            for i in range(count):
                base = args_off + i * 8
                reg = struct.unpack_from("<I", aptbuffer, base)[0]
                arg_name_off = struct.unpack_from("<I", aptbuffer, base + 4)[0]
                n2 = ET.SubElement(n, "argument")
                n2.set("reg", str(reg))
                n2.set("name", _read_cstring(aptbuffer, arg_name_off))
            body = ET.SubElement(n, "body") if size > 0 else None
            insert(n)
            a += 4
            a += 4
            a += 4  # skip size, 0x98765432, 0x12345678
            if body is not None:
                scopes.append([body, a + size])
        elif opcode == ACTION_DEFINEFUNCTION:
            a = _align_offset(a)
            name_off = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            count = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            args_off = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            size = struct.unpack_from("<I", aptbuffer, a)[0]
            n = ET.Element("definefunction")
            n.set("name", _read_cstring(aptbuffer, name_off))
            n.set("size", str(size))
            for i in range(count):
                arg_ptr = struct.unpack_from("<I", aptbuffer, args_off + i * 4)[0]
                n2 = ET.SubElement(n, "argument")
                n2.set("name", _read_cstring(aptbuffer, arg_ptr))
            a += 4
            a += 4
            a += 4  # skip size, 0x98765432, 0x12345678
            body = ET.SubElement(n, "body") if size > 0 else None
            insert(n)
            if body is not None:
                scopes.append([body, a + size])
        elif opcode in (
            EA_PUSHSTRING,
            EA_GETSTRINGVAR,
            EA_GETSTRINGMEMBER,
            EA_SETSTRINGVAR,
            EA_SETSTRINGMEMBER,
            ACTION_SETTARGET,
            ACTION_GOTOLABEL,
        ):
            a = _align_offset(a)
            s_off = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            s = _read_cstring(aptbuffer, s_off)
            tag = {
                EA_PUSHSTRING: "pushstring",
                EA_GETSTRINGVAR: "getstringvar",
                EA_GETSTRINGMEMBER: "getstringmember",
                EA_SETSTRINGVAR: "setstringvar",
                EA_SETSTRINGMEMBER: "setstringmember",
                ACTION_SETTARGET: "settarget",
                ACTION_GOTOLABEL: "gotolabel",
            }[opcode]
            n = ET.Element(tag)
            n.set("label" if opcode == ACTION_GOTOLABEL else "str", s)
            insert(n)
        elif opcode in (
            EA_CALLNAMEDFUNCTIONPOP,
            EA_CALLNAMEDFUNCTION,
            EA_CALLNAMEDMETHODPOP,
            EA_CALLNAMEDMETHOD,
            EA_PUSHCONSTANT,
            EA_PUSHVALUEOFVAR,
            EA_GETNAMEDMEMBER,
            EA_PUSHBYTE,
            EA_PUSHREGISTER,
        ):
            val = aptbuffer[a]
            a += 1
            tag = {
                EA_CALLNAMEDFUNCTIONPOP: "callnamedfuncpop",
                EA_CALLNAMEDFUNCTION: "callnamedfunc",
                EA_CALLNAMEDMETHODPOP: "callnamedmethodpop",
                EA_CALLNAMEDMETHOD: "callnamedmethod",
                EA_PUSHCONSTANT: "pushconstant",
                EA_PUSHVALUEOFVAR: "pushvalue",
                EA_GETNAMEDMEMBER: "getnamedmember",
                EA_PUSHBYTE: "pushbyte",
                EA_PUSHREGISTER: "pushregister",
            }[opcode]
            n = ET.Element(tag)
            # Divergence from the original C++ AptConverter, which wrote the opcode
            # itself as pushregister's val (a read bug): emit the real one-byte
            # register operand so a round-trip preserves the register number.
            n.set("val", str(val))
            insert(n)
        elif opcode == EA_PUSHWORDCONSTANT:
            # Divergence from the original C++ AptConverter, which fell through into
            # PUSHSHORT here (a missing break), fabricating a phantom pushshort and
            # consuming two extra bytes: pushwordconstant reads exactly one uint16.
            val = struct.unpack_from("<H", aptbuffer, a)[0]
            a += 2
            n = ET.Element("pushwordconstant")
            n.set("val", str(val))
            insert(n)
        elif opcode == EA_PUSHSHORT:
            val = struct.unpack_from("<H", aptbuffer, a)[0]
            a += 2
            n = ET.Element("pushshort")
            n.set("val", str(val))
            insert(n)
        elif opcode == EA_PUSHFLOAT:
            val = struct.unpack_from("<f", aptbuffer, a)[0]
            a += 4
            n = ET.Element("pushfloat")
            n.set("val", str(val))
            insert(n)
        elif opcode == EA_PUSHLONG:
            val = struct.unpack_from("<I", aptbuffer, a)[0]
            a += 4
            n = ET.Element("pushvalue")
            n.set("val", str(val))
            insert(n)
        else:
            # No-arg opcodes
            _NOARG = {
                ACTION_END: "end",
                ACTION_LOGICALAND: "logicaland",
                ACTION_LOGICALOR: "logicalor",
                ACTION_LOGICALNOT: "logicalnot",
                EA_PUSHONE: "pushone",
                ACTION_TRACE: "trace",
                ACTION_NEW: "new",
                ACTION_SETMEMBER: "setmember",
                EA_PUSHZERO: "pushzero",
                ACTION_POP: "pop",
                ACTION_GETMEMBER: "getmember",
                ACTION_DUP: "dup",
                ACTION_NEWADD: "newadd",
                ACTION_NEWLESSTHAN: "newlessthan",
                ACTION_NEWEQUALS: "newequals",
                EA_PUSHTRUE: "pushtrue",
                EA_PUSHFALSE: "pushfalse",
                EA_PUSHNULL: "pushnull",
                EA_PUSHUNDEFINED: "pushundefined",
                ACTION_INCREMENT: "increment",
                ACTION_DECREMENT: "decrement",
                ACTION_DEFINELOCAL: "definelocal",
                ACTION_GREATER: "greater",
                EA_PUSHTHIS: "pushthis",
                EA_PUSHGLOBAL: "pushglobal",
                ACTION_GETVARIABLE: "getvariable",
                ACTION_SETVARIABLE: "setvariable",
                ACTION_WAITFORFRAME: "waitforframe",
                ACTION_GETURL2: "geturl2",
            }
            if opcode in _NOARG:
                n = ET.Element(_NOARG[opcode])
                insert(n)
            else:
                n = ET.Element("noarg")
                n.set("action", str(opcode))
                insert(n)

        while scopes and a >= scopes[-1][1]:
            scopes.pop()

        if opcode == ACTION_END:
            break

    # Resolve branch destinations to shared labels, numbered in byte order. A branch
    # whose destination is not an instruction boundary in this block stays offset-only.
    # The destination attribute is `anchor`, not `label`: gotolabel already uses
    # `label` for its frame-label string operand.
    destinations = sorted({dest for _, dest in branches if dest in pos_map})
    labels = {dest: f"L{i + 1}" for i, dest in enumerate(destinations)}
    for dest, label in labels.items():
        pos_map[dest].set("anchor", label)
    for node, dest in branches:
        if dest in labels:
            node.set("target", labels[dest])


# Writing: XML → ActionBytes


def xml_process_actions(entry_elem, ab, data, top_level=True):
    """Walk XML action elements and emit bytecode into ActionBytes `ab`.
    `data` is the mutable const-pool dict {'itemcount': int, 'items': list}.

    Branch operands are resolved from `target` labels after the whole block is
    emitted; `top_level` is False for recursive function-body emission so the
    resolution runs once, over the block's full byte layout.
    """
    for child in entry_elem:
        name = child.tag

        anchor = child.get("anchor")
        if anchor is not None:
            ab.labelpositions[anchor] = ab.actionbytecount

        if name == "branchalways":
            _emit_branch(ab, ACTION_BRANCHALWAYS, child)
        elif name == "branchiftrue":
            _emit_branch(ab, ACTION_BRANCHIFTRUE, child)
        elif name == "branchiffalse":
            _emit_branch(ab, EA_BRANCHIFFALSE, child)
        elif name == "gotoframe":
            ab.add_int_action(ACTION_GOTOFRAME, int(child.get("frame", 0)))
        elif name == "setregister":
            ab.add_int_action(ACTION_SETREGISTER, int(child.get("reg", 0)))
        elif name == "with":
            ab.add_int_action(ACTION_WITH, int(child.get("pos", 0)))
        elif name == "gotoexpression":
            ab.add_int_action(ACTION_GOTOEXPRESSION, int(child.get("pos", 0)))
        elif name == "geturl":
            ab.add_url_action(ACTION_GETURL, child.get("str1", ""), child.get("str2", ""))
        elif name == "constantpool":
            for c in child:
                item = _make_const_item(c)
                data["items"].append(item)
                ab.constants.append(data["itemcount"])
                data["itemcount"] += 1
                ab.constantcount += 1
            ab.add_constant_pool_action(ACTION_CONSTANTPOOL, ab.constantcount)
        elif name == "pushdata":
            pd = {"offset": 0, "count": 0, "data": []}
            for c in child:
                item = _make_const_item(c)
                data["items"].append(item)
                pd["data"].append(data["itemcount"])
                data["itemcount"] += 1
                pd["count"] += 1
            ab.actionpushdatas.append(pd)
            ab.pushdatacount += 1
            ab.add_pushdata_action(ACTION_PUSHDATA, pd)
        elif name == "definefunction2":
            pd = {"offset": 0, "argumentcount": 0, "arguments": []}
            flags = int(child.get("flags", 0))
            # The XML `size` is advisory; the compiler measures the emitted body.
            size = int(child.get("size", 0))
            fname = child.get("name", "")
            for arg in child.findall("argument"):
                pd["argumentcount"] += 1
                pd["arguments"].append({"reg": int(arg.get("reg", 0)), "name": arg.get("name", "")})
            ab.actiondefinefunction2s.append(pd)
            ab.definefunction2count += 1
            ab.add_definefunction2_action(ACTION_DEFINEFUNCTION2, pd, flags, size, fname)
            body = child.find("body")
            if body is not None:
                _emit_function_body(body, ab, data, pd)
        elif name == "definefunction":
            pd = {"offset": 0, "argumentcount": 0, "arguments": []}
            # The XML `size` is advisory; the compiler measures the emitted body.
            size = int(child.get("size", 0))
            fname = child.get("name", "")
            for arg in child.findall("argument"):
                pd["argumentcount"] += 1
                pd["arguments"].append(arg.get("name", ""))
            ab.actiondefinefunctions.append(pd)
            ab.definefunctioncount += 1
            ab.add_definefunction_action(ACTION_DEFINEFUNCTION, pd, size, fname)
            body = child.find("body")
            if body is not None:
                _emit_function_body(body, ab, data, pd)
        elif name == "pushstring":
            ab.add_string_action(EA_PUSHSTRING, child.get("str", ""))
        elif name == "getstringvar":
            ab.add_string_action(EA_GETSTRINGVAR, child.get("str", ""))
        elif name == "getstringmember":
            ab.add_string_action(EA_GETSTRINGMEMBER, child.get("str", ""))
        elif name == "setstringvar":
            ab.add_string_action(EA_SETSTRINGVAR, child.get("str", ""))
        elif name == "setstringmember":
            ab.add_string_action(EA_SETSTRINGMEMBER, child.get("str", ""))
        elif name == "settarget":
            ab.add_string_action(ACTION_SETTARGET, child.get("str", ""))
        elif name == "gotolabel":
            ab.add_string_action(ACTION_GOTOLABEL, child.get("label", ""))
        elif name == "callnamedfuncpop":
            ab.add_byte_action(EA_CALLNAMEDFUNCTIONPOP, int(child.get("val", 0)))
        elif name == "callnamedfunc":
            ab.add_byte_action(EA_CALLNAMEDFUNCTION, int(child.get("val", 0)))
        elif name == "callnamedmethodpop":
            ab.add_byte_action(EA_CALLNAMEDMETHODPOP, int(child.get("val", 0)))
        elif name == "callnamedmethod":
            ab.add_byte_action(EA_CALLNAMEDMETHOD, int(child.get("val", 0)))
        elif name == "pushconstant":
            ab.add_byte_action(EA_PUSHCONSTANT, int(child.get("val", 0)))
        elif name == "pushvalue":
            ab.add_byte_action(EA_PUSHVALUEOFVAR, int(child.get("val", 0)))
        elif name == "pushbyte":
            ab.add_byte_action(EA_PUSHBYTE, int(child.get("val", 0)))
        elif name == "getnamedmember":
            ab.add_byte_action(EA_GETNAMEDMEMBER, int(child.get("val", 0)))
        elif name == "pushregister":
            ab.add_byte_action(EA_PUSHREGISTER, int(child.get("val", 0)))
        elif name == "pushshort":
            ab.add_short_action(EA_PUSHSHORT, int(child.get("val", 0)))
        elif name == "pushwordconstant":
            ab.add_short_action(EA_PUSHWORDCONSTANT, int(child.get("val", 0)))
        elif name == "pushfloat":
            ab.add_float_action(EA_PUSHFLOAT, float(child.get("val", 0)))
        elif name == "pushlong":
            ab.add_long_action(EA_PUSHLONG, int(child.get("val", 0)))
        elif name == "logicaland":
            ab.add_action(ACTION_LOGICALAND)
        elif name == "logicalor":
            ab.add_action(ACTION_LOGICALOR)
        elif name == "logicalnot":
            ab.add_action(ACTION_LOGICALNOT)
        elif name == "pushone":
            ab.add_action(EA_PUSHONE)
        elif name == "trace":
            ab.add_action(ACTION_TRACE)
        elif name == "new":
            ab.add_action(ACTION_NEW)
        elif name == "setmember":
            ab.add_action(ACTION_SETMEMBER)
        elif name == "pushzero":
            ab.add_action(EA_PUSHZERO)
        elif name == "pop":
            ab.add_action(ACTION_POP)
        elif name == "getmember":
            ab.add_action(ACTION_GETMEMBER)
        elif name == "dup":
            ab.add_action(ACTION_DUP)
        elif name == "newadd":
            ab.add_action(ACTION_NEWADD)
        elif name == "newlessthan":
            ab.add_action(ACTION_NEWLESSTHAN)
        elif name == "newequals":
            ab.add_action(ACTION_NEWEQUALS)
        elif name == "pushtrue":
            ab.add_action(EA_PUSHTRUE)
        elif name == "pushfalse":
            ab.add_action(EA_PUSHFALSE)
        elif name == "pushnull":
            ab.add_action(EA_PUSHNULL)
        elif name == "pushundefined":
            ab.add_action(EA_PUSHUNDEFINED)
        elif name == "increment":
            ab.add_action(ACTION_INCREMENT)
        elif name == "decrement":
            ab.add_action(ACTION_DECREMENT)
        elif name == "definelocal":
            ab.add_action(ACTION_DEFINELOCAL)
        elif name == "greater":
            ab.add_action(ACTION_GREATER)
        elif name == "pushthis":
            ab.add_action(EA_PUSHTHIS)
        elif name == "pushglobal":
            ab.add_action(EA_PUSHGLOBAL)
        elif name == "getvariable":
            ab.add_action(ACTION_GETVARIABLE)
        elif name == "setvariable":
            ab.add_action(ACTION_SETVARIABLE)
        elif name == "waitforframe":
            ab.add_action(ACTION_WAITFORFRAME)
        elif name == "geturl2":
            ab.add_action(ACTION_GETURL2)
        elif name == "end":
            ab.add_action(ACTION_END)
        elif name == "noarg":
            ab.add_action(int(child.get("action", 0)))
        else:
            print(f"Unknown action: {name}")

    if top_level:
        ab.resolve_branches()


def _emit_branch(ab, opcode, child):
    """Emit a branch. A `target` label is resolved after the block is laid out; a
    branch carrying only the legacy `offset` compiles that raw value verbatim so
    pre-Phase-4 XML still assembles."""
    target = child.get("target")
    if target is not None:
        ab.add_branch_target_action(opcode, target)
    else:
        ab.add_int_action(opcode, int(child.get("offset", 0)))


def _emit_function_body(body_elem, ab, data, pd):
    """Emit a definefunction[2] body and patch its recorded size field with the
    measured byte length. The reader scopes the body from the byte right after the
    function header (`df_ptr`) until `df_ptr + df_size`, so the body byte count is
    exactly the growth of `actionbytecount` across emitting the body. `pd` is local
    to each invocation, so nested functions patch their own size fields. Branch
    resolution is deferred to the enclosing top-level call so labels and targets
    that cross the body boundary still resolve over the full block layout."""
    body_start = ab.actionbytecount
    xml_process_actions(body_elem, ab, data, top_level=False)
    struct.pack_into("<I", ab.buf, pd["size_offset"], ab.actionbytecount - body_start)


def _make_const_item(elem):
    if elem.get("string") is not None:
        return {"type": 1, "value": elem.get("string")}
    else:
        return {"type": 4, "value": int(elem.get("integer", 0))}
