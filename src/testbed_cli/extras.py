from __future__ import annotations

from importlib.resources import files as package_files
from pathlib import Path
import re
import webbrowser

from testbed_cli.config import Config
from testbed_cli.dockerctl import (
    compose_cmd,
    compose_exec_capture,
    compose_network_name,
    compose_ps,
    compose_stream_cmd,
)
from testbed_cli.process import LogFn, combined_output, run_command, run_interactive, stream_command
from testbed_cli.project import Project


def open_browser_url(project: Project) -> str:
    status = compose_ps(project)
    port = status.http_port or project.http_port
    url = f"http://localhost:{port}"
    webbrowser.open(url)
    return url


def open_browser(project: Project) -> None:
    open_browser_url(project)


def run_psql(project: Project) -> int:
    return run_interactive(compose_stream_cmd(project) + ["exec", "db", "psql", "-x", "-U", "odoo", "-d", project.database_name])


def run_odoo_shell(project: Project) -> int:
    return run_interactive(
        compose_stream_cmd(project)
        + [
            "exec",
            "web",
            "odoo",
            "shell",
            "-d",
            project.database_name,
            "-c",
            "/etc/odoo/odoo.conf",
        ]
    )


def run_psql_query(project: Project, sql: str) -> str:
    result = compose_exec_capture(
        project,
        "db",
        ["psql", "-x", "-U", "odoo", "-d", project.database_name, "-c", sql],
    )
    output = combined_output(result)
    if result.returncode != 0:
        raise RuntimeError(output or "psql failed")
    return output or "ok"


def run_odoo_shell_code(project: Project, code: str) -> str:
    command = compose_cmd(project) + [
        "exec",
        "-T",
        "web",
        "odoo",
        "shell",
        "-d",
        project.database_name,
        "-c",
        "/etc/odoo/odoo.conf",
    ]
    result = run_command(command, timeout=120, input_text=code)
    output = combined_output(result)
    if result.returncode != 0:
        raise RuntimeError(output or "odoo shell failed")
    return output or "ok"


def start_mailpit(project: Project, on_line: LogFn | None = None) -> tuple[int, int]:
    ui_port = 8025 + max(project.http_port - 8069, 0)
    smtp_port = 1025 + max(project.http_port - 8069, 0)
    name = f"testbed-{project.database_name}-mailpit"
    run_command(["docker", "rm", "-f", name])
    network = compose_network_name(project)
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        network,
        "-p",
        f"{ui_port}:8025",
        "-p",
        f"{smtp_port}:1025",
        "axllent/mailpit",
    ]
    code = stream_command(command)
    if code != 0:
        raise RuntimeError("Failed to start Mailpit")
    if on_line:
        on_line(f"Mailpit UI: http://localhost:{ui_port}")
        on_line(f"SMTP: mailpit:{smtp_port} from inside the compose network (host port {smtp_port})")
    return ui_port, smtp_port


def update_licenses(addons_dir: Path, on_line: LogFn | None = None) -> int:
    if not addons_dir.is_dir():
        raise FileNotFoundError(f"Addons directory not found: {addons_dir}")
    updated = 0
    license_single = re.compile(r"'license'\s*:\s*'[^']*'")
    license_double = re.compile(r'"license"\s*:\s*"[^"]*"')
    for manifest in addons_dir.rglob("__manifest__.py"):
        text = manifest.read_text(encoding="utf-8")
        if "'license'" not in text and '"license"' not in text:
            continue
        new_text = license_single.sub("'license': 'LGPL-3'", text)
        new_text = license_double.sub('"license": "LGPL-3"', new_text)
        if new_text != text:
            manifest.write_text(new_text, encoding="utf-8")
            updated += 1
            if on_line:
                on_line(f"Updated: {manifest}")
    if on_line:
        on_line(f"Files updated: {updated}")
    return updated


def generate_vscode(project: Project, config: Config, on_line: LogFn | None = None) -> None:
    vscode_dir = project.root / ".vscode"
    vscode_dir.mkdir(parents=True, exist_ok=True)
    values = {
        "name": project.database_name,
        "debug_port": str(project.debug_port),
        "odoo_root": str(config.odoo_root),
        "odoo_version": project.odoo_version,
    }
    (vscode_dir / "launch.json").write_text(_vscode_template("launch.json", values), encoding="utf-8")
    (vscode_dir / "tasks.json").write_text(_vscode_template("tasks.json", values), encoding="utf-8")
    (vscode_dir / "settings.json").write_text(_vscode_template("settings.json", values), encoding="utf-8")
    workspace_path = project.root / f"{project.database_name}.code-workspace"
    workspace_path.write_text(_vscode_template("workspace.json", values), encoding="utf-8")
    if on_line:
        on_line(f"Wrote VS Code files under {vscode_dir} and {workspace_path}")


def _vscode_template(filename: str, values: dict[str, str]) -> str:
    text = (package_files("testbed_cli") / "templates" / "vscode" / filename).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    if not text.endswith("\n"):
        text += "\n"
    return text


