from __future__ import annotations

from pathlib import Path
from typing import Optional
import datetime
import os

import typer

from testbed_cli.config import (
    apply_setup,
    format_config,
    join_paths,
    load_config,
    parse_path_csv,
)
from testbed_cli.discovery import discover_projects, project_from_path, resolve_project
from testbed_cli.dockerctl import compose_ps, docker_available, follow_logs_command
from testbed_cli.extras import (
    generate_vscode,
    open_browser,
    run_odoo_shell,
    run_psql,
    start_mailpit,
    update_licenses,
)
from testbed_cli.i18n import export_translations, import_translations
from testbed_cli.init_project import init_project
from testbed_cli.lifecycle import (
    dump_database,
    neutralize_database,
    restore_backup,
    restart_debugpy,
    start_project,
    stop_project,
    tear_down_project,
)
from testbed_cli.modules import create_module, reload_module, update_custom_modules
from testbed_cli.process import run_interactive
from testbed_cli.tests_run import run_tests

SETUP = "Setup and initialise"
CREATE = "Create"
DOCKER = "Docker and running"
DATABASE = "Database"
MODULES = "Modules and tests"
PROJECT_HELP = "Project name, folder or path. Omit to use the current folder."

app = typer.Typer(
    help="CLI for Odoo testbeds.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
i18n_app = typer.Typer(help="Import or export translations.")
app.add_typer(i18n_app, name="i18n", rich_help_panel=MODULES)


def _config():
    return load_config()


def _project(name: str | None = None):
    config = _config()
    if name:
        try:
            return resolve_project(config, name)
        except LookupError as error:
            raise typer.BadParameter(str(error)) from error
    here = project_from_path(Path.cwd())
    if here is not None:
        return here
    projects = discover_projects(config)
    if not projects:
        typer.secho(
            "No testbed projects found. Run tb doctor, or cd into a project folder.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    typer.echo("Not in a testbed folder. Projects:")
    for index, project in enumerate(projects, start=1):
        typer.echo(f"  {index}. {project.database_name}  {project.root}")
    raw = typer.prompt("Project name or number")
    picked = _match_listed_project(projects, raw)
    if picked is not None:
        return picked
    try:
        return resolve_project(config, raw)
    except LookupError as error:
        typer.secho(str(error), fg=typer.colors.RED)
        raise typer.Exit(1) from error


def _match_listed_project(projects: list, raw: str):
    text = raw.strip()
    if text.isdigit():
        index = int(text)
        if 1 <= index <= len(projects):
            return projects[index - 1]
    for project in projects:
        if project.database_name == text or project.folder_name == text:
            return project
    return None


def _project_and_extra(first: str, second: str | None):
    if second is not None:
        return _project(first), second
    return _project(None), first


def _siblings():
    return discover_projects(_config())


def _print(line: str) -> None:
    typer.echo(line)


@app.command(rich_help_panel=SETUP)
def setup(
    show: bool = typer.Option(False, "--show", help="Print the current config and exit"),
    odoo_root: Optional[Path] = typer.Option(None, "--odoo-root", help="Odoo source root (enterprise clones live here)"),
    project_root: list[Path] = typer.Option(
        [],
        "--project-root",
        help="Folder that contains Odoo repos. Repeat for more than one.",
    ),
    backup_root: list[Path] = typer.Option(
        [],
        "--backup-root",
        help="Folder to search for backups. Repeat for more than one. Empty uses project folders.",
    ),
    parallel: Optional[bool] = typer.Option(
        None,
        "--parallel/--no-parallel",
        help="Allow more than one testbed to run at a time",
    ),
    defaults: bool = typer.Option(
        False,
        "--defaults",
        help="Save config without prompting",
    ),
) -> None:
    """Write ~/.config/testbed-cli/config.toml. Prompts if you pass no flags."""
    current = _config()
    if show:
        typer.echo(format_config(current))
        return

    has_flags = bool(odoo_root or project_root or backup_root or parallel is not None or defaults)
    if has_flags:
        updated = apply_setup(
            project_roots=project_root or None,
            odoo_root=odoo_root,
            backup_roots=backup_root or None,
            allow_parallel=parallel,
            base=current,
        )
        typer.echo(format_config(updated))
        return

    roots_raw = typer.prompt(
        "Project folders (comma-separated)",
        default=join_paths(current.project_roots),
    )
    odoo_raw = typer.prompt("Odoo source root", default=str(current.odoo_root))
    backup_raw = typer.prompt(
        "Backup folders (comma-separated, blank uses project folders)",
        default=join_paths(current.backup_roots),
    )
    allow_parallel = typer.confirm(
        "Allow more than one testbed to run at a time",
        default=current.allow_parallel,
    )
    updated = apply_setup(
        project_roots=parse_path_csv(roots_raw),
        odoo_root=Path(odoo_raw),
        backup_roots=parse_path_csv(backup_raw),
        allow_parallel=allow_parallel,
        base=current,
    )
    typer.echo(format_config(updated))


@app.command(rich_help_panel=SETUP)
def doctor() -> None:
    """Check Docker, config paths, and discovered projects."""
    config = _config()
    typer.echo(format_config(config))
    problems = 0

    available, message = docker_available()
    if available:
        typer.echo("docker: ok")
    else:
        problems += 1
        typer.secho(f"docker: {message}", fg=typer.colors.RED)
        typer.echo("Install Docker, add your user to the docker group, then log out and back in.")

    odoo_root = config.odoo_root.expanduser()
    if odoo_root.is_dir() and os.access(odoo_root, os.W_OK):
        typer.echo(f"odoo_root: writable ({odoo_root})")
    elif odoo_root.is_dir():
        problems += 1
        typer.secho(f"odoo_root: not writable ({odoo_root})", fg=typer.colors.RED)
        typer.echo(f'sudo chown "$USER" "{odoo_root}"')
    else:
        typer.secho(f"odoo_root: missing ({odoo_root})", fg=typer.colors.YELLOW)
        typer.echo(f'sudo mkdir -p "{odoo_root}" && sudo chown "$USER" "{odoo_root}"')
        typer.echo("Or point it somewhere you own: tb setup --odoo-root ~/odoo")

    projects = _siblings()
    if not projects:
        typer.secho("projects: none found under project_roots", fg=typer.colors.YELLOW)
        typer.echo("Clone each Odoo repo into a project folder, including its .testbed stack.")
    else:
        for project in projects:
            typer.echo(f"project: {project.database_name}  odoo {project.odoo_version}  {project.root}")

    if problems:
        raise typer.Exit(1)


@app.command(rich_help_panel=SETUP)
def vscode(name: Optional[str] = typer.Argument(None, help=PROJECT_HELP)) -> None:
    """Write VS Code launch/tasks/settings that call tb."""
    generate_vscode(_project(name), _config(), on_line=_print)


@app.command("init", rich_help_panel=SETUP)
def init_cmd(
    path: Path,
    database_name: str = typer.Option(..., "--db", help="Lowercase database / compose name"),
    odoo_version: str = typer.Option(..., "--odoo", help="Two-digit Odoo version, e.g. 18"),
    module: str = typer.Option("", "--module", help="Initial module to test"),
) -> None:
    """Create .env and VS Code files. The folder must already contain .testbed."""
    init_project(path, database_name, odoo_version, module, _config(), on_line=_print)


@app.command("create-module", rich_help_panel=CREATE)
def create_module_cmd(
    first: str = typer.Argument(..., help="Module name, or project then module"),
    second: Optional[str] = typer.Argument(None, help="Module name when the first argument is a project"),
    full: bool = typer.Option(
        False,
        "--full",
        "-d",
        help="Also create data, security, tests, wizards, reports and static folders",
    ),
    odoo_version: Optional[str] = typer.Option(
        None,
        "--odoo",
        help="Major Odoo version for the manifest, e.g. 18 (defaults to the project)",
    ),
) -> None:
    """Scaffold a new addon under the project's addons/ folder."""
    project, module = _project_and_extra(first, second)
    create_module(project, module, full=full, odoo_version=odoo_version, on_line=_print)


@app.command(rich_help_panel=DOCKER)
def status(name: Optional[str] = typer.Argument(None, help=PROJECT_HELP)) -> None:
    """Show Docker and project status."""
    available, message = docker_available()
    if not available:
        typer.secho(message, fg=typer.colors.RED)
        raise typer.Exit(1)
    if name is not None:
        projects = [_project(name)]
    else:
        here = project_from_path(Path.cwd())
        projects = [here] if here is not None else _siblings()
    for project in projects:
        state = compose_ps(project)
        http_port = state.http_port or project.http_port
        debug_port = state.debug_port or project.debug_port
        typer.echo(
            f"{project.database_name:12} odoo {project.odoo_version}  "
            f"web={state.web} db={state.db}  http://localhost:{http_port}  debug={debug_port}"
        )


@app.command(rich_help_panel=DOCKER)
def start(
    name: Optional[str] = typer.Argument(None, help=PROJECT_HELP),
    init: bool = typer.Option(False, "--init", help="Initialise an empty database"),
    parallel: bool = typer.Option(
        False,
        "--parallel",
        help="Allow another testbed to keep running (assigns extra host ports)",
    ),
) -> None:
    """Start the testbed. Stops any other running testbed unless --parallel. Use --init for an empty database with MODULES_TO_TEST installed."""
    start_project(
        _project(name),
        _config(),
        _siblings(),
        initialise=init,
        on_line=_print,
        parallel=parallel or None,
    )


@app.command(rich_help_panel=DOCKER)
def stop(name: Optional[str] = typer.Argument(None, help=PROJECT_HELP)) -> None:
    """Stop containers without removing volumes."""
    stop_project(_project(name), on_line=_print)


@app.command(rich_help_panel=DOCKER)
def down(
    name: Optional[str] = typer.Argument(None, help=PROJECT_HELP),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Tear down containers and volumes."""
    if not yes and not typer.confirm("This deletes the database volume. Continue?"):
        raise typer.Abort()
    tear_down_project(_project(name), on_line=_print)


@app.command(rich_help_panel=DOCKER)
def logs(
    name: Optional[str] = typer.Argument(None, help=PROJECT_HELP),
    service: Optional[str] = typer.Option(None, "--service", "-s", help="Follow one service (default: all)"),
) -> None:
    """Follow container logs in colour."""
    raise typer.Exit(run_interactive(follow_logs_command(_project(name), service)))


@app.command(rich_help_panel=DOCKER)
def open(name: Optional[str] = typer.Argument(None, help=PROJECT_HELP)) -> None:
    """Open the Odoo HTTP URL in a browser."""
    open_browser(_project(name))


@app.command(rich_help_panel=DOCKER)
def mailpit(name: Optional[str] = typer.Argument(None, help=PROJECT_HELP)) -> None:
    """Start a Mailpit sidecar on the compose network."""
    start_mailpit(_project(name), on_line=_print)


@app.command("debug-restart", rich_help_panel=DOCKER)
def debug_restart(name: Optional[str] = typer.Argument(None, help=PROJECT_HELP)) -> None:
    """Kill Python in the web container so debugpy respawns."""
    restart_debugpy(_project(name), on_line=_print)


@app.command(rich_help_panel=DATABASE)
def restore(
    first: str = typer.Argument(..., help="Backup path, or project then backup"),
    second: Optional[Path] = typer.Argument(None, help="Backup path when the first argument is a project"),
    parallel: bool = typer.Option(False, "--parallel"),
) -> None:
    """Restore a .zip, .sql or .dump backup (wipes volumes)."""
    if second is not None:
        project = _project(first)
        backup = second
    else:
        project = _project(None)
        backup = Path(first)
    if not typer.confirm(f"Restore {backup} into {project.database_name}? This wipes existing volumes."):
        raise typer.Abort()
    restore_backup(
        project,
        backup.expanduser(),
        on_line=_print,
        config=_config(),
        siblings=_siblings(),
        parallel=parallel or None,
    )


@app.command(rich_help_panel=DATABASE)
def dump(
    first: Optional[str] = typer.Argument(None, help=PROJECT_HELP),
    second: Optional[Path] = typer.Argument(None, help="Dump file path"),
) -> None:
    """Dump the current database."""
    if first is None:
        project = _project(None)
        output = None
    elif second is not None:
        project = _project(first)
        output = second
    else:
        as_path = Path(first)
        if as_path.suffix.lower() in {".dump", ".sql", ".zip"}:
            project = _project(None)
            output = as_path
        else:
            project = _project(first)
            output = None
    if output is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        output = project.snapshots_dir / f"{project.database_name}-{stamp}.dump"
    dump_database(project, output.expanduser(), on_line=_print)


@app.command(rich_help_panel=DATABASE)
def neutralize(name: Optional[str] = typer.Argument(None, help=PROJECT_HELP)) -> None:
    """Run neutralise SQL on the running database."""
    neutralize_database(_project(name), on_line=_print)


@app.command(rich_help_panel=DATABASE)
def psql(name: Optional[str] = typer.Argument(None, help=PROJECT_HELP)) -> None:
    """Open psql in the database container."""
    raise typer.Exit(run_psql(_project(name)))


@app.command("shell", rich_help_panel=DATABASE)
def odoo_shell(name: Optional[str] = typer.Argument(None, help=PROJECT_HELP)) -> None:
    """Open an Odoo shell on the project database."""
    raise typer.Exit(run_odoo_shell(_project(name)))


@app.command(rich_help_panel=MODULES)
def reload(
    first: str = typer.Argument(..., help="Module name, or project then module"),
    second: Optional[str] = typer.Argument(None, help="Module name when the first argument is a project"),
) -> None:
    """Update one custom module (odoo -u)."""
    project, module = _project_and_extra(first, second)
    reload_module(project, module, on_line=_print)


@app.command("update-modules", rich_help_panel=MODULES)
def update_modules(name: Optional[str] = typer.Argument(None, help=PROJECT_HELP)) -> None:
    """Update every custom module under addons/."""
    update_custom_modules(_project(name), on_line=_print)


@app.command(rich_help_panel=MODULES)
def test(
    name: Optional[str] = typer.Argument(None, help=PROJECT_HELP),
    modules: Optional[str] = typer.Option(None, "--modules", "-m"),
    keyword: Optional[str] = typer.Option(None, "-k"),
    reinit_db: bool = typer.Option(False, "--reinit-db"),
    parallel: bool = typer.Option(False, "--parallel"),
) -> None:
    """Run pytest-odoo / Odoo tests for the given modules."""
    run_tests(
        _project(name),
        modules=modules,
        keyword=keyword,
        reinit_db=reinit_db,
        on_line=_print,
        parallel=parallel or None,
    )


@app.command(rich_help_panel=MODULES)
def license(
    name: Optional[str] = typer.Argument(None, help=PROJECT_HELP),
    path: Optional[Path] = typer.Option(None, "--addons"),
) -> None:
    """Set licence keys in manifests to LGPL-3."""
    project = _project(name)
    update_licenses(path.expanduser() if path else project.addons_dir, on_line=_print)


@i18n_app.command("export")
def i18n_export(
    first: str,
    second: str,
    third: Optional[str] = typer.Argument(None),
) -> None:
    if third is not None:
        export_translations(_project(first), second, third, on_line=_print)
    else:
        export_translations(_project(None), first, second, on_line=_print)


@i18n_app.command("import")
def i18n_import(
    first: str,
    second: str,
    third: Optional[str] = typer.Argument(None),
) -> None:
    if third is not None:
        import_translations(_project(first), second, third, on_line=_print)
    else:
        import_translations(_project(None), first, second, on_line=_print)

