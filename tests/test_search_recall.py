import unittest

from database import SongDatabase, combine_cross_channel_groups
from timeline_parser import TimelineEntry, normalize_song_title


class SearchRecallTests(unittest.TestCase):
    def make_database(self, raw_titles: list[str]) -> SongDatabase:
        db = SongDatabase(":memory:")
        db.init_schema()
        db.upsert_channel("channel", "Test Channel")
        db.upsert_video("video", "channel", "歌枠", "2026-01-01")
        db.insert_song_entries(
            "video",
            [
                TimelineEntry(
                    timestamp_text=f"00:{index:02d}",
                    seconds=index,
                    raw_song_title=raw_title,
                    normalized_song_title=normalize_song_title(raw_title),
                )
                for index, raw_title in enumerate(raw_titles, start=1)
            ],
            "timeline",
        )
        return db

    def test_compact_song_query_keeps_space_variant(self):
        db = self.make_database(["Stellar Stellar"])
        try:
            groups = db.search_grouped(song_query="StellarStellar", limit=50)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["entry_count"], 1)
        finally:
            db.close()

    def test_one_character_typo_keeps_fuzzy_match(self):
        db = self.make_database(["Starlight"])
        try:
            groups = db.search_grouped(song_query="Starligh", limit=50)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["entry_count"], 1)
        finally:
            db.close()

    def test_version_variant_remains_in_the_merged_group(self):
        db = self.make_database(["Stellar Stellar", "Stellar Stellar—Live"])
        try:
            groups = db.search_grouped(song_query="Stellar Stellar", limit=50)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["entry_count"], 2)
            self.assertEqual(
                {entry["raw_song_title"] for entry in groups[0]["entries"]},
                {"Stellar Stellar", "Stellar Stellar—Live"},
            )
        finally:
            db.close()

    def test_cross_channel_index_keeps_first_seen_group_after_artist_promotion(self):
        def group(song_key: str, entry_id: int, artist_key: str = "", artist: str = ""):
            channel_id = f"channel-{entry_id}"
            return {
                "channel_id": channel_id,
                "channel_title": channel_id,
                "song_key": song_key,
                "artist_key": artist_key,
                "artist": artist,
                "song_title": song_key,
                "title_keys": {song_key},
                "artist_keys": {artist_key} if artist_key else set(),
                "normalized_title_keys": {song_key},
                "entries": [
                    {
                        "entry_id": entry_id,
                        "channel_id": channel_id,
                        "channel_title": channel_id,
                        "published_at": "2026-01-01",
                        "seconds": entry_id,
                    }
                ],
                "raw_titles": [song_key],
                "song_ids": {entry_id},
                "source_channels": {channel_id: channel_id},
                "entry_count": 1,
            }

        groups = combine_cross_channel_groups(
            [
                group("catalogsongbeta", 1),
                group("catalogsongbetx", 2, "artist", "Artist"),
                group("catalogsongbeta", 3, "artist", "Artist"),
                group("catalogsongbetx", 4, "artist", "Artist"),
            ]
        )
        self.assertEqual(len(groups), 2)
        by_song_key = {group["song_key"]: group for group in groups}
        self.assertEqual(
            [entry["entry_id"] for entry in by_song_key["catalogsongbeta"]["entries"]],
            [1, 3, 4],
        )
        self.assertEqual(
            [entry["entry_id"] for entry in by_song_key["catalogsongbetx"]["entries"]],
            [2],
        )

    def test_channel_candidate_index_keeps_first_seen_group_after_artist_promotion(self):
        db = SongDatabase(":memory:")
        try:
            unknown_key = ("channel", "catalogsongbeta", "")
            fuzzy_key = ("channel", "catalogsongbetx", "artist")
            grouped = {
                unknown_key: {"song_key": "catalogsongbeta", "artist_key": ""},
                fuzzy_key: {"song_key": "catalogsongbetx", "artist_key": "artist"},
            }
            by_song = {
                ("channel", "catalogsongbeta"): [unknown_key],
                ("channel", "catalogsongbetx"): [fuzzy_key],
            }
            by_artist = {("channel", "artist"): [fuzzy_key]}
            order = {unknown_key: 0, fuzzy_key: 1}

            self.assertEqual(
                db._find_similar_group_key(
                    grouped,
                    "channel",
                    "catalogsongbeta",
                    "artist",
                    by_song,
                    by_artist,
                    order,
                ),
                unknown_key,
            )
            grouped[unknown_key]["artist_key"] = "artist"
            by_artist[("channel", "artist")].append(unknown_key)
            self.assertEqual(
                db._find_similar_group_key(
                    grouped,
                    "channel",
                    "catalogsongbetz",
                    "artist",
                    by_song,
                    by_artist,
                    order,
                ),
                unknown_key,
            )
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
