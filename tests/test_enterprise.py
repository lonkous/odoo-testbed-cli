from __future__ import annotations

from pathlib import Path

import pytest

from testbed_cli.enterprise import sync_enterprise


def test_sync_enterprise_clones_when_missing(tmp_path: Path, monkeypatch) -> None:
    commands: list[list[str]] = []

    def fake_stream(command, on_line=None):
        commands.append(command)
        return 0

    monkeypatch.setattr("testbed_cli.enterprise.stream_command", fake_stream)
    notes: list[str] = []
    sync_enterprise(tmp_path / "odoo", "18", on_line=notes.append)
    assert any("clone" in command for command in commands)
    assert notes[-1] == "Enterprise addons are up to date."


def test_sync_enterprise_updates_existing(tmp_path: Path, monkeypatch) -> None:
    enterprise_dir = tmp_path / "odoo" / "enterprise_18"
    enterprise_dir.mkdir(parents=True)
    commands: list[list[str]] = []

    def fake_stream(command, on_line=None):
        commands.append(command)
        return 0

    monkeypatch.setattr("testbed_cli.enterprise.stream_command", fake_stream)
    sync_enterprise(tmp_path / "odoo", "18")
    joined = " ".join(commands[0])
    assert "fetch" in joined


def test_sync_enterprise_runs_submodules_after_clone(tmp_path: Path, monkeypatch) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "testbed_cli.enterprise.stream_command",
        lambda command, on_line=None: commands.append(command) or 0,
    )
    sync_enterprise(tmp_path / "odoo", "18")
    joined = [" ".join(command) for command in commands]
    assert any("clone" in item for item in joined)
    assert any("submodule init" in item for item in joined)
    assert any("submodule update" in item for item in joined)


def test_sync_enterprise_clone_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.enterprise.stream_command", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError, match="Failed to clone enterprise"):
        sync_enterprise(tmp_path / "odoo", "18")


def test_sync_enterprise_fetch_failure(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "odoo" / "enterprise_18").mkdir(parents=True)
    monkeypatch.setattr("testbed_cli.enterprise.stream_command", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError, match="git fetch failed"):
        sync_enterprise(tmp_path / "odoo", "18")


def test_sync_enterprise_reset_failure(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "odoo" / "enterprise_18").mkdir(parents=True)
    calls = {"count": 0}

    def fake_stream(command, on_line=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return 0
        return 1

    monkeypatch.setattr("testbed_cli.enterprise.stream_command", fake_stream)
    with pytest.raises(RuntimeError, match="git reset failed"):
        sync_enterprise(tmp_path / "odoo", "18")
