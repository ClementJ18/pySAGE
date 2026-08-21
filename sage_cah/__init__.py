"""Reader/writer for the BFME2/RotWK Create-a-Hero `.cah` file: one custom hero's identity,
class, colors, powers, "bling" customization/attributes, GUID, and validating checksum. See
`sage_cah.cah` and README.md for the binary layout; `sage-cah` is the command-line front end
(`sage_cah.__main__`) and `sage-cah-ui` the desktop editor (`sage_cah.ui`).

Two modules sit outside this package's exports, since both reach past the file itself and pull
in dependencies a plain parse does not need: `sage_cah.gamedata` reads a game's ini tree for the
classes, powers and bling a hero can name (`sage_ini`), and `sage_cah.ui` is the editor (PyQt6,
the `cah-ui` extra). Import either directly."""

from sage_cah.cah import (
    BLING_STAT_GROUPS,
    CLASS_NAMES,
    POWER_SLOT_COUNT,
    SUB_CLASS_NAMES,
    CahBling,
    CahError,
    CahPower,
    CustomHero,
    compute_checksum,
    new_guid,
    parse_cah,
    parse_cah_from_path,
    write_cah,
    write_cah_to_path,
)

__all__ = [
    "BLING_STAT_GROUPS",
    "CLASS_NAMES",
    "POWER_SLOT_COUNT",
    "SUB_CLASS_NAMES",
    "CahBling",
    "CahError",
    "CahPower",
    "CustomHero",
    "compute_checksum",
    "new_guid",
    "parse_cah",
    "parse_cah_from_path",
    "write_cah",
    "write_cah_to_path",
]
