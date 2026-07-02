import pytest

import recorder_cli.skill_setup as skill_setup

BUNDLED_CONTENT = "# Bundled skill content\n"


@pytest.fixture
def skill(tmp_path, monkeypatch):
    target_dir = tmp_path / "skills" / skill_setup.SKILL_NAME
    bundled = tmp_path / "bundled" / "SKILL.md"
    bundled.parent.mkdir(parents=True)
    bundled.write_text(BUNDLED_CONTENT)
    monkeypatch.setattr(skill_setup, "_target_dir", lambda: target_dir)
    monkeypatch.setattr(skill_setup, "BUNDLED_SKILL_MD", bundled)
    return target_dir


def test_install_creates_file(skill):
    skill_setup.install()
    assert (skill / "SKILL.md").read_text() == BUNDLED_CONTENT


def test_install_noop_writes_no_backup(skill):
    skill_setup.install()
    skill_setup.install()
    assert list(skill.glob("*.bak-*")) == []


def test_install_backs_up_and_overwrites_drifted_content(skill):
    skill_setup.install()
    target_file = skill / "SKILL.md"
    target_file.write_text("local edits")
    skill_setup.install()
    assert target_file.read_text() == BUNDLED_CONTENT
    backups = list(skill.glob("SKILL.md.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "local edits"


def test_uninstall_roundtrip(skill):
    skill_setup.install()
    skill_setup.uninstall()
    assert not (skill / "SKILL.md").exists()
    assert not skill.exists()  # empty dir is cleaned up too


def test_uninstall_when_absent_is_noop(skill):
    skill_setup.uninstall()  # must not raise
    assert not skill.exists()


def test_uninstall_leaves_other_files_in_directory(skill):
    skill_setup.install()
    (skill / "extra.txt").write_text("keep me")
    skill_setup.uninstall()
    assert not (skill / "SKILL.md").exists()
    assert (skill / "extra.txt").read_text() == "keep me"


def test_status_reflects_install_state(skill, capsys):
    skill_setup.status()
    assert "not installed" in capsys.readouterr().out

    skill_setup.install()
    capsys.readouterr()
    skill_setup.status()
    assert "up to date" in capsys.readouterr().out

    (skill / "SKILL.md").write_text("drifted")
    capsys.readouterr()
    skill_setup.status()
    assert "differs" in capsys.readouterr().out
