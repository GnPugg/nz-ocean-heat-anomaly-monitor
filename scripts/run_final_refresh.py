from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"


def run_command(command: list[str]) -> None:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")

    if existing_pythonpath:
        env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + existing_pythonpath
    else:
        env["PYTHONPATH"] = str(SRC_DIR)

    print("\nRunning:")
    print(" ".join(command))

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}")


def main() -> None:
    print("===============================")
    print("Running final/historical refresh")
    print("===============================")

    run_command(
        [
            sys.executable,
            "-m",
            "nzheat.analytics.anomalies",
        ]
    )

    run_command(
        [
            sys.executable,
            "-m",
            "nzheat.analytics.events",
        ]
    )

    run_command(
        [
            sys.executable,
            "-m",
            "nzheat.load.load_postgres",
        ]
    )

    print("\nFinal/historical refresh complete.")


if __name__ == "__main__":
    main()
