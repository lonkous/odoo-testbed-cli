from __future__ import annotations

import pytest

from testbed_cli.i18n import LANGUAGES, export_translations, import_translations


def test_languages_include_swiss_locales() -> None:
    assert "de_CH" in LANGUAGES
    assert "en_US" in LANGUAGES


def test_export_translations(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.i18n.compose_exec", lambda *args, **kwargs: 0)
    copied: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "testbed_cli.i18n.compose_cp",
        lambda proj, source, dest, on_line=None: copied.append((source, dest)),
    )
    notes: list[str] = []
    export_translations(project, "de_CH", "sale_custom", on_line=notes.append)
    assert (project.addons_dir / "sale_custom" / "i18n").is_dir()
    assert copied[0][0] == "web:/opt/de_CH.po"
    assert copied[0][1].endswith("de_CH.po")


def test_export_translations_failure(project, monkeypatch) -> None:
    monkeypatch.setattr("testbed_cli.i18n.compose_exec", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError, match="Translation export failed"):
        export_translations(project, "de_CH", "sale_custom")


def test_import_translations(project, monkeypatch) -> None:
    po_dir = project.addons_dir / "sale_custom" / "i18n"
    po_dir.mkdir(parents=True)
    (po_dir / "de_CH.po").write_text('msgid ""\n', encoding="utf-8")
    monkeypatch.setattr("testbed_cli.i18n.compose_cp", lambda *args, **kwargs: None)
    monkeypatch.setattr("testbed_cli.i18n.compose_exec", lambda *args, **kwargs: 0)
    import_translations(project, "de_CH", "sale_custom")
    monkeypatch.setattr("testbed_cli.i18n.compose_exec", lambda *args, **kwargs: 1)
    with pytest.raises(RuntimeError, match="Translation import failed"):
        import_translations(project, "de_CH", "sale_custom")


def test_import_missing_po(project) -> None:
    with pytest.raises(FileNotFoundError, match="Missing translation file"):
        import_translations(project, "de_CH", "sale_custom")
