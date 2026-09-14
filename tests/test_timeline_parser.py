import unittest

from timeline_parser import (
    build_timeline_candidate,
    parse_timeline_entries,
    timestamp_to_seconds,
)


class TimelineParserTests(unittest.TestCase):
    def test_blank_lines_and_mc_do_not_split_a_timeline(self):
        comment = """00:01 First Song

00:02 Second Song
00:03 MC / talking
00:04 Third Song
"""
        entries = parse_timeline_entries(comment)
        self.assertEqual([entry.raw_song_title for entry in entries], [
            "First Song",
            "Second Song",
            "Third Song",
        ])

    def test_word_filter_does_not_reject_end_inside_a_song_title(self):
        comment = """00:01 friend
00:02 pretend
"""
        entries = parse_timeline_entries(comment)
        self.assertEqual([entry.raw_song_title for entry in entries], ["friend", "pretend"])

    def test_invalid_seconds_and_duration_are_rejected(self):
        self.assertRaises(ValueError, timestamp_to_seconds, "00:99")
        self.assertIsNone(build_timeline_candidate("00:01 First Song\n00:02 Second Song", duration_seconds=1))


if __name__ == "__main__":
    unittest.main()
