from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
