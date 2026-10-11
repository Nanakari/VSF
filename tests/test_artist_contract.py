import json
from pathlib import Path
import unittest

from database import SongDatabase
from song_identity import parse_song_identity
from timeline_parser import TimelineEntry, normalize_song_title


class ArtistContractTests(unittest.TestCase):
    def test_artist_names_and_collaborations_follow_the_shared_contract(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/artist_contract.json").read_text(encoding="utf-8"))
        db = SongDatabase(":memory:")
        self.addCleanup(db.close)
        db.init_schema()
        db.upsert_channel("artists", "Artists")
        db.upsert_video("video", "artists", "karaoke", "2026-01-01")
        for artist in fixture["artists"]:
            title = artist["title"] + (f" / {artist['name']}" if artist["name"] else "")
            with self.subTest(artist=artist["name"]):
                self.assertEqual(list(parse_song_identity(title).artist_keys), artist["keys"])
            db.insert_song_entries("video", [TimelineEntry(
                f"00:{artist['id']:02d}", artist["id"], title, normalize_song_title(title),
            )], "contract fixture")
        for query in fixture["queries"]:
            with self.subTest(query=query["artist"]):
                groups = db.search_grouped(artist_query=query["artist"])
                actual = sorted(entry["seconds"] for group in groups for entry in group["entries"])
                self.assertEqual(actual, query["ids"])
