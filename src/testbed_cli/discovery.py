from __future__ import annotations

from pathlib import Path

from testbed_cli.config import Config
from testbed_cli.project import Project, load_project


def discover_projects(config: Config) -> list[Project]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in config.project_roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            resolved = child.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(resolved)

    named: list[tuple[str, Path]] = []
    for candidate in candidates:
        env_preview = candidate / ".env"
        compose_preview = candidate / ".testbed" / "docker" / "docker-compose.yml"
        if env_preview.exists() and compose_preview.exists():
            named.append((candidate.name, candidate))
    named.sort(key=lambda item: item[0])

    projects: list[Project] = []
    for _folder_name, candidate in named:
        project = load_project(candidate)
        if project is not None:
            projects.append(project)
    projects.sort(key=lambda item: item.database_name)
    return projects


def project_from_path(path: Path) -> Project | None:
    current = path.expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        project = load_project(candidate)
        if project is not None:
            return project
    return None


def resolve_project(config: Config, name: str) -> Project:
    needle = name.strip()
    path = Path(needle).expanduser()
    if path.exists():
        project = load_project(path)
        if project is not None:
            return project
    for project in discover_projects(config):
        if project.database_name == needle or project.folder_name == needle:
            return project
    raise LookupError(f"No testbed project matched '{name}'")
