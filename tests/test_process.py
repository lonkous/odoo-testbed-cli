from __future__ import annotations

from pathlib import Path
import sys

from testbed_cli.process import combined_output, run_command, run_interactive, stream_command

from tests.helpers import completed


def test_run_command_captures_stdout() -> None:
    result = run_command([sys.executable, "-c", "print('hello-tb')"])
    assert result.returncode == 0
    assert "hello-tb" in (result.stdout or "")


def test_run_command_sends_stdin() -> None:
    result = run_command(
        [sys.executable, "-c", "import sys; print(sys.stdin.read())"],
        input_text="piped-in",
    )
    assert result.returncode == 0
    assert "piped-in" in (result.stdout or "")


def test_stream_command_calls_on_line(tmp_path: Path) -> None:
    lines: list[str] = []
    code = stream_command(
        [sys.executable, "-c", "print('one'); print('two')"],
        on_line=lines.append,
        cwd=tmp_path,
    )
    assert code == 0
    assert lines == ["one", "two"]


def test_stream_command_prints_without_callback(capfd) -> None:
    code = stream_command([sys.executable, "-c", "print('plain')"])
    assert code == 0
    assert "plain" in capfd.readouterr().out


def test_run_interactive_returns_exit_code() -> None:
    assert run_interactive([sys.executable, "-c", "raise SystemExit(7)"]) == 7


def test_combined_output_joins_streams() -> None:
    assert combined_output(completed(stdout="out", stderr="err")) == "out\nerr"
    assert combined_output(completed(stdout="only")) == "only"
    assert combined_output(completed()) == ""
