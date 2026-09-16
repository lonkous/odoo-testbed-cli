from __future__ import annotations

from pathlib import Path

from testbed_cli.config import Config, apply_setup, expand_env, format_config, load_config, parse_path_csv, save_config


def test_save_and_load_config(isolated_config: Config, tmp_path: Path) -> None:
    isolated_config.project_roots = [tmp_path / "docs"]
    isolated_config.odoo_root = tmp_path / "odoo"
    isolated_config.backup_roots = [tmp_path / "backups"]
    isolated_config.allow_parallel = True
    save_config(isolated_config)

    loaded = load_config()
    assert loaded.project_roots == [tmp_path / "docs"]
    assert loaded.odoo_root == tmp_path / "odoo"
    assert loaded.backup_roots == [tmp_path / "backups"]
    assert loaded.allow_parallel is True


def test_load_config_writes_defaults_when_missing(isolated_config: Config) -> None:
    from testbed_cli import config as config_module

    assert not config_module.CONFIG_PATH.exists()
    loaded = load_config()
    assert config_module.CONFIG_PATH.exists()
    assert loaded.odoo_root == Path("/opt/odoo")
    assert loaded.allow_parallel is False


def test_resolved_backup_roots_fall_back_to_project_roots(tmp_path: Path) -> None:
    config = Config(project_roots=[tmp_path], backup_roots=[])
    assert config.resolved_backup_roots() == [tmp_path]
    config.backup_roots = [tmp_path / "dumps"]
    assert config.resolved_backup_roots() == [tmp_path / "dumps"]


def test_expand_env(monkeypatch) -> None:
    monkeypatch.setenv("TB_TEST_HOME", "/tmp/tb-home")
    assert expand_env("$TB_TEST_HOME/addons") == "/tmp/tb-home/addons"


def test_load_config_ignores_non_list_roots(isolated_config: Config) -> None:
    from testbed_cli import config as config_module

    config_module.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_module.CONFIG_PATH.write_text(
        'project_roots = "not-a-list"\nodoo_root = "~/odoo"\n',
        encoding="utf-8",
    )
    loaded = load_config()
    assert loaded.project_roots
    assert loaded.odoo_root == Path.home() / "odoo"


def test_load_config_reads_legacy_path(isolated_config, tmp_path, monkeypatch) -> None:
    from testbed_cli import config as config_module

    legacy = tmp_path / "legacy.toml"
    legacy.write_text('odoo_root = "/opt/legacy"\nproject_roots = ["/tmp/docs"]\n', encoding="utf-8")
    monkeypatch.setattr(config_module, "LEGACY_CONFIG_PATH", legacy)
    loaded = load_config()
    assert loaded.odoo_root == Path("/opt/legacy")
    assert loaded.project_roots == [Path("/tmp/docs")]


def test_parse_path_csv() -> None:
    assert parse_path_csv(" ~/docs , /opt/odoo ") == [Path("~/docs").expanduser(), Path("/opt/odoo")]
    assert parse_path_csv("  ") == []


def test_apply_setup_updates_and_saves(isolated_config: Config, tmp_path: Path) -> None:
    updated = apply_setup(
        project_roots=[tmp_path / "repos"],
        odoo_root=tmp_path / "odoo-src",
        backup_roots=[tmp_path / "dumps"],
        allow_parallel=True,
        base=isolated_config,
    )
    loaded = load_config()
    assert loaded.project_roots == [tmp_path / "repos"]
    assert loaded.odoo_root == tmp_path / "odoo-src"
    assert loaded.backup_roots == [tmp_path / "dumps"]
    assert loaded.allow_parallel is True
    text = format_config(updated)
    assert "allow_parallel: true" in text
    assert str(tmp_path / "repos") in text


def test_apply_setup_empty_roots_uses_defaults(isolated_config: Config) -> None:
    updated = apply_setup(project_roots=[], base=isolated_config)
    assert updated.project_roots


def test_join_paths_and_format_without_backups(tmp_path: Path) -> None:
    from testbed_cli.config import join_paths

    config = Config(project_roots=[tmp_path], backup_roots=[], allow_parallel=False)
    assert join_paths(config.project_roots) == str(tmp_path)
    text = format_config(config)
    assert "same as project folders" in text
    assert "allow_parallel: false" in text


def test_apply_setup_loads_when_base_missing(isolated_config: Config) -> None:
    save_config(isolated_config)
    updated = apply_setup(allow_parallel=True)
    assert updated.allow_parallel is True
    assert updated.project_roots == isolated_config.project_roots


def test_save_config_swallows_oserror(isolated_config: Config, monkeypatch) -> None:
    def fail_write(self, *args, **kwargs):
        raise OSError("denied")

    monkeypatch.setattr(Path, "write_text", fail_write)
    save_config(isolated_config)
