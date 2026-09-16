from __future__ import annotations

import socket

from testbed_cli.ports import allocate_ports, next_free_port, port_in_use
from testbed_cli.project import parse_env_file


def test_port_in_use_detects_bound_socket() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        assert port_in_use(port) is True
    finally:
        listener.close()


def test_next_free_port_skips_occupied() -> None:
    free = next_free_port(40000, {40000, 40001})
    assert free >= 40002


def test_allocate_ports_moves_when_occupied(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.ports.port_in_use", lambda port, host="127.0.0.1": False)
    changed = allocate_ports(project, occupied={project.http_port}, our_ports=set())
    assert changed is True
    assert project.http_port != 18069
    values = parse_env_file(project.env_path)
    assert values["HTTP_PORT"] == str(project.http_port)


def test_allocate_ports_persists_when_env_missing_ports(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.ports.port_in_use", lambda port, host="127.0.0.1": False)
    project.env_values.pop("HTTP_PORT", None)
    changed = allocate_ports(project, occupied=set(), our_ports={project.http_port, project.test_port, project.debug_port})
    assert changed is True
    values = parse_env_file(project.env_path)
    assert "HTTP_PORT" in values


def test_next_free_port_exhausted(monkeypatch) -> None:
    import pytest

    monkeypatch.setattr("testbed_cli.ports.port_in_use", lambda port, host="127.0.0.1": True)
    with pytest.raises(RuntimeError, match="Could not find a free port"):
        next_free_port(65000, set())


def test_allocate_ports_moves_colliding_test_port(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.ports.port_in_use", lambda port, host="127.0.0.1": False)
    project.test_port = project.http_port
    changed = allocate_ports(project, occupied=set(), our_ports={project.http_port, project.debug_port})
    assert changed is True
    assert project.test_port != project.http_port


def test_allocate_ports_moves_colliding_debug_port(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.ports.port_in_use", lambda port, host="127.0.0.1": False)
    project.debug_port = project.http_port
    changed = allocate_ports(
        project,
        occupied=set(),
        our_ports={project.http_port, project.test_port},
    )
    assert changed is True
    assert project.debug_port not in {project.http_port, project.test_port}


def test_allocate_ports_unchanged_when_free(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.ports.port_in_use", lambda port, host="127.0.0.1": False)
    original = (project.http_port, project.test_port, project.debug_port)
    changed = allocate_ports(
        project,
        occupied=set(),
        our_ports={project.http_port, project.test_port, project.debug_port},
    )
    assert changed is False
    assert (project.http_port, project.test_port, project.debug_port) == original
