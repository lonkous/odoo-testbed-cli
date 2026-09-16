from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import tomllib

CONFIG_DIR = Path.home() / ".config" / "testbed-cli"
CONFIG_PATH = CONFIG_DIR / "config.toml"
LEGACY_CONFIG_PATH = Path.home() / ".config" / "testbed-tui" / "config.toml"


def _default_project_roots() -> list[Path]:
    documents = Path.home() / "Documents"
    if documents.is_dir():
        return [documents]
    return [Path.home()]


@dataclass
class Config:
    project_roots: list[Path] = field(default_factory=_default_project_roots)
    odoo_root: Path = field(default_factory=lambda: Path("/opt/odoo"))
    backup_roots: list[Path] = field(default_factory=list)
    allow_parallel: bool = False

    def resolved_backup_roots(self) -> list[Path]:
        if self.backup_roots:
            return self.backup_roots
        return list(self.project_roots)


def _parse_path_list(raw: object) -> list[Path]:
    if not isinstance(raw, list):
        return []
    paths: list[Path] = []
    for item in raw:
        paths.append(Path(str(item)).expanduser())
    return paths


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _toml_paths(paths: list[Path]) -> str:
    lines = ["["]
    for path in paths:
        lines.append(f'  "{_toml_escape(str(path))}",')
    lines.append("]")
    return "\n".join(lines)


def save_config(config: Config) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        backup_roots = config.backup_roots
        contents = (
            f"project_roots = {_toml_paths(config.project_roots)}\n"
            f'odoo_root = "{_toml_escape(str(config.odoo_root))}"\n'
            f"backup_roots = {_toml_paths(backup_roots)}\n"
            f"allow_parallel = {'true' if config.allow_parallel else 'false'}\n"
        )
        CONFIG_PATH.write_text(contents, encoding="utf-8")
    except OSError:
        return


def load_config() -> Config:
    path = CONFIG_PATH
    if not path.exists() and LEGACY_CONFIG_PATH.exists():
        path = LEGACY_CONFIG_PATH
    if not path.exists():
        config = Config()
        save_config(config)
        return config

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project_roots = _parse_path_list(data.get("project_roots")) or _default_project_roots()
    odoo_root = Path(str(data.get("odoo_root", "/opt/odoo"))).expanduser()
    backup_roots = _parse_path_list(data.get("backup_roots"))
    return Config(
        project_roots=project_roots,
        odoo_root=odoo_root,
        backup_roots=backup_roots,
        allow_parallel=bool(data.get("allow_parallel", False)),
    )


def expand_env(value: str) -> str:
    return os.path.expanduser(os.path.expandvars(value))


def parse_path_csv(raw: str) -> list[Path]:
    parts = [item.strip() for item in raw.split(",") if item.strip()]
    return [Path(item).expanduser() for item in parts]


def join_paths(paths: list[Path]) -> str:
    return ", ".join(str(path) for path in paths)


def apply_setup(
    *,
    project_roots: list[Path] | None = None,
    odoo_root: Path | None = None,
    backup_roots: list[Path] | None = None,
    allow_parallel: bool | None = None,
    base: Config | None = None,
) -> Config:
    config = base or load_config()
    if project_roots is not None:
        config.project_roots = [path.expanduser() for path in project_roots] or _default_project_roots()
    if odoo_root is not None:
        config.odoo_root = odoo_root.expanduser()
    if backup_roots is not None:
        config.backup_roots = [path.expanduser() for path in backup_roots]
    if allow_parallel is not None:
        config.allow_parallel = allow_parallel
    save_config(config)
    return config


def format_config(config: Config) -> str:
    backup = join_paths(config.backup_roots) if config.backup_roots else "(same as project folders)"
    return (
        f"config: {CONFIG_PATH}\n"
        f"project_roots: {join_paths(config.project_roots)}\n"
        f"odoo_root: {config.odoo_root}\n"
        f"backup_roots: {backup}\n"
        f"allow_parallel: {'true' if config.allow_parallel else 'false'}"
    )
