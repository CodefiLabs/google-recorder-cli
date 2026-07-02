"""Register, unregister, and inspect the recorder-mcp server in local MCP clients.

Each supported client gets a Client entry in CLIENTS with three operations
(install / uninstall / status), all idempotent. The CLI derives its argument
choices from CLIENTS, so adding a client here is the only change needed.
"""

import json
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import click

SERVER_NAME = "google-recorder"


def _recorder_mcp_path() -> str:
    path = shutil.which("recorder-mcp")
    if not path:
        raise click.ClickException(
            "Could not find 'recorder-mcp' on PATH. Install this package first "
            "(pipx install . or pip install -e .)."
        )
    return path


# --- Claude Desktop (direct config-file management) ---


def _claude_desktop_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    raise click.ClickException(f"Claude Desktop config location is not known for platform: {system}")


def _read_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    return json.loads(config_path.read_text())


def _backup_config(config_path: Path) -> Path:
    """Copy the config aside before a modifying write. Preserves file mode."""
    stamp = f"{datetime.now():%Y%m%d%H%M%S%f}"
    backup_path = config_path.with_name(f"{config_path.name}.bak-{stamp}")
    shutil.copy2(config_path, backup_path)
    return backup_path


def _write_config(config_path: Path, config: dict) -> None:
    """Write config atomically (temp file + rename) with 0600 perms."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=config_path.parent, prefix=f".{config_path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, config_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def desktop_install() -> None:
    command = _recorder_mcp_path()
    config_path = _claude_desktop_config_path()
    config = _read_config(config_path)
    servers = config.setdefault("mcpServers", {})
    entry = {"command": command}

    if servers.get(SERVER_NAME) == entry:
        click.echo(f"{SERVER_NAME} is already configured in Claude Desktop — nothing to do.")
        return

    updating = SERVER_NAME in servers
    if config_path.exists():
        backup_path = _backup_config(config_path)
        click.echo(f"Backed up config to {backup_path}")
    servers[SERVER_NAME] = entry
    _write_config(config_path, config)
    click.echo(f"{'Updated' if updating else 'Registered'} {SERVER_NAME} ({command}) in {config_path}")
    click.echo("Restart Claude Desktop to pick up the change.")


def desktop_uninstall() -> None:
    config_path = _claude_desktop_config_path()
    config = _read_config(config_path)
    servers = config.get("mcpServers", {})

    if SERVER_NAME not in servers:
        click.echo(f"{SERVER_NAME} is not configured in Claude Desktop — nothing to do.")
        return

    backup_path = _backup_config(config_path)
    del servers[SERVER_NAME]
    _write_config(config_path, config)
    click.echo(f"Removed {SERVER_NAME} from {config_path} (backup at {backup_path})")
    click.echo("Restart Claude Desktop to pick up the change.")


def desktop_status() -> None:
    config_path = _claude_desktop_config_path()
    entry = _read_config(config_path).get("mcpServers", {}).get(SERVER_NAME)
    if not entry:
        click.echo("Claude Desktop: not registered")
        return

    command = entry.get("command", "")
    warnings = []
    if not Path(command).exists():
        warnings.append("registered binary no longer exists")
    else:
        current = shutil.which("recorder-mcp")
        if current and Path(current).resolve() != Path(command).resolve():
            warnings.append(f"differs from current install ({current})")
    if warnings:
        click.echo(f"Claude Desktop: registered → {command}  ⚠ {'; '.join(warnings)} — re-run: recorder mcp install claude-desktop")
    else:
        click.echo(f"Claude Desktop: registered → {command}")


# --- Claude Code (delegated to the `claude mcp` CLI) ---


def _claude_bin() -> str:
    claude = shutil.which("claude")
    if not claude:
        raise click.ClickException(
            "Could not find 'claude' on PATH. Install Claude Code first, or register manually:\n"
            f"  claude mcp add {SERVER_NAME} -s user -- {_recorder_mcp_path()}"
        )
    return claude


def _run_claude_mcp(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([_claude_bin(), "mcp", *args], capture_output=True, text=True)


def _code_registered_command() -> str | None:
    """Parse the command out of `claude mcp get`, or None if unregistered/unparseable."""
    result = _run_claude_mcp("get", SERVER_NAME)
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("command:"):
            return stripped.split(":", 1)[1].strip() or None
    return None


def code_install() -> None:
    command = _recorder_mcp_path()
    result = _run_claude_mcp("add", SERVER_NAME, "-s", "user", "--", command)
    output = (result.stdout + result.stderr).strip()

    if "already exists" in output.lower():
        registered = _code_registered_command()
        if registered == command:
            click.echo(f"{SERVER_NAME} is already registered with Claude Code (user scope) — nothing to do.")
            return
        if registered is None:
            click.echo(f"{SERVER_NAME} is already registered with Claude Code. Check it with: recorder mcp status")
            return
        # Stale registration pointing at an old binary: replace it.
        remove_result = _run_claude_mcp("remove", SERVER_NAME, "-s", "user")
        if remove_result.returncode != 0:
            raise click.ClickException(
                f"Found a stale registration ({registered}) but 'claude mcp remove' failed:\n"
                f"{(remove_result.stdout + remove_result.stderr).strip()}"
            )
        readd_result = _run_claude_mcp("add", SERVER_NAME, "-s", "user", "--", command)
        if readd_result.returncode != 0:
            raise click.ClickException(
                f"'claude mcp add' failed after removing the stale registration:\n"
                f"{(readd_result.stdout + readd_result.stderr).strip()}"
            )
        click.echo(f"Updated {SERVER_NAME} registration: {registered} → {command}")
        return

    if result.returncode != 0:
        raise click.ClickException(f"'claude mcp add' failed:\n{output}")
    click.echo(output or f"Registered {SERVER_NAME} ({command}) with Claude Code (user scope).")


def code_uninstall() -> None:
    _claude_bin()  # fail early with a clear message if claude is missing
    result = _run_claude_mcp("remove", SERVER_NAME, "-s", "user")
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        if any(phrase in output.lower() for phrase in ("not found", "does not exist", "no mcp server")):
            click.echo(f"{SERVER_NAME} is not registered with Claude Code — nothing to do.")
            return
        raise click.ClickException(f"'claude mcp remove' failed:\n{output}")
    click.echo(output or f"Removed {SERVER_NAME} from Claude Code (user scope).")


def code_status() -> None:
    if not shutil.which("claude"):
        click.echo("Claude Code: 'claude' CLI not found")
        return
    result = _run_claude_mcp("get", SERVER_NAME)
    if result.returncode != 0:
        click.echo("Claude Code: not registered")
        return
    click.echo("Claude Code:")
    for line in result.stdout.strip().splitlines():
        click.echo(f"  {line}")


# --- Client registry (the single place to add support for a new client) ---


@dataclass(frozen=True)
class Client:
    install: Callable[[], None]
    uninstall: Callable[[], None]
    status: Callable[[], None]


CLIENTS: dict[str, Client] = {
    "claude-desktop": Client(desktop_install, desktop_uninstall, desktop_status),
    "claude-code": Client(code_install, code_uninstall, code_status),
}
