from __future__ import annotations

import socket

from testbed_cli.project import Project


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def next_free_port(start: int, used: set[int], host: str = "127.0.0.1") -> int:
    port = start
    while port in used or port_in_use(port, host):
        port += 1
        if port > 65000:
            raise RuntimeError(f"Could not find a free port starting at {start}")
    return port


def allocate_ports(project: Project, occupied: set[int], our_ports: set[int]) -> bool:
    """Assign host ports. Returns True if the project ports changed."""
    changed = False
    http_port = project.http_port
    test_port = project.test_port
    debug_port = project.debug_port

    def needs_move(port: int) -> bool:
        return port in occupied or (port_in_use(port) and port not in our_ports)

    if needs_move(http_port):
        http_port = next_free_port(http_port, occupied | {test_port, debug_port})
        changed = True
    occupied.add(http_port)

    if needs_move(test_port) or test_port == http_port:
        test_port = next_free_port(test_port, occupied | {http_port, debug_port})
        changed = True
    occupied.add(test_port)

    if needs_move(debug_port) or debug_port in {http_port, test_port}:
        debug_port = next_free_port(debug_port, occupied | {http_port, test_port})
        changed = True
    occupied.add(debug_port)

    if changed:
        project.http_port = http_port
        project.test_port = test_port
        project.debug_port = debug_port
        project.persist_ports()
    elif "HTTP_PORT" not in project.env_values:
        project.persist_ports()
        changed = True
    return changed
