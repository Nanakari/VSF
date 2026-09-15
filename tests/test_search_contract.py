from __future__ import annotations

import json
from pathlib import Path
import io
import re
import unittest
from contextlib import redirect_stdout

from database import SongDatabase
from main import run_search
from search import search_songs
from song_identity import compact_key
from timeline_parser import TimelineEntry, normalize_song_title


FIXTURE = Path(__file__).with_name("fixtures") / "search_contract.json"


def load_fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_database(fixture: dict[str, object]) -> SongDatabase:
    db = SongDatabase(":memory:")
    db.init_schema()
    for row in fixture["channels"]:  # type: ignore[index]
        db.upsert_channel(row["channel_id"], row["channel_title"])
    for row in fixture["videos"]:  # type: ignore[index]
        db.upsert_video(
            row["video_id"],
            row["channel_id"],
            row["title"],
            row["published_at"],
        )
    for video in fixture["videos"]:  # type: ignore[index]
        video_id = video["video_id"]
        entries = [
            TimelineEntry(
                timestamp_text=row["timestamp_text"],
                seconds=row["seconds"],
                raw_song_title=row["raw_song_title"],
                normalized_song_title=normalize_song_title(row["raw_song_title"]),
            )
            for row in fixture["entries"]  # type: ignore[index]
            if row["video_id"] == video_id
        ]
        db.insert_song_entries(video_id, entries, f"fixture:{video_id}")
    return db


def group_key(group: dict[str, object]) -> str:
    return str(group.get("group_key") or "")


def compact_group_result(groups: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "group_key": group_key(group),
            "entry_count": int(group["entry_count"]),
            "channel_count": int(group["channel_count"]),
            "channels": [
                {
                    "channel_id": channel["channel_id"],
                    "entry_count": len(channel["entries"]),
                    "entries": [
                        {
                            "raw_song_title": entry["raw_song_title"],
                            "entry_id": int(entry["entry_id"]),
                        }
                        for entry in channel["entries"]
                    ],
                }
                for channel in group["channels"]
            ],
        }
        for group in groups
    ]


class SearchContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = load_fixture()
        self.db = make_database(self.fixture)

    def tearDown(self) -> None:
        self.db.close()

    def test_handwritten_query_contract_and_grouped_shape(self) -> None:
        for query in self.fixture["queries"]:  # type: ignore[index]
            with self.subTest(query=query["name"]):
                groups = self.db.search_grouped(
                    song_query=query.get("song"),
                    channel_query=query.get("channel"),
                    artist_query=query.get("artist"),
                    limit=50,
                )
                actual_keys = [group_key(group) for group in groups]
                self.assertEqual(actual_keys, query["expected_groups"])
                if "expected_entry_count" in query:
                    self.assertEqual(len(groups), 1)
                    self.assertEqual(groups[0]["entry_count"], query["expected_entry_count"])

    def test_shared_fixture_metadata_matches_python_grouping(self) -> None:
        actual = {
            group_key(group): group
            for group in self.db.search_grouped(limit=100, offset=0)
        }
        for expected in self.fixture["groups"]:  # type: ignore[index]
            with self.subTest(group=expected["group_key"]):
                group = actual[expected["group_key"]]
                self.assertEqual(group["song_title"], expected["song_title"])
                self.assertEqual(group["artist"], expected["artist"])
                self.assertEqual(group["entry_count"], expected["entry_count"])
                self.assertEqual(group["channel_count"], expected["channel_count"])

    def test_python_flat_search_uses_same_match_contract(self) -> None:
        for query in self.fixture["queries"]:  # type: ignore[index]
            with self.subTest(query=query["name"]):
                rows = search_songs(
                    self.db,
                    query.get("song", ""),
                    limit=100,
                    channel_query=query.get("channel"),
                    artist_query=query.get("artist"),
                )
                actual_keys = {compact_key(str(row["raw_song_title"]).split(" / ")[0]) for row in rows}
                if query["name"] == "compact":
                    self.assertEqual(actual_keys, {"stellarstellar", "stellarstellarlive"})
                    self.assertEqual(len(rows), 5)
                elif query["name"] == "unknown-author":
                    self.assertEqual([row["raw_song_title"] for row in rows], ["Encore / Ado"])
                elif query["name"] in {"typo-negative", "short-substring-negative"}:
                    self.assertEqual(rows, [])
                elif query["name"] == "literal-channel-filter":
                    self.assertEqual(len(rows), 3)
                    self.assertTrue(all(row["channel_id"] == "chan-a" for row in rows))
                elif query["name"] == "channel-filter":
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]["channel_id"], "chan-b")
                else:
                    self.assertEqual(
                        {group_key(group) for group in self.db.search_grouped(
                            song_query=query.get("song"),
                            channel_query=query.get("channel"),
                            artist_query=query.get("artist"),
                            limit=50,
                        )},
                        set(query["expected_groups"]),
                    )

    def test_group_pagination_counts_and_order_are_stable(self) -> None:
        first = self.db.search_grouped(limit=3, offset=0)
        second = self.db.search_grouped(limit=3, offset=3)
        self.assertEqual([group_key(group) for group in first], [
            "stellarstellar::ado",
            "abcdefghij::ado",
            "encore::ado",
        ])
        self.assertEqual([group_key(group) for group in second], [
            "starlight::ado",
            "alphasong::ado",
            "betasong::ado",
        ])

    def test_cli_handler_respects_flat_limit_and_artist_filter(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                run_search(
                    self.db,
                    "Stellar Stellar",
                    limit=2,
                    channel="100%_Live",
                    artist="Ado",
                ),
                0,
            )
        numbered = re.findall(r"^\d+\. ", output.getvalue(), flags=re.MULTILINE)
        self.assertEqual(len(numbered), 2)
        self.assertIn("Stellar Stellar—Live / Ado", output.getvalue())

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(run_search(self.db, "StellarStellar", limit=1), 0)
        self.assertEqual(len(re.findall(r"^\d+\. ", output.getvalue(), flags=re.MULTILINE)), 1)


if __name__ == "__main__":
    unittest.main()
