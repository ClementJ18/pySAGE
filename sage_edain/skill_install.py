"""Install the bundled `bfme-faction` Claude Code skill into a skills directory, so a user who
pip-installed the `edain` extra can opt into the agent workflow. The skill is static — it drives the
`sage-edain` CLI live rather than embedding generated data — so installing is a plain copy of the
packaged asset; there is nothing to regenerate.
"""

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

__all__ = ["SKILL_NAME", "default_skills_dir", "install_skill"]

SKILL_NAME = "bfme-faction"


def default_skills_dir() -> Path:
    """The per-user Claude Code skills directory."""
    return Path.home() / ".claude" / "skills"


def _packaged_skill() -> Traversable:
    return resources.files("sage_edain").joinpath("skill_assets", SKILL_NAME)


def _copy_tree(source: Traversable, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        target = dest / entry.name
        if entry.is_dir():
            _copy_tree(entry, target)
        else:
            target.write_bytes(entry.read_bytes())


def install_skill(dest: str | Path | None = None, force: bool = False) -> Path:
    """Copy the bundled skill into `<dest>/bfme-faction` (default: the per-user skills dir). Returns
    the installed skill directory. Refuses to overwrite an existing install unless `force`."""
    dest_root = Path(dest) if dest is not None else default_skills_dir()
    target = dest_root / SKILL_NAME
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(target)
    _copy_tree(_packaged_skill(), target)
    return target
