from __future__ import annotations

import unittest

from scripts.benchmark_search import (
    BENCHMARK_CASES,
    _combine_cross_channel_groups_reference,
    _timed_search,
    build_benchmark_database,
    benchmark_failures,
    cross_channel_collision_probe,
)


class SearchBenchmarkTests(unittest.TestCase):
    def test_reference_combiner_uses_global_first_seen_order(self) -> None:
        fuzzy = {
            "label": "fuzzy-first",
            "channel_id": "fuzzy",
            "channel_title": "Fuzzy",
            "song_key": "catalogsongbetx",
            "artist_key": "artist",
            "artist_keys": {"artist"},
            "title_keys": {"catalogsongbetx"},
            "normalized_title_keys": {"catalogsongbetx"},
            "song_title": "Catalog Song Bet X",
            "artist": "Artist",
            "raw_titles": ["Catalog Song Bet X"],
            "entries": [],
            "song_ids": {1},
            "entry_count": 1,
            "source_channels": {"fuzzy": "Fuzzy"},
        }
        exact = dict(fuzzy)
        exact.update(
            {
                "label": "exact-later",
                "channel_id": "exact",
                "channel_title": "Exact",
                "song_key": "catalogsongbeta",
                "title_keys": {"catalogsongbeta"},
                "normalized_title_keys": {"catalogsongbeta"},
                "song_title": "Catalog Song Beta",
                "raw_titles": ["Catalog Song Beta"],
                "song_ids": {2},
                "source_channels": {"exact": "Exact"},
            }
        )

        combined = _combine_cross_channel_groups_reference([fuzzy, exact])

        self.assertEqual([group["label"] for group in combined], ["fuzzy-first"])
        self.assertEqual(combined[0]["song_ids"], {1, 2})

    def test_collision_probe_matches_and_generated_data_matches(self) -> None:
        probe = cross_channel_collision_probe()
        self.assertEqual(probe["indexed_label"], "fuzzy-first")
        self.assertEqual(probe["linear_label"], "fuzzy-first")
        self.assertTrue(probe["equivalent"])

        db = build_benchmark_database(40, 100)
        try:
            for query in BENCHMARK_CASES.values():
                indexed = _timed_search(db, query, reference=False)
                reference = _timed_search(db, query, reference=True)
                self.assertEqual(indexed[1], reference[1], query)
                self.assertEqual(indexed[2], reference[2], query)
                self.assertGreater(indexed[2], 0, query)

            channel_groups = db.search_grouped(
                song_query="catalog song",
                channel_query="Channel 000",
                artist_query="artist",
                limit=None,
            )
            self.assertTrue(channel_groups)
            self.assertEqual(
                {str(group["channel_id"]) for group in channel_groups},
                {"channel-000"},
            )
        finally:
            db.close()

    def test_validation_rejects_collision_or_fingerprint_mismatch(self) -> None:
        valid = {
            "collision_probe": {"equivalent": True},
            "sizes": [
                {
                    "name": "fixture",
                    "cases": [
                        {
                            "case": "query",
                            "fingerprints_equal": True,
                            "result_fingerprints": {
                                "indexed": ["same", "same"],
                                "reference": ["same", "same"],
                            },
                        }
                    ],
                }
            ],
        }
        self.assertEqual(benchmark_failures(valid), [])

        invalid_collision = dict(valid)
        invalid_collision["collision_probe"] = {"equivalent": False}
        self.assertTrue(benchmark_failures(invalid_collision))

        invalid_fingerprint = {
            **valid,
            "sizes": [
                {
                    "name": "fixture",
                    "cases": [
                        {
                            "case": "query",
                            "fingerprints_equal": False,
                            "result_fingerprints": {
                                "indexed": ["one"],
                                "reference": ["two"],
                            },
                        }
                    ],
                }
            ],
        }
        self.assertTrue(benchmark_failures(invalid_fingerprint))


if __name__ == "__main__":
    unittest.main()
