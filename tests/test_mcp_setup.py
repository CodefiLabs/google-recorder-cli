import json
import subprocess

import pytest

import recorder_cli.mcp_setup as mcp_setup

FAKE_BIN = "/fake/bin/recorder-mcp"


def _backups(config_path):
    return sorted(config_path.parent.glob(f"{config_path.name}.bak-*"))


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    config_path = tmp_path / "claude_desktop_config.json"
    monkeypatch.setattr(mcp_setup, "_claude_desktop_config_path", lambda: config_path)
    monkeypatch.setattr(mcp_setup, "_recorder_mcp_path", lambda: FAKE_BIN)
    return config_path


def test_desktop_install_creates_config(desktop):
    mcp_setup.desktop_install()
    config = json.loads(desktop.read_text())
    assert config["mcpServers"]["google-recorder"] == {"command": FAKE_BIN}
    assert desktop.stat().st_mode & 0o777 == 0o600
    assert _backups(desktop) == []  # nothing existed to back up


def test_desktop_install_noop_writes_no_backup(desktop):
    mcp_setup.desktop_install()
    before = desktop.read_text()
    mcp_setup.desktop_install()
    assert desktop.read_text() == before
    assert _backups(desktop) == []


def test_desktop_install_updates_stale_entry_with_backup(desktop):
    desktop.write_text(json.dumps({"mcpServers": {"google-recorder": {"command": "/old/path"}}}))
    mcp_setup.desktop_install()
    config = json.loads(desktop.read_text())
    assert config["mcpServers"]["google-recorder"] == {"command": FAKE_BIN}
    assert len(_backups(desktop)) == 1
    backed_up = json.loads(_backups(desktop)[0].read_text())
    assert backed_up["mcpServers"]["google-recorder"] == {"command": "/old/path"}


def test_desktop_install_preserves_other_config(desktop):
    desktop.write_text(json.dumps({
        "mcpServers": {"pencil": {"command": "/pencil", "args": ["--app"]}},
        "preferences": {"menuBarEnabled": False},
    }))
    mcp_setup.desktop_install()
    config = json.loads(desktop.read_text())
    assert config["mcpServers"]["pencil"] == {"command": "/pencil", "args": ["--app"]}
    assert config["preferences"] == {"menuBarEnabled": False}
    assert config["mcpServers"]["google-recorder"] == {"command": FAKE_BIN}


def test_desktop_uninstall_roundtrip(desktop):
    desktop.write_text(json.dumps({"mcpServers": {"pencil": {"command": "/pencil"}}}))
    mcp_setup.desktop_install()
    mcp_setup.desktop_uninstall()
    config = json.loads(desktop.read_text())
    assert "google-recorder" not in config["mcpServers"]
    assert config["mcpServers"]["pencil"] == {"command": "/pencil"}


def test_desktop_uninstall_when_absent_is_noop(desktop):
    desktop.write_text(json.dumps({"mcpServers": {}}))
    before = desktop.read_text()
    mcp_setup.desktop_uninstall()
    assert desktop.read_text() == before
    assert _backups(desktop) == []


def test_token_created_0600_and_stable(tmp_path, monkeypatch):
    import recorder_cli.mcp_server as mcp_server

    token_path = tmp_path / "mcp_token"
    monkeypatch.setattr(mcp_server, "TOKEN_PATH", token_path)
    first = mcp_server._load_or_create_token()
    second = mcp_server._load_or_create_token()
    assert first == second
    assert len(first) >= 32
    assert token_path.stat().st_mode & 0o777 == 0o600


class FakeClaude:
    """Scripted stand-in for the `claude mcp ...` subprocess calls."""

    def __init__(self, registered_command=None):
        self.registered_command = registered_command
        self.calls = []

    def which(self, name):
        return f"/fake/bin/{name}"

    def run(self, cmd, capture_output, text):
        assert cmd[0] == "/fake/bin/claude" and cmd[1] == "mcp"
        action = cmd[2]
        self.calls.append(cmd[2:])
        if action == "add":
            if self.registered_command is not None:
                return subprocess.CompletedProcess(cmd, 1, "", "MCP server google-recorder already exists in user config")
            self.registered_command = cmd[-1]
            return subprocess.CompletedProcess(cmd, 0, "Added stdio MCP server google-recorder to user config", "")
        if action == "get":
            if self.registered_command is None:
                return subprocess.CompletedProcess(cmd, 1, "", "No MCP server found with name: google-recorder")
            return subprocess.CompletedProcess(cmd, 0, f"google-recorder:\n  Type: stdio\n  Command: {self.registered_command}\n", "")
        if action == "remove":
            if self.registered_command is None:
                return subprocess.CompletedProcess(cmd, 1, "", "No MCP server found with name: google-recorder")
            self.registered_command = None
            return subprocess.CompletedProcess(cmd, 0, "Removed MCP server google-recorder from user config", "")
        raise AssertionError(f"unexpected claude mcp action: {action}")


@pytest.fixture
def fake_claude(monkeypatch):
    fake = FakeClaude()
    monkeypatch.setattr(mcp_setup.shutil, "which", fake.which)
    monkeypatch.setattr(mcp_setup.subprocess, "run", fake.run)
    return fake


def test_code_install_fresh(fake_claude):
    mcp_setup.code_install()
    assert fake_claude.registered_command == "/fake/bin/recorder-mcp"
    assert [c[0] for c in fake_claude.calls] == ["add"]


def test_code_install_already_registered_same_command(fake_claude):
    fake_claude.registered_command = "/fake/bin/recorder-mcp"
    mcp_setup.code_install()
    assert [c[0] for c in fake_claude.calls] == ["add", "get"]  # no remove/re-add churn


def test_code_install_replaces_stale_registration(fake_claude):
    fake_claude.registered_command = "/old/stale/recorder-mcp"
    mcp_setup.code_install()
    assert fake_claude.registered_command == "/fake/bin/recorder-mcp"
    assert [c[0] for c in fake_claude.calls] == ["add", "get", "remove", "add"]


def test_code_uninstall_roundtrip(fake_claude):
    fake_claude.registered_command = "/fake/bin/recorder-mcp"
    mcp_setup.code_uninstall()
    assert fake_claude.registered_command is None
    mcp_setup.code_uninstall()  # second run must not raise
    assert [c[0] for c in fake_claude.calls] == ["remove", "remove"]


def test_clients_registry_names():
    assert set(mcp_setup.CLIENTS) == {"claude-desktop", "claude-code"}
