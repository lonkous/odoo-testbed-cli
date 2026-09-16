from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from testbed_cli.cli import app
from testbed_cli.config import Config
from testbed_cli.dockerctl import ContainerStatus


runner = CliRunner()


def _bind_project(monkeypatch, project, isolated_config: Config) -> None:
    monkeypatch.setattr("testbed_cli.cli.load_config", lambda: isolated_config)
    monkeypatch.setattr("testbed_cli.cli.discover_projects", lambda config: [project])
    monkeypatch.setattr("testbed_cli.cli.resolve_project", lambda config, name: project)


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Start the testbed" in result.stdout
    assert "Setup and initialise" in result.stdout
    assert "Docker and running" in result.stdout
    assert "Create" in result.stdout
    assert "Database" in result.stdout
    assert "Modules and tests" in result.stdout
    command_names = [
        command.name or command.callback.__name__
        for command in app.registered_commands
        if command.callback is not None
    ]
    assert "tui" not in command_names
    assert "status" in command_names
    assert "setup" in command_names
    assert "create-module" in command_names


def test_status_without_docker(monkeypatch, isolated_config: Config) -> None:
    monkeypatch.setattr("testbed_cli.cli.load_config", lambda: isolated_config)
    monkeypatch.setattr("testbed_cli.cli.docker_available", lambda: (False, "Cannot connect"))
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "Cannot connect" in result.stdout


def test_status_lists_projects(project, isolated_config: Config, monkeypatch) -> None:
    _bind_project(monkeypatch, project, isolated_config)
    monkeypatch.setattr("testbed_cli.cli.docker_available", lambda: (True, "ok"))
    monkeypatch.setattr(
        "testbed_cli.cli.compose_ps",
        lambda item: ContainerStatus(web="running", db="running", http_port=18069, debug_port=18888),
    )
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "demo" in result.stdout
    assert "web=running" in result.stdout


def test_status_unknown_project(isolated_config: Config, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.cli.load_config", lambda: isolated_config)
    monkeypatch.setattr("testbed_cli.cli.docker_available", lambda: (True, "ok"))

    def fail_resolve(config, name: str):
        raise LookupError(f"No testbed project matched '{name}'")

    monkeypatch.setattr("testbed_cli.cli.resolve_project", fail_resolve)
    result = runner.invoke(app, ["status", "ghost"])
    assert result.exit_code != 0


def test_start_stop_down(project, isolated_config: Config, monkeypatch) -> None:
    _bind_project(monkeypatch, project, isolated_config)
    calls: list[str] = []
    monkeypatch.setattr("testbed_cli.cli.start_project", lambda *args, **kwargs: calls.append("start"))
    monkeypatch.setattr("testbed_cli.cli.stop_project", lambda *args, **kwargs: calls.append("stop"))
    monkeypatch.setattr("testbed_cli.cli.tear_down_project", lambda *args, **kwargs: calls.append("down"))
    assert runner.invoke(app, ["start", "demo", "--init", "--parallel"]).exit_code == 0
    assert runner.invoke(app, ["stop", "demo"]).exit_code == 0
    assert runner.invoke(app, ["down", "demo", "--yes"]).exit_code == 0
    assert calls == ["start", "stop", "down"]


def test_down_aborts_without_yes(project, isolated_config: Config, monkeypatch) -> None:
    _bind_project(monkeypatch, project, isolated_config)
    result = runner.invoke(app, ["down", "demo"], input="n\n")
    assert result.exit_code != 0


def test_restore_dump_neutralize_reload(project, isolated_config: Config, tmp_path: Path, monkeypatch) -> None:
    _bind_project(monkeypatch, project, isolated_config)
    backup = tmp_path / "backup.sql"
    backup.write_text("SELECT 1;", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr("testbed_cli.cli.restore_backup", lambda *args, **kwargs: calls.append("restore"))
    monkeypatch.setattr("testbed_cli.cli.dump_database", lambda *args, **kwargs: calls.append("dump"))
    monkeypatch.setattr("testbed_cli.cli.neutralize_database", lambda *args, **kwargs: calls.append("neutralise"))
    monkeypatch.setattr("testbed_cli.cli.reload_module", lambda *args, **kwargs: calls.append("reload"))
    monkeypatch.setattr("testbed_cli.cli.update_custom_modules", lambda *args, **kwargs: calls.append("update"))
    monkeypatch.setattr("testbed_cli.cli.create_module", lambda *args, **kwargs: calls.append("create"))
    monkeypatch.setattr("testbed_cli.cli.restart_debugpy", lambda *args, **kwargs: calls.append("debug"))
    assert runner.invoke(app, ["restore", "demo", str(backup)], input="y\n").exit_code == 0
    assert runner.invoke(app, ["dump", "demo"]).exit_code == 0
    assert runner.invoke(app, ["neutralize", "demo"]).exit_code == 0
    assert runner.invoke(app, ["reload", "demo", "sale_custom"]).exit_code == 0
    assert runner.invoke(app, ["update-modules", "demo"]).exit_code == 0
    assert runner.invoke(app, ["create-module", "demo", "sale_custom", "-d", "--odoo", "18"]).exit_code == 0
    assert runner.invoke(app, ["debug-restart", "demo"]).exit_code == 0
    assert calls == ["restore", "dump", "neutralise", "reload", "update", "create", "debug"]


def test_restore_aborts(project, isolated_config: Config, tmp_path: Path, monkeypatch) -> None:
    _bind_project(monkeypatch, project, isolated_config)
    backup = tmp_path / "backup.sql"
    backup.write_text("SELECT 1;", encoding="utf-8")
    result = runner.invoke(app, ["restore", "demo", str(backup)], input="n\n")
    assert result.exit_code != 0


def test_test_psql_shell_logs_open(project, isolated_config: Config, monkeypatch) -> None:
    _bind_project(monkeypatch, project, isolated_config)
    monkeypatch.setattr("testbed_cli.cli.run_tests", lambda *args, **kwargs: "ok")
    monkeypatch.setattr("testbed_cli.cli.run_psql", lambda item: 0)
    monkeypatch.setattr("testbed_cli.cli.run_odoo_shell", lambda item: 3)
    monkeypatch.setattr("testbed_cli.cli.run_interactive", lambda command: 0)
    monkeypatch.setattr("testbed_cli.cli.open_browser", lambda item: None)
    assert runner.invoke(app, ["test", "demo", "-m", "base", "-k", "login", "--reinit-db"]).exit_code == 0
    assert runner.invoke(app, ["psql", "demo"]).exit_code == 0
    assert runner.invoke(app, ["shell", "demo"]).exit_code == 3
    assert runner.invoke(app, ["logs", "demo", "-s", "db"]).exit_code == 0
    assert runner.invoke(app, ["open", "demo"]).exit_code == 0


def test_mailpit_license_vscode_i18n_init(project, isolated_config: Config, tmp_path: Path, monkeypatch) -> None:
    _bind_project(monkeypatch, project, isolated_config)
    monkeypatch.setattr("testbed_cli.cli.start_mailpit", lambda *args, **kwargs: (8025, 1025))
    monkeypatch.setattr("testbed_cli.cli.update_licenses", lambda *args, **kwargs: 1)
    monkeypatch.setattr("testbed_cli.cli.generate_vscode", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.cli.export_translations", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.cli.import_translations", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.cli.init_project", lambda *args, **kwargs: tmp_path)
    assert runner.invoke(app, ["mailpit", "demo"]).exit_code == 0
    assert runner.invoke(app, ["license", "demo"]).exit_code == 0
    assert runner.invoke(app, ["vscode", "demo"]).exit_code == 0
    assert runner.invoke(app, ["i18n", "export", "demo", "de_CH", "sale_custom"]).exit_code == 0
    assert runner.invoke(app, ["i18n", "import", "demo", "de_CH", "sale_custom"]).exit_code == 0
    assert runner.invoke(app, ["init", str(tmp_path / "new"), "--db", "demo", "--odoo", "18", "--module", "base"]).exit_code == 0


def test_setup_show(isolated_config: Config) -> None:
    result = runner.invoke(app, ["setup", "--show"])
    assert result.exit_code == 0
    assert "odoo_root:" in result.stdout
    assert "project_roots:" in result.stdout
    assert "allow_parallel:" in result.stdout


def test_setup_flags(isolated_config: Config, tmp_path: Path) -> None:
    repos = tmp_path / "repos"
    dumps = tmp_path / "dumps"
    odoo_src = tmp_path / "odoo-src"
    result = runner.invoke(
        app,
        [
            "setup",
            "--odoo-root",
            str(odoo_src),
            "--project-root",
            str(repos),
            "--backup-root",
            str(dumps),
            "--parallel",
        ],
    )
    assert result.exit_code == 0
    assert str(odoo_src) in result.stdout
    assert "allow_parallel: true" in result.stdout
    from testbed_cli.config import load_config

    loaded = load_config()
    assert loaded.odoo_root == odoo_src
    assert loaded.project_roots == [repos]
    assert loaded.backup_roots == [dumps]
    assert loaded.allow_parallel is True


def test_setup_prompts(isolated_config: Config, tmp_path: Path) -> None:
    repos = tmp_path / "repos"
    odoo_src = tmp_path / "odoo-src"
    result = runner.invoke(
        app,
        ["setup"],
        input=f"{repos}\n{odoo_src}\n\nn\n",
    )
    assert result.exit_code == 0
    from testbed_cli.config import load_config

    loaded = load_config()
    assert loaded.project_roots == [repos]
    assert loaded.odoo_root == odoo_src
    assert loaded.backup_roots == []
    assert loaded.allow_parallel is False


def test_setup_no_parallel_flag(isolated_config: Config) -> None:
    isolated_config.allow_parallel = True
    from testbed_cli.config import save_config

    save_config(isolated_config)
    result = runner.invoke(app, ["setup", "--no-parallel"])
    assert result.exit_code == 0
    from testbed_cli.config import load_config

    assert load_config().allow_parallel is False


def test_dump_with_output_path(project, isolated_config: Config, tmp_path: Path, monkeypatch) -> None:
    _bind_project(monkeypatch, project, isolated_config)
    output = tmp_path / "custom.dump"
    seen: list[Path] = []
    monkeypatch.setattr("testbed_cli.cli.dump_database", lambda proj, path, on_line=None: seen.append(path))
    assert runner.invoke(app, ["dump", "demo", str(output)]).exit_code == 0
    assert seen == [output]


def test_license_addons_option(project, isolated_config: Config, tmp_path: Path, monkeypatch) -> None:
    _bind_project(monkeypatch, project, isolated_config)
    addons = tmp_path / "extra-addons"
    seen: list[Path] = []
    monkeypatch.setattr("testbed_cli.cli.update_licenses", lambda path, on_line=None: seen.append(path) or 0)
    assert runner.invoke(app, ["license", "demo", "--addons", str(addons)]).exit_code == 0
    assert seen == [addons]


def test_start_passes_init_and_parallel(project, isolated_config: Config, monkeypatch) -> None:
    _bind_project(monkeypatch, project, isolated_config)
    seen: dict[str, object] = {}

    def fake_start(proj, config, siblings, initialise=False, on_line=None, parallel=None):
        seen["initialise"] = initialise
        seen["parallel"] = parallel

    monkeypatch.setattr("testbed_cli.cli.start_project", fake_start)
    assert runner.invoke(app, ["start", "demo", "--init", "--parallel"]).exit_code == 0
    assert seen["initialise"] is True
    assert seen["parallel"] is True


def test_dump_default_output_path(project, isolated_config: Config, monkeypatch) -> None:
    _bind_project(monkeypatch, project, isolated_config)
    seen: list[Path] = []
    monkeypatch.setattr("testbed_cli.cli.dump_database", lambda proj, path, on_line=None: seen.append(path))
    assert runner.invoke(app, ["dump", "demo"]).exit_code == 0
    assert seen[0].parent == project.snapshots_dir
    assert seen[0].name.startswith("demo-")
    assert seen[0].suffix == ".dump"


def test_restore_passes_parallel(project, isolated_config: Config, tmp_path: Path, monkeypatch) -> None:
    _bind_project(monkeypatch, project, isolated_config)
    backup = tmp_path / "backup.sql"
    backup.write_text("SELECT 1;", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_restore(proj, path, on_line=None, config=None, siblings=None, parallel=None):
        seen["parallel"] = parallel

    monkeypatch.setattr("testbed_cli.cli.restore_backup", fake_restore)
    assert runner.invoke(app, ["restore", "demo", str(backup), "--parallel"], input="y\n").exit_code == 0
    assert seen["parallel"] is True


def test_status_named_project(project, isolated_config: Config, monkeypatch) -> None:
    _bind_project(monkeypatch, project, isolated_config)
    monkeypatch.setattr("testbed_cli.cli.docker_available", lambda: (True, "ok"))
    monkeypatch.setattr(
        "testbed_cli.cli.compose_ps",
        lambda item: ContainerStatus(web="stopped", db="stopped"),
    )
    result = runner.invoke(app, ["status", "demo"])
    assert result.exit_code == 0
    assert "web=stopped" in result.stdout
