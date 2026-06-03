from pathlib import Path

from nzheat.utils.paths import find_project_root


def test_find_project_root_returns_existing_directory():
    root = find_project_root()

    assert isinstance(root, Path)
    assert root.exists()
    assert (root / "nzheat").exists()
    assert (root / "scripts").exists()
