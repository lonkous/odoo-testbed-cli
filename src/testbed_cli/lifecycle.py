from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import zipfile

from testbed_cli.config import Config, load_config
from testbed_cli.discovery import discover_projects
from testbed_cli.dockerctl import (
    compose_cp,
    compose_down,
    compose_exec,
    compose_stop,
    compose_stream_cmd,
    compose_up,
    copy_requirements,
    other_running_projects,
    pull_odoo_image,
    wait_for_db,
    wait_for_ready,
)
from testbed_cli.enterprise import sync_enterprise
from testbed_cli.ports import allocate_ports, reclaim_default_ports
from testbed_cli.process import LogFn, stream_command
from testbed_cli.project import Project


def _occupied_ports(projects: list[Project], current: Project) -> set[int]:
    occupied: set[int] = set()
    for project in projects:
        if project.database_name == current.database_name:
            continue
        occupied.add(project.http_port)
        occupied.add(project.test_port)
        occupied.add(project.debug_port)
    return occupied


def _use_parallel(config: Config, parallel: bool | None) -> bool:
    if parallel is not None:
        return parallel
    return config.allow_parallel


def ensure_exclusive(
    project: Project,
    config: Config,
    siblings: list[Project],
    parallel: bool | None = None,
    on_line: LogFn | None = None,
) -> None:
    if _use_parallel(config, parallel):
        return
    others = other_running_projects(project, siblings)
    if others:
        names = ", ".join(item.database_name for item in others)
        label = "testbed" if len(others) == 1 else "testbeds"
        message = (
            f"Heads up: stopping running {label} {names} so {project.database_name} can start."
        )
        if on_line:
            on_line(message)
        else:
            print(message)
        for other in others:
            compose_stop(other, on_line=on_line)
    if reclaim_default_ports(project) and on_line:
        on_line(
            f"Host HTTP is back on {project.http_port} "
            f"(test {project.test_port}, debug {project.debug_port})."
        )


def allocate_if_parallel(
    project: Project,
    config: Config,
    siblings: list[Project],
    on_line: LogFn | None = None,
    parallel: bool | None = None,
) -> None:
    if not _use_parallel(config, parallel):
        return
    our_ports = {project.http_port, project.test_port, project.debug_port}
    if allocate_ports(project, _occupied_ports(siblings, project), our_ports) and on_line:
        on_line(
            f"Parallel mode: HTTP {project.http_port}, "
            f"test {project.test_port}, debug {project.debug_port}"
        )


def prepare_start(
    project: Project,
    config: Config,
    siblings: list[Project],
    on_line: LogFn | None = None,
    parallel: bool | None = None,
) -> None:
    _docker_or_raise()
    if on_line:
        on_line("Docker is available.")
    if _use_parallel(config, parallel):
        allocate_if_parallel(project, config, siblings, on_line=on_line, parallel=True)
    else:
        ensure_exclusive(project, config, siblings, parallel=False, on_line=on_line)
    pull_odoo_image(project, on_line=on_line)
    sync_enterprise(config.odoo_root, project.odoo_version, on_line=on_line)
    copy_requirements(project, on_line=on_line)


def start_project(
    project: Project,
    config: Config,
    siblings: list[Project],
    initialise: bool = False,
    on_line: LogFn | None = None,
    parallel: bool | None = None,
) -> None:
    prepare_start(project, config, siblings, on_line=on_line, parallel=parallel)
    compose_up(project, on_line=on_line)
    wait_for_ready(project, on_line=on_line)
    if initialise:
        modules = project.modules_to_test.strip() or "base"
        if on_line:
            on_line(f"Initialising database {project.database_name} with {modules}")
        code = compose_exec(
            project,
            "web",
            [
                "odoo",
                "-d",
                project.database_name,
                "-c",
                "/etc/odoo/odoo.conf",
                "-i",
                modules,
                "--no-http",
                "--stop-after-init",
            ],
            on_line=on_line,
        )
        if code != 0:
            raise RuntimeError("Odoo database initialisation failed")


def stop_project(project: Project, on_line: LogFn | None = None) -> None:
    compose_stop(project, on_line=on_line)


def tear_down_project(project: Project, on_line: LogFn | None = None) -> None:
    compose_down(project, on_line=on_line, volumes=True)


def restart_debugpy(project: Project, on_line: LogFn | None = None) -> None:
    compose_exec(project, "web", ["bash", "-c", "pkill -9 python3 || true"], on_line=on_line)


def neutralize_database(project: Project, on_line: LogFn | None = None) -> None:
    if not project.neutralize_sql.exists():
        raise FileNotFoundError(f"Missing neutralize SQL at {project.neutralize_sql}")
    wait_for_db(project)
    compose_cp(
        project,
        str(project.neutralize_sql),
        "db:/tmp/neutralize.sql",
        on_line=on_line,
    )
    code = compose_exec(
        project,
        "db",
        ["psql", "-U", "odoo", "-d", project.database_name, "-f", "/tmp/neutralize.sql"],
        on_line=on_line,
    )
    if code != 0:
        raise RuntimeError("Neutralise SQL failed")


def restore_backup(
    project: Project,
    backup_path: Path,
    on_line: LogFn | None = None,
    config: Config | None = None,
    siblings: list[Project] | None = None,
    parallel: bool | None = None,
) -> None:
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")
    resolved_config = config or load_config()
    resolved_siblings = siblings if siblings is not None else discover_projects(resolved_config)
    ensure_exclusive(
        project, resolved_config, resolved_siblings, parallel=parallel, on_line=on_line
    )
    allocate_if_parallel(
        project, resolved_config, resolved_siblings, on_line=on_line, parallel=parallel
    )
    work_dir = Path(tempfile.mkdtemp(prefix="testbed-restore-"))
    dump_file: Path | None = None
    filestore_dir: Path | None = None
    try:
        dump_file, filestore_dir = _extract_backup(backup_path, work_dir, on_line)
        compose_down(project, on_line=on_line, volumes=True)
        compose_up(project, on_line=on_line)
        wait_for_ready(project, on_line=on_line)
        wait_for_db(project)
        _tune_postgres(project, on_line)
        _recreate_database(project, on_line)
        _load_dump(project, dump_file, on_line)
        neutralize_database(project, on_line=on_line)
        if filestore_dir is not None:
            _restore_filestore(project, filestore_dir, on_line)
        stream_command(compose_stream_cmd(project) + ["start", "web"])
        if on_line:
            on_line(f"Restore finished. Open {project.http_url} (admin / admin).")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def dump_database(project: Project, output: Path, on_line: LogFn | None = None) -> Path:
    wait_for_db(project)
    output.parent.mkdir(parents=True, exist_ok=True)
    remote = f"/tmp/{project.database_name}.dump"
    code = compose_exec(
        project,
        "db",
        ["pg_dump", "-U", "odoo", "-d", project.database_name, "-F", "c", "-f", remote],
        on_line=on_line,
    )
    if code != 0:
        raise RuntimeError("pg_dump failed")
    compose_cp(project, f"db:{remote}", str(output), on_line=on_line)
    if on_line:
        on_line(f"Wrote dump to {output}")
    return output


def _docker_or_raise() -> tuple[bool, str]:
    from testbed_cli.dockerctl import docker_available

    available, message = docker_available()
    if not available:
        raise RuntimeError(message)
    return available, message


def _extract_backup(
    backup_path: Path, work_dir: Path, on_line: LogFn | None
) -> tuple[Path, Path | None]:
    suffix = backup_path.suffix.lower()
    if suffix == ".zip":
        if on_line:
            on_line(f"Unpacking {backup_path}")
        with zipfile.ZipFile(backup_path) as archive:
            archive.extractall(work_dir)
        dump_file = _find_dump(work_dir)
        filestore_dir = _find_filestore(work_dir)
        return dump_file, filestore_dir
    if suffix in {".sql", ".dump"}:
        return backup_path, None
    raise ValueError("Backup must be a .zip, .sql or .dump file")


def _find_dump(work_dir: Path) -> Path:
    for name in ("dump.sql", "dump.dump"):
        direct = work_dir / name
        if direct.exists():
            return direct
    matches = list(work_dir.rglob("dump.sql")) + list(work_dir.rglob("dump.dump"))
    sql_matches = list(work_dir.rglob("*.sql"))
    dump_matches = list(work_dir.rglob("*.dump"))
    for candidate in matches + sql_matches + dump_matches:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Zip must contain dump.sql or dump.dump")


def _find_filestore(work_dir: Path) -> Path | None:
    direct = work_dir / "filestore"
    if direct.is_dir():
        return direct
    matches = [path for path in work_dir.rglob("filestore") if path.is_dir()]
    if matches:
        return matches[0]
    return None


def _tune_postgres(project: Project, on_line: LogFn | None) -> None:
    compose_exec(
        project,
        "db",
        [
            "sed",
            "-i",
            "-e",
            "s%shared_buffers = 128MB%shared_buffers = 512MB%g",
            "/var/lib/postgresql/data/pgdata/postgresql.conf",
        ],
        on_line=on_line,
    )
    stream_command(compose_stream_cmd(project) + ["restart", "db"])
    wait_for_db(project)


def _recreate_database(project: Project, on_line: LogFn | None) -> None:
    compose_exec(
        project,
        "db",
        [
            "psql",
            "-U",
            "odoo",
            "-d",
            "postgres",
            "-c",
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{project.database_name}' AND pid <> pg_backend_pid();",
        ],
        on_line=on_line,
    )
    compose_exec(
        project,
        "db",
        ["psql", "-U", "odoo", "-d", "postgres", "-c", f"DROP DATABASE IF EXISTS {project.database_name};"],
        on_line=on_line,
    )
    code = compose_exec(
        project,
        "db",
        ["psql", "-U", "odoo", "-d", "postgres", "-c", f"CREATE DATABASE {project.database_name};"],
        on_line=on_line,
    )
    if code != 0:
        raise RuntimeError("Could not create database")


def _load_dump(project: Project, dump_file: Path, on_line: LogFn | None) -> None:
    remote_name = dump_file.name
    compose_cp(project, str(dump_file), f"db:/tmp/{remote_name}", on_line=on_line)
    if dump_file.suffix.lower() == ".dump":
        code = compose_exec(
            project,
            "db",
            [
                "pg_restore",
                "-U",
                "odoo",
                "-d",
                project.database_name,
                "--no-owner",
                "--no-acl",
                f"/tmp/{remote_name}",
            ],
            on_line=on_line,
        )
    else:
        code = compose_exec(
            project,
            "db",
            ["psql", "-U", "odoo", "-d", project.database_name, "-f", f"/tmp/{remote_name}"],
            on_line=on_line,
        )
    if code != 0:
        raise RuntimeError("Database restore failed")


def _restore_filestore(project: Project, filestore_dir: Path, on_line: LogFn | None) -> None:
    remote = f"/var/lib/odoo/filestore/{project.database_name}"
    if on_line:
        on_line(f"Restoring filestore to {remote}")
    compose_exec(project, "web", ["mkdir", "-p", remote], on_line=on_line)
    compose_cp(project, f"{filestore_dir}/.", f"web:{remote}/", on_line=on_line)
