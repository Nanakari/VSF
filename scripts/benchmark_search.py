"""Benchmark indexed search grouping against the pre-index reference paths.

The benchmark deliberately keeps hydration out of the timed section.  The
change under test is candidate selection and cross-channel grouping; loading
all entry rows for every result would measure response serialization and drown
out that signal.  Both variants execute the same SQL and return the same
pre-hydration groups, which are compared by a stable fingerprint.

Run from the project root with::

    python scripts/benchmark_search.py

The default run uses the two requested data sizes and three timed repetitions
per case and per implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Support the documented ``python scripts/benchmark_search.py`` invocation,
# where Python otherwise puts only the scripts directory on sys.path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database as database_module
from database import SongDatabase


SEED = 20260915
DEFAULT_REPEATS = 3


@dataclass(frozen=True)
class BenchmarkSize:
    name: str
    songs: int
    entries: int


BENCHMARK_SIZES = (
    BenchmarkSize("3000 songs / 20000 entries", 3_000, 20_000),
    BenchmarkSize("10000 songs / 100000 entries", 10_000, 100_000),
)


BENCHMARK_CASES: dict[str, dict[str, str]] = {
    # The channel filter names one generated channel so this case exercises a
    # real channel hit instead of merely passing a value through an untested
    # query path.  The song and artist filters remain broad within that
    # channel.
    "channel + song + artist": {
        "channel_query": "Channel 000",
        "song_query": "catalog song",
        "artist_query": "artist",
    },
    # No channel filter invokes cross-channel merging, where the linear
    # reference and indexed implementation can make different choices.
    "cross-channel": {},
    "song only": {"song_query": "catalog song"},
}


def _channel_count(song_count: int) -> int:
    return max(16, min(64, song_count // 50))


def _make_rows(song_count: int, entry_count: int) -> tuple[
    list[tuple[str, str]],
    list[tuple[str, str, str, str, str, str]],
    list[tuple[str, str, str, str, str, str]],
    list[tuple[int, int, str, str, int, str, str, str, str, str]],
]:
    """Create channels, songs/videos, and entries without per-row SQL calls.

    Most rows have unique, non-similar titles.  The first three rows in every
    four-row cluster are related variants spread over one or two channels; the
    fourth row is unrelated.  This creates both fuzzy candidate work and
    negative comparisons while keeping the dataset deterministic.
    """

    channel_count = _channel_count(song_count)
    channels = [
        (f"channel-{index:03d}", f"Channel {index:03d}")
        for index in range(channel_count)
    ]
    songs: list[tuple[str, str, str, str, str, str]] = []
    videos: list[tuple[str, str, str, str, str, str]] = []
    entries: list[tuple[int, int, str, str, int, str, str, str, str, str]] = []
    base_entries, remainder = divmod(entry_count, song_count)
    next_entry_id = 1

    for song_index in range(song_count):
        cluster = song_index // 4
        variant = song_index % 4
        if variant < 2:
            channel_index = cluster % channel_count
            suffix = "x" if variant == 0 else "y"
            song_key = f"catalogsong{cluster:05d}{suffix}"
            artist_key = f"artist{cluster:05d}"
            title = f"Catalog Song {cluster:05d} {suffix.upper()}"
        elif variant == 2:
            channel_index = (cluster + 1) % channel_count
            # This is one edit away from the first two variants.  It exercises
            # the indexed same-artist fuzzy fallback across channels.
            song_key = f"catalogsong{cluster:05d}z"
            artist_key = f"artist{cluster:05d}"
            title = f"Catalog Song {cluster:05d} Z"
        else:
            channel_index = (song_index * 7 + 3) % channel_count
            song_key = f"uniquesong{song_index:05d}"
            artist_key = f"artistunique{song_index:05d}"
            title = f"Unrelated Song {song_index:05d}"

        channel_id = f"channel-{channel_index:03d}"
        normalized_title = title.casefold()
        artist = artist_key.title()
        video_id = f"video-{song_index:05d}"
        published_at = f"2025-01-{song_index % 28 + 1:02d}T00:00:00Z"
        songs.append(
            (
                channel_id,
                title,
                normalized_title,
                artist,
                song_key,
                artist_key,
            )
        )
        videos.append(
            (
                video_id,
                channel_id,
                f"Archive video {song_index:05d}",
                published_at,
                f"https://example.test/{video_id}",
                published_at,
            )
        )

        count = base_entries + (song_index < remainder)
        for seconds in range(count):
            entries.append(
                (
                    next_entry_id,
                    song_index + 1,
                    video_id,
                    f"{seconds // 60:02d}:{seconds % 60:02d}",
                    seconds,
                    title,
                    normalized_title,
                    "",
                    f"https://example.test/{video_id}#t={seconds}",
                    published_at,
                )
            )
            next_entry_id += 1

    return channels, songs, videos, entries


def build_benchmark_database(song_count: int, entry_count: int) -> SongDatabase:
    """Build an in-memory database using bulk inserts."""

    if song_count <= 0 or entry_count < song_count:
        raise ValueError("entry_count must be at least song_count and both must be positive")

    db = SongDatabase(":memory:")
    db.init_schema()
    channels, songs, videos, entries = _make_rows(song_count, entry_count)
    db.conn.executemany(
        "INSERT INTO channels (channel_id, channel_title) VALUES (?, ?)",
        channels,
    )
    db.conn.executemany(
        """
        INSERT INTO songs (
            channel_id, canonical_song_title, normalized_song_title, artist,
            song_key, artist_key, title_search, artist_search
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                channel_id,
                title,
                normalized_title,
                artist,
                song_key,
                artist_key,
                normalized_title,
                artist_key,
            )
            for channel_id, title, normalized_title, artist, song_key, artist_key in songs
        ],
    )
    db.conn.executemany(
        """
        INSERT INTO videos (
            video_id, channel_id, title, published_at, url, indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        videos,
    )
    db.conn.executemany(
        """
        INSERT INTO song_entries (
            id, song_id, video_id, timestamp_text, seconds, raw_song_title,
            normalized_song_title, source_comment, jump_url, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        entries,
    )
    db.conn.commit()
    return db


def _combine_cross_channel_groups_reference(
    groups: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Run the pre-index combiner against ``groups`` in their input order.

    The old implementation scanned one ``combined`` list.  Keeping that list
    here is essential: iterating the new song-key and artist-key buckets would
    reconstruct a different order whenever an exact key and an earlier fuzzy
    key share an artist.  This function intentionally contains no index
    lookup, so it remains a faithful reference for the indexed implementation.
    """

    combined: list[dict[str, object]] = []
    for group in groups:
        target = database_module.find_cross_channel_target(combined, group)
        if target is None:
            copied = dict(group)
            copied["title_keys"] = set(group.get("title_keys", set()))
            copied["artist_keys"] = set(group.get("artist_keys", set()))
            copied["normalized_title_keys"] = set(
                group.get("normalized_title_keys", set())
            )
            copied["entries"] = list(group.get("entries", []))
            copied["raw_titles"] = list(group.get("raw_titles", []))
            copied["song_ids"] = set(group.get("song_ids", set()))
            copied["source_channels"] = dict(
                group.get(
                    "source_channels",
                    {group.get("channel_id"): group.get("channel_title")},
                )
            )
            copied["entry_count"] = int(
                group.get("entry_count", len(copied["entries"]))
            )
            copied["channel_titles"] = {group.get("channel_title")}
            combined.append(copied)
            continue

        target["title_keys"].update(group.get("title_keys", set()))
        target["artist_keys"].update(group.get("artist_keys", set()))
        target.setdefault("normalized_title_keys", set()).update(
            group.get("normalized_title_keys", set())
        )
        target["entries"].extend(group.get("entries", []))
        target["raw_titles"].extend(group.get("raw_titles", []))
        target["song_ids"].update(group.get("song_ids", set()))
        target["source_channels"].update(
            group.get(
                "source_channels",
                {group.get("channel_id"): group.get("channel_title")},
            )
        )
        target["entry_count"] += int(
            group.get("entry_count", len(group.get("entries", [])))
        )
        target["channel_titles"].add(group.get("channel_title"))
        if len(str(group.get("song_title", ""))) < len(str(target.get("song_title", ""))):
            target["song_title"] = group.get("song_title", "")
        if not target.get("artist") and group.get("artist"):
            target["artist"] = group.get("artist", "")
            target["artist_key"] = group.get("artist_key", "")
        database_module.sort_search_entries(target["entries"])
        target["channels"] = database_module.make_channel_groups(target["entries"])

    for group in combined:
        group["channels"] = database_module.make_channel_groups(group.get("entries", []))
        group["channel_count"] = len(group["channels"]) or len(
            group.get("source_channels", {})
        )
    return combined


def _find_similar_group_key_reference(
    grouped: dict[tuple[str, str, str], dict[str, object]],
    channel_id: str,
    merge_key: str,
    artist_key: str,
) -> tuple[str, str, str]:
    """Use the pre-index channel-local scan without current helper overhead."""

    exact_key = (channel_id, merge_key, artist_key)
    if exact_key in grouped:
        return exact_key

    if not artist_key:
        for key, group in grouped.items():
            if key[0] == channel_id and str(group.get("song_key")) == merge_key:
                return key
        return exact_key

    unknown_key = (channel_id, merge_key, "")
    if unknown_key in grouped:
        return unknown_key

    for key, group in grouped.items():
        if key[0] != channel_id:
            continue
        if str(group.get("song_key")) != merge_key:
            continue
        if database_module.are_artist_keys_compatible(
            str(group.get("artist_key", "")), artist_key
        ):
            return key

    for key, group in grouped.items():
        if key[0] != channel_id:
            continue
        if group.get("artist_key") != artist_key:
            continue
        if database_module.is_similar_song_key(str(group["song_key"]), merge_key):
            return key
    return exact_key


def _run_search(
    db: SongDatabase,
    query: dict[str, str],
    reference: bool,
) -> tuple[str, int]:
    """Run one variant and return its grouping fingerprint and group count."""

    original_find = db._find_similar_group_key
    original_hydrate = db._hydrate_search_groups
    original_combine = database_module.combine_cross_channel_groups

    if reference:
        def reference_find(*args: object, **kwargs: object) -> tuple[str, str, str]:
            del args
            return _find_similar_group_key_reference(
                grouped=kwargs["grouped"],
                channel_id=kwargs["channel_id"],
                merge_key=kwargs["merge_key"],
                artist_key=kwargs["artist_key"],
            )

        db._find_similar_group_key = reference_find  # type: ignore[method-assign]
        # Patch the whole combiner instead of its indexed callback.  The old
        # callback received the complete ``combined`` list, whose order cannot
        # be recovered from the two new lookup buckets.
        database_module.combine_cross_channel_groups = _combine_cross_channel_groups_reference

    # Hydration is orthogonal to candidate selection and can account for most
    # of the runtime at 100000 entries.  Keep both variants on this identical
    # pre-hydration path while preserving the complete grouped result.
    db._hydrate_search_groups = lambda groups: None  # type: ignore[method-assign]
    try:
        groups = db.search_grouped(limit=None, offset=0, **query)
    finally:
        db._find_similar_group_key = original_find  # type: ignore[method-assign]
        db._hydrate_search_groups = original_hydrate  # type: ignore[method-assign]
        database_module.combine_cross_channel_groups = original_combine
    return fingerprint_groups(groups), len(groups)


def fingerprint_groups(groups: Iterable[dict[str, object]]) -> str:
    """Hash grouping semantics without depending on dict/set ordering."""

    canonical: list[dict[str, object]] = []
    for group in groups:
        source_channels = group.get("source_channels", {})
        channel_ids = sorted(str(value) for value in source_channels)
        canonical.append(
            {
                "group_key": f"{group.get('song_key', '')}::{group.get('artist_key', '')}",
                "song_ids": sorted(int(value) for value in group.get("song_ids", set())),
                "entry_count": int(group.get("entry_count", 0) or 0),
                "channel_ids": channel_ids,
                "title_keys": sorted(str(value) for value in group.get("title_keys", set())),
                "artist_keys": sorted(str(value) for value in group.get("artist_keys", set())),
            }
        )
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _timed_search(
    db: SongDatabase,
    query: dict[str, str],
    reference: bool,
) -> tuple[float, str, int]:
    started = time.perf_counter()
    result, group_count = _run_search(db, query, reference)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return elapsed_ms, result, group_count


def cross_channel_collision_probe() -> dict[str, object]:
    """Check first-seen order for an exact/fuzzy cross-channel collision."""

    fuzzy = _collision_group("fuzzy-first", "catalogsongbetx", "artist")
    exact = _collision_group("exact-later", "catalogsongbeta", "artist")
    # The production combiner attaches these ordinals before indexing.  Keep
    # the index buckets deliberately in the awkward order below so this probe
    # verifies that indexed lookup honors global first-seen order rather than
    # whichever bucket happens to be visited first.
    fuzzy["_cross_channel_order"] = 0
    exact["_cross_channel_order"] = 1
    candidate = _collision_group("candidate", "catalogsongbeta", "artist")
    indexed = database_module.find_cross_channel_target_indexed(
        {exact["song_key"]: [exact], fuzzy["song_key"]: [fuzzy]},
        {"artist": [fuzzy, exact]},
        candidate,
    )
    linear = database_module.find_cross_channel_target([fuzzy, exact], candidate)
    indexed_label = indexed.get("label") if indexed else None
    linear_label = linear.get("label") if linear else None
    return {
        "indexed_label": indexed_label,
        "linear_label": linear_label,
        "equivalent": indexed_label == linear_label,
    }


def _collision_group(label: str, song_key: str, artist_key: str) -> dict[str, object]:
    """Build the smallest complete group accepted by the production combiner."""

    return {
        "label": label,
        "channel_id": label,
        "channel_title": label,
        "song_key": song_key,
        "artist_key": artist_key,
        "artist_keys": {artist_key},
        "title_keys": {song_key},
        "normalized_title_keys": {song_key},
        "song_title": song_key,
        "artist": artist_key,
        "raw_titles": [song_key],
        "entries": [],
        "song_ids": {1 if label == "fuzzy-first" else 2},
        "entry_count": 1,
        "latest_published_at": "2025-01-01T00:00:00Z",
        "source_channels": {label: label},
    }


def _stats(values: list[float]) -> dict[str, float]:
    return {
        "p50_ms": round(statistics.median(values), 3),
        "max_ms": round(max(values), 3),
    }


def run_benchmark(repeats: int = DEFAULT_REPEATS) -> dict[str, object]:
    if repeats <= 0:
        raise ValueError("repeats must be positive")

    output: dict[str, object] = {
        "command": f"python scripts/benchmark_search.py --repeats {repeats}",
        "seed": SEED,
        "repeats": repeats,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
        "collision_probe": cross_channel_collision_probe(),
        "sizes": [],
    }
    size_results: list[dict[str, object]] = []
    for size in BENCHMARK_SIZES:
        db = build_benchmark_database(size.songs, size.entries)
        try:
            cases: list[dict[str, object]] = []
            for case_name, query in BENCHMARK_CASES.items():
                # Warm both paths once so schema and Python bytecode setup do
                # not become part of either p50.
                _timed_search(db, query, reference=False)
                _timed_search(db, query, reference=True)
                timings: dict[str, list[float]] = {"indexed": [], "reference": []}
                fingerprints: dict[str, list[str]] = {"indexed": [], "reference": []}
                group_counts: dict[str, int] = {}
                for _ in range(repeats):
                    for variant, reference in (("indexed", False), ("reference", True)):
                        elapsed_ms, fingerprint, group_count = _timed_search(
                            db, query, reference
                        )
                        timings[variant].append(elapsed_ms)
                        fingerprints[variant].append(fingerprint)
                        group_counts[variant] = group_count
                equal = fingerprints["indexed"] == fingerprints["reference"]
                cases.append(
                    {
                        "case": case_name,
                        "query": query,
                        "groups": group_counts,
                        "result_fingerprints": fingerprints,
                        "fingerprints_equal": equal,
                        "indexed": _stats(timings["indexed"]),
                        "reference": _stats(timings["reference"]),
                        "reference_over_indexed_p50": round(
                            statistics.median(timings["reference"])
                            / max(statistics.median(timings["indexed"]), 0.001),
                            3,
                        ),
                    }
                )
            size_results.append(
                {
                    "name": size.name,
                    "songs": size.songs,
                    "entries": size.entries,
                    "cases": cases,
                }
            )
        finally:
            db.close()
    output["sizes"] = size_results
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repeats",
        type=int,
        default=DEFAULT_REPEATS,
        help="Timed repetitions per implementation and query case (default: 3).",
    )
    return parser


def benchmark_failures(result: dict[str, object]) -> list[str]:
    """Return invariant failures that make benchmark output unusable."""

    failures: list[str] = []
    collision_probe = result.get("collision_probe")
    if not isinstance(collision_probe, dict) or not collision_probe.get("equivalent"):
        failures.append("collision probe is not equivalent")

    sizes = result.get("sizes")
    if not isinstance(sizes, list):
        return failures + ["benchmark output has no sizes"]
    for size in sizes:
        if not isinstance(size, dict):
            failures.append("benchmark output contains an invalid size result")
            continue
        size_name = str(size.get("name", "<unnamed size>"))
        cases = size.get("cases")
        if not isinstance(cases, list):
            failures.append(f"{size_name}: benchmark output has no cases")
            continue
        for case in cases:
            if not isinstance(case, dict):
                failures.append(f"{size_name}: invalid case result")
                continue
            case_name = str(case.get("case", "<unnamed case>"))
            if not case.get("fingerprints_equal"):
                failures.append(f"{size_name} / {case_name}: fingerprints differ")
            fingerprints = case.get("result_fingerprints")
            if not isinstance(fingerprints, dict):
                failures.append(f"{size_name} / {case_name}: missing fingerprints")
                continue
            for variant in ("indexed", "reference"):
                values = fingerprints.get(variant)
                if not isinstance(values, list) or not values:
                    failures.append(
                        f"{size_name} / {case_name}: missing {variant} fingerprint"
                    )
                elif len(set(values)) != 1:
                    failures.append(
                        f"{size_name} / {case_name}: {variant} fingerprints vary"
                    )
    return failures


def main() -> int:
    args = build_parser().parse_args()
    result = run_benchmark(args.repeats)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    failures = benchmark_failures(result)
    if failures:
        print("Benchmark validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
