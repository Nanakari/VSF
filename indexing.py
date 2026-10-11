"""Indexing service shared by the CLI and local setup application.

This module owns scan/retry orchestration. It does not read environment
configuration, start web servers, or synchronize the hosted site.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from database import SongDatabase
from timeline_parser import select_best_timeline_comment
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


@dataclass
class IndexStats:
    videos_seen: int = 0
    videos_indexed: int = 0
    videos_skipped: int = 0
    videos_failed: int = 0
    comments_seen: int = 0
    timeline_comments: int = 0
    entries_inserted: int = 0


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
    existing_channel = db.get_channel(channel_info.channel_id)
    db.upsert_channel(channel_info.channel_id, channel_info.title)

    if reset_backfill:
        db.reset_backfill(channel_info.channel_id)

    recent_rescan_days = max(0, int(recent_rescan_days))
    recent_recheck_days = DEFAULT_RECENT_RECHECK_DAYS if incremental else None
    backfill_state = db.get_backfill_state(channel_info.channel_id) if backfill else None
    backfill_complete = bool(backfill_state is not None and backfill_state["backfill_complete"])
    latest_published_at = (
        db.begin_incremental_scan(channel_info.channel_id)
        if incremental
        else None
    )

    log(f"Channel: {channel_info.title} ({channel_info.channel_id})")
    if existing_channel is not None:
        log("频道已存在，仍会重新查询其上传列表并继续更新。")
    else:
        log("发现新频道，开始建立索引。")
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
        if latest_published_at:
            log(
                "增量更新以本轮起始发布时间 "
                f"{latest_published_at} 为边界，只处理之后的新上传，"
                "并检查边界视频避免遗漏。"
            )
        else:
            log("数据库中还没有该频道的视频，将从最新上传开始建立索引。")
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
        include_filtered=include_all_videos,
    )
    for row in retry_rows:
        retried_video_ids.add(row["video_id"])
        stats.videos_seen += 1
        if not include_all_videos and not looks_like_song_stream_title(row["title"]):
            db.mark_video_index_status(row["video_id"], "filtered")
            stats.videos_skipped += 1
            notify_stats(on_stats, stats)
            continue
        log(f"Retrying: {row['title']} ({row['video_id']})")
        notify_stats(on_stats, stats)
        try:
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
        except QuotaExceededError:
            stats.videos_failed += 1
            notify_stats(on_stats, stats)
            raise
        merge_stats(stats, video_stats)
        notify_stats(on_stats, stats)

    if backfill and backfill_complete:
        if retry_rows:
            log("Historical backfill remains complete; pending retries were processed.")
        else:
            log("Historical backfill is already complete; no pending retries are due.")
        return stats

    cursor = backfill_state if backfill else None
    past_cursor = not backfill or cursor is None or not cursor["backfill_before_video_id"]
    processed_in_batch = 0
    uploads_exhausted = True
    playlist_limit = None if backfill or incremental else max_videos
    for upload in client.iter_uploads_playlist(
        channel_info.uploads_playlist_id,
        max_videos=playlist_limit,
    ):
        if incremental and latest_published_at and upload.published_at:
            if upload.published_at < latest_published_at:
                log(
                    "已到达本轮起始发布时间之前的上传，停止本次增量检索。"
                )
                break

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

        if incremental:
            # Discover each upload once. Known rows consume the budget only
            # when eligible for indexing under the current title/filter. This
            # lets capped runs pass filtered uploads while still rechecking a
            # renamed video or a video enabled by include_all_videos.
            known = db.get_video_index_state(upload.video_id)
            needs_work = known is None or (
                (include_all_videos or looks_like_song_stream_title(upload.title))
                and upload.video_id not in retried_video_ids
                and should_process_video(
                    db, upload.video_id,
                    recent_rescan_days=recent_rescan_days,
                    recent_after_days=recent_recheck_days,
                )
            )
            if needs_work:
                if processed_in_batch >= max_videos:
                    uploads_exhausted = False
                    break
                processed_in_batch += 1
        else:
            processed_in_batch += 1
        if upload.video_id not in retried_video_ids:
            stats.videos_seen += 1
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
            # A narrower filter must not erase a successful include-all index.
            if state is None or state["index_status"] != "indexed":
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
        notify_stats(on_stats, stats)
        try:
            video_stats = index_upload(
                db,
                client,
                upload,
                max_comments,
                on_message=log,
            )
        except QuotaExceededError:
            stats.videos_failed += 1
            notify_stats(on_stats, stats)
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

    if incremental and uploads_exhausted:
        db.finish_incremental_scan(channel_info.channel_id)

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


def merge_stats(total: IndexStats, child: IndexStats) -> None:
    total.videos_indexed += child.videos_indexed
    total.videos_skipped += child.videos_skipped
    total.videos_failed += child.videos_failed
    total.comments_seen += child.comments_seen
    total.timeline_comments += child.timeline_comments
    total.entries_inserted += child.entries_inserted
