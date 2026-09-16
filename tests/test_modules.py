from __future__ import annotations

import pytest

from testbed_cli.modules import create_module, reload_module, update_custom_modules


def test_reload_module(project, monkeypatch) -> None:
    notes: list[str] = []
    monkeypatch.setattr("testbed_cli.modules.compose_exec", lambda *args, **kwargs: 0)
    reload_module(project, "sale_custom", on_line=notes.append)
    assert notes == ["Reloading module sale_custom"]


def test_reload_module_requires_name(project) -> None:
    with pytest.raises(ValueError, match="Module name is required"):
        reload_module(project, "  ")


def test_reload_module_failure(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.modules.compose_exec", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError, match="Failed to reload"):
        reload_module(project, "sale_custom")


def test_update_custom_modules(project, monkeypatch) -> None:
    addon = project.addons_dir / "sale_custom"
    addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{}", encoding="utf-8")
    seen: list[str] = []
    monkeypatch.setattr("testbed_cli.modules.reload_module", lambda proj, name, on_line=None: seen.append(name))
    update_custom_modules(project)
    assert seen == ["sale_custom"]


def test_update_custom_modules_none(project) -> None:
    with pytest.raises(RuntimeError, match="No custom modules found"):
        update_custom_modules(project)


def test_create_module(project) -> None:
    notes: list[str] = []
    target = create_module(project, "sale_custom", on_line=notes.append)
    assert target == project.addons_dir / "sale_custom"
    assert (target / "models" / "__init__.py").exists()
    assert (target / "views").is_dir()
    manifest = (target / "__manifest__.py").read_text(encoding="utf-8")
    assert "'name': 'sale custom'" in manifest
    assert "'version': '18.0.0.0.1'" in manifest
    assert "'author': ''" in manifest
    assert "'license': 'LGPL-3'" in manifest
    assert (target / "__init__.py").read_text(encoding="utf-8") == "from . import models\n"
    assert not (target / "security").exists()
    assert notes[0].startswith("Created module sale_custom")


def test_create_module_full(project) -> None:
    target = create_module(project, "itsz_foo", full=True, odoo_version="19")
    assert (target / "data").is_dir()
    assert (target / "wizards").is_dir()
    assert (target / "reports").is_dir()
    assert (target / "tests" / "__init__.py").exists()
    assert (target / "static" / "description").is_dir()
    access = (target / "security" / "ir.model.access.csv").read_text(encoding="utf-8")
    assert access.startswith("id,name,model_id:id")
    assert "from . import tests" in (target / "__init__.py").read_text(encoding="utf-8")
    assert "'version': '19.0.0.0.1'" in (target / "__manifest__.py").read_text(encoding="utf-8")


def test_create_module_rejects_bad_name_and_existing(project) -> None:
    with pytest.raises(ValueError, match="Module name"):
        create_module(project, "Bad-Name")
    create_module(project, "sale_custom")
    with pytest.raises(FileExistsError):
        create_module(project, "sale_custom")
    with pytest.raises(ValueError, match="Odoo version"):
        create_module(project, "other_mod", odoo_version="18.0")
