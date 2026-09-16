from __future__ import annotations

import re

from testbed_cli.config import load_config
from testbed_cli.discovery import discover_projects
from testbed_cli.dockerctl import (
    compose_cmd,
    compose_exec,
    compose_exec_capture,
    compose_up,
    wait_for_db,
    wait_for_ready,
)
from testbed_cli.lifecycle import allocate_if_parallel, ensure_exclusive
from testbed_cli.process import LogFn, stream_command
from testbed_cli.project import Project

ODOO_ADDONS_PATH = "/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons,/mnt/enterprise"


def run_tests(
    project: Project,
    modules: str | None = None,
    keyword: str | None = None,
    reinit_db: bool = False,
    on_line: LogFn | None = None,
    parallel: bool | None = None,
) -> str:
    chosen = (modules or project.modules_to_test).strip()
    if not chosen:
        raise ValueError("No modules to test. Set MODULES_TO_TEST or pass module names.")
    config = load_config()
    siblings = discover_projects(config)
    ensure_exclusive(project, config, siblings, parallel=parallel, on_line=on_line)
    allocate_if_parallel(project, config, siblings, on_line=on_line, parallel=parallel)
    compose_up(project, on_line=on_line, compose_file=project.compose_test_file)
    wait_for_ready(project, on_line=on_line, compose_file=project.compose_test_file)
    wait_for_db(project, compose_file=project.compose_test_file)
    custom_modules, standard_modules = _categorise_modules(project, chosen, on_line)
    if not custom_modules and not standard_modules:
        raise RuntimeError(f"No test directories found for modules: {chosen}")
    if reinit_db:
        _reinit_test_db(project, on_line)
    if reinit_db or not _modules_installed(project, chosen):
        if on_line:
            on_line(f"Installing modules: {chosen}")
        _odoo_install(project, chosen, install=True, on_line=on_line)
    else:
        if on_line:
            on_line(f"Updating modules: {chosen}")
        _odoo_install(project, chosen, install=False, on_line=on_line)

    summary_parts: list[str] = []
    total_tests = 0
    total_passed = 0
    total_failed = 0

    if custom_modules:
        passed, failed, errors, total, message = _run_custom_pytest(
            project, custom_modules, keyword, on_line
        )
        summary_parts.append(message)
        total_tests += total
        total_passed += passed
        total_failed += failed + errors
        _copy_coverage(project, on_line)

    if standard_modules:
        for module_name in standard_modules:
            passed, failed, errors, total, message = _run_standard_tests(
                project, module_name, on_line
            )
            summary_parts.append(message)
            total_tests += total
            total_passed += passed
            total_failed += failed + errors

    header = [
        "",
        "==========================================",
        "           TEST EXECUTION SUMMARY",
        "==========================================",
        "",
        *summary_parts,
        "",
        "OVERALL RESULTS:",
        f"   Total tests: {total_tests}",
        f"   Passed: {total_passed}",
        f"   Failed: {total_failed}",
        "   Status: ALL TESTS PASSED" if total_failed == 0 else "   Status: SOME TESTS FAILED",
        "",
        "Coverage HTML (if generated) is copied to htmlcov/ in the project root.",
        "==========================================",
    ]
    summary = "\n".join(header)
    if on_line:
        for line in header:
            on_line(line)
    if total_failed:
        raise RuntimeError("SOME TESTS FAILED")
    return summary


def _categorise_modules(
    project: Project, modules: str, on_line: LogFn | None
) -> tuple[list[str], list[str]]:
    custom_modules: list[str] = []
    standard_modules: list[str] = []
    for module_name in [name.strip() for name in modules.split(",") if name.strip()]:
        if _dir_exists(project, f"/mnt/extra-addons/{module_name}"):
            custom_modules.append(module_name)
            if on_line:
                on_line(f"Found custom module: {module_name}")
        elif _dir_exists(project, f"/usr/lib/python3/dist-packages/odoo/addons/{module_name}"):
            standard_modules.append(module_name)
            if on_line:
                on_line(f"Found standard module: {module_name}")
        elif _dir_exists(project, f"/mnt/enterprise/{module_name}"):
            standard_modules.append(module_name)
            if on_line:
                on_line(f"Found enterprise module: {module_name}")
        elif on_line:
            on_line(f"Warning: no tests directory found for '{module_name}'")
    return custom_modules, standard_modules


def _dir_exists(project: Project, path: str) -> bool:
    result = compose_exec_capture(
        project, "web", ["test", "-d", path], compose_file=project.compose_test_file
    )
    return result.returncode == 0


def _reinit_test_db(project: Project, on_line: LogFn | None) -> None:
    if on_line:
        on_line("Reinit: dropping test database")
    for sql in (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'test' AND pid <> pg_backend_pid();",
        "DROP DATABASE IF EXISTS test;",
        "CREATE DATABASE test OWNER odoo;",
    ):
        compose_exec(
            project,
            "db",
            ["psql", "-U", "odoo", "-d", "postgres", "-c", sql],
            on_line=on_line,
            compose_file=project.compose_test_file,
        )


def _modules_installed(project: Project, modules: str) -> bool:
    names = [name.strip() for name in modules.split(",") if name.strip()]
    if not names:
        return False
    quoted = ",".join(f"'{name}'" for name in names)
    result = compose_exec_capture(
        project,
        "db",
        [
            "psql",
            "-U",
            "odoo",
            "-d",
            "test",
            "-t",
            "-c",
            f"SELECT name FROM ir_module_module WHERE state='installed' AND name IN ({quoted});",
        ],
        compose_file=project.compose_test_file,
    )
    installed = [
        line.strip()
        for line in (result.stdout or "").splitlines()
        if line.strip()
    ]
    return len(installed) == len(names)


def _odoo_install(project: Project, modules: str, install: bool, on_line: LogFn | None) -> None:
    flag = "-i" if install else "-u"
    code = compose_exec(
        project,
        "web",
        [
            "odoo",
            "-d",
            "test",
            "-c",
            "/etc/odoo/odoo-pytest.conf",
            f"--addons-path={ODOO_ADDONS_PATH}",
            flag,
            modules,
            "--stop-after-init",
        ],
        on_line=on_line,
        compose_file=project.compose_test_file,
        env={"MODULES_TO_TEST": modules},
    )
    if code != 0:
        raise RuntimeError("Odoo module install/update for tests failed")


def _run_custom_pytest(
    project: Project,
    modules: list[str],
    keyword: str | None,
    on_line: LogFn | None,
) -> tuple[int, int, int, int, str]:
    locations = [f"/mnt/extra-addons/{name}/tests/" for name in modules]
    args = [
        "pytest",
        "--color=yes",
        "--cov=/mnt/extra-addons",
        "--cov-report=html",
        "-s",
        "--odoo-database=test",
        "--odoo-log-level=info",
        "--odoo-http",
        "--odoo-config=/etc/odoo/odoo-pytest.conf",
    ]
    if keyword:
        args.extend(["-k", keyword])
        if on_line:
            on_line(f"Filtering tests with -k: {keyword}")
    args.extend(locations)
    output_lines: list[str] = []

    def capture(line: str) -> None:
        output_lines.append(line)
        if on_line:
            on_line(line)

    code = compose_exec(
        project,
        "web",
        args,
        on_line=capture,
        compose_file=project.compose_test_file,
        env={
            "MODULES_TO_TEST": ",".join(modules),
            "PYTHONPATH": "/usr/lib/python3/dist-packages",
        },
    )
    text = "\n".join(output_lines)
    passed = _last_count(text, r"(\d+) passed")
    failed = _last_count(text, r"(\d+) failed")
    errors = _last_count(text, r"(\d+) error")
    collected = _last_count(text, r"(\d+) collected")
    total = passed + failed + errors if (passed or failed or errors) else collected
    passed, failed, errors, total = _include_exec_failure(code, passed, failed, errors, total)
    label = ",".join(modules)
    message = f"Custom modules ({label}): {passed} passed, {failed} failed, {errors} errors (total: {total})"
    return passed, failed, errors, total, message


def _run_standard_tests(
    project: Project, module_name: str, on_line: LogFn | None
) -> tuple[int, int, int, int, str]:
    if on_line:
        on_line(f"Testing standard module: {module_name}")
    output_lines: list[str] = []

    def capture(line: str) -> None:
        output_lines.append(line)
        if on_line:
            on_line(line)

    code = compose_exec(
        project,
        "web",
        [
            "odoo",
            "-d",
            "test",
            "-c",
            "/etc/odoo/odoo-pytest.conf",
            f"--test-tags={module_name}",
            "--stop-after-init",
        ],
        on_line=capture,
        compose_file=project.compose_test_file,
        env={"MODULES_TO_TEST": module_name},
    )
    text = "\n".join(output_lines)
    match = re.search(r"(\d+) failed, (\d+) error\(s\) of (\d+) tests", text)
    if match:
        failed = int(match.group(1))
        errors = int(match.group(2))
        total = int(match.group(3))
        passed = total - failed - errors
    else:
        passed = _last_count(text, r"(\d+) passed")
        failed = _last_count(text, r"(\d+) failed")
        errors = _last_count(text, r"(\d+) error")
        total = passed + failed + errors
    passed, failed, errors, total = _include_exec_failure(code, passed, failed, errors, total)
    message = (
        f"Standard module {module_name}: {passed} passed, {failed} failed, "
        f"{errors} errors (total: {total})"
    )
    return passed, failed, errors, total, message


def _copy_coverage(project: Project, on_line: LogFn | None) -> None:
    dest = project.root / "htmlcov"
    result = stream_command(
        compose_cmd(project, project.compose_test_file) + ["cp", "web:/usr/src/htmlcov", str(dest)],
        on_line=on_line,
    )
    if result == 0 and on_line:
        on_line(f"Coverage HTML copied to {dest}")


def _last_count(text: str, pattern: str) -> int:
    matches = re.findall(pattern, text)
    if not matches:
        return 0
    return int(matches[-1])


def _include_exec_failure(
    code: int, passed: int, failed: int, errors: int, total: int
) -> tuple[int, int, int, int]:
    if code == 0 or failed or errors:
        return passed, failed, errors, total
    errors = 1
    if total == 0:
        total = 1
    return passed, failed, errors, total
