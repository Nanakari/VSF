from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from site_sync import import_snapshot as _import_snapshot
from site_sync import request_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import a complete VTuber Song Finder D1 snapshot.")
    parser.add_argument("--base-url", required=True, help="Site URL, for example https://example.chatgpt.site")
    parser.add_argument("--token", required=True, help="Value configured as the site's SEED_TOKEN")
    parser.add_argument(
        "--input-dir",
        default="build/d1-seed",
        help="Directory containing manifest.json and exported table JSON files.",
    )
    return parser


def import_snapshot(base_url: str, token: str, input_dir: Path) -> None:
    # Keep request_json as a module-level seam for the existing unit test and
    # for callers that want to replace the HTTP transport.
    _import_snapshot(
        base_url,
        token,
        input_dir,
        on_message=print,
        request_json_fn=request_json,
    )


if __name__ == "__main__":
    args = build_parser().parse_args()
    import_snapshot(args.base_url, args.token, Path(args.input_dir))
