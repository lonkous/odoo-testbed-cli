from __future__ import annotations

from pathlib import Path
import json

import pytest

from testbed_cli.config import Config
from testbed_cli.dockerctl import ContainerStatus
from tests.helpers import completed
from testbed_cli.extras import (
    generate_vscode,
    open_browser,
    open_browser_url,
    run_odoo_shell,
    run_odoo_shell_code,
    run_psql,
    run_psql_query,
    start_mailpit,
    update_licenses,
)


def test_open_browser_uses_published_port(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.extras.compose_ps",
        lambda item: ContainerStatus(http_port=19999),
    )
    opened: list[str] = []
    monkeypatch.setattr("testbed_cli.extras.webbrowser.open", opened.append)
    open_browser(project)
    assert opened == ["http://localhost:19999"]


def test_open_browser_falls_back_to_project_port(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.extras.compose_ps", lambda item: ContainerStatus())
    opened: list[str] = []
    monkeypatch.setattr("testbed_cli.extras.webbrowser.open", opened.append)
    open_browser(project)
    assert opened == [f"http://localhost:{project.http_port}"]


def test_open_browser_url_returns_url(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.extras.compose_ps",
        lambda item: ContainerStatus(http_port=19999),
    )
    opened: list[str] = []
    monkeypatch.setattr("testbed_cli.extras.webbrowser.open", opened.append)
    assert open_browser_url(project) == "http://localhost:19999"
    assert opened == ["http://localhost:19999"]


def test_run_psql_query(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.extras.compose_exec_capture",
        lambda item, service, command: completed(stdout=" count \n-------\n     3"),
    )
    assert "3" in run_psql_query(project, "select count(*) from res_partner")


def test_run_psql_query_failure(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.extras.compose_exec_capture",
        lambda item, service, command: completed(returncode=1, stderr="syntax error"),
    )
    with pytest.raises(RuntimeError, match="syntax error"):
        run_psql_query(project, "bad")


def test_run_psql_query_empty_ok(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.extras.compose_exec_capture",
        lambda item, service, command: completed(),
    )
    assert run_psql_query(project, "select 1") == "ok"


def test_run_odoo_shell_code_failure(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.extras.compose_cmd", lambda item: ["docker", "compose"])
    monkeypatch.setattr("testbed_cli.extras.run_command", lambda *args, **kwargs: completed(returncode=1))
    with pytest.raises(RuntimeError, match="odoo shell failed"):
        run_odoo_shell_code(project, "print(1)")


def test_run_odoo_shell_code(project, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(command, cwd=None, timeout=None, input_text=None):
        seen["command"] = command
        seen["input_text"] = input_text
        return completed(stdout="42")

    monkeypatch.setattr("testbed_cli.extras.compose_cmd", lambda item: ["docker", "compose"])
    monkeypatch.setattr("testbed_cli.extras.run_command", fake_run)
    assert run_odoo_shell_code(project, "print(1)") == "42"
    assert seen["input_text"] == "print(1)"
    assert "-T" in seen["command"]
    assert "shell" in seen["command"]


def test_run_psql_and_shell(project, monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr("testbed_cli.extras.compose_stream_cmd", lambda item: ["docker", "compose"])
    monkeypatch.setattr("testbed_cli.extras.run_interactive", lambda command: seen.append(command) or 0)
    assert run_psql(project) == 0
    assert "psql" in seen[0]
    assert run_odoo_shell(project) == 0
    assert "shell" in seen[1]


def test_start_mailpit(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.extras.run_command", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.extras.stream_command", lambda *args, **kwargs: 0)
    notes: list[str] = []
    ui_port, smtp_port = start_mailpit(project, on_line=notes.append)
    assert ui_port == 8025 + (project.http_port - 8069)
    assert smtp_port == 1025 + (project.http_port - 8069)
    assert any("Mailpit UI" in item for item in notes)
    monkeypatch.setattr("testbed_cli.extras.stream_command", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError, match="Failed to start Mailpit"):
        start_mailpit(project)


def test_update_licenses(tmp_path: Path) -> None:
    addons = tmp_path / "addons"
    module_dir = addons / "sale_custom"
    module_dir.mkdir(parents=True)
    (module_dir / "__manifest__.py").write_text(
        "{'name': 'X', 'license': 'OEEL-1'}\n",
        encoding="utf-8",
    )
    other = addons / "other"
    other.mkdir()
    (other / "__manifest__.py").write_text('{"name": "Y", "license": "AGPL-3"}\n', encoding="utf-8")
    skipped = addons / "skip"
    skipped.mkdir()
    (skipped / "__manifest__.py").write_text("{'name': 'Z'}\n", encoding="utf-8")
    notes: list[str] = []
    updated = update_licenses(addons, on_line=notes.append)
    assert updated == 2
    assert "LGPL-3" in (module_dir / "__manifest__.py").read_text(encoding="utf-8")
    assert "LGPL-3" in (other / "__manifest__.py").read_text(encoding="utf-8")


def test_update_licenses_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        update_licenses(tmp_path / "missing")


def test_generate_vscode(project, isolated_config: Config) -> None:
    generate_vscode(project, isolated_config)
    launch = json.loads((project.root / ".vscode" / "launch.json").read_text(encoding="utf-8"))
    assert any(item.get("command") == f"tb start {project.database_name}" for item in launch["configurations"])
    tasks = json.loads((project.root / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    assert tasks["tasks"][0]["command"] == f"tb debug-restart {project.database_name}"
    workspace = json.loads((project.root / f"{project.database_name}.code-workspace").read_text(encoding="utf-8"))
    assert workspace["settings"]["window.title"] == project.database_name


def test_update_licenses_no_change(tmp_path: Path) -> None:
    addons = tmp_path / "addons"
    module_dir = addons / "sale_custom"
    module_dir.mkdir(parents=True)
    (module_dir / "__manifest__.py").write_text("{'name': 'X', 'license': 'LGPL-3'}\n", encoding="utf-8")
    assert update_licenses(addons) == 0


def test_start_mailpit_default_offset(project, monkeypatch) -> None:
    project.http_port = 8000
    monkeypatch.setattr("testbed_cli.extras.run_command", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.extras.stream_command", lambda *args, **kwargs: 0)
    ui_port, smtp_port = start_mailpit(project)
    assert ui_port == 8025
    assert smtp_port == 1025


def test_generate_vscode_logs_paths(project, isolated_config: Config) -> None:
    notes: list[str] = []
    generate_vscode(project, isolated_config, on_line=notes.append)
    assert notes
    assert "Wrote VS Code files" in notes[0]
