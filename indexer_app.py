from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
import time
import webbrowser

from flask import Flask, jsonify, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from config import get_app_dir, get_database_path, get_resource_dir
from database import SongDatabase
from main import IndexStats, index_video, merge_stats
from youtube_client import (
    CommentsDisabledError,
    QuotaExceededError,
    YouTubeAPIError,
    YouTubeClient,
    looks_like_song_stream_title,
)


DEFAULT_MAX_VIDEOS = 1000
DEFAULT_MAX_COMMENTS = 100
SETUP_PORT = 5001
SHUTDOWN_DELAY_SECONDS = 3
AUTO_EXIT_ENABLED = bool(getattr(sys, "frozen", False))

job_lock = threading.Lock()
job_state: dict[str, object] = {
    "running": False,
    "done": False,
    "ok": False,
    "message": "等待开始索引。",
    "log": [],
    "stats": {},
}
active_clients: set[str] = set()
active_clients_lock = threading.Lock()
shutdown_timer: threading.Timer | None = None


def get_log_path() -> Path:
    candidates = [
        get_app_dir() / "logs" / "setup.log",
        Path(os.getenv("LOCALAPPDATA", Path.home())) / "VTuberSongFinder" / "logs" / "setup.log",
    ]
    for candidate in candidates:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return Path.home() / "VTuberSongFinder-setup.log"


LOG_PATH = get_log_path()


def setup_logging() -> None:
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)


setup_logging()
logger = logging.getLogger(__name__)
resource_dir = get_resource_dir()
app = Flask(
    __name__,
    template_folder=str(resource_dir / "templates"),
    static_folder=str(resource_dir / "static"),
)
app.logger.handlers.clear()
app.logger.propagate = True
logging.getLogger("werkzeug").setLevel(logging.INFO)


@app.route("/")
def index():
    return render_template(
        "indexer.html",
        default_max_videos=DEFAULT_MAX_VIDEOS,
        default_max_comments=DEFAULT_MAX_COMMENTS,
        auto_exit_enabled=AUTO_EXIT_ENABLED,
    )


@app.post("/start")
def start_index():
    api_key = request.form.get("api_key", "").strip()
    channel = request.form.get("channel", "").strip()
    include_all = request.form.get("include_all") == "on"
    save_key = request.form.get("save_key") == "on"
    max_videos = parse_positive_int(request.form.get("max_videos"), DEFAULT_MAX_VIDEOS)
    max_comments = parse_positive_int(request.form.get("max_comments"), DEFAULT_MAX_COMMENTS)

    if not api_key:
        return jsonify({"ok": False, "message": "请填写 YouTube Data API Key。"}), 400
    if not channel:
        return jsonify({"ok": False, "message": "请填写频道 URL、handle 或 channel ID。"}), 400

    with job_lock:
        if job_state["running"]:
            return jsonify({"ok": False, "message": "已有索引任务正在运行。"}), 409
        reset_job_state()
        job_state["running"] = True
        job_state["message"] = "索引任务已开始。"

    if save_key:
        write_env_api_key(api_key)

    worker = threading.Thread(
        target=run_index_job,
        args=(api_key, channel, max_videos, max_comments, include_all),
        daemon=True,
    )
    worker.start()
    return jsonify({"ok": True, "message": "索引任务已开始。"})


@app.get("/status")
def status():
    with job_lock:
        return jsonify(job_state)


@app.post("/client-ping")
def client_ping():
    client_id = get_client_id()
    if client_id:
        with active_clients_lock:
            active_clients.add(client_id)
    return ("", 204)


@app.post("/client-close")
def client_close():
    client_id = get_client_id()
    if client_id:
        with active_clients_lock:
            active_clients.discard(client_id)
    schedule_shutdown_if_idle()
    return ("", 204)


@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    if isinstance(error, HTTPException):
        return error
    logger.exception("Unhandled setup request error")
    return "Internal server error. See logs/setup.log.", 500


def run_index_job(
    api_key: str,
    channel: str,
    max_videos: int,
    max_comments: int,
    include_all: bool,
) -> None:
    db = SongDatabase(get_database_path())
    db.init_schema()
    stats = IndexStats()
    try:
        client = YouTubeClient(api_key)
        channel_info = client.get_channel(channel)
        db.upsert_channel(channel_info.channel_id, channel_info.title)
        add_log(f"频道：{channel_info.title} ({channel_info.channel_id})")

        for upload in client.iter_uploads_playlist(
            channel_info.uploads_playlist_id,
            max_videos=max_videos,
        ):
            stats.videos_seen += 1
            update_stats(stats)
            if not include_all and not looks_like_song_stream_title(upload.title):
                stats.videos_skipped += 1
                update_stats(stats)
                continue

            add_log(f"索引：{upload.title} ({upload.video_id})")
            try:
                full_video = client.get_video(upload.video_id)
                video_stats = index_video(db, client, full_video, max_comments)
            except CommentsDisabledError:
                stats.videos_skipped += 1
                add_log(f"跳过：评论关闭 {upload.video_id}")
                update_stats(stats)
                continue

            merge_stats(stats, video_stats)
            update_stats(stats)

        finish_job(True, "索引完成。", stats)
    except QuotaExceededError as exc:
        finish_job(False, f"YouTube API quota 已用尽：{exc}", stats)
    except YouTubeAPIError as exc:
        finish_job(False, f"YouTube API 错误：{exc}", stats)
    except Exception as exc:
        logger.exception("Indexer job failed")
        finish_job(False, f"索引失败：{exc}", stats)
    finally:
        db.close()


def reset_job_state() -> None:
    job_state.update(
        {
            "running": False,
            "done": False,
            "ok": False,
            "message": "等待开始索引。",
            "log": [],
            "stats": {},
        }
    )


def add_log(message: str) -> None:
    logger.info(message)
    with job_lock:
        log = list(job_state.get("log", []))
        log.append(message)
        job_state["log"] = log[-200:]
        job_state["message"] = message


def update_stats(stats: IndexStats) -> None:
    with job_lock:
        job_state["stats"] = stats_to_dict(stats)


def finish_job(ok: bool, message: str, stats: IndexStats) -> None:
    logger.info(message)
    with job_lock:
        job_state.update(
            {
                "running": False,
                "done": True,
                "ok": ok,
                "message": message,
                "stats": stats_to_dict(stats),
            }
        )
        log = list(job_state.get("log", []))
        log.append(message)
        job_state["log"] = log[-200:]


def stats_to_dict(stats: IndexStats) -> dict[str, int]:
    return {
        "videos_seen": stats.videos_seen,
        "videos_indexed": stats.videos_indexed,
        "videos_skipped": stats.videos_skipped,
        "comments_seen": stats.comments_seen,
        "timeline_comments": stats.timeline_comments,
        "entries_inserted": stats.entries_inserted,
    }


def write_env_api_key(api_key: str) -> None:
    env_path = get_app_dir() / ".env"
    env_path.write_text(f"YOUTUBE_API_KEY={api_key}\n", encoding="utf-8")


def parse_positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or default)
    except ValueError:
        return default
    return max(parsed, 1)


def get_client_id() -> str:
    data = request.get_json(silent=True) or {}
    return str(data.get("client_id") or request.form.get("client_id") or "").strip()


def schedule_shutdown_if_idle() -> None:
    global shutdown_timer
    if not AUTO_EXIT_ENABLED:
        return
    with active_clients_lock:
        if active_clients:
            return
    if shutdown_timer and shutdown_timer.is_alive():
        return

    shutdown_timer = threading.Timer(SHUTDOWN_DELAY_SECONDS, shutdown_if_still_idle)
    shutdown_timer.daemon = True
    shutdown_timer.start()


def shutdown_if_still_idle() -> None:
    if not AUTO_EXIT_ENABLED:
        return
    with active_clients_lock:
        if active_clients:
            return
    with job_lock:
        if job_state.get("running"):
            return
    logger.info("No setup clients remain; exiting VTuber Song Finder Setup")
    os._exit(0)


def open_browser_later(url: str) -> None:
    if os.getenv("VTUBER_SONG_FINDER_NO_BROWSER") == "1":
        logger.info("Skipping browser launch because VTUBER_SONG_FINDER_NO_BROWSER=1")
        return

    def worker() -> None:
        time.sleep(1.0)
        try:
            webbrowser.open(url)
            logger.info("Opened browser: %s", url)
        except Exception:
            logger.exception("Failed to open browser")

    threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    url = f"http://127.0.0.1:{SETUP_PORT}"
    logger.info("Starting VTuber Song Finder Setup")
    logger.info("Application directory: %s", get_app_dir())
    logger.info("Database path: %s", get_database_path())
    logger.info("Log path: %s", LOG_PATH)
    logger.info("Local URL: %s", url)
    try:
        open_browser_later(url)
        app.run(host="127.0.0.1", port=SETUP_PORT, debug=False, use_reloader=False)
    except Exception:
        logger.exception("Failed to start VTuber Song Finder Setup")
        raise
