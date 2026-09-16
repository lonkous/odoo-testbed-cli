from __future__ import annotations

from pathlib import Path
import json

import pytest

from testbed_cli.config import save_config
from testbed_cli.dockerctl import ContainerStatus
from testbed_cli.mcp_server import (
    DASHBOARD_URI,
    _capture,
    _resolve,
    dashboard_html,
    main,
    mcp,
    parse_mcp_args,
    tb_create_module,
    tb_dashboard,
    tb_dashboard_app,
    tb_doctor,
    tb_down,
    tb_dump,
    tb_list_projects,
    tb_logs,
    tb_open,
    tb_psql,
    tb_reload,
    tb_restore,
    tb_setup,
    tb_shell,
    tb_start,
    tb_status,
    tb_stop,
    tb_test,
    tb_vscode,
)
from tests.helpers import write_project

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {
    "tb_list_projects",
    "tb_doctor",
    "tb_status",
    "tb_dashboard",
    "tb_start",
    "tb_stop",
    "tb_down",
    "tb_restore",
    "tb_dump",
    "tb_test",
    "tb_reload",
    "tb_create_module",
    "tb_vscode",
    "tb_logs",
    "tb_psql",
    "tb_shell",
    "tb_open",
    "tb_setup",
}


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
    assert names == EXPECTED_TOOLS
    dashboard = next(tool for tool in mcp._tool_manager.list_tools() if tool.name == "tb_dashboard")
    assert dashboard.meta is not None
    assert dashboard.meta["ui"]["resourceUri"] == DASHBOARD_URI
    resources = list(mcp._resource_manager.list_resources())
    uris = {str(resource.uri) for resource in resources}
    assert DASHBOARD_URI in uris
    mime_types = {resource.mime_type for resource in resources if str(resource.uri) == DASHBOARD_URI}
    assert "text/html;profile=mcp-app" in mime_types
    html = dashboard_html()
    assert "tb testbed" in html
    assert html == tb_dashboard_app()
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
    assert tb_psql(None) == "Error: pass sql."  # type: ignore[arg-type]
    assert tb_shell(None) == "Error: pass code."  # type: ignore[arg-type]


def test_capture_ok_error_and_result() -> None:
    assert _capture(lambda on_line: None) == "ok"

    def with_lines(on_line) -> str:
        on_line("hello")
        return "done"

    assert _capture(with_lines) == "hello\ndone"

    def boom(on_line) -> None:
        raise RuntimeError("boom")

    assert _capture(boom) == "Error: boom"


def test_resolve_from_cwd_name_and_errors(isolated_config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = write_project(tmp_path / "projects" / "shop", database_name="shop")
    save_config(isolated_config)
    monkeypatch.chdir(root)
    assert _resolve(None).database_name == "shop"
    assert _resolve("shop").database_name == "shop"
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LookupError, match="shop"):
        _resolve(None)
    with pytest.raises(LookupError, match="No testbed project matched"):
        _resolve("ghost")


def test_resolve_without_projects(isolated_config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_config(isolated_config)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LookupError, match="No testbed projects found"):
        _resolve(None)


def test_tb_list_projects_empty(isolated_config) -> None:
    save_config(isolated_config)
    assert tb_list_projects() == "No testbed projects found under project_roots."


def test_tb_doctor_branches(isolated_config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_config(isolated_config)
    monkeypatch.setattr("testbed_cli.mcp_server.docker_available", lambda: (False, "Cannot connect"))
    missing = tb_doctor()
    assert "docker: Cannot connect" in missing
    assert "odoo_root: missing" in missing
    assert "projects: none found" in missing

    odoo = tmp_path / "odoo"
    odoo.mkdir()
    monkeypatch.setattr("testbed_cli.mcp_server.os.access", lambda path, mode: False)
    monkeypatch.setattr("testbed_cli.mcp_server.docker_available", lambda: (True, "ok"))
    write_project(tmp_path / "projects" / "shop", database_name="shop")
    blocked = tb_doctor()
    assert "docker: ok" in blocked
    assert "odoo_root: not writable" in blocked
    assert "shop" in blocked

    monkeypatch.setattr("testbed_cli.mcp_server.os.access", lambda path, mode: True)
    writable = tb_doctor()
    assert "odoo_root: writable" in writable


def test_tb_status_none_named_and_error(isolated_config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_config(isolated_config)
    monkeypatch.chdir(tmp_path)
    assert tb_status() == "No testbed projects found."
    write_project(tmp_path / "projects" / "shop", database_name="shop")
    monkeypatch.setattr(
        "testbed_cli.mcp_server.compose_ps",
        lambda item: ContainerStatus(web="running", db="running", http_port=18069),
    )
    named = tb_status(name="shop")
    assert "shop" in named
    assert "http://localhost:18069" in named
    assert "Error:" in tb_status(name="ghost")


def test_tb_setup_paths(isolated_config, tmp_path: Path) -> None:
    save_config(isolated_config)
    roots = tmp_path / "repos"
    backups = tmp_path / "backups"
    text = tb_setup(project_roots=str(roots), backup_roots=str(backups))
    assert str(roots) in text
    assert str(backups) in text


def test_tb_start_stop_down(project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("testbed_cli.mcp_server._resolve", lambda name: project)
    monkeypatch.setattr("testbed_cli.mcp_server.load_config", lambda: "cfg")
    monkeypatch.setattr("testbed_cli.mcp_server.discover_projects", lambda config: [project])
    calls: list[object] = []
    monkeypatch.setattr(
        "testbed_cli.mcp_server.start_project",
        lambda item, config, siblings, initialise=False, on_line=None, parallel=None: calls.append(
            ("start", initialise, parallel)
        ),
    )
    monkeypatch.setattr("testbed_cli.mcp_server.stop_project", lambda item, on_line=None: calls.append("stop"))
    monkeypatch.setattr("testbed_cli.mcp_server.tear_down_project", lambda item, on_line=None: calls.append("down"))
    text = tb_start(init=True, parallel=True)
    assert "Started demo" in text
    assert calls[0] == ("start", True, True)
    assert tb_stop() == "ok"
    assert tb_down(confirm=True) == "ok"
    assert calls[-2:] == ["stop", "down"]


def test_tb_restore_dump_test_reload_vscode(project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("testbed_cli.mcp_server._resolve", lambda name: project)
    monkeypatch.setattr("testbed_cli.mcp_server.load_config", lambda: "cfg")
    monkeypatch.setattr("testbed_cli.mcp_server.discover_projects", lambda config: [project])
    restore_calls: list[object] = []
    monkeypatch.setattr(
        "testbed_cli.mcp_server.restore_backup",
        lambda item, backup, on_line=None, config=None, siblings=None, parallel=None: restore_calls.append(
            (backup, parallel)
        ),
    )
    monkeypatch.setattr("testbed_cli.mcp_server.dump_database", lambda item, path, on_line=None: None)
    monkeypatch.setattr("testbed_cli.mcp_server.run_tests", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.mcp_server.reload_module", lambda item, module, on_line=None: on_line(f"reload {module}"))
    monkeypatch.setattr(
        "testbed_cli.mcp_server.create_module",
        lambda item, module, full=False, odoo_version=None, on_line=None: Path("/tmp/sale_custom"),
    )
    monkeypatch.setattr("testbed_cli.mcp_server.generate_vscode", lambda item, config, on_line=None: on_line("wrote vscode"))
    backup = tmp_path / "shop.dump"
    assert tb_restore(str(backup), confirm=True, parallel=True) == "ok"
    assert restore_calls[0][0] == backup
    assert restore_calls[0][1] is True
    dumped = tb_dump(output=str(tmp_path / "out.dump"))
    assert str(tmp_path / "out.dump") in dumped
    default_dump = tb_dump()
    assert project.database_name in default_dump
    assert default_dump.endswith(".dump")
    assert tb_test(modules="sale") == "ok"
    assert "reload sale_custom" in tb_reload("sale_custom")
    assert "/tmp/sale_custom" in tb_create_module("sale_custom", full=True)
    assert "wrote vscode" in tb_vscode()


def test_tool_errors_from_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_resolve(name: str | None):
        raise LookupError("nope")

    monkeypatch.setattr("testbed_cli.mcp_server._resolve", fail_resolve)
    assert tb_logs().startswith("Error:")
    assert tb_psql("select 1").startswith("Error:")
    assert tb_shell("print(1)").startswith("Error:")
    assert tb_open().startswith("Error:")
    assert tb_start().startswith("Error:")


def test_main_stdio_and_http(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr("testbed_cli.mcp_server.mcp.run", lambda transport="stdio": seen.append(transport))
    original_host = mcp.settings.host
    original_port = mcp.settings.port
    try:
        main([])
        assert seen == ["stdio"]
        main(["--http", "--host", "127.0.0.1", "--port", "9001"])
        assert seen[-1] == "streamable-http"
        assert mcp.settings.host == "127.0.0.1"
        assert mcp.settings.port == 9001
    finally:
        mcp.settings.host = original_host
        mcp.settings.port = original_port


def test_plugin_packaging_matches_templates() -> None:
    package_skill = (REPO_ROOT / "src/testbed_cli/templates/cursor/SKILL.md").read_text(encoding="utf-8")
    plugin_skill = (REPO_ROOT / "plugin/skills/tb/SKILL.md").read_text(encoding="utf-8")
    assert package_skill == plugin_skill
    plugin = json.loads((REPO_ROOT / "plugin/.cursor-plugin/plugin.json").read_text(encoding="utf-8"))
    assert plugin["mcpServers"] == "./mcp.json"
    mcp_json = json.loads((REPO_ROOT / "plugin/mcp.json").read_text(encoding="utf-8"))
    assert mcp_json["mcpServers"]["tb"]["command"] == "tb-mcp"
    market = json.loads((REPO_ROOT / ".cursor-plugin/marketplace.json").read_text(encoding="utf-8"))
    assert market["plugins"][0]["source"] == "./plugin"
    logo = REPO_ROOT / "plugin/assets/logo.svg"
    assert logo.is_file()
