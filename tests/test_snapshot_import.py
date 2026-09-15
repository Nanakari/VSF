from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.import_d1_snapshot import import_snapshot


class SnapshotImportTests(unittest.TestCase):
    def test_already_ready_snapshot_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_dir = Path(directory)
            (input_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "version": "snapshot-1",
                        "tables": {
                            "channels": 0,
                            "videos": 0,
                            "song_groups": 0,
                            "songs": 0,
                            "song_entries": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            calls: list[tuple[str, dict[str, object]]] = []

            def already_ready(session: object, url: str, token: str, payload: dict[str, object]) -> dict[str, object]:
                calls.append((url, payload))
                return {"ok": True, "version": "snapshot-1", "status": "ready"}

            with patch("scripts.import_d1_snapshot.request_json", side_effect=already_ready):
                import_snapshot("https://snapshot.test/", "secret", input_dir)

            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0][0].endswith("/api/admin/snapshot/start"))
            self.assertEqual(calls[0][1]["version"], "snapshot-1")


if __name__ == "__main__":
    unittest.main()
