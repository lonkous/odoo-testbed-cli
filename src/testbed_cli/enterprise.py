from __future__ import annotations

from pathlib import Path

from testbed_cli.process import LogFn, stream_command


def sync_enterprise(odoo_root: Path, odoo_version: str, on_line: LogFn | None = None) -> None:
    odoo_root.mkdir(parents=True, exist_ok=True)
    enterprise_dir = odoo_root / f"enterprise_{odoo_version}"
    branch = f"{odoo_version}.0"
    remote = "git@github.com:odoo/enterprise.git"

    def log(message: str) -> None:
        if on_line:
            on_line(message)

    if not enterprise_dir.exists():
        log(f"Cloning Odoo enterprise {branch} into {enterprise_dir}")
        code = stream_command(
            ["git", "clone", "--branch", branch, "--single-branch", remote, str(enterprise_dir)],
        )
        if code != 0:
            raise RuntimeError(
                f"Failed to clone enterprise into {enterprise_dir}. "
                "Check GitHub SSH access to odoo/enterprise."
            )
    else:
        log(f"Updating enterprise at {enterprise_dir} ({branch})")
        fetch_code = stream_command(
            ["git", "-C", str(enterprise_dir), "fetch", "origin", branch],
        )
        if fetch_code != 0:
            raise RuntimeError(f"git fetch failed in {enterprise_dir}")
        reset_code = stream_command(
            ["git", "-C", str(enterprise_dir), "reset", "--hard", f"origin/{branch}"],
        )
        if reset_code != 0:
            raise RuntimeError(f"git reset failed in {enterprise_dir}")

    stream_command(
        ["git", "-C", str(enterprise_dir), "submodule", "init"],
    )
    stream_command(
        ["git", "-C", str(enterprise_dir), "submodule", "update"],
    )
    log("Enterprise addons are up to date.")
