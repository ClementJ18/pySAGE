"""Tests for installing the bundled `bfme-ini` skill and keeping the project-local copy in sync."""

from pathlib import Path

import pytest

from sage_ini.__main__ import main
from sage_ini.skill_install import SKILL_NAME, install_skill

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGED = REPO_ROOT / "sage_ini" / "skill_assets" / SKILL_NAME / "SKILL.md"
PROJECT_LOCAL = REPO_ROOT / ".claude" / "skills" / SKILL_NAME / "SKILL.md"


def test_project_local_copy_matches_packaged():
    # One source of truth: the active project-local skill must equal the packaged asset.
    assert PROJECT_LOCAL.read_bytes() == PACKAGED.read_bytes()


class TestInstall:
    def test_installs_into_dest(self, tmp_path):
        installed = install_skill(tmp_path)
        assert installed == tmp_path / SKILL_NAME
        assert (installed / "SKILL.md").read_bytes() == PACKAGED.read_bytes()

    def test_refuses_to_overwrite_without_force(self, tmp_path):
        install_skill(tmp_path)
        with pytest.raises(FileExistsError):
            install_skill(tmp_path)

    def test_force_overwrites(self, tmp_path):
        install_skill(tmp_path)
        (tmp_path / SKILL_NAME / "SKILL.md").write_text("stale", encoding="utf-8")
        install_skill(tmp_path, force=True)
        assert (tmp_path / SKILL_NAME / "SKILL.md").read_bytes() == PACKAGED.read_bytes()


class TestInstallCommand:
    def test_command_installs(self, tmp_path, capsys):
        assert main(["install-skill", "--dest", str(tmp_path)]) == 0
        assert "installed skill to" in capsys.readouterr().out
        assert (tmp_path / SKILL_NAME / "SKILL.md").is_file()

    def test_command_reports_existing(self, tmp_path, capsys):
        main(["install-skill", "--dest", str(tmp_path)])
        assert main(["install-skill", "--dest", str(tmp_path)]) == 1
        assert "already exists" in capsys.readouterr().out
