from __future__ import annotations

import zipfile

import pytest

from testbed_cli.config import Config
from testbed_cli.lifecycle import (
    _docker_or_raise,
    _extract_backup,
    _find_dump,
    _find_filestore,
    _load_dump,
    _occupied_ports,
    _recreate_database,
    _restore_filestore,
    _tune_postgres,
    _use_parallel,
    dump_database,
    ensure_exclusive,
    neutralize_database,
    prepare_start,
    restore_backup,
    restart_debugpy,
    start_project,
    stop_project,
    tear_down_project,
)
from testbed_cli.project import load_project

from tests.helpers import write_project


def test_ensure_exclusive_stops_other_running(project, monkeypatch) -> None:
    other = load_project(write_project(project.root.parent / "shop", database_name="shop"))
    assert other is not None
    stopped: list[str] = []
    notes: list[str] = []
    monkeypatch.setattr(
        "testbed_cli.lifecycle.other_running_projects",
        lambda current, siblings: [other],
    )
    monkeypatch.setattr(
        "testbed_cli.lifecycle.compose_stop",
        lambda item, on_line=None: stopped.append(item.database_name),
    )
    ensure_exclusive(project, Config(allow_parallel=False), [other], on_line=notes.append)
    assert stopped == ["shop"]
    assert any("shop" in item and "demo" in item for item in notes)


def test_ensure_exclusive_allows_parallel(project, monkeypatch) -> None:
    other = load_project(write_project(project.root.parent / "shop", database_name="shop"))
    assert other is not None
    monkeypatch.setattr(
        "testbed_cli.lifecycle.other_running_projects",
        lambda current, siblings: [other],
    )
    ensure_exclusive(project, Config(allow_parallel=True), [other])
    ensure_exclusive(project, Config(allow_parallel=False), [other], parallel=True)


def test_start_and_init(project, isolated_config, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("testbed_cli.lifecycle._docker_or_raise", lambda: (True, "ok"))
    monkeypatch.setattr("testbed_cli.lifecycle.ensure_exclusive", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.pull_odoo_image", lambda *args, **kwargs: calls.append("pull"))
    monkeypatch.setattr("testbed_cli.lifecycle.sync_enterprise", lambda *args, **kwargs: calls.append("enterprise"))
    monkeypatch.setattr("testbed_cli.lifecycle.copy_requirements", lambda *args, **kwargs: calls.append("reqs"))
    monkeypatch.setattr("testbed_cli.lifecycle.compose_up", lambda *args, **kwargs: calls.append("up"))
    monkeypatch.setattr("testbed_cli.lifecycle.wait_for_ready", lambda *args, **kwargs: calls.append("ready"))
    monkeypatch.setattr("testbed_cli.lifecycle.compose_exec", lambda *args, **kwargs: 0)
    start_project(project, isolated_config, [], initialise=True, on_line=calls.append)
    assert "up" in calls
    assert "ready" in calls
    assert any("Initialising database" in item for item in calls)


def test_start_init_failure(project, isolated_config, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.lifecycle.prepare_start", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.compose_up", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.wait_for_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.compose_exec", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError, match="initialisation failed"):
        start_project(project, isolated_config, [], initialise=True)


def test_prepare_start_parallel_allocates_ports(project, isolated_config, monkeypatch) -> None:
    isolated_config.allow_parallel = True
    notes: list[str] = []
    monkeypatch.setattr("testbed_cli.lifecycle._docker_or_raise", lambda: (True, "ok"))
    monkeypatch.setattr("testbed_cli.lifecycle.allocate_ports", lambda *args, **kwargs: True)
    monkeypatch.setattr("testbed_cli.lifecycle.pull_odoo_image", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.sync_enterprise", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.copy_requirements", lambda *args, **kwargs: None)
    prepare_start(project, isolated_config, [], on_line=notes.append, parallel=True)
    assert any("Parallel mode" in item for item in notes)


def test_stop_and_tear_down(project, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("testbed_cli.lifecycle.compose_stop", lambda *args, **kwargs: calls.append("stop"))
    monkeypatch.setattr("testbed_cli.lifecycle.compose_down", lambda *args, **kwargs: calls.append("down"))
    stop_project(project)
    tear_down_project(project)
    assert calls == ["stop", "down"]


def test_restart_debugpy(project, monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(
        "testbed_cli.lifecycle.compose_exec",
        lambda proj, service, command, on_line=None: seen.append(command) or 0,
    )
    restart_debugpy(project)
    assert "pkill -9 python3 || true" in seen[0]


def test_neutralize_missing_sql(tmp_path) -> None:
    project = load_project(write_project(tmp_path / "demo"))
    assert project is not None
    project.neutralize_sql.unlink()
    with pytest.raises(FileNotFoundError, match="Missing neutralize SQL"):
        neutralize_database(project)


def test_neutralize_database(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.lifecycle.wait_for_db", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.compose_cp", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.compose_exec", lambda *args, **kwargs: 0)
    neutralize_database(project)
    monkeypatch.setattr("testbed_cli.lifecycle.compose_exec", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError, match="Neutralise SQL failed"):
        neutralize_database(project)


def test_dump_database(project, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.lifecycle.wait_for_db", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.compose_exec", lambda *args, **kwargs: 0)
    monkeypatch.setattr("testbed_cli.lifecycle.compose_cp", lambda *args, **kwargs: None)
    output = tmp_path / "out" / "demo.dump"
    notes: list[str] = []
    result = dump_database(project, output, on_line=notes.append)
    assert result == output
    assert output.parent.is_dir()
    monkeypatch.setattr("testbed_cli.lifecycle.compose_exec", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError, match="pg_dump failed"):
        dump_database(project, output)


def test_extract_backup_zip_and_sql(tmp_path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    dump_sql = tmp_path / "src" / "dump.sql"
    dump_sql.parent.mkdir()
    dump_sql.write_text("SELECT 1;", encoding="utf-8")
    filestore = tmp_path / "src" / "filestore"
    filestore.mkdir()
    (filestore / "file").write_text("blob", encoding="utf-8")
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.write(dump_sql, "dump.sql")
        zip_file.write(filestore / "file", "filestore/file")
    dump_file, filestore_dir = _extract_backup(archive, work_dir, on_line=None)
    assert dump_file.name == "dump.sql"
    assert filestore_dir is not None and filestore_dir.name == "filestore"

    sql_backup = tmp_path / "plain.sql"
    sql_backup.write_text("SELECT 1;", encoding="utf-8")
    dump_file, filestore_dir = _extract_backup(sql_backup, work_dir, on_line=None)
    assert dump_file == sql_backup
    assert filestore_dir is None

    with pytest.raises(ValueError, match="Backup must be"):
        _extract_backup(tmp_path / "nope.txt", work_dir, on_line=None)


def test_find_dump_nested(tmp_path) -> None:
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    dump_file = nested / "backup.dump"
    dump_file.write_text("data", encoding="utf-8")
    assert _find_dump(tmp_path) == dump_file
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="Zip must contain"):
        _find_dump(empty)


def test_find_filestore_nested(tmp_path) -> None:
    nested = tmp_path / "pack" / "filestore"
    nested.mkdir(parents=True)
    assert _find_filestore(tmp_path) == nested
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _find_filestore(empty) is None


def test_restore_backup(project, tmp_path, isolated_config, monkeypatch) -> None:
    backup = tmp_path / "backup.sql"
    backup.write_text("SELECT 1;", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr("testbed_cli.lifecycle.ensure_exclusive", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.allocate_ports", lambda *args, **kwargs: False)
    monkeypatch.setattr("testbed_cli.lifecycle.compose_down", lambda *args, **kwargs: calls.append("down"))
    monkeypatch.setattr("testbed_cli.lifecycle.compose_up", lambda *args, **kwargs: calls.append("up"))
    monkeypatch.setattr("testbed_cli.lifecycle.wait_for_ready", lambda *args, **kwargs: calls.append("ready"))
    monkeypatch.setattr("testbed_cli.lifecycle.wait_for_db", lambda *args, **kwargs: calls.append("db"))
    monkeypatch.setattr("testbed_cli.lifecycle._tune_postgres", lambda *args, **kwargs: calls.append("tune"))
    monkeypatch.setattr("testbed_cli.lifecycle._recreate_database", lambda *args, **kwargs: calls.append("recreate"))
    monkeypatch.setattr("testbed_cli.lifecycle._load_dump", lambda *args, **kwargs: calls.append("load"))
    monkeypatch.setattr("testbed_cli.lifecycle.neutralize_database", lambda *args, **kwargs: calls.append("neutralise"))
    monkeypatch.setattr("testbed_cli.lifecycle.stream_command", lambda *args, **kwargs: 0)
    restore_backup(project, backup, config=isolated_config, siblings=[], parallel=True)
    assert calls[:4] == ["down", "up", "ready", "db"]
    assert "neutralise" in calls
    with pytest.raises(FileNotFoundError):
        restore_backup(project, tmp_path / "missing.sql", config=isolated_config, siblings=[])


def test_docker_or_raise(monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.dockerctl.docker_available", lambda: (False, "offline"))
    with pytest.raises(RuntimeError, match="offline"):
        _docker_or_raise()
    monkeypatch.setattr("testbed_cli.dockerctl.docker_available", lambda: (True, "ok"))
    assert _docker_or_raise() == (True, "ok")


def test_load_dump_sql_and_custom(project, tmp_path, monkeypatch) -> None:
    sql_file = tmp_path / "dump.sql"
    sql_file.write_text("SELECT 1;", encoding="utf-8")
    dump_file = tmp_path / "dump.dump"
    dump_file.write_text("data", encoding="utf-8")
    seen: list[str] = []
    monkeypatch.setattr("testbed_cli.lifecycle.compose_cp", lambda *args, **kwargs: None)

    def fake_exec(proj, service, command, on_line=None):
        seen.append(command[0])
        return 0

    monkeypatch.setattr("testbed_cli.lifecycle.compose_exec", fake_exec)
    _load_dump(project, sql_file, None)
    _load_dump(project, dump_file, None)
    assert seen == ["psql", "pg_restore"]
    monkeypatch.setattr("testbed_cli.lifecycle.compose_exec", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError, match="Database restore failed"):
        _load_dump(project, sql_file, None)


def test_recreate_database_and_filestore(project, tmp_path, monkeypatch) -> None:
    commands: list[str] = []
    monkeypatch.setattr(
        "testbed_cli.lifecycle.compose_exec",
        lambda proj, service, command, on_line=None: commands.append(command[0]) or 0,
    )
    monkeypatch.setattr("testbed_cli.lifecycle.compose_cp", lambda *args, **kwargs: commands.append("cp"))
    _recreate_database(project, None)
    assert commands.count("psql") == 3
    notes: list[str] = []
    _restore_filestore(project, tmp_path, on_line=notes.append)
    assert any("filestore" in item for item in notes)
    assert "cp" in commands
    monkeypatch.setattr("testbed_cli.lifecycle.compose_exec", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError, match="Could not create database"):
        _recreate_database(project, None)


def test_tune_postgres(project, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("testbed_cli.lifecycle.compose_exec", lambda *args, **kwargs: 0)
    monkeypatch.setattr("testbed_cli.lifecycle.stream_command", lambda command, on_line=None: calls.append("restart"))
    monkeypatch.setattr("testbed_cli.lifecycle.wait_for_db", lambda *args, **kwargs: calls.append("db"))
    _tune_postgres(project, None)
    assert calls == ["restart", "db"]


def test_start_without_init(project, isolated_config, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.lifecycle.prepare_start", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.compose_up", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.wait_for_ready", lambda *args, **kwargs: None)

    def fail_exec(*args, **kwargs):
        raise AssertionError("compose_exec should not run without --init")

    monkeypatch.setattr("testbed_cli.lifecycle.compose_exec", fail_exec)
    start_project(project, isolated_config, [], initialise=False)


def test_prepare_start_checks_exclusive(project, isolated_config, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("testbed_cli.lifecycle._docker_or_raise", lambda: (True, "ok"))
    monkeypatch.setattr("testbed_cli.lifecycle.ensure_exclusive", lambda *args, **kwargs: calls.append("exclusive"))
    monkeypatch.setattr("testbed_cli.lifecycle.pull_odoo_image", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.sync_enterprise", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.copy_requirements", lambda *args, **kwargs: None)
    prepare_start(project, isolated_config, [], parallel=False)
    assert calls == ["exclusive"]


def test_restore_zip_restores_filestore(project, tmp_path, isolated_config, monkeypatch) -> None:
    dump_sql = tmp_path / "dump.sql"
    dump_sql.write_text("SELECT 1;", encoding="utf-8")
    filestore = tmp_path / "filestore"
    filestore.mkdir()
    (filestore / "blob").write_text("x", encoding="utf-8")
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.write(dump_sql, "dump.sql")
        zip_file.write(filestore / "blob", "filestore/blob")
    calls: list[str] = []
    monkeypatch.setattr("testbed_cli.lifecycle.ensure_exclusive", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.allocate_ports", lambda *args, **kwargs: False)
    monkeypatch.setattr("testbed_cli.lifecycle.compose_down", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.compose_up", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.wait_for_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.wait_for_db", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle._tune_postgres", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle._recreate_database", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle._load_dump", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle.neutralize_database", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.lifecycle._restore_filestore", lambda *args, **kwargs: calls.append("filestore"))
    monkeypatch.setattr("testbed_cli.lifecycle.stream_command", lambda *args, **kwargs: 0)
    restore_backup(project, archive, config=isolated_config, siblings=[], parallel=True)
    assert calls == ["filestore"]


def test_extract_dump_file(tmp_path) -> None:
    dump_file = tmp_path / "plain.dump"
    dump_file.write_text("data", encoding="utf-8")
    found, filestore_dir = _extract_backup(dump_file, tmp_path / "work", on_line=None)
    assert found == dump_file
    assert filestore_dir is None


def test_find_dump_direct_sql(tmp_path) -> None:
    dump_sql = tmp_path / "dump.sql"
    dump_sql.write_text("SELECT 1;", encoding="utf-8")
    assert _find_dump(tmp_path) == dump_sql


def test_occupied_ports_skips_current(project, tmp_path) -> None:
    other = load_project(
        write_project(
            tmp_path / "shop",
            database_name="shop",
            http_port=19069,
            test_port=19068,
            debug_port=19888,
        )
    )
    assert other is not None
    occupied = _occupied_ports([project, other], project)
    assert project.http_port not in occupied
    assert other.http_port in occupied
    assert other.debug_port in occupied


def test_use_parallel_prefers_explicit_flag() -> None:
    config = Config(allow_parallel=False)
    assert _use_parallel(config, True) is True
    assert _use_parallel(config, False) is False
    assert _use_parallel(config, None) is False
    assert _use_parallel(Config(allow_parallel=True), None) is True


def test_ensure_exclusive_when_nothing_else_running(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.lifecycle.other_running_projects", lambda *args, **kwargs: [])
    ensure_exclusive(project, Config(allow_parallel=False), [])
