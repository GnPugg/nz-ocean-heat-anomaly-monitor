from __future__ import annotations

import subprocess
from pathlib import Path

from nzheat.utils.paths import find_project_root

PROJECT_ROOT = find_project_root()


def run_command(command: list[str]) -> None:
    """
    Run a project command from the project root.

    The project is installed with:
        pip install -e .

    So we no longer need to manually set PYTHONPATH.
    """
    print("\nRunning:")
    print(" ".join(command))

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}")
