from __future__ import annotations

from testbed_cli.dockerctl import compose_cp, compose_exec
from testbed_cli.process import LogFn
from testbed_cli.project import Project

LANGUAGES = ["de_CH", "en_US", "fr_CH", "it_CH", "it"]


def export_translations(
    project: Project, language: str, module_name: str, on_line: LogFn | None = None
) -> None:
    module_name = module_name.strip()
    dest_dir = project.addons_dir / module_name / "i18n"
    dest_dir.mkdir(parents=True, exist_ok=True)
    if on_line:
        on_line(f"Exporting translations for {language} / {module_name}")
    code = compose_exec(
        project,
        "web",
        [
            "odoo",
            "-d",
            project.database_name,
            "-c",
            "/etc/odoo/odoo.conf",
            "--load-language",
            language,
            "-l",
            language,
            f"--i18n-export=/opt/{language}.po",
            f"--modules={module_name}",
            "--no-http",
            "--stop-after-init",
        ],
        on_line=on_line,
    )
    if code != 0:
        raise RuntimeError("Translation export failed")
    compose_cp(
        project,
        f"web:/opt/{language}.po",
        str(dest_dir / f"{language}.po"),
        on_line=on_line,
    )


def import_translations(
    project: Project, language: str, module_name: str, on_line: LogFn | None = None
) -> None:
    module_name = module_name.strip()
    po_file = project.addons_dir / module_name / "i18n" / f"{language}.po"
    if not po_file.exists():
        raise FileNotFoundError(f"Missing translation file {po_file}")
    if on_line:
        on_line(f"Importing translations for {language} / {module_name}")
    compose_cp(project, str(po_file), f"web:/opt/{language}.po", on_line=on_line)
    code = compose_exec(
        project,
        "web",
        [
            "odoo",
            "-d",
            project.database_name,
            "-c",
            "/etc/odoo/odoo.conf",
            "--load-language",
            language,
            "-l",
            language,
            f"--i18n-import=/opt/{language}.po",
            "--i18n-overwrite",
            f"--modules={module_name}",
            "--no-http",
            "--stop-after-init",
        ],
        on_line=on_line,
    )
    if code != 0:
        raise RuntimeError("Translation import failed")
