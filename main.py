from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Callable

from config import get_database_path, get_youtube_api_key
from database import SongDatabase
from timeline_parser import select_best_timeline_comment
from search import search_songs
from youtube_client import (
    CommentsDisabledError,
    QuotaExceededError,
    VideoInfo,
    YouTubeAPIError,
    YouTubeClient,
    looks_like_song_stream_title,
)


DEFAULT_MAX_COMMENTS = 100
DEFAULT_RECENT_RESCAN_DAYS = 30
DEFAULT_RECENT_RECHECK_DAYS = 1


def configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


@dataclass
class IndexStats:
    videos_seen: int = 0
    videos_indexed: int = 0
    videos_skipped: int = 0
    videos_failed: int = 0
    comments_seen: int = 0
    timeline_comments: int = 0
    entries_inserted: int = 0


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
        help="Scan recent uploads without stopping at existing videos; retry incomplete work.",
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
        help="Safety cap for recent uploads to inspect. Default: 1000.",
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
    db = SongDatabase(get_database_path(args.db))
    db.init_schema()

    try:
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
            print_index_stats(stats)
            return 0

        if args.command == "index-channel":
            stats = run_index_channel(
                db=db,
                client=client,
                channel=args.channel,
                max_videos=args.max_videos,
                max_comments=args.max_comments,
                include_all_videos=args.include_all_videos,
            )
            print_index_stats(stats)
            return 0

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
            print_index_stats(stats)
            return 0

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
            print_index_stats(stats)
            return 0

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
        db.close()


def run_index_channel(
    db: SongDatabase,
    client: YouTubeClient,
    channel: str,
    max_videos: int,
    max_comments: int,
    include_all_videos: bool,
    incremental: bool = False,
    backfill: bool = False,
    reset_backfill: bool = False,
    on_message: Callable[[str], None] | None = None,
    on_stats: Callable[[IndexStats], None] | None = None,
    recent_rescan_days: int = DEFAULT_RECENT_RESCAN_DAYS,
) -> IndexStats:
    log = on_message or print

    channel_info = client.get_channel(channel)
    db.upsert_channel(channel_info.channel_id, channel_info.title)

    if reset_backfill:
        db.reset_backfill(channel_info.channel_id)

    recent_rescan_days = max(0, int(recent_rescan_days))
    recent_recheck_days = DEFAULT_RECENT_RECHECK_DAYS if incremental else None
    backfill_state = db.get_backfill_state(channel_info.channel_id) if backfill else None
    backfill_complete = bool(backfill_state is not None and backfill_state["backfill_complete"])

    log(f"Channel: {channel_info.title} ({channel_info.channel_id})")
    if backfill:
        if backfill_complete:
            log("Historical backfill is complete; checking any pending retries.")
        elif backfill_state is not None and backfill_state["backfill_before_published_at"]:
            log(
                "Resuming historical backfill before "
                f"{backfill_state['backfill_before_published_at']} "
                f"({backfill_state['backfill_before_video_id']})"
            )
        else:
            log("Starting historical backfill from the newest upload.")
    elif incremental:
        log("Incremental update scans recent uploads without stopping at existing videos.")
        log(
            "Completed videos are skipped; failed videos use bounded exponential retry "
            f"backoff, and no-timeline videos from the last {recent_rescan_days} days "
            f"are rechecked every {recent_recheck_days} day(s)."
        )
    else:
        log("Scanning uploads from the newest position; existing completed videos are skipped.")

    stats = IndexStats()
    retried_video_ids: set[str] = set()
    retry_rows = db.list_videos_for_retry(
        channel_info.channel_id,
        max_videos,
        recent_rescan_days=recent_rescan_days if incremental else 0,
        recent_after_days=recent_recheck_days,
    )
    for row in retry_rows:
        retried_video_ids.add(row["video_id"])
        if not include_all_videos and not looks_like_song_stream_title(row["title"]):
            db.mark_video_index_status(row["video_id"], "filtered")
            stats.videos_skipped += 1
            continue
        stats.videos_seen += 1
        log(f"Retrying: {row['title']} ({row['video_id']})")
        video_stats = index_upload(
            db,
            client,
            VideoInfo(
                video_id=row["video_id"],
                title=row["title"],
                channel_id=row["channel_id"],
                channel_title=row["channel_title"],
                published_at=row["published_at"],
                duration_seconds=row["duration_seconds"],
            ),
            max_comments,
            on_message=log,
        )
        merge_stats(stats, video_stats)
        notify_stats(on_stats, stats)

    if backfill and backfill_complete:
        if retry_rows:
            log("Historical backfill remains complete; pending retries were processed.")
        else:
            log("Historical backfill is already complete; no pending retries are due.")
        return stats

    cursor = backfill_state if backfill else None
    past_cursor = not backfill or cursor is None or not cursor["backfill_before_published_at"]
    processed_in_batch = 0
    uploads_exhausted = True
    playlist_limit = None if backfill else max_videos
    for upload in client.iter_uploads_playlist(
        channel_info.uploads_playlist_id,
        max_videos=playlist_limit,
    ):
        if backfill and not past_cursor:
            cursor_published_at = cursor["backfill_before_published_at"]
            if upload.video_id == cursor["backfill_before_video_id"]:
                past_cursor = True
                continue
            if upload.published_at and cursor_published_at and upload.published_at < cursor_published_at:
                past_cursor = True
            else:
                continue

        if backfill and processed_in_batch >= max_videos:
            uploads_exhausted = False
            break

        stats.videos_seen += 1
        processed_in_batch += 1
        db.upsert_video(
            upload.video_id,
            upload.channel_id,
            upload.title,
            upload.published_at,
        )
        state = db.get_video_index_state(upload.video_id)

        if upload.video_id in retried_video_ids:
            # A retry row was already attempted at the beginning of this run.
            # Do not immediately issue a second request when the same video is
            # also inside the recent upload window; backoff must apply to the
            # whole run, not only to the next run.
            if backfill:
                db.update_backfill_cursor(
                    channel_info.channel_id,
                    upload.published_at,
                    upload.video_id,
                )
            notify_stats(on_stats, stats)
            continue

        if not include_all_videos and not looks_like_song_stream_title(upload.title):
            db.mark_video_index_status(upload.video_id, "filtered")
            stats.videos_skipped += 1
            if backfill:
                db.update_backfill_cursor(
                    channel_info.channel_id,
                    upload.published_at,
                    upload.video_id,
                )
            notify_stats(on_stats, stats)
            continue

        if not should_process_video(
            db,
            upload.video_id,
            recent_rescan_days=recent_rescan_days if incremental else 0,
            recent_after_days=recent_recheck_days,
        ):
            if state is not None and state["index_status"] in {
                "indexed",
                "filtered",
                "no_timeline",
                "comments_disabled",
            }:
                stats.videos_skipped += 1
            if backfill:
                db.update_backfill_cursor(
                    channel_info.channel_id,
                    upload.published_at,
                    upload.video_id,
                )
            notify_stats(on_stats, stats)
            continue

        log(f"Indexing: {upload.title} ({upload.video_id})")
        try:
            video_stats = index_upload(
                db,
                client,
                upload,
                max_comments,
                on_message=log,
            )
        except QuotaExceededError:
            # The video is already marked retry. Persist the cursor before the
            # task exits so a later run can retry it without blocking older
            # uploads in the historical scan.
            if backfill:
                db.update_backfill_cursor(
                    channel_info.channel_id,
                    upload.published_at,
                    upload.video_id,
                )
                uploads_exhausted = False
            raise
        merge_stats(stats, video_stats)
        notify_stats(on_stats, stats)
        if backfill:
            # A failed video remains in the retry queue, but must not block the
            # cursor from progressing through the rest of the channel.
            db.update_backfill_cursor(
                channel_info.channel_id,
                upload.published_at,
                upload.video_id,
            )
            if video_stats.videos_failed:
                log(
                    f"  continuing historical scan; retry remains queued for "
                    f"{upload.video_id}"
                )

    if backfill and uploads_exhausted:
        db.mark_backfill_complete(channel_info.channel_id)
        log("Historical backfill reached the end of the uploads playlist.")

    return stats


def notify_stats(callback: Callable[[IndexStats], None] | None, stats: IndexStats) -> None:
    if callback is not None:
        callback(stats)


def should_process_video(
    db: SongDatabase,
    video_id: str,
    recent_rescan_days: int = 0,
    recent_after_days: int | None = None,
) -> bool:
    state = db.get_video_index_state(video_id)
    if state is None:
        return True
    status = state["index_status"]
    if status in {"discovered", "retry", "indexing"}:
        return db.video_retry_is_due(video_id)
    if status == "no_timeline":
        return db.video_needs_recheck(
            video_id,
            after_days=7,
            recent_rescan_days=recent_rescan_days,
            recent_after_days=recent_after_days,
        )
    if status == "comments_disabled":
        return db.video_needs_recheck(video_id, after_days=30)
    if status == "filtered":
        return True
    return False


def index_upload(
    db: SongDatabase,
    client: YouTubeClient,
    upload: VideoInfo,
    max_comments: int | None,
    on_message: Callable[[str], None] | None = None,
) -> IndexStats:
    log = on_message or print
    db.upsert_video(
        upload.video_id,
        upload.channel_id,
        upload.title,
        upload.published_at,
    )
    db.begin_video_index(upload.video_id)
    try:
        full_video = client.get_video(upload.video_id)
    except QuotaExceededError:
        db.mark_video_index_status(upload.video_id, "retry", "YouTube quota exceeded")
        raise
    except YouTubeAPIError as exc:
        db.mark_video_index_status(upload.video_id, "retry", str(exc))
        log(f"  failed and queued for retry: {upload.video_id} ({exc})")
        return IndexStats(videos_seen=1, videos_failed=1)
    return index_video(
        db,
        client,
        full_video,
        max_comments,
        on_message=log,
        attempt_started=True,
    )


def index_video(
    db: SongDatabase,
    client: YouTubeClient,
    video: VideoInfo,
    max_comments: int | None,
    on_message: Callable[[str], None] | None = None,
    attempt_started: bool = False,
) -> IndexStats:
    log = on_message or print
    stats = IndexStats(videos_seen=1)
    db.upsert_channel(video.channel_id, video.channel_title)
    db.upsert_video(
        video.video_id,
        video.channel_id,
        video.title,
        video.published_at,
        duration_seconds=video.duration_seconds,
    )
    if not attempt_started:
        db.begin_video_index(video.video_id)

    try:
        comments = client.get_comments(video.video_id, max_comments=max_comments)
        comment_texts = []
        for comment in comments:
            stats.comments_seen += 1
            comment_texts.append(comment.text)

        candidate = select_best_timeline_comment(
            comment_texts,
            duration_seconds=video.duration_seconds,
        )
        if candidate:
            stats.timeline_comments = 1
            stats.entries_inserted += db.replace_song_entries_for_video(
                video_id=video.video_id,
                entries=candidate.entries,
                source_comment=candidate.comment_text,
            )
            db.mark_video_index_status(video.video_id, "indexed", comments_fetched=True)
        else:
            db.mark_video_index_status(video.video_id, "no_timeline", comments_fetched=True)
        stats.videos_indexed = 1
    except CommentsDisabledError:
        stats.videos_skipped += 1
        db.mark_video_index_status(video.video_id, "comments_disabled", "Comments are disabled")
        log(f"Comments disabled for video: {video.video_id}")
    except QuotaExceededError:
        db.mark_video_index_status(video.video_id, "retry", "YouTube quota exceeded")
        raise
    except YouTubeAPIError as exc:
        stats.videos_failed = 1
        db.mark_video_index_status(video.video_id, "retry", str(exc))
        log(f"  failed and queued for retry: {video.video_id} ({exc})")

    return stats


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


def merge_stats(total: IndexStats, child: IndexStats) -> None:
    total.videos_indexed += child.videos_indexed
    total.videos_skipped += child.videos_skipped
    total.videos_failed += child.videos_failed
    total.comments_seen += child.comments_seen
    total.timeline_comments += child.timeline_comments
    total.entries_inserted += child.entries_inserted


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
