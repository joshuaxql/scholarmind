"""Run ScholarMind API and web processes directly on the local machine."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
ALL_INTERFACE_HOSTS = {"0.0.0.0", "::"}  # noqa: S104 - values are compared, never bound here


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        from dotenv import dotenv_values
    except ImportError:
        # The launcher can run under system Python; dotenv is installed in the project venv.
        if not VENV_PYTHON.exists():
            raise SystemExit(".venv is missing. Run: python scripts/setup.py") from None
        result = subprocess.run(  # noqa: S603 - fixed project Python; output stays in memory
            [
                str(VENV_PYTHON),
                "-c",
                "import json,sys; from dotenv import dotenv_values; "
                "print(json.dumps(dotenv_values(sys.argv[1], "
                "encoding='utf-8-sig', interpolate=False)))",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        values = json.loads(result.stdout)
    else:
        values = dotenv_values(path, encoding="utf-8-sig", interpolate=False)
    return {key: value for key, value in values.items() if value is not None}


def next_command(action: str) -> list[str]:
    node = shutil.which("node.exe" if sys.platform == "win32" else "node")
    next_cli = ROOT / "apps/web/node_modules/next/dist/bin/next"
    if not node or not next_cli.exists():
        raise SystemExit("Web dependencies are missing. Run: python scripts/setup.py")
    return [node, str(next_cli), action]


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        taskkill = shutil.which("taskkill.exe") or "C:/Windows/System32/taskkill.exe"
        subprocess.run(  # noqa: S603 - fixed system executable and numeric child PID
            [taskkill, "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--api-only", action="store_true", help="start only FastAPI")
    mode.add_argument("--web-only", action="store_true", help="start only Next.js")
    parser.add_argument(
        "--production", action="store_true", help="build and run the web production server"
    )
    parser.add_argument("--reload", action="store_true", help="enable API auto-reload")
    args = parser.parse_args()

    env = os.environ.copy()
    for key, value in load_env(ROOT / ".env").items():
        env.setdefault(key, value)
    env.setdefault("PYTHONUNBUFFERED", "1")
    api_port = env.get("API_PORT", "8000")
    web_host = env.get("WEB_HOST", "127.0.0.1")
    web_port = env.get("WEB_PORT", env.get("PORT", "3000"))
    env.setdefault("API_INTERNAL_URL", f"http://127.0.0.1:{api_port}")
    if env.get("API_BEARER_TOKEN") and not env.get("API_INTERNAL_BEARER_TOKEN"):
        env["API_INTERNAL_BEARER_TOKEN"] = env["API_BEARER_TOKEN"]

    processes: list[subprocess.Popen[bytes]] = []
    if not args.web_only:
        if not VENV_PYTHON.exists():
            raise SystemExit(".venv is missing. Run: python scripts/setup.py")
        print("Applying database migrations...", flush=True)
        subprocess.run(  # noqa: S603 - fixed virtualenv executable and arguments
            [
                str(VENV_PYTHON),
                "-m",
                "alembic",
                "-c",
                str(ROOT / "apps/api/alembic.ini"),
                "upgrade",
                "head",
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )
        api_command = [
            str(VENV_PYTHON),
            "-m",
            "uvicorn",
            "scholarmind.main:app",
            "--app-dir",
            str(ROOT / "apps/api"),
            "--host",
            env.get("API_HOST", "127.0.0.1"),
            "--port",
            api_port,
        ]
        if args.reload:
            api_command.append("--reload")
        processes.append(
            subprocess.Popen(  # noqa: S603 - fixed virtualenv executable
                api_command, cwd=ROOT, env=env
            )
        )

    if not args.api_only:
        web_action = "start" if args.production else "dev"
        if args.production:
            subprocess.run(  # noqa: S603 - Node executable and Next CLI are fixed
                next_command("build"),
                cwd=ROOT / "apps/web",
                env=env,
                check=True,
            )
        web_command = [
            *next_command(web_action),
            "--hostname",
            web_host,
            "--port",
            web_port,
        ]
        processes.append(
            subprocess.Popen(  # noqa: S603 - Node executable and Next CLI are fixed
                web_command,
                cwd=ROOT / "apps/web",
                env=env,
            )
        )

    print(f"ScholarMind API: http://127.0.0.1:{api_port}")
    if not args.api_only:
        display_host = "127.0.0.1" if web_host in ALL_INTERFACE_HOSTS else web_host
        print(f"ScholarMind Web: http://{display_host}:{web_port}")
    print("Press Ctrl+C to stop.")
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(processes):
            stop_process(process)
    return next((process.returncode or 0 for process in processes if process.returncode), 0)


if __name__ == "__main__":
    raise SystemExit(main())
