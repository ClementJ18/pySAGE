"""Reader/writer for the BFME2/RotWK Create-a-Hero `.cah` file: one custom hero's identity,
class, colors, powers, "bling" customization/attributes, GUID, and validating checksum. See
`sage_cah.cah` and README.md for the binary layout; `sage-cah` is the command-line front end
(`sage_cah.__main__`)."""

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
