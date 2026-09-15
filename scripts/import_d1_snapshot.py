from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests


TABLE_ORDER = ("channels", "videos", "song_groups", "songs", "song_entries")
BATCH_SIZE = 90


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


def request_json(session: requests.Session, url: str, token: str, payload: dict[str, object]) -> dict[str, object]:
    response = session.post(
        url,
        headers={"x-seed-token": token},
        json=payload,
        timeout=120,
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        raise RuntimeError(f"{url} failed with HTTP {response.status_code}: {body.get('message', 'unknown error')}")
    if body.get("ok") is False:
        raise RuntimeError(f"{url} failed: {body.get('message', 'unknown error')}")
    return body


def import_snapshot(base_url: str, token: str, input_dir: Path) -> None:
    manifest = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest.get("version") or "").strip()
    if not version:
        raise RuntimeError("manifest.json does not contain a snapshot version")

    base_url = base_url.rstrip("/")
    session = requests.Session()
    tables = manifest.get("tables")
    if not isinstance(tables, dict):
        raise RuntimeError("manifest.json does not contain table row counts")
    start_result = request_json(
        session,
        f"{base_url}/api/admin/snapshot/start",
        token,
        {"version": version, "tables": tables},
    )
    # A retry after a successful commit is already complete.  Seeding a ready
    # snapshot is intentionally rejected by the Worker, so finish idempotently
    # here instead of treating that expected 409 as an import failure.
    if start_result.get("status") == "ready":
        print(f"Snapshot {version} is already committed.")
        return
    for table in TABLE_ORDER:
        rows = json.loads((input_dir / f"{table}.json").read_text(encoding="utf-8"))
        for start in range(0, len(rows), BATCH_SIZE):
            batch = rows[start : start + BATCH_SIZE]
            request_json(
                session,
                f"{base_url}/api/admin/seed",
                token,
                {"version": version, "table": table, "rows": batch},
            )
            print(f"{table}: {min(start + BATCH_SIZE, len(rows))}/{len(rows)}")

    request_json(session, f"{base_url}/api/admin/snapshot/commit", token, {"version": version})
    print(f"Committed snapshot {version}.")


if __name__ == "__main__":
    args = build_parser().parse_args()
    import_snapshot(args.base_url, args.token, Path(args.input_dir))
