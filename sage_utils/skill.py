"""Install a package's bundled Claude Code skill into a skills directory, so a user who
pip-installed the package can opt into the agent workflow. The skills are static - they drive
their package's CLI live rather than embedding generated data - so installing is a plain copy
of the packaged asset; there is nothing to regenerate. Each shipping package keeps a thin
`skill_install` wrapper naming its own package and skill.
"""

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

__all__ = ["default_skills_dir", "install_packaged_skill"]


def default_skills_dir() -> Path:
    """The per-user Claude Code skills directory."""
    return Path.home() / ".claude" / "skills"


def _copy_tree(source: Traversable, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        target = dest / entry.name
        if entry.is_dir():
            _copy_tree(entry, target)
        else:
            target.write_bytes(entry.read_bytes())


def install_packaged_skill(
    package: str, skill_name: str, dest: str | Path | None = None, force: bool = False
) -> Path:
    """Copy `package`'s bundled `skill_assets/<skill_name>` into `<dest>/<skill_name>`
    (default: the per-user skills dir). Returns the installed skill directory. Refuses to
    overwrite an existing install unless `force`."""
    dest_root = Path(dest) if dest is not None else default_skills_dir()
    target = dest_root / skill_name
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(target)
    _copy_tree(resources.files(package).joinpath("skill_assets", skill_name), target)
    return target
