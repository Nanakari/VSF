"""Cross-platform checks for the application, hosted site, or both.

Run with the project's Python environment. All database tests use disposable
data; this script never indexes YouTube or synchronizes a live site.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys


PROJECT_DIR = Path(__file__).resolve().parents[1]


def run(*command: str) -> None:
    print("+ " + " ".join(command), flush=True)
    env = {**os.environ, "PYTHON": sys.executable, "PYTHONUTF8": "1"}
    subprocess.run(command, cwd=PROJECT_DIR, env=env, check=True)


def check_python() -> None:
    run(sys.executable, "-m", "pip", "check")
    # Compile maintained sources, not node_modules, portable output, or a venv.
    sources = list(PROJECT_DIR.glob("*.py"))
    for directory in ("scripts", "tests"):
        sources.extend((PROJECT_DIR / directory).rglob("*.py"))
    for source in sources:
        py_compile.compile(str(source), doraise=True)
    run(sys.executable, "-c",
        "import app, config, database, indexer_app, indexing, main, search, "
        "site_sync, song_identity, timeline_parser, youtube_client")
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v")


def check_site() -> None:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js 20+ is required for site checks")
    for script in ("build-worker.mjs", "validate-worker.mjs", "test-worker.mjs"):
        run(node, str(PROJECT_DIR / "scripts" / script))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("all", "python", "site"), default="all")
    args = parser.parse_args()
    try:
        if args.scope in ("all", "python"):
            check_python()
        if args.scope in ("all", "site"):
            check_site()
        run("git", "diff", "--check")
    except (OSError, RuntimeError, py_compile.PyCompileError, subprocess.CalledProcessError) as error:
        print(f"Checks failed: {error}", file=sys.stderr)
        return 1
    print(f"All checks passed (scope: {args.scope}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
