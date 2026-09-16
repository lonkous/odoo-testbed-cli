from __future__ import annotations

from pathlib import Path

import pytest

from testbed_cli.config import Config
from testbed_cli.init_project import init_project
from testbed_cli.project import parse_env_file


def test_init_project_writes_env_and_vscode(tmp_path: Path, isolated_config: Config, monkeypatch) -> None:
    target = tmp_path / "new-project"
    compose_dir = target / ".testbed" / "docker"
    compose_dir.mkdir(parents=True)
    (compose_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

    notes: list[str] = []
    result = init_project(target, "demo", "18", "sale_custom", isolated_config, on_line=notes.append)
    assert result == target.resolve()
    values = parse_env_file(target / ".env")
    assert values["DATABASE_NAME"] == "demo"
    assert values["ODOO_VERSION"] == "18"
    assert values["MODULES_TO_TEST"] == "sale_custom"
    assert (target / ".vscode" / "launch.json").exists()


def test_init_requires_testbed(tmp_path: Path, isolated_config: Config) -> None:
    with pytest.raises(RuntimeError, match="No .testbed compose file"):
        init_project(tmp_path / "fresh", "demo", "18", "", isolated_config)


def test_init_validation_errors(tmp_path: Path, isolated_config: Config) -> None:
    with pytest.raises(ValueError, match="Database name"):
        init_project(tmp_path, "Demo", "18", "", isolated_config)
    with pytest.raises(ValueError, match="Odoo version"):
        init_project(tmp_path, "demo", "18.0", "", isolated_config)
    with pytest.raises(ValueError, match="Module name"):
        init_project(tmp_path, "demo", "18", "Bad-Module", isolated_config)


def test_init_fails_without_compose(tmp_path: Path, isolated_config: Config) -> None:
    with pytest.raises(RuntimeError, match="No .testbed compose file"):
        init_project(tmp_path / "broken", "demo", "18", "", isolated_config)
