from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess
import json
import re
import tempfile
import time

from testbed_cli.process import LogFn, combined_output, run_command, stream_command
from testbed_cli.project import Project

READY_PATTERN = re.compile(
    r"HTTP service \(werkzeug\) running|Evented Service \(longpolling\) running"
)


@dataclass
class ContainerStatus:
    web: str = "missing"
    db: str = "missing"
    http_port: int | None = None
    test_port: int | None = None
    debug_port: int | None = None

    @property
    def label(self) -> str:
        if self.web == "running" and self.db == "running":
            return "up"
        if self.web == "missing" and self.db == "missing":
            return "missing"
        if self.web == "exited" or self.db == "exited" or self.web == "stopped" or self.db == "stopped":
            return "stopped"
        if self.web == "running" or self.db == "running":
            return "partial"
        return self.web or "unknown"


class DockerError(RuntimeError):
    pass


def docker_available() -> tuple[bool, str]:
    result = run_command(["docker", "info"], timeout=8)
    if result.returncode != 0:
        message = combined_output(result) or "Docker is not available"
        return False, message.splitlines()[0] if message else "Docker is not available"
    return True, "ok"


def write_ports_override(project: Project) -> Path:
    override_dir = Path(tempfile.gettempdir()) / "testbed-cli" / project.database_name
    override_dir.mkdir(parents=True, exist_ok=True)
    override_path = override_dir / "ports.override.yml"
    override_path.write_text(
        "services:\n"
        "  web:\n"
        "    ports: !override\n"
        f'      - "{project.http_port}:8069"\n'
        f'      - "{project.test_port}:8068"\n'
        f'      - "{project.debug_port}:3001"\n',
        encoding="utf-8",
    )
    return override_path


def compose_cmd(project: Project, compose_file: Path | None = None) -> list[str]:
    override_path = write_ports_override(project)
    chosen = compose_file or project.compose_file
    return [
        "docker",
        "compose",
        "-f",
        str(chosen),
        "-f",
        str(override_path),
        "--env-file",
        str(project.env_path),
    ]


def compose_stream_cmd(project: Project, compose_file: Path | None = None) -> list[str]:
    command = compose_cmd(project, compose_file)
    return command[:2] + ["--ansi", "always"] + command[2:]


def compose_ps(project: Project) -> ContainerStatus:
    status = ContainerStatus()
    result = run_command(compose_cmd(project) + ["ps", "--format", "json"], timeout=12)
    if result.returncode != 0:
        return status
    output = (result.stdout or "").strip()
    if not output:
        return status
    items: list[dict]
    if output.startswith("["):
        items = json.loads(output)
    else:
        items = [json.loads(line) for line in output.splitlines() if line.strip()]
    for item in items:
        service = str(item.get("Service") or item.get("Name") or "")
        state = str(item.get("State") or item.get("Status") or "unknown").lower()
        if "running" in state:
            normalised = "running"
        elif "exit" in state:
            normalised = "exited"
        elif "stop" in state:
            normalised = "stopped"
        else:
            normalised = state
        if service.endswith("web") or service == "web" or "-web-" in service:
            status.web = normalised
            for publisher in item.get("Publishers") or []:
                target = int(publisher.get("TargetPort") or 0)
                published = int(publisher.get("PublishedPort") or 0)
                if not published:
                    continue
                if target == 8069:
                    status.http_port = published
                elif target == 8068:
                    status.test_port = published
                elif target == 3001:
                    status.debug_port = published
        elif service.endswith("db") or service == "db" or "-db-" in service:
            status.db = normalised
    return status


def other_running_projects(project: Project, siblings: list[Project]) -> list[Project]:
    running: list[Project] = []
    for sibling in siblings:
        if sibling.database_name == project.database_name:
            continue
        status = compose_ps(sibling)
        if status.label in {"up", "partial"}:
            running.append(sibling)
    return running


def compose_up(project: Project, on_line: LogFn | None = None, compose_file: Path | None = None) -> None:
    command = compose_stream_cmd(project, compose_file) + ["up", "--build", "-d"]
    code = stream_command(command)
    if code != 0:
        raise DockerError("docker compose up failed")


def compose_stop(project: Project, on_line: LogFn | None = None) -> None:
    code = stream_command(compose_stream_cmd(project) + ["stop", "-t", "2"])
    if code != 0:
        raise DockerError("docker compose stop failed")


def compose_down(project: Project, on_line: LogFn | None = None, volumes: bool = False) -> None:
    command = compose_stream_cmd(project) + ["down"]
    if volumes:
        command.append("--volumes")
    code = stream_command(command)
    if code != 0:
        raise DockerError("docker compose down failed")


def compose_exec(
    project: Project,
    service: str,
    command: list[str],
    on_line: LogFn | None = None,
    tty: bool = False,
    env: dict[str, str] | None = None,
    compose_file: Path | None = None,
) -> int:
    full = compose_stream_cmd(project, compose_file) + ["exec"]
    if not tty:
        full.append("-T")
    merged_env = {"TERM": "xterm-256color", "FORCE_COLOR": "1", "PY_COLORS": "1"}
    if env:
        merged_env.update(env)
    for key, value in merged_env.items():
        full.extend(["-e", f"{key}={value}"])
    full.append(service)
    full.extend(command)
    return stream_command(full, on_line=on_line)


def compose_exec_capture(
    project: Project,
    service: str,
    command: list[str],
    compose_file: Path | None = None,
    env: dict[str, str] | None = None,
) -> CompletedProcess[str]:
    full = compose_cmd(project, compose_file) + ["exec", "-T"]
    if env:
        for key, value in env.items():
            full.extend(["-e", f"{key}={value}"])
    full.append(service)
    full.extend(command)
    return run_command(full, timeout=None)


def compose_cp(
    project: Project,
    source: str,
    destination: str,
    on_line: LogFn | None = None,
    compose_file: Path | None = None,
) -> None:
    code = stream_command(
        compose_stream_cmd(project, compose_file) + ["cp", source, destination],
    )
    if code != 0:
        raise DockerError(f"docker compose cp failed: {source} -> {destination}")


def wait_for_ready(
    project: Project,
    on_line: LogFn | None = None,
    timeout: int = 180,
    compose_file: Path | None = None,
) -> None:
    deadline = time.time() + timeout
    last_note = 0.0
    while time.time() < deadline:
        result = run_command(compose_cmd(project, compose_file) + ["logs", "web"], timeout=20)
        logs = combined_output(result)
        if READY_PATTERN.search(logs):
            if on_line:
                on_line("Odoo is ready.")
            return
        now = time.time()
        if on_line and now - last_note >= 5:
            on_line("Waiting for Odoo HTTP/longpolling to come up...")
            last_note = now
        time.sleep(1)
    raise DockerError(f"Timed out waiting for Odoo after {timeout}s")


def wait_for_db(project: Project, timeout: int = 60, compose_file: Path | None = None) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = run_command(
            compose_cmd(project, compose_file) + ["exec", "-T", "db", "pg_isready", "-U", "odoo"],
            timeout=10,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise DockerError("Timed out waiting for Postgres")


def follow_logs_command(project: Project, service: str | None = None) -> list[str]:
    command = compose_stream_cmd(project) + ["logs", "-f", "--tail", "200"]
    if service:
        command.append(service)
    return command


def fetch_logs(project: Project, service: str | None = None, tail: int = 200) -> str:
    lines = max(1, min(int(tail), 2000))
    command = compose_cmd(project) + ["logs", "--tail", str(lines)]
    if service:
        command.append(service)
    result = run_command(command, timeout=30)
    text = combined_output(result)
    if result.returncode != 0 and not text:
        raise DockerError("docker compose logs failed")
    return text or "(no logs)"


def copy_requirements(project: Project, on_line: LogFn | None = None) -> None:
    dest_dir = project.testbed_dir / "docker" / "docker-odoo-test"
    dest_dir.mkdir(parents=True, exist_ok=True)
    requirements = project.root / "requirements.txt"
    if requirements.exists():
        target = dest_dir / "requirements.txt"
        target.write_text(requirements.read_text(encoding="utf-8"), encoding="utf-8")
        if on_line:
            on_line(f"Copied {requirements} -> {target}")
    apt_requirements = project.root / "apt-requirements.txt"
    if apt_requirements.exists():
        target = dest_dir / "apt-requirements.txt"
        target.write_text(apt_requirements.read_text(encoding="utf-8"), encoding="utf-8")
        if on_line:
            on_line(f"Copied {apt_requirements} -> {target}")


def pull_odoo_image(project: Project, on_line: LogFn | None = None) -> None:
    tag = f"odoo:{project.odoo_version}.0"
    if on_line:
        on_line(f"Pulling {tag}")
    code = stream_command(["docker", "image", "pull", tag])
    if code != 0:
        raise DockerError(f"Failed to pull {tag}")


def web_container_name(project: Project) -> str:
    return f"{project.compose_project}-web-1"


def db_container_name(project: Project) -> str:
    return f"{project.compose_project}-db-1"


def compose_network_name(project: Project) -> str:
    return f"{project.compose_project}_my_network"
