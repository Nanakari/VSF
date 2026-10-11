from __future__ import annotations

import argparse
import sys
from pathlib import Path

from config import (
    get_app_dir,
    get_database_path,
    get_site_base_url,
    get_site_seed_token,
    get_youtube_api_key,
)
from database import SongDatabase
# Keep service exports available to existing callers of main.py.
from indexing import (
    DEFAULT_MAX_COMMENTS,
    DEFAULT_RECENT_RESCAN_DAYS,
    DEFAULT_RECENT_RECHECK_DAYS,
    IndexStats,
    index_upload,
    index_video,
    merge_stats,
    notify_stats,
    run_index_channel,
    should_process_video,
)
from search import search_songs
from site_sync import sync_database_to_site
from youtube_client import (
    QuotaExceededError,
    YouTubeAPIError,
    YouTubeClient,
)


def configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and search a local VTuber YouTube song timeline index."
    )
    parser.add_argument(
        "--db",
        help="SQLite database path. Defaults to vtuber_songs.sqlite3 next to main.py.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    index_video = subparsers.add_parser("index-video", help="Index one YouTube video by ID.")
    index_video.add_argument("--video-id", required=True, help="YouTube video ID.")
    index_video.add_argument(
        "--max-comments",
        type=int,
        default=DEFAULT_MAX_COMMENTS,
        help=f"Maximum top-level comments to scan. Default: {DEFAULT_MAX_COMMENTS}.",
    )

    index_channel = subparsers.add_parser(
        "index-channel",
        help="Index likely singing/karaoke videos from a channel handle or channel ID.",
    )
    index_channel.add_argument(
        "--channel",
        required=True,
        help='Channel handle such as "@Shairu_Vsinger" or channel ID such as "UC...".',
    )
    index_channel.add_argument(
        "--max-videos",
        type=int,
        default=100,
        help="Maximum recent uploads to inspect. Default: 100.",
    )
    index_channel.add_argument(
        "--max-comments",
        type=int,
        default=DEFAULT_MAX_COMMENTS,
        help=f"Maximum top-level comments to scan per video. Default: {DEFAULT_MAX_COMMENTS}.",
    )
    index_channel.add_argument(
        "--include-all-videos",
        action="store_true",
        help="Do not filter by singing/karaoke keywords in the title.",
    )

    update_channel = subparsers.add_parser(
        "update-channel",
        help="Update uploads after the channel's latest local publication; retry incomplete work.",
    )
    update_channel.add_argument(
        "--channel",
        required=True,
        help='Channel handle such as "@Shairu_Vsinger" or channel ID such as "UC...".',
    )
    update_channel.add_argument(
        "--max-videos",
        type=int,
        default=1000,
        help="Maximum pending uploads to process per incremental batch. Default: 1000.",
    )
    update_channel.add_argument(
        "--max-comments",
        type=int,
        default=DEFAULT_MAX_COMMENTS,
        help=f"Maximum top-level comments to scan per video. Default: {DEFAULT_MAX_COMMENTS}.",
    )
    update_channel.add_argument(
        "--include-all-videos",
        action="store_true",
        help="Do not filter by singing/karaoke keywords in the title.",
    )
    update_channel.add_argument(
        "--rescan-days",
        type=int,
        default=DEFAULT_RECENT_RESCAN_DAYS,
        help=(
            "For recent videos without a timeline, retry after each interval day "
            f"within this window. Default: {DEFAULT_RECENT_RESCAN_DAYS}."
        ),
    )

    backfill_channel = subparsers.add_parser(
        "backfill-channel",
        help="Resume historical channel indexing from the saved backfill cursor.",
    )
    backfill_channel.add_argument(
        "--channel",
        required=True,
        help='Channel handle such as "@Shairu_Vsinger" or channel ID such as "UC...".',
    )
    backfill_channel.add_argument(
        "--max-videos",
        type=int,
        default=1000,
        help="Maximum older uploads to process in this batch. Default: 1000.",
    )
    backfill_channel.add_argument(
        "--max-comments",
        type=int,
        default=DEFAULT_MAX_COMMENTS,
        help=f"Maximum top-level comments to scan per video. Default: {DEFAULT_MAX_COMMENTS}.",
    )
    backfill_channel.add_argument(
        "--include-all-videos",
        action="store_true",
        help="Do not filter by singing/karaoke keywords in the title.",
    )
    backfill_channel.add_argument(
        "--reset",
        action="store_true",
        help="Reset the saved historical cursor before starting.",
    )

    search = subparsers.add_parser("search", help="Search indexed song titles.")
    search.add_argument("query", help="Song title keyword.")
    search.add_argument("--channel", help="Optional channel title keyword or channel ID filter.")
    search.add_argument("--artist", help="Optional artist or author filter.")
    search.add_argument("--limit", type=int, default=25, help="Maximum results. Default: 25.")

    list_songs = subparsers.add_parser(
        "list-songs",
        help="List normalized songs grouped under channels.",
    )
    list_songs.add_argument(
        "--channel",
        help="Optional channel title keyword or channel ID filter.",
    )
    list_songs.add_argument("--limit", type=int, default=100, help="Maximum rows. Default: 100.")

    subparsers.add_parser(
        "cleanup-non-songs",
        help="Remove indexed timeline entries that look like MC/announcements/non-song markers.",
    )
    subparsers.add_parser(
        "cleanup-best-timelines",
        help="Keep only the best timeline comment for each indexed video.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_output_encoding()
    args = build_parser().parse_args(argv)
    database_path = get_database_path(args.db)
    db: SongDatabase | None = SongDatabase(database_path)
    db.init_schema()

    def finish_index_command(stats: IndexStats) -> int:
        nonlocal db
        if db is not None:
            db.close()
            db = None
        print_index_stats(stats)
        sync_indexed_database(database_path)
        return 0

    try:
        if db is None:
            raise RuntimeError("Database connection is unavailable")

        if args.command == "search":
            return run_search(db, args.query, args.limit, args.channel, args.artist)

        if args.command == "list-songs":
            return run_list_songs(db, args.channel, args.limit)

        if args.command == "cleanup-non-songs":
            removed = db.prune_non_song_entries()
            print(f"Removed {removed} non-song timeline entries.")
            return 0

        if args.command == "cleanup-best-timelines":
            result = db.rebuild_best_timeline_comments()
            print(f"Videos rebuilt: {result['videos_changed']}")
            print(f"Entries before: {result['entries_before']}")
            print(f"Entries after: {result['entries_after']}")
            print(f"Entries removed: {result['entries_removed']}")
            return 0

        client = YouTubeClient(get_youtube_api_key())
        if args.command == "index-video":
            video = client.get_video(args.video_id)
            stats = index_video(db, client, video, args.max_comments)
            return finish_index_command(stats)

        if args.command == "index-channel":
            stats = run_index_channel(
                db=db,
                client=client,
                channel=args.channel,
                max_videos=args.max_videos,
                max_comments=args.max_comments,
                include_all_videos=args.include_all_videos,
            )
            return finish_index_command(stats)

        if args.command == "update-channel":
            stats = run_index_channel(
                db=db,
                client=client,
                channel=args.channel,
                max_videos=args.max_videos,
                max_comments=args.max_comments,
                include_all_videos=args.include_all_videos,
                incremental=True,
                recent_rescan_days=max(args.rescan_days, 0),
            )
            return finish_index_command(stats)

        if args.command == "backfill-channel":
            stats = run_index_channel(
                db=db,
                client=client,
                channel=args.channel,
                max_videos=args.max_videos,
                max_comments=args.max_comments,
                include_all_videos=args.include_all_videos,
                backfill=True,
                reset_backfill=args.reset,
            )
            return finish_index_command(stats)

        raise RuntimeError(f"Unknown command: {args.command}")
    except QuotaExceededError as exc:
        print(f"Quota exceeded: {exc}", file=sys.stderr)
        return 2
    except YouTubeAPIError as exc:
        print(f"YouTube API error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        if db is not None:
            db.close()


def sync_indexed_database(database_path: Path) -> None:
    """Synchronize a successfully updated local database when configured."""
    base_url = get_site_base_url().strip().rstrip("/")
    seed_token = get_site_seed_token().strip()
    if not base_url and not seed_token:
        return
    if not base_url or not seed_token:
        raise RuntimeError(
            "SITE_BASE_URL and SITE_SEED_TOKEN must both be configured for site sync."
        )

    print("Syncing the completed local index to the site...")
    manifest = sync_database_to_site(
        database_path,
        base_url,
        seed_token,
        get_app_dir() / "build" / "d1-seed",
        on_message=print,
    )
    tables = manifest.get("tables", {})
    mode = manifest.get("sync_mode", "full")
    print(
        f"Site sync complete ({mode}; "
        f"{tables.get('channels', 0)} channels)."
    )


def run_search(
    db: SongDatabase,
    query: str,
    limit: int,
    channel: str | None = None,
    artist: str | None = None,
) -> int:
    results = search_songs(
        db,
        query,
        limit=limit,
        channel_query=channel,
        artist_query=artist,
    )
    if not results:
        print(f'No results for "{query}".')
        return 0

    for index, row in enumerate(results, start=1):
        published_at = row.get("published_at") or "unknown date"
        print(f"{index}. {row['raw_song_title']}  [{row['timestamp_text']}]")
        print(f"   Video: {row['video_title']}")
        print(f"   Channel: {row['channel_title']} | Published: {published_at}")
        print(f"   Link: {row['jump_url']}")
    return 0


def run_list_songs(db: SongDatabase, channel: str | None, limit: int) -> int:
    rows = db.list_songs(channel_query=channel, limit=limit)
    if not rows:
        print("No songs found.")
        return 0

    current_channel_id = None
    for row in rows:
        if row["channel_id"] != current_channel_id:
            current_channel_id = row["channel_id"]
            print(f"\n{row['channel_title']} ({row['channel_id']})")
        print(
            f"  - {row['canonical_song_title']} "
            f"[{row['video_count']} videos, {row['entry_count']} entries]"
        )
    return 0


def print_index_stats(stats: IndexStats) -> None:
    print()
    print("Done.")
    print(f"Videos seen: {stats.videos_seen}")
    print(f"Videos indexed: {stats.videos_indexed}")
    print(f"Videos skipped: {stats.videos_skipped}")
    print(f"Videos failed and queued for retry: {stats.videos_failed}")
    print(f"Comments scanned: {stats.comments_seen}")
    print(f"Timeline comments found: {stats.timeline_comments}")
    print(f"New song entries inserted: {stats.entries_inserted}")


if __name__ == "__main__":
    raise SystemExit(main())
