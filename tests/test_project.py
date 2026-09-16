from __future__ import annotations

from pathlib import Path

from testbed_cli.project import load_project, parse_env_file, write_env_file

from tests.helpers import write_project


def test_parse_env_file_skips_comments_and_inline_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# comment\n"
        "DATABASE_NAME=demo  # inline\n"
        "EMPTY=\n"
        "NOEQUALS\n"
        "\n"
        "ODOO_VERSION=18\n",
        encoding="utf-8",
    )
    values = parse_env_file(env_path)
    assert values["DATABASE_NAME"] == "demo"
    assert values["ODOO_VERSION"] == "18"
    assert values["EMPTY"] == ""
    assert "NOEQUALS" not in values


def test_parse_env_file_missing_returns_empty(tmp_path: Path) -> None:
    assert parse_env_file(tmp_path / "missing.env") == {}


def test_write_env_file_keeps_known_order(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    write_env_file(
        env_path,
        {
            "EXTRA": "keep",
            "DATABASE_NAME": "demo",
            "ODOO_VERSION": "18",
            "MODULES_TO_TEST": "base",
        },
        extra_keys={"HTTP_PORT": "8069"},
    )
    lines = env_path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("MODULES_TO_TEST=")
    assert "HTTP_PORT=8069" in lines
    assert "EXTRA=keep" in lines


def test_load_project_reads_compose_and_ports(project_root: Path) -> None:
    loaded = load_project(project_root)
    assert loaded is not None
    assert loaded.database_name == "demo"
    assert loaded.odoo_version == "18"
    assert loaded.http_port == 18069
    assert loaded.compose_project == "testbed-demo"
    assert loaded.http_url == "http://localhost:18069"
    assert loaded.folder_name == "demo"
    assert loaded.compose_file.exists()
    assert loaded.compose_test_file == loaded.compose_file


def test_load_project_uses_local_test_compose(tmp_path: Path) -> None:
    root = write_project(tmp_path / "demo", local_test_compose=True)
    loaded = load_project(root)
    assert loaded is not None
    assert loaded.compose_test_file.name == "docker-compose-localtest.yml"


def test_load_project_returns_none_when_incomplete(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DATABASE_NAME=demo\n", encoding="utf-8")
    assert load_project(tmp_path) is None
    write_project(tmp_path / "broken", database_name="")
    # empty DATABASE_NAME still writes the key; force a missing version
    env_path = tmp_path / "broken" / ".env"
    env_path.write_text("DATABASE_NAME=\nODOO_VERSION=\n", encoding="utf-8")
    assert load_project(tmp_path / "broken") is None


def test_module_list_and_custom_modules(project) -> None:
    assert project.module_list() == ["base"]
    project.modules_to_test = " a , b, ,c "
    assert project.module_list() == ["a", "b", "c"]
    project.modules_to_test = "  "
    assert project.module_list() == []

    addons = project.addons_dir
    (addons / "sale_custom").mkdir(parents=True)
    (addons / "sale_custom" / "__manifest__.py").write_text("{}", encoding="utf-8")
    (addons / "not_a_module").mkdir()
    assert project.custom_modules() == ["sale_custom"]


def test_persist_ports_writes_env(project) -> None:
    project.http_port = 19069
    project.persist_ports()
    values = parse_env_file(project.env_path)
    assert values["HTTP_PORT"] == "19069"


def test_custom_modules_empty_without_addons(project) -> None:
    assert project.custom_modules() == []
    assert project.snapshots_dir.name == "snapshots"


def test_int_env_defaults(tmp_path: Path) -> None:
    root = write_project(tmp_path / "demo", extra_env={"HTTP_PORT": "nope", "TEST_PORT": ""})
    loaded = load_project(root)
    assert loaded is not None
    assert loaded.http_port == 8069
    assert loaded.test_port == 8068
