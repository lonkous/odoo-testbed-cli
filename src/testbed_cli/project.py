from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        value = raw_value.split("#", 1)[0].strip()
        values[key.strip()] = value
    return values


def write_env_file(path: Path, values: dict[str, str], extra_keys: dict[str, str] | None = None) -> None:
    existing = parse_env_file(path)
    existing.update(values)
    if extra_keys:
        existing.update(extra_keys)
    order = [
        "MODULES_TO_TEST",
        "DATABASE_NAME",
        "ODOO_VERSION",
        "HTTP_PORT",
        "TEST_PORT",
        "DEBUG_PORT",
    ]
    lines: list[str] = []
    seen: set[str] = set()
    for key in order:
        if key in existing:
            lines.append(f"{key}={existing[key]}")
            seen.add(key)
    for key, value in existing.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass
class Project:
    root: Path
    database_name: str
    odoo_version: str
    modules_to_test: str
    http_port: int
    test_port: int
    debug_port: int
    env_values: dict[str, str]

    @property
    def folder_name(self) -> str:
        return self.root.name

    @property
    def env_path(self) -> Path:
        return self.root / ".env"

    @property
    def testbed_dir(self) -> Path:
        return self.root / ".testbed"

    @property
    def compose_file(self) -> Path:
        return self.testbed_dir / "docker" / "docker-compose.yml"

    @property
    def compose_test_file(self) -> Path:
        local_test = self.testbed_dir / "docker" / "docker-compose-localtest.yml"
        if local_test.exists():
            return local_test
        return self.compose_file

    @property
    def neutralize_sql(self) -> Path:
        return self.testbed_dir / "sql" / "neutralize.sql"

    @property
    def addons_dir(self) -> Path:
        return self.root / "addons"

    @property
    def snapshots_dir(self) -> Path:
        return self.testbed_dir / "snapshots"

    @property
    def compose_project(self) -> str:
        return f"testbed-{self.database_name}"

    @property
    def http_url(self) -> str:
        return f"http://localhost:{self.http_port}"

    def module_list(self) -> list[str]:
        if not self.modules_to_test.strip():
            return []
        return [name.strip() for name in self.modules_to_test.split(",") if name.strip()]

    def custom_modules(self) -> list[str]:
        names: list[str] = []
        if not self.addons_dir.is_dir():
            return names
        for path in sorted(self.addons_dir.iterdir()):
            if path.is_dir() and (path / "__manifest__.py").exists():
                names.append(path.name)
        return names

    def persist_ports(self) -> None:
        write_env_file(
            self.env_path,
            {
                "MODULES_TO_TEST": self.modules_to_test,
                "DATABASE_NAME": self.database_name,
                "ODOO_VERSION": self.odoo_version,
                "HTTP_PORT": str(self.http_port),
                "TEST_PORT": str(self.test_port),
                "DEBUG_PORT": str(self.debug_port),
            },
        )


def load_project(root: Path, port_offset: int = 0) -> Project | None:
    env_path = root / ".env"
    compose_file = root / ".testbed" / "docker" / "docker-compose.yml"
    if not env_path.exists() or not compose_file.exists():
        return None
    values = parse_env_file(env_path)
    database_name = values.get("DATABASE_NAME", "").strip()
    odoo_version = values.get("ODOO_VERSION", "").strip()
    if not database_name or not odoo_version:
        return None
    http_port = _int_env(values, "HTTP_PORT", 8069)
    test_port = _int_env(values, "TEST_PORT", 8068)
    debug_port = _int_env(values, "DEBUG_PORT", 8888)
    return Project(
        root=root.resolve(),
        database_name=database_name,
        odoo_version=odoo_version,
        modules_to_test=values.get("MODULES_TO_TEST", ""),
        http_port=http_port,
        test_port=test_port,
        debug_port=debug_port,
        env_values=values,
    )


def _int_env(values: dict[str, str], key: str, default: int) -> int:
    raw = values.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
