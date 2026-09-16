from __future__ import annotations

from pathlib import Path
import re

from testbed_cli.dockerctl import compose_exec
from testbed_cli.process import LogFn
from testbed_cli.project import Project

MODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
VERSION_RE = re.compile(r"^[0-9]{2}$")


def reload_module(project: Project, module_name: str, on_line: LogFn | None = None) -> None:
    module_name = module_name.strip()
    if not module_name:
        raise ValueError("Module name is required")
    if on_line:
        on_line(f"Reloading module {module_name}")
    code = compose_exec(
        project,
        "web",
        [
            "odoo",
            "-d",
            project.database_name,
            "-c",
            "/etc/odoo/odoo.conf",
            "-u",
            module_name,
            "--stop-after-init",
            "--no-http",
        ],
        on_line=on_line,
    )
    if code != 0:
        raise RuntimeError(f"Failed to reload {module_name}")


def update_custom_modules(project: Project, on_line: LogFn | None = None) -> None:
    modules = project.custom_modules()
    if not modules:
        raise RuntimeError(f"No custom modules found under {project.addons_dir}")
    joined = ",".join(modules)
    if on_line:
        on_line(f"Updating custom modules ({len(modules)}): {joined}")
    reload_module(project, joined, on_line=on_line)


def create_module(
    project: Project,
    module_name: str,
    *,
    full: bool = False,
    odoo_version: str | None = None,
    on_line: LogFn | None = None,
) -> Path:
    module_name = module_name.strip()
    if not MODULE_NAME_RE.match(module_name):
        raise ValueError("Module name must be lowercase letters, numbers and underscores")
    version = (odoo_version or project.odoo_version).strip()
    if not VERSION_RE.match(version):
        raise ValueError("Odoo version must be a two-digit number such as 18")

    target = project.addons_dir / module_name
    if target.exists():
        raise FileExistsError(f"Module already exists at {target}")

    title = module_name.replace("_", " ")
    (target / "models").mkdir(parents=True)
    (target / "views").mkdir()
    (target / "models" / "__init__.py").write_text("", encoding="utf-8")
    (target / "__init__.py").write_text("from . import models\n", encoding="utf-8")
    (target / "__manifest__.py").write_text(
        "# -*- coding: utf-8 -*-\n"
        "{\n"
        f"    'name': '{title}',\n"
        "    'summary': '',\n"
        "    'author': '',\n"
        "    'website': '',\n"
        "    'category': 'Uncategorized',\n"
        f"    'version': '{version}.0.0.0.1',\n"
        "    'application': True,\n"
        "    'depends': [\n"
        "        'base',\n"
        "    ],\n"
        "    'data': [],\n"
        "    'assets': {},\n"
        "    'license': 'LGPL-3',\n"
        "}\n",
        encoding="utf-8",
    )
    if full:
        for folder in ("data", "wizards", "reports", "security", "tests", "static/description"):
            (target / folder).mkdir(parents=True, exist_ok=True)
        (target / "security" / "ir.model.access.csv").write_text(
            "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n",
            encoding="utf-8",
        )
        (target / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (target / "__init__.py").write_text(
            "from . import models\nfrom . import tests\n",
            encoding="utf-8",
        )
    if on_line:
        on_line(f"Created module {module_name} at {target}")
    return target
