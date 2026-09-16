from __future__ import annotations

from pathlib import Path
import re

from testbed_cli.config import Config
from testbed_cli.extras import generate_vscode
from testbed_cli.process import LogFn
from testbed_cli.project import write_env_file

DB_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
VERSION_RE = re.compile(r"^[0-9]{2}$")
MODULE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def init_project(
    target: Path,
    database_name: str,
    odoo_version: str,
    module_name: str,
    config: Config,
    on_line: LogFn | None = None,
) -> Path:
    if not DB_NAME_RE.match(database_name):
        raise ValueError("Database name must be lowercase letters, numbers and underscores")
    if not VERSION_RE.match(odoo_version):
        raise ValueError("Odoo version must be a two-digit number such as 18")
    if module_name and not MODULE_RE.match(module_name):
        raise ValueError("Module name must be lowercase letters, numbers and underscores")

    target = Path(target).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    if on_line:
        on_line(f"Initialising project at {target}")

    compose_file = target / ".testbed" / "docker" / "docker-compose.yml"
    if not compose_file.exists():
        raise RuntimeError(
            "No .testbed compose file found. Put the testbed stack in "
            f"{target / '.testbed'} and re-run init."
        )

    write_env_file(
        target / ".env",
        {
            "MODULES_TO_TEST": module_name,
            "DATABASE_NAME": database_name,
            "ODOO_VERSION": odoo_version,
        },
    )
    from testbed_cli.project import load_project

    project = load_project(target)
    if project is None:
        raise RuntimeError(
            "Project files were written but .testbed compose is missing. "
            "Add the .testbed stack and try again."
        )
    generate_vscode(project, config, on_line=on_line)
    if on_line:
        on_line("Don't forget to update requirements.txt if the project needs extra Python libraries.")
    return target
