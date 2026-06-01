from __future__ import annotations

from pathlib import Path


def find_project_root() -> Path:
    """
    Find the project root by walking upward until pyproject.toml or .git is found.
    T
    """
    current = Path(__file__).resolve()

    for parent in current.parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent

    raise RuntimeError("Could not find project root. Expected pyproject.toml or .git.")
