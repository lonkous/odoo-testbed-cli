from __future__ import annotations

from pathlib import Path

import pytest

from testbed_cli.config import save_config
from testbed_cli.dockerctl import ContainerStatus
from testbed_cli.mcp_server import (
    DASHBOARD_URI,
    dashboard_html,
    mcp,
    parse_mcp_args,
    tb_dashboard,
    tb_down,
    tb_list_projects,
    tb_logs,
    tb_open,
    tb_psql,
    tb_restore,
    tb_setup,
    tb_shell,
    tb_status,
)
from tests.helpers import write_project


def test_parse_mcp_args_defaults() -> None:
    args = parse_mcp_args([])
    assert args.http is False
    assert args.host == "127.0.0.1"
    assert args.port == 8765


def test_parse_mcp_args_http() -> None:
    args = parse_mcp_args(["--http", "--host", "0.0.0.0", "--port", "9000"])
    assert args.http is True
    assert args.host == "0.0.0.0"
    assert args.port == 9000


def test_mcp_registers_dashboard_and_new_tools() -> None:
    names = {tool.name for tool in mcp._tool_manager.list_tools()}
    expected = {"tb_logs", "tb_psql", "tb_shell", "tb_open", "tb_setup", "tb_dashboard"}
    assert expected <= names
    dashboard = next(tool for tool in mcp._tool_manager.list_tools() if tool.name == "tb_dashboard")
    assert dashboard.meta is not None
    assert dashboard.meta["ui"]["resourceUri"] == DASHBOARD_URI
    uris = {str(resource.uri) for resource in mcp._resource_manager.list_resources()}
    assert DASHBOARD_URI in uris
    html = dashboard_html()
    assert "tb testbed" in html
    assert "text/html" not in html


def test_tb_down_and_restore_require_confirm() -> None:
    assert "confirm=true" in tb_down(confirm=False)
    assert "confirm=true" in tb_restore("/tmp/backup.dump", confirm=False)


def test_tb_list_projects(isolated_config, tmp_path: Path) -> None:
    write_project(tmp_path / "projects" / "shop", database_name="shop")
    save_config(isolated_config)
    text = tb_list_projects()
    assert "shop" in text
    assert "odoo 18" in text


def test_tb_setup_show_and_write(isolated_config, tmp_path: Path) -> None:
    save_config(isolated_config)
    shown = tb_setup()
    assert "project_roots" in shown
    odoo = tmp_path / "enterprise"
    written = tb_setup(odoo_root=str(odoo), allow_parallel=True)
    assert str(odoo) in written
    assert "allow_parallel: true" in written


def test_tb_status_and_dashboard(isolated_config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = write_project(tmp_path / "projects" / "shop", database_name="shop")
    save_config(isolated_config)
    monkeypatch.chdir(root)
    monkeypatch.setattr(
        "testbed_cli.mcp_server.compose_ps",
        lambda item: ContainerStatus(web="running", db="running", http_port=18069, debug_port=18888),
    )
    status = tb_status()
    assert "shop" in status
    assert "http://localhost:18069" in status
    assert tb_dashboard() == status


def test_tb_logs_psql_shell_open(project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("testbed_cli.mcp_server._resolve", lambda name: project)
    monkeypatch.setattr("testbed_cli.mcp_server.fetch_logs", lambda item, service=None, tail=200: f"{service}:{tail}")
    monkeypatch.setattr("testbed_cli.mcp_server.run_psql_query", lambda item, sql: f"sql:{sql}")
    monkeypatch.setattr("testbed_cli.mcp_server.run_odoo_shell_code", lambda item, code: f"code:{code}")
    monkeypatch.setattr("testbed_cli.mcp_server.open_browser_url", lambda item: "http://localhost:18069")
    assert tb_logs(service="web", tail=20) == "web:20"
    assert tb_psql("select 1") == "sql:select 1"
    assert tb_shell("print(1)") == "code:print(1)"
    assert tb_open() == "http://localhost:18069"
    assert tb_psql("   ") == "Error: pass sql."
    assert tb_shell("") == "Error: pass code."
