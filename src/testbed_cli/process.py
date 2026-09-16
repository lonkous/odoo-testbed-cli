from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess

LogFn = Callable[[str], None]


def run_command(
    command: list[str],
    cwd: Path | None = None,
    timeout: float | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        input=input_text,
    )


def stream_command(
    command: list[str],
    on_line: LogFn | None = None,
    cwd: Path | None = None,
) -> int:
    if on_line is None:
        return subprocess.call(command, cwd=cwd)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if process.stdout is None:
        return process.wait()
    for line in process.stdout:
        on_line(line.rstrip("\n"))
    return process.wait()


def run_interactive(command: list[str], cwd: Path | None = None) -> int:
    return subprocess.call(command, cwd=cwd)


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    parts = [result.stdout or "", result.stderr or ""]
    return "\n".join(part for part in parts if part).strip()
