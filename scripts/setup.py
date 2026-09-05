"""Create a local ScholarMind development environment."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def run(command: list[str]) -> None:
    print(f"\n> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)  # noqa: S603 - commands are internal


def main() -> None:
    if not ((3, 11) <= sys.version_info[:2] < (3, 13)):
        raise SystemExit("ScholarMind requires Python 3.11 or 3.12.")
    if not VENV_PYTHON.exists():
        run([sys.executable, "-m", "venv", str(VENV)])

    run([str(VENV_PYTHON), "-m", "pip", "install", "-e", "apps/api[dev]"])
    node = shutil.which("node.exe" if sys.platform == "win32" else "node")
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if not node or not npm:
        raise SystemExit("Node.js/npm was not found. Install Node.js 22 or newer first.")
    node_version = (
        subprocess.check_output(  # noqa: S603 - executable resolved from PATH
            [node, "--version"], text=True
        )
        .strip()
        .lstrip("v")
    )
    if int(node_version.split(".", 1)[0]) < 22:
        raise SystemExit(f"Node.js 22 or newer is required; found {node_version}.")
    run([npm, "--prefix", "apps/web", "ci"])

    env_file = ROOT / ".env"
    if not env_file.exists():
        shutil.copy2(ROOT / ".env.example", env_file)
        print("\nCreated .env from .env.example.")
    print("\nSetup complete. Configure .env, then run: python scripts/start.py")


if __name__ == "__main__":
    main()
