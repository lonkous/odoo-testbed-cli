from __future__ import annotations

import pytest

from testbed_cli.tests_run import (
    _categorise_modules,
    _copy_coverage,
    _dir_exists,
    _last_count,
    _modules_installed,
    _odoo_install,
    _reinit_test_db,
    _run_custom_pytest,
    _run_standard_tests,
    run_tests,
)

from tests.helpers import completed


def test_last_count() -> None:
    assert _last_count("1 passed\n5 passed", r"(\d+) passed") == 5
    assert _last_count("nothing", r"(\d+) passed") == 0


def test_run_tests_requires_modules(project) -> None:
    project.modules_to_test = ""
    with pytest.raises(ValueError, match="No modules to test"):
        run_tests(project)


def test_run_tests_summary(project, isolated_config, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.tests_run.load_config", lambda: isolated_config)
    monkeypatch.setattr("testbed_cli.tests_run.discover_projects", lambda config: [])
    monkeypatch.setattr("testbed_cli.tests_run.ensure_exclusive", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.tests_run.compose_up", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.tests_run.wait_for_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.tests_run.wait_for_db", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "testbed_cli.tests_run._categorise_modules",
        lambda proj, modules, on_line: (["sale_custom"], ["base"]),
    )
    monkeypatch.setattr("testbed_cli.tests_run._modules_installed", lambda *args, **kwargs: True)
    monkeypatch.setattr("testbed_cli.tests_run._odoo_install", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "testbed_cli.tests_run._run_custom_pytest",
        lambda *args, **kwargs: (2, 0, 0, 2, "custom ok"),
    )
    monkeypatch.setattr("testbed_cli.tests_run._copy_coverage", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "testbed_cli.tests_run._run_standard_tests",
        lambda *args, **kwargs: (1, 1, 0, 2, "standard mixed"),
    )
    notes: list[str] = []
    with pytest.raises(RuntimeError, match="SOME TESTS FAILED"):
        run_tests(project, on_line=notes.append)
    assert any("Total tests: 4" in item for item in notes)
    assert notes[-1].startswith("==")


def test_run_tests_no_directories(project, isolated_config, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.tests_run.load_config", lambda: isolated_config)
    monkeypatch.setattr("testbed_cli.tests_run.discover_projects", lambda config: [])
    monkeypatch.setattr("testbed_cli.tests_run.ensure_exclusive", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.tests_run.compose_up", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.tests_run.wait_for_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.tests_run.wait_for_db", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.tests_run._categorise_modules", lambda *args, **kwargs: ([], []))
    with pytest.raises(RuntimeError, match="No test directories found"):
        run_tests(project, modules="missing")


def test_categorise_modules(project, monkeypatch) -> None:
    def exists(proj, path: str) -> bool:
        return path.endswith("/sale_custom") or path.endswith("/odoo/addons/base") or path.endswith("/enterprise/account")

    monkeypatch.setattr("testbed_cli.tests_run._dir_exists", exists)
    notes: list[str] = []
    custom_modules, standard_modules = _categorise_modules(
        project, "sale_custom,base,account,ghost", on_line=notes.append
    )
    assert custom_modules == ["sale_custom"]
    assert standard_modules == ["base", "account"]
    assert any("ghost" in item for item in notes)


def test_modules_installed(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.tests_run.compose_exec_capture",
        lambda *args, **kwargs: completed(stdout=" base \n sale \n"),
    )
    assert _modules_installed(project, "base,sale") is True
    assert _modules_installed(project, "base,sale,extra") is False
    assert _modules_installed(project, "") is False
    monkeypatch.setattr(
        "testbed_cli.tests_run.compose_exec_capture",
        lambda *args, **kwargs: completed(returncode=1, stdout=" base \n"),
    )
    assert _modules_installed(project, "base") is False


def test_odoo_install_failure(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.tests_run.compose_exec", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError, match="install/update for tests failed"):
        _odoo_install(project, "base", install=True, on_line=None)


def test_reinit_test_db(project, monkeypatch) -> None:
    sqls: list[str] = []

    def fake_exec(proj, service, command, on_line=None, compose_file=None):
        sqls.append(command[-1])
        return 0

    monkeypatch.setattr("testbed_cli.tests_run.compose_exec", fake_exec)
    notes: list[str] = []
    _reinit_test_db(project, on_line=notes.append)
    assert any("DROP DATABASE" in item for item in sqls)
    assert notes[0].startswith("Reinit")


def test_run_custom_pytest_parses_output(project, monkeypatch) -> None:
    def fake_exec(proj, service, command, on_line=None, compose_file=None, env=None):
        on_line("5 collected")
        on_line("3 passed, 1 failed, 1 error")
        return 0

    monkeypatch.setattr("testbed_cli.tests_run.compose_exec", fake_exec)
    passed, failed, errors, total, message = _run_custom_pytest(project, ["sale_custom"], "login", on_line=None)
    assert (passed, failed, errors, total) == (3, 1, 1, 5)
    assert "sale_custom" in message


def test_run_standard_tests_odoo_format(project, monkeypatch) -> None:
    def fake_exec(proj, service, command, on_line=None, compose_file=None, env=None):
        on_line("2 failed, 1 error(s) of 10 tests")
        return 0

    monkeypatch.setattr("testbed_cli.tests_run.compose_exec", fake_exec)
    passed, failed, errors, total, message = _run_standard_tests(project, "base", on_line=None)
    assert (passed, failed, errors, total) == (7, 2, 1, 10)
    assert "base" in message


def test_copy_coverage(project, monkeypatch) -> None:
    notes: list[str] = []
    monkeypatch.setattr("testbed_cli.tests_run.stream_command", lambda *args, **kwargs: 0)
    _copy_coverage(project, notes.append)
    assert notes[0].startswith("Coverage HTML copied")
    monkeypatch.setattr("testbed_cli.tests_run.stream_command", lambda *args, **kwargs: 1)
    notes.clear()
    _copy_coverage(project, notes.append)
    assert notes == []


def test_run_tests_all_passed_reinit(project, isolated_config, monkeypatch) -> None:
    reinit = {"called": False}
    monkeypatch.setattr("testbed_cli.tests_run.load_config", lambda: isolated_config)
    monkeypatch.setattr("testbed_cli.tests_run.discover_projects", lambda config: [])
    monkeypatch.setattr("testbed_cli.tests_run.ensure_exclusive", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.tests_run.compose_up", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.tests_run.wait_for_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.tests_run.wait_for_db", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "testbed_cli.tests_run._categorise_modules",
        lambda proj, modules, on_line: (["sale_custom"], []),
    )
    monkeypatch.setattr("testbed_cli.tests_run._modules_installed", lambda *args, **kwargs: False)
    monkeypatch.setattr("testbed_cli.tests_run._reinit_test_db", lambda *args, **kwargs: reinit.__setitem__("called", True))
    monkeypatch.setattr("testbed_cli.tests_run._odoo_install", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "testbed_cli.tests_run._run_custom_pytest",
        lambda *args, **kwargs: (3, 0, 0, 3, "custom ok"),
    )
    monkeypatch.setattr("testbed_cli.tests_run._copy_coverage", lambda *args, **kwargs: None)
    summary = run_tests(project, reinit_db=True)
    assert reinit["called"] is True
    assert "ALL TESTS PASSED" in summary
    assert "Total tests: 3" in summary


def test_dir_exists(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.tests_run.compose_exec_capture",
        lambda *args, **kwargs: completed(returncode=0),
    )
    assert _dir_exists(project, "/mnt/extra-addons/sale_custom") is True
    monkeypatch.setattr(
        "testbed_cli.tests_run.compose_exec_capture",
        lambda *args, **kwargs: completed(returncode=1),
    )
    assert _dir_exists(project, "/missing") is False


def test_run_custom_pytest_collected_only(project, monkeypatch) -> None:
    def fake_exec(proj, service, command, on_line=None, compose_file=None, env=None):
        on_line("4 collected")
        return 0

    monkeypatch.setattr("testbed_cli.tests_run.compose_exec", fake_exec)
    passed, failed, errors, total, message = _run_custom_pytest(project, ["sale_custom"], None, on_line=None)
    assert (passed, failed, errors, total) == (0, 0, 0, 4)
    assert "sale_custom" in message


def test_run_standard_tests_pytest_format(project, monkeypatch) -> None:
    def fake_exec(proj, service, command, on_line=None, compose_file=None, env=None):
        on_line("2 passed, 1 failed")
        return 0

    monkeypatch.setattr("testbed_cli.tests_run.compose_exec", fake_exec)
    passed, failed, errors, total, message = _run_standard_tests(project, "base", on_line=None)
    assert (passed, failed, errors, total) == (2, 1, 0, 3)
    assert "base" in message


def test_run_tests_updates_when_already_installed(project, isolated_config, monkeypatch) -> None:
    installs: list[tuple[str, bool]] = []
    monkeypatch.setattr("testbed_cli.tests_run.load_config", lambda: isolated_config)
    monkeypatch.setattr("testbed_cli.tests_run.discover_projects", lambda config: [])
    monkeypatch.setattr("testbed_cli.tests_run.ensure_exclusive", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.tests_run.compose_up", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.tests_run.wait_for_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.tests_run.wait_for_db", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "testbed_cli.tests_run._categorise_modules",
        lambda proj, modules, on_line: (["sale_custom"], []),
    )
    monkeypatch.setattr("testbed_cli.tests_run._modules_installed", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        "testbed_cli.tests_run._odoo_install",
        lambda proj, modules, install, on_line: installs.append((modules, install)),
    )
    monkeypatch.setattr(
        "testbed_cli.tests_run._run_custom_pytest",
        lambda *args, **kwargs: (1, 0, 0, 1, "custom ok"),
    )
    monkeypatch.setattr("testbed_cli.tests_run._copy_coverage", lambda *args, **kwargs: None)
    project.modules_to_test = "sale_custom,base"
    run_tests(project, modules="sale_custom", reinit_db=False)
    assert installs == [("sale_custom,base", False)]


def test_odoo_install_uses_install_flag(project, monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(
        "testbed_cli.tests_run.compose_exec",
        lambda proj, service, command, on_line=None, compose_file=None, env=None: seen.append(command) or 0,
    )
    _odoo_install(project, "base", install=True, on_line=None)
    _odoo_install(project, "base", install=False, on_line=None)
    assert "-i" in seen[0]
    assert "-u" in seen[1]
