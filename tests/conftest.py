from __future__ import annotations

from pathlib import Path

import pytest

from testbed_cli.config import Config
from testbed_cli.project import Project, load_project

from tests.helpers import write_project


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    return write_project(tmp_path / "demo")


@pytest.fixture
def project(project_root: Path) -> Project:
    loaded = load_project(project_root)
    assert loaded is not None
    return loaded


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    config_dir = tmp_path / "config"
    monkeypatch.setattr("testbed_cli.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("testbed_cli.config.CONFIG_PATH", config_dir / "config.toml")
    monkeypatch.setattr("testbed_cli.config.LEGACY_CONFIG_PATH", tmp_path / "missing-legacy.toml")
    return Config(
        project_roots=[tmp_path / "projects"],
        odoo_root=tmp_path / "odoo",
        backup_roots=[],
        allow_parallel=False,
    )
