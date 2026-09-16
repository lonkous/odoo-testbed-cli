from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

from testbed_cli.project import write_env_file


def write_project(
    root: Path,
    *,
    database_name: str = "demo",
    odoo_version: str = "18",
    modules_to_test: str = "base",
    http_port: int = 18069,
    test_port: int = 18068,
    debug_port: int = 18888,
    extra_env: dict[str, str] | None = None,
    local_test_compose: bool = False,
) -> Path:
    compose_dir = root / ".testbed" / "docker"
    compose_dir.mkdir(parents=True)
    (compose_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    if local_test_compose:
        (compose_dir / "docker-compose-localtest.yml").write_text(
            "services:\n  web:\n    image: odoo\n",
            encoding="utf-8",
        )
    sql_dir = root / ".testbed" / "sql"
    sql_dir.mkdir(parents=True, exist_ok=True)
    (sql_dir / "neutralize.sql").write_text("SELECT 1;\n", encoding="utf-8")
    values = {
        "MODULES_TO_TEST": modules_to_test,
        "DATABASE_NAME": database_name,
        "ODOO_VERSION": odoo_version,
        "HTTP_PORT": str(http_port),
        "TEST_PORT": str(test_port),
        "DEBUG_PORT": str(debug_port),
    }
    if extra_env:
        values.update(extra_env)
    write_env_file(root / ".env", values)
    return root


def completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> CompletedProcess[str]:
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)
