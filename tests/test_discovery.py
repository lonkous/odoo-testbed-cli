from __future__ import annotations

from pathlib import Path

import pytest

from testbed_cli.config import Config
from testbed_cli.discovery import discover_projects, project_from_path, resolve_project
from testbed_cli.project import load_project

from tests.helpers import write_project


def test_discover_projects_finds_valid_testbeds(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    write_project(projects_root / "demo", database_name="demo")
    write_project(projects_root / "shop", database_name="shop")
    (projects_root / "notes.txt").write_text("ignore", encoding="utf-8")
    (projects_root / "empty").mkdir()
    config = Config(project_roots=[projects_root])
    found = discover_projects(config)
    assert [item.database_name for item in found] == ["demo", "shop"]


def test_discover_skips_duplicate_resolved_paths(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    write_project(projects_root / "demo", database_name="demo")
    config = Config(project_roots=[projects_root, projects_root])
    found = discover_projects(config)
    assert [item.database_name for item in found] == ["demo"]
    config = Config(project_roots=[tmp_path / "missing"])
    assert discover_projects(config) == []


def test_resolve_project_by_database_and_folder(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    write_project(projects_root / "my-project", database_name="demo")
    config = Config(project_roots=[projects_root])
    by_db = resolve_project(config, "demo")
    by_folder = resolve_project(config, "my-project")
    assert by_db.database_name == "demo"
    assert by_folder.folder_name == "my-project"


def test_resolve_project_by_path(tmp_path: Path) -> None:
    root = write_project(tmp_path / "demo")
    config = Config(project_roots=[tmp_path / "unused"])
    loaded = resolve_project(config, str(root))
    assert loaded.database_name == "demo"
    nested = root / "addons" / "sale"
    nested.mkdir(parents=True)
    assert project_from_path(nested).database_name == "demo"
    assert project_from_path(tmp_path / "unused") is None


def test_resolve_project_unknown_raises(tmp_path: Path) -> None:
    config = Config(project_roots=[tmp_path])
    with pytest.raises(LookupError, match="No testbed project matched"):
        resolve_project(config, "nope")


def test_load_project_used_by_discover(tmp_path: Path) -> None:
    root = write_project(tmp_path / "demo")
    assert load_project(root) is not None
