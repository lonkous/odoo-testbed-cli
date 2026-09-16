from __future__ import annotations

import json

import pytest

from testbed_cli.dockerctl import (
    ContainerStatus,
    DockerError,
    compose_cmd,
    compose_cp,
    compose_down,
    compose_exec,
    compose_exec_capture,
    fetch_logs,
    compose_network_name,
    compose_ps,
    compose_stop,
    compose_up,
    copy_requirements,
    db_container_name,
    docker_available,
    follow_logs_command,
    other_running_projects,
    pull_odoo_image,
    wait_for_db,
    wait_for_ready,
    web_container_name,
    write_ports_override,
)
from testbed_cli.project import load_project

from tests.helpers import completed, write_project


def test_container_status_labels() -> None:
    assert ContainerStatus(web="running", db="running").label == "up"
    assert ContainerStatus().label == "missing"
    assert ContainerStatus(web="exited", db="running").label == "stopped"
    assert ContainerStatus(web="running", db="missing").label == "partial"
    assert ContainerStatus(web="created", db="created").label == "created"


def test_write_ports_override_and_compose_cmd(project) -> None:
    override = write_ports_override(project)
    text = override.read_text(encoding="utf-8")
    assert f'"{project.http_port}:8069"' in text
    command = compose_cmd(project)
    assert command[:2] == ["docker", "compose"]
    assert str(project.compose_file) in command
    assert str(project.env_path) in command
    assert str(override) in command


def test_compose_ps_parses_json_array(project, monkeypatch) -> None:
    payload = [
        {
            "Service": "web",
            "State": "running",
            "Publishers": [
                {"TargetPort": 8069, "PublishedPort": 18069},
                {"TargetPort": 8068, "PublishedPort": 18068},
                {"TargetPort": 3001, "PublishedPort": 18888},
            ],
        },
        {"Service": "db", "State": "running"},
    ]
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(stdout=json.dumps(payload)),
    )
    status = compose_ps(project)
    assert status.web == "running"
    assert status.db == "running"
    assert status.http_port == 18069
    assert status.debug_port == 18888


def test_compose_ps_parses_ndjson_and_name_fallback(project, monkeypatch) -> None:
    lines = "\n".join(
        [
            json.dumps({"Name": "testbed-demo-web-1", "Status": "Exit 0"}),
            json.dumps({"Name": "testbed-demo-db-1", "State": "stopped"}),
        ]
    )
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(stdout=lines),
    )
    status = compose_ps(project)
    assert status.web == "exited"
    assert status.db == "stopped"


def test_compose_ps_returns_missing_on_failure(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(returncode=1, stderr="no docker"),
    )
    status = compose_ps(project)
    assert status.web == "missing"
    assert status.db == "missing"


def test_other_running_projects(tmp_path, monkeypatch) -> None:
    demo = load_project(write_project(tmp_path / "demo", database_name="demo"))
    shop = load_project(write_project(tmp_path / "shop", database_name="shop"))
    assert demo is not None and shop is not None

    def fake_ps(item):
        if item.database_name == "shop":
            return ContainerStatus(web="running", db="running")
        return ContainerStatus()

    monkeypatch.setattr("testbed_cli.dockerctl.compose_ps", fake_ps)
    running = other_running_projects(demo, [demo, shop])
    assert [item.database_name for item in running] == ["shop"]


def test_docker_available(monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(returncode=0, stdout="ok"),
    )
    available, message = docker_available()
    assert available is True
    assert message == "ok"
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(returncode=1, stderr="Cannot connect\nmore"),
    )
    available, message = docker_available()
    assert available is False
    assert message == "Cannot connect"


def test_fetch_logs_snapshot(project, monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda command, timeout=None: seen.append(command) or completed(stdout="web-1 | hello"),
    )
    text = fetch_logs(project, service="web", tail=50)
    assert text == "web-1 | hello"
    assert "--tail" in seen[0]
    assert "50" in seen[0]
    assert seen[0][-1] == "web"
    logs_index = seen[0].index("logs")
    assert "-f" not in seen[0][logs_index:]


def test_fetch_logs_empty_failure(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(returncode=1),
    )
    with pytest.raises(DockerError, match="docker compose logs failed"):
        fetch_logs(project)


def test_fetch_logs_empty_ok_keeps_error_text_and_clamps(project, monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_run(command, timeout=None):
        seen.append(command)
        if len(seen) == 1:
            return completed(stdout="")
        if len(seen) == 2:
            return completed(returncode=1, stderr="no container")
        return completed(stdout="ok")

    monkeypatch.setattr("testbed_cli.dockerctl.run_command", fake_run)
    assert fetch_logs(project) == "(no logs)"
    assert fetch_logs(project) == "no container"
    fetch_logs(project, tail=0)
    assert seen[2][seen[2].index("--tail") + 1] == "1"
    fetch_logs(project, tail=9000)
    assert seen[3][seen[3].index("--tail") + 1] == "2000"


def test_follow_logs_command_inserts_ansi(project) -> None:
    command = follow_logs_command(project, "web")
    assert command[:4] == ["docker", "compose", "--ansi", "always"]
    assert command[-5:] == ["logs", "-f", "--tail", "200", "web"]
    all_services = follow_logs_command(project)
    assert all_services[-1] == "200"
    assert "web" not in all_services[-5:]


def test_copy_requirements(project) -> None:
    (project.root / "requirements.txt").write_text("lxml\n", encoding="utf-8")
    (project.root / "apt-requirements.txt").write_text("git\n", encoding="utf-8")
    notes: list[str] = []
    copy_requirements(project, on_line=notes.append)
    dest = project.testbed_dir / "docker" / "docker-odoo-test"
    assert (dest / "requirements.txt").read_text(encoding="utf-8") == "lxml\n"
    assert (dest / "apt-requirements.txt").read_text(encoding="utf-8") == "git\n"
    assert len(notes) == 2


def test_container_and_network_names(project) -> None:
    assert web_container_name(project) == "testbed-demo-web-1"
    assert db_container_name(project) == "testbed-demo-db-1"
    assert compose_network_name(project) == "testbed-demo_my_network"


def test_compose_up_stop_down_raise_on_failure(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.dockerctl.stream_command", lambda *args, **kwargs: 1)
    with pytest.raises(DockerError, match="up failed"):
        compose_up(project)
    with pytest.raises(DockerError, match="stop failed"):
        compose_stop(project)
    with pytest.raises(DockerError, match="down failed"):
        compose_down(project, volumes=True)
    with pytest.raises(DockerError, match="cp failed"):
        compose_cp(project, "a", "b")


def test_compose_exec_builds_command(project, monkeypatch) -> None:
    seen: list[list[str]] = []

    def capture(command, on_line=None):
        seen.append(command)
        return 0

    monkeypatch.setattr("testbed_cli.dockerctl.stream_command", capture)
    compose_exec(project, "web", ["odoo", "-d", "demo"], env={"FOO": "bar"})
    assert "-T" in seen[0]
    assert "web" in seen[0]
    assert "-e" in seen[0]
    assert "FOO=bar" in seen[0]


def test_compose_exec_capture(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda command, timeout=None: completed(stdout="ok"),
    )
    result = compose_exec_capture(project, "web", ["true"], env={"A": "1"})
    assert result.stdout == "ok"


def test_wait_for_ready(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(stdout="HTTP service (werkzeug) running"),
    )
    notes: list[str] = []
    wait_for_ready(project, on_line=notes.append, timeout=5)
    assert notes == ["Odoo is ready."]


def test_wait_for_ready_timeout(project, monkeypatch) -> None:
    clock = {"value": 0.0}
    monkeypatch.setattr("testbed_cli.dockerctl.time.time", lambda: clock["value"])
    monkeypatch.setattr("testbed_cli.dockerctl.time.sleep", lambda seconds: clock.__setitem__("value", clock["value"] + seconds))
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(stdout="starting"),
    )
    with pytest.raises(DockerError, match="Timed out waiting for Odoo"):
        wait_for_ready(project, timeout=1)


def test_wait_for_db(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(returncode=0),
    )
    wait_for_db(project, timeout=2)


def test_wait_for_db_timeout(project, monkeypatch) -> None:
    clock = {"value": 0.0}
    monkeypatch.setattr("testbed_cli.dockerctl.time.time", lambda: clock["value"])
    monkeypatch.setattr("testbed_cli.dockerctl.time.sleep", lambda seconds: clock.__setitem__("value", clock["value"] + seconds))
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(returncode=1),
    )
    with pytest.raises(DockerError, match="Timed out waiting for Postgres"):
        wait_for_db(project, timeout=1)


def test_pull_odoo_image(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.dockerctl.stream_command", lambda *args, **kwargs: 0)
    notes: list[str] = []
    pull_odoo_image(project, on_line=notes.append)
    assert notes[0] == "Pulling odoo:18.0"
    monkeypatch.setattr("testbed_cli.dockerctl.stream_command", lambda *args, **kwargs: 1)
    with pytest.raises(DockerError, match="Failed to pull"):
        pull_odoo_image(project)


def test_compose_ps_empty_and_unpublished(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(stdout=""),
    )
    status = compose_ps(project)
    assert status.web == "missing"
    payload = [
        {
            "Service": "web",
            "State": "running",
            "Publishers": [{"TargetPort": 8069, "PublishedPort": 0}],
        }
    ]
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(stdout=json.dumps(payload)),
    )
    status = compose_ps(project)
    assert status.web == "running"
    assert status.http_port is None


def test_compose_up_success(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.dockerctl.stream_command", lambda *args, **kwargs: 0)
    compose_up(project)
    compose_stop(project)
    compose_down(project)
    compose_cp(project, "a", "b")


def test_compose_exec_tty_skips_t_flag(project, monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr("testbed_cli.dockerctl.stream_command", lambda command, on_line=None: seen.append(command) or 0)
    compose_exec(project, "web", ["bash"], tty=True)
    assert "-T" not in seen[0]


def test_copy_requirements_without_files(project) -> None:
    notes: list[str] = []
    copy_requirements(project, on_line=notes.append)
    assert notes == []


def test_wait_for_ready_longpolling(project, monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(stdout="Evented Service (longpolling) running"),
    )
    wait_for_ready(project, timeout=2)


def test_wait_for_ready_waiting_notes(project, monkeypatch) -> None:
    clock = {"value": 0.0}
    monkeypatch.setattr("testbed_cli.dockerctl.time.time", lambda: clock["value"])
    monkeypatch.setattr(
        "testbed_cli.dockerctl.time.sleep",
        lambda seconds: clock.__setitem__("value", clock["value"] + seconds),
    )

    def fake_run(*args, **kwargs):
        if clock["value"] < 6:
            return completed(stdout="starting")
        return completed(stdout="HTTP service (werkzeug) running")

    monkeypatch.setattr("testbed_cli.dockerctl.run_command", fake_run)
    notes: list[str] = []
    wait_for_ready(project, on_line=notes.append, timeout=20)
    assert "Waiting for Odoo HTTP/longpolling to come up..." in notes
    assert notes[-1] == "Odoo is ready."


def test_compose_down_includes_volumes(project, monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(
        "testbed_cli.dockerctl.stream_command",
        lambda command, on_line=None: seen.append(command) or 0,
    )
    compose_down(project, volumes=True)
    assert "--volumes" in seen[0]


def test_docker_available_blank_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "testbed_cli.dockerctl.run_command",
        lambda *args, **kwargs: completed(returncode=1, stdout="", stderr=""),
    )
    available, message = docker_available()
    assert available is False
    assert message == "Docker is not available"
