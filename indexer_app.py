from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from config import get_app_dir, get_database_path, get_resource_dir, get_youtube_api_key
from database import SongDatabase
from main import IndexStats, run_index_channel
from youtube_client import (
    QuotaExceededError,
    YouTubeAPIError,
    YouTubeClient,
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
active_clients: dict[str, float] = {}
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
        search_url=url_for("open_search"),
        has_saved_api_key=bool(read_saved_api_key()),
    )



@app.get("/search")
def open_search():
    if not ensure_peer_app("VTuberSongFinder.exe", 5000, "app.py"):
        return (
            "搜索工具启动失败，请确认 VTuberSongFinder.exe 与更新工具位于同一目录，"
            f"并查看日志：{LOG_PATH}",
            503,
        )
    return redirect("http://127.0.0.1:5000/")

@app.post("/start")
def start_index():
    api_key = request.form.get("api_key", "").strip()
    channel = request.form.get("channel", "").strip()
    include_all = request.form.get("include_all") == "on"
    mode = request.form.get("mode", "")
    if not mode:
        mode = "incremental" if request.form.get("incremental") == "on" else "full"
    if mode not in {"incremental", "full", "backfill"}:
        return jsonify({"ok": False, "message": "无效的索引模式。"}), 400
    reset_backfill = request.form.get("reset_backfill") == "on"
    max_videos = parse_positive_int(request.form.get("max_videos"), DEFAULT_MAX_VIDEOS)
    max_comments = parse_positive_int(request.form.get("max_comments"), DEFAULT_MAX_COMMENTS)

    if api_key:
        write_env_api_key(api_key)
    else:
        api_key = read_saved_api_key()

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

    worker = threading.Thread(
        target=run_index_job,
        args=(api_key, channel, max_videos, max_comments, include_all, mode, reset_backfill),
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
            active_clients[client_id] = time.monotonic()
        schedule_shutdown_check()
    return ("", 204)


@app.post("/client-close")
def client_close():
    client_id = get_client_id()
    if client_id:
        with active_clients_lock:
            active_clients.pop(client_id, None)
    schedule_shutdown_check()
    return ("", 204)



@app.post("/shutdown")
def shutdown():
    if is_index_job_running():
        logger.warning("Ignoring shutdown request while an index job is running")
        return jsonify({"ok": False, "message": "索引任务正在运行，任务完成后才能退出。"}), 409
    logger.info("Browser requested VTuber Song Finder Setup shutdown")
    threading.Timer(1.5, force_shutdown).start()
    return jsonify({"ok": True})



@app.get("/launcher")
def launcher():
    target = request.args.get("target", "/")
    if not target.startswith("/") or target.startswith("//"):
        target = "/"
    target_url = f"http://127.0.0.1:5001{target}"
    return Response(make_launcher_page("VTuber Song Finder Setup", target_url), mimetype="text/html")

@app.get("/shutdown-close")
def shutdown_close():
    if is_index_job_running():
        return Response("索引任务正在运行，任务完成后才能退出。", status=409, mimetype="text/plain")
    logger.info("Browser requested VTuber Song Finder Setup shutdown page")
    threading.Timer(1.0, force_shutdown).start()
    return Response(make_close_page("VTuber Song Finder Setup"), mimetype="text/html")
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
    mode: str,
    reset_backfill: bool,
) -> None:
    db = SongDatabase(get_database_path())
    db.init_schema()
    stats = IndexStats()
    try:
        client = YouTubeClient(api_key)
        stats = run_index_channel(
            db=db,
            client=client,
            channel=channel,
            max_videos=max_videos,
            max_comments=max_comments,
            include_all_videos=include_all,
            incremental=mode == "incremental",
            backfill=mode == "backfill",
            reset_backfill=reset_backfill,
            on_message=add_log,
            on_stats=update_stats,
        )
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
        "videos_failed": stats.videos_failed,
        "comments_seen": stats.comments_seen,
        "timeline_comments": stats.timeline_comments,
        "entries_inserted": stats.entries_inserted,
    }




def read_saved_api_key() -> str:
    try:
        return get_youtube_api_key()
    except RuntimeError:
        return ""

def write_env_api_key(api_key: str) -> None:
    env_path = get_app_dir() / ".env"
    env_path.write_text(f"YOUTUBE_API_KEY={api_key}\n", encoding="utf-8")


def parse_positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or default)
    except ValueError:
        return default
    return max(parsed, 1)




def ensure_peer_app(exe_name: str, port: int, source_script: str | None = None) -> bool:
    if is_port_open(port):
        return True
    exe_path = get_app_dir() / exe_name
    command: list[str]
    if exe_path.exists():
        command = [str(exe_path)]
    elif not getattr(sys, "frozen", False) and source_script:
        script_path = get_app_dir() / source_script
        if not script_path.exists():
            logger.warning("Peer application not found: %s or %s", exe_path, script_path)
            return False
        command = [sys.executable, str(script_path)]
    else:
        logger.warning("Peer executable not found: %s", exe_path)
        return False

    try:
        child_env = os.environ.copy()
        child_env["VTUBER_SONG_FINDER_NO_BROWSER"] = "1"
        subprocess.Popen(
            command,
            cwd=str(get_app_dir()),
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError:
        logger.exception("Failed to launch peer application: %s", command[0])
        return False

    deadline = time.time() + 5
    while time.time() < deadline:
        if is_port_open(port):
            return True
        time.sleep(0.2)
    logger.error("Peer application did not start listening on port %s", port)
    return False


def is_port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False

def get_client_id() -> str:
    data = request.get_json(silent=True) or {}
    return str(data.get("client_id") or request.form.get("client_id") or "").strip()


def has_active_clients() -> bool:
    with active_clients_lock:
        return bool(active_clients)


def is_index_job_running() -> bool:
    with job_lock:
        return bool(job_state["running"])


def schedule_shutdown_check() -> None:
    global shutdown_timer
    if not AUTO_EXIT_ENABLED:
        return
    if shutdown_timer and shutdown_timer.is_alive():
        return

    shutdown_timer = threading.Timer(SHUTDOWN_DELAY_SECONDS, shutdown_if_still_idle)
    shutdown_timer.daemon = True
    shutdown_timer.start()


def shutdown_if_still_idle() -> None:
    global shutdown_timer
    if not AUTO_EXIT_ENABLED:
        return
    shutdown_timer = None
    if is_index_job_running():
        schedule_shutdown_check()
        return
    if has_active_clients():
        schedule_shutdown_check()
        return
    logger.info("No setup clients remain; exiting VTuber Song Finder Setup")
    os._exit(0)






def make_launcher_page(title: str, target_url: str) -> str:
    target_json = json.dumps(target_url)
    return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family: Segoe UI, Microsoft YaHei, sans-serif; padding: 24px;">
  <p>正在打开页面...</p>
  <script>
    const target = {target_json};
    const opened = window.open(target, '_blank');
    if (!opened) {{ window.location.replace(target); }}
    else {{ window.close(); setTimeout(() => window.location.replace(target), 300); }}
  </script>
</body>
</html>"""

def make_close_page(title: str) -> str:
    return f"""<!doctype html>
<html lang=\"zh-CN\">
<head><meta charset=\"utf-8\"><title>{title} closing</title></head>
<body style=\"font-family: Segoe UI, Microsoft YaHei, sans-serif; padding: 24px;\">
  <p>正在退出，若此标签页没有自动关闭，可以手动关闭。</p>
  <script>
    window.open('', '_self');
    window.close();
    setTimeout(() => {{ document.body.style.background = '#fff'; }}, 300);
  </script>
</body>
</html>"""

def force_shutdown() -> None:
    if is_index_job_running():
        logger.warning("Refusing to terminate while an index job is running")
        schedule_shutdown_check()
        return
    logger.info("Exiting VTuber Song Finder Setup by browser request")
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
    url = f"http://127.0.0.1:{SETUP_PORT}/"
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
