"""Install the bundled `bfme-faction` Claude Code skill into a skills directory, so a user who
pip-installed the `edain` extra can opt into the agent workflow. The copy machinery lives in
`sage_utils.skill`; this module only names the package and skill.
"""

from pathlib import Path

from sage_utils.skill import default_skills_dir, install_packaged_skill

__all__ = ["SKILL_NAME", "default_skills_dir", "install_skill"]

SKILL_NAME = "bfme-faction"


def install_skill(dest: str | Path | None = None, force: bool = False) -> Path:
    """Copy the bundled skill into `<dest>/bfme-faction` (default: the per-user skills dir).
    Returns the installed skill directory. Refuses to overwrite an existing install unless
    `force`."""
    return install_packaged_skill("sage_mods.edain", SKILL_NAME, dest, force=force)
