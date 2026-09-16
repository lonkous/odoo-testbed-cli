from __future__ import annotations

from argparse import ArgumentParser, Namespace
from importlib.resources import files as package_files
from pathlib import Path
import datetime
import os

from mcp.server.fastmcp import FastMCP

from testbed_cli.config import apply_setup, format_config, load_config, parse_path_csv
from testbed_cli.discovery import discover_projects, project_from_path, resolve_project
from testbed_cli.dockerctl import compose_ps, docker_available, fetch_logs
from testbed_cli.extras import generate_vscode, open_browser_url, run_odoo_shell_code, run_psql_query
from testbed_cli.lifecycle import dump_database, restore_backup, start_project, stop_project, tear_down_project
from testbed_cli.modules import create_module, reload_module
from testbed_cli.project import Project
from testbed_cli.tests_run import run_tests

DASHBOARD_URI = "ui://tb/dashboard.html"
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8765

mcp = FastMCP(
    "tb",
    instructions=(
        "Odoo testbed CLI. Prefer these tools over shelling out to tb. "
        "tb_down and tb_restore need confirm=true."
    ),
)


def parse_mcp_args(argv: list[str] | None = None) -> Namespace:
    parser = ArgumentParser(prog="tb-mcp", description="MCP server for tb (stdio or Streamable HTTP).")
    parser.add_argument("--http", action="store_true", help="Serve Streamable HTTP instead of stdio")
    parser.add_argument("--host", default=DEFAULT_HTTP_HOST, help="HTTP bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT, help="HTTP port (default 8765)")
    return parser.parse_args(argv)


def dashboard_html() -> str:
    return (package_files("testbed_cli") / "templates" / "cursor" / "dashboard.html").read_text(encoding="utf-8")


def _resolve(name: str | None) -> Project:
    config = load_config()
    if name and name.strip():
        return resolve_project(config, name.strip())
    here = project_from_path(Path.cwd())
    if here is not None:
        return here
    projects = discover_projects(config)
    if not projects:
        raise LookupError("No testbed projects found. Run tb_doctor, or pass name.")
    listed = "\n".join(f"  {item.database_name}  {item.root}" for item in projects)
    raise LookupError("Not in a testbed folder. Pass name. Projects:\n" + listed)


def _capture(action) -> str:
    lines: list[str] = []
    try:
        result = action(lines.append)
        if result:
            lines.append(str(result))
    except Exception as error:
        lines.append(f"Error: {error}")
    return "\n".join(lines) if lines else "ok"


def _status_line(project: Project) -> str:
    state = compose_ps(project)
    http_port = state.http_port or project.http_port
    debug_port = state.debug_port or project.debug_port
    return (
        f"{project.database_name:12} odoo {project.odoo_version}  "
        f"web={state.web} db={state.db}  http://localhost:{http_port}  debug={debug_port}"
    )


@mcp.resource(
    DASHBOARD_URI,
    mime_type="text/html;profile=mcp-app",
    name="tb dashboard",
    description="MCP App dashboard for discovered testbeds.",
)
def tb_dashboard_app() -> str:
    return dashboard_html()


@mcp.tool()
def tb_list_projects() -> str:
    """List discovered Odoo testbed projects."""
    projects = discover_projects(load_config())
    if not projects:
        return "No testbed projects found under project_roots."
    return "\n".join(f"{item.database_name}  odoo {item.odoo_version}  {item.root}" for item in projects)


@mcp.tool()
def tb_doctor() -> str:
    """Check Docker, config paths, and discovered projects."""
    config = load_config()
    lines = [format_config(config)]
    available, message = docker_available()
    if available:
        lines.append("docker: ok")
    else:
        lines.append(f"docker: {message}")
        lines.append("Install Docker, add your user to the docker group, then log out and back in.")
    odoo_root = config.odoo_root.expanduser()
    if odoo_root.is_dir() and os.access(odoo_root, os.W_OK):
        lines.append(f"odoo_root: writable ({odoo_root})")
    elif odoo_root.is_dir():
        lines.append(f"odoo_root: not writable ({odoo_root})")
        lines.append(f'sudo chown "$USER" "{odoo_root}"')
    else:
        lines.append(f"odoo_root: missing ({odoo_root})")
        lines.append(f'sudo mkdir -p "{odoo_root}" && sudo chown "$USER" "{odoo_root}"')
    projects = discover_projects(config)
    if not projects:
        lines.append("projects: none found under project_roots")
    else:
        for project in projects:
            lines.append(f"project: {project.database_name}  odoo {project.odoo_version}  {project.root}")
    return "\n".join(lines)


@mcp.tool()
def tb_status(name: str | None = None) -> str:
    """Show Docker status for one project, the current folder, or every discovered testbed."""
    try:
        if name and name.strip():
            projects = [_resolve(name)]
        else:
            here = project_from_path(Path.cwd())
            projects = [here] if here is not None else discover_projects(load_config())
        if not projects:
            return "No testbed projects found."
        return "\n".join(_status_line(project) for project in projects)
    except Exception as error:
        return f"Error: {error}"


@mcp.tool(meta={"ui": {"resourceUri": DASHBOARD_URI}})
def tb_dashboard(name: str | None = None) -> str:
    """Show status in the tb MCP App dashboard (and as text)."""
    return tb_status(name)


@mcp.tool()
def tb_start(name: str | None = None, init: bool = False, parallel: bool = False) -> str:
    """Start the testbed. Stops any other running stack unless parallel is true."""
    def action(on_line) -> None:
        project = _resolve(name)
        start_project(
            project,
            load_config(),
            discover_projects(load_config()),
            initialise=init,
            on_line=on_line,
            parallel=True if parallel else None,
        )
        on_line(f"Started {project.database_name} at {project.http_url}")

    return _capture(action)


@mcp.tool()
def tb_stop(name: str | None = None) -> str:
    """Stop containers without removing volumes."""
    return _capture(lambda on_line: stop_project(_resolve(name), on_line=on_line))


@mcp.tool()
def tb_down(name: str | None = None, confirm: bool = False) -> str:
    """Tear down containers and volumes. Requires confirm=true."""
    if not confirm:
        return "Refused: pass confirm=true to delete the database volume."
    return _capture(lambda on_line: tear_down_project(_resolve(name), on_line=on_line))


@mcp.tool()
def tb_restore(backup: str, name: str | None = None, confirm: bool = False, parallel: bool = False) -> str:
    """Restore a .zip, .sql or .dump backup. Wipes volumes. Requires confirm=true."""
    if not confirm:
        return "Refused: pass confirm=true to wipe volumes and restore."

    def action(on_line) -> None:
        project = _resolve(name)
        restore_backup(
            project,
            Path(backup).expanduser(),
            on_line=on_line,
            config=load_config(),
            siblings=discover_projects(load_config()),
            parallel=True if parallel else None,
        )

    return _capture(action)


@mcp.tool()
def tb_dump(name: str | None = None, output: str | None = None) -> str:
    """Dump the current database. Default path is .testbed/snapshots/."""

    def action(on_line) -> str:
        project = _resolve(name)
        if output:
            path = Path(output).expanduser()
        else:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            path = project.snapshots_dir / f"{project.database_name}-{stamp}.dump"
        dump_database(project, path, on_line=on_line)
        return str(path)

    return _capture(action)


@mcp.tool()
def tb_test(
    name: str | None = None,
    modules: str | None = None,
    keyword: str | None = None,
    reinit_db: bool = False,
    parallel: bool = False,
) -> str:
    """Run pytest-odoo / Odoo tests for the given modules."""

    def action(on_line) -> None:
        run_tests(
            _resolve(name),
            modules=modules,
            keyword=keyword,
            reinit_db=reinit_db,
            on_line=on_line,
            parallel=True if parallel else None,
        )

    return _capture(action)


@mcp.tool()
def tb_reload(module: str, name: str | None = None) -> str:
    """Update one custom module (odoo -u)."""
    return _capture(lambda on_line: reload_module(_resolve(name), module, on_line=on_line))


@mcp.tool()
def tb_create_module(
    module: str,
    name: str | None = None,
    full: bool = False,
    odoo_version: str | None = None,
) -> str:
    """Scaffold a new addon under the project's addons/ folder."""

    def action(on_line) -> str:
        path = create_module(
            _resolve(name),
            module,
            full=full,
            odoo_version=odoo_version,
            on_line=on_line,
        )
        return str(path)

    return _capture(action)


@mcp.tool()
def tb_vscode(name: str | None = None) -> str:
    """Write VS Code launch/tasks/settings that call tb."""
    return _capture(lambda on_line: generate_vscode(_resolve(name), load_config(), on_line=on_line))


@mcp.tool()
def tb_logs(name: str | None = None, service: str | None = None, tail: int = 200) -> str:
    """Return recent compose logs (a snapshot, not a follow). Default last 200 lines."""
    try:
        return fetch_logs(_resolve(name), service=service, tail=tail)
    except Exception as error:
        return f"Error: {error}"


@mcp.tool()
def tb_psql(sql: str, name: str | None = None) -> str:
    """Run one SQL statement against the project database (non-interactive)."""
    if not sql.strip():
        return "Error: pass sql."
    try:
        return run_psql_query(_resolve(name), sql)
    except Exception as error:
        return f"Error: {error}"


@mcp.tool()
def tb_shell(code: str, name: str | None = None) -> str:
    """Run Python in odoo shell (piped, non-interactive)."""
    if not code.strip():
        return "Error: pass code."
    try:
        return run_odoo_shell_code(_resolve(name), code)
    except Exception as error:
        return f"Error: {error}"


@mcp.tool()
def tb_open(name: str | None = None) -> str:
    """Open the Odoo web UI in the default browser and return the URL."""
    try:
        return open_browser_url(_resolve(name))
    except Exception as error:
        return f"Error: {error}"


@mcp.tool()
def tb_setup(
    project_roots: str | None = None,
    odoo_root: str | None = None,
    backup_roots: str | None = None,
    allow_parallel: bool | None = None,
) -> str:
    """Write ~/.config/testbed-cli/config.toml. Paths are comma-separated. Omit all args to show the current config."""
    if project_roots is None and odoo_root is None and backup_roots is None and allow_parallel is None:
        return format_config(load_config())
    config = apply_setup(
        project_roots=parse_path_csv(project_roots) if project_roots else None,
        odoo_root=Path(odoo_root).expanduser() if odoo_root else None,
        backup_roots=parse_path_csv(backup_roots) if backup_roots else None,
        allow_parallel=allow_parallel,
    )
    return format_config(config)


def main(argv: list[str] | None = None) -> None:
    args = parse_mcp_args(argv)
    if args.http:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
        return
    mcp.run(transport="stdio")
