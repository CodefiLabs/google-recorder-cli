"""Install, uninstall, and inspect the google-recorder-cli Claude Code skill.

Same idempotent install/uninstall/status shape as mcp_setup.py, but there's
only one target: the user-level skill directory Claude Code reads directly
from disk, so no client registry is needed here.
"""

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import click

SKILL_NAME = "google-recorder-cli"
BUNDLED_SKILL_MD = Path(__file__).parent / "skills" / SKILL_NAME / "SKILL.md"


def _target_dir() -> Path:
    return Path.home() / ".claude" / "skills" / SKILL_NAME


def _backup(path: Path) -> Path:
    stamp = f"{datetime.now():%Y%m%d%H%M%S%f}"
    backup_path = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, backup_path)
    return backup_path


def _write_atomic(path: Path, content: str) -> None:
    """Write content atomically (temp file + rename) so a concurrent reader never sees a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def install() -> None:
    target_file = _target_dir() / "SKILL.md"
    content = BUNDLED_SKILL_MD.read_text()

    if target_file.exists():
        if target_file.read_text() == content:
            click.echo(f"{SKILL_NAME} skill is already installed and up to date — nothing to do.")
            return
        backup_path = _backup(target_file)
        click.echo(f"Backed up existing skill to {backup_path}")
        _write_atomic(target_file, content)
        click.echo(f"Updated {SKILL_NAME} skill at {target_file}")
        return

    _write_atomic(target_file, content)
    click.echo(f"Installed {SKILL_NAME} skill to {target_file}")


def uninstall() -> None:
    target_dir = _target_dir()
    target_file = target_dir / "SKILL.md"
    if not target_file.exists():
        click.echo(f"{SKILL_NAME} skill is not installed — nothing to do.")
        return
    target_file.unlink()
    try:
        target_dir.rmdir()  # only succeeds if empty; leaves any other files alone
    except OSError:
        pass
    click.echo(f"Removed {SKILL_NAME} skill from {target_dir}")


def status() -> None:
    target_file = _target_dir() / "SKILL.md"
    if not target_file.exists():
        click.echo(f"{SKILL_NAME}: not installed")
        return

    if target_file.read_text() == BUNDLED_SKILL_MD.read_text():
        click.echo(f"{SKILL_NAME}: installed and up to date → {target_file}")
    else:
        click.echo(f"{SKILL_NAME}: installed but differs from the bundled version → {target_file} — re-run: recorder skill install")
