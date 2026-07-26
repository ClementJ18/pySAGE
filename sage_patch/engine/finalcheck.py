import os

import pefile

HERE = os.path.dirname(__file__)
TARGET = os.path.join(HERE, os.environ.get("TARGET", "game.dat"))
pe = pefile.PE(TARGET)
print(
    f"PE parses OK ({os.path.basename(TARGET)}). "
    f"sections={pe.FILE_HEADER.NumberOfSections} "
    f"SizeOfImage=0x{pe.OPTIONAL_HEADER.SizeOfImage:x}"
)
s = pe.sections[-1]
name = s.Name.rstrip(b"\x00").decode()
print(f"last section: {name} VA=0x{0x400000 + s.VirtualAddress:x} VS=0x{s.Misc_VirtualSize:x}")
print(
    "  -> "
    + (
        ".cmdext table section present as expected"
        if name == ".cmdext"
        else "UNEXPECTED last section (want .cmdext)"
    )
)
