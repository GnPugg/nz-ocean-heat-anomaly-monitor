from __future__ import annotations

import sys

from nzheat.utils.commands import run_command


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
