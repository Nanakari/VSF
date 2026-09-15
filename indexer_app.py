from __future__ import annotations

import json
import hmac
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from config import (
    get_app_dir,
    get_database_path,
    get_resource_dir,
    get_site_base_url,
    get_site_seed_token,
    get_youtube_api_key,
)
from database import SongDatabase
from main import DEFAULT_RECENT_RESCAN_DAYS, IndexStats, run_index_channel
from site_sync import sync_database_to_site
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
LOCAL_SESSION_TOKEN = secrets.token_urlsafe(32)
LOCAL_SESSION_COOKIE = f"VTuberSongFinderSession{SETUP_PORT}"
LOOPBACK_ADDRESSES = {"127.0.0.1", "::1"}

job_lock = threading.Lock()
job_state: dict[str, object] = {
    "running": False,
    "done": False,
    "ok": False,
    "operation": "idle",
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


@app.after_request
def attach_local_session_cookie(response: Response) -> Response:
    if request.method == "GET" and request.path == "/":
        response.set_cookie(
            LOCAL_SESSION_COOKIE,
            LOCAL_SESSION_TOKEN,
            httponly=True,
            samesite="Strict",
        )
    return response


def require_local_management() -> None:
    if request.remote_addr not in LOOPBACK_ADDRESSES:
        abort(403)
    supplied = request.headers.get("X-VTuber-Session") or request.cookies.get(LOCAL_SESSION_COOKIE, "")
    if not hmac.compare_digest(supplied, LOCAL_SESSION_TOKEN):
        abort(403)


@app.route("/")
def index():
    db = SongDatabase(get_database_path())
    db.init_schema()
    try:
        channels = [dict(row) for row in db.list_channels()]
    finally:
        db.close()

    return render_template(
        "indexer.html",
        default_max_videos=DEFAULT_MAX_VIDEOS,
        default_max_comments=DEFAULT_MAX_COMMENTS,
        default_recent_rescan_days=DEFAULT_RECENT_RESCAN_DAYS,
        channels=channels,
        site_base_url=read_saved_site_base_url(),
        has_saved_site_seed_token=bool(read_saved_site_seed_token()),
        auto_exit_enabled=AUTO_EXIT_ENABLED,
        search_url=url_for("open_search"),
        has_saved_api_key=bool(read_saved_api_key()),
    )



@app.get("/search")
def open_search():
    require_local_management()
    if not ensure_peer_app("VTuberSongFinder.exe", 5000, "app.py"):
        return (
            "搜索工具启动失败，请确认 VTuberSongFinder.exe 与更新工具位于同一目录，"
            f"并查看日志：{LOG_PATH}",
            503,
        )
    return redirect("http://127.0.0.1:5000/")

@app.post("/start")
def start_index():
    require_local_management()
    api_key = request.form.get("api_key", "").strip()
    channel = request.form.get("channel", "").strip()
    include_all = request.form.get("include_all") == "on"
    mode = request.form.get("mode", "")
    if not mode:
        mode = "incremental" if request.form.get("incremental") == "on" else "full"
    if mode not in {"incremental", "full", "backfill"}:
        return jsonify({"ok": False, "message": "无效的索引模式。"}), 400
    if not channel:
        return jsonify({"ok": False, "message": "请填写频道 URL、handle 或 channel ID。"}), 400

    reset_backfill = request.form.get("reset_backfill") == "on"
    max_videos = parse_positive_int(request.form.get("max_videos"), DEFAULT_MAX_VIDEOS)
    max_comments = parse_positive_int(request.form.get("max_comments"), DEFAULT_MAX_COMMENTS)
    recent_rescan_days = parse_nonnegative_int(
        request.form.get("recent_rescan_days"),
        DEFAULT_RECENT_RESCAN_DAYS,
    )

    # Keep the running check and key persistence in one critical section.  A
    # second /start request must observe the reservation before it can write a
    # different key.  Do not hold this lock while starting the worker: the
    # worker can finish immediately and its callbacks also use job_lock.
    with job_lock:
        if job_state["running"]:
            return jsonify({"ok": False, "message": "已有索引任务正在运行。"}), 409

        if api_key:
            try:
                write_env_api_key(api_key)
            except Exception:
                logger.exception("Failed to save YouTube API key")
                return jsonify({"ok": False, "message": "无法保存 YouTube Data API Key。"}), 500
        else:
            api_key = read_saved_api_key()

        if not api_key:
            return jsonify({"ok": False, "message": "请填写 YouTube Data API Key。"}), 400

        reset_job_state()
        job_state["running"] = True
        job_state["operation"] = "index"
        job_state["message"] = "索引任务已开始。"

    try:
        worker = threading.Thread(
            target=run_index_job,
            args=(
                api_key,
                channel,
                max_videos,
                max_comments,
                include_all,
                mode,
                reset_backfill,
                recent_rescan_days,
            ),
            daemon=True,
        )
        worker.start()
    except Exception:
        logger.exception("Failed to start indexer job")
        with job_lock:
            # A failed Thread construction/start must not leave the setup UI
            # reporting a task that can never finish.
            if job_state["running"]:
                reset_job_state()
        return jsonify({"ok": False, "message": "无法启动索引任务。"}), 500
    return jsonify({"ok": True, "message": "索引任务已开始。"})


@app.post("/save-site-config")
def save_site_config():
    require_local_management()
    base_url = request.form.get("site_base_url", "").strip()
    seed_token = request.form.get("site_seed_token", "").strip()
    if not base_url:
        base_url = read_saved_site_base_url()
    if not seed_token:
        seed_token = read_saved_site_seed_token()
    try:
        save_site_sync_config(base_url, seed_token)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    except OSError:
        logger.exception("Failed to save Site sync configuration")
        return jsonify({"ok": False, "message": "无法保存站点同步配置。"}), 500
    return jsonify({"ok": True, "message": "站点同步配置已保存。"})


@app.post("/delete-channel")
def delete_channel():
    require_local_management()
    channel_id = request.form.get("channel_id", "").strip()
    confirmation = request.form.get("confirmation", "").strip()
    if not channel_id:
        return jsonify({"ok": False, "message": "缺少频道 ID。"}), 400
    if is_index_job_running():
        return jsonify({"ok": False, "message": "索引任务正在运行，暂时不能删除频道。"}), 409

    db = SongDatabase(get_database_path())
    try:
        db.init_schema()
        channel = db.get_channel(channel_id)
    finally:
        db.close()
    if channel is None:
        return jsonify({"ok": False, "message": "频道不存在，可能已经被删除。"}), 404
    if confirmation != channel["channel_title"]:
        return jsonify({"ok": False, "message": "确认名称不匹配，未执行删除。"}), 400

    base_url = request.form.get("site_base_url", "").strip() or read_saved_site_base_url()
    seed_token = request.form.get("site_seed_token", "").strip() or read_saved_site_seed_token()
    try:
        base_url = normalize_site_base_url(base_url)
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    if not seed_token:
        return jsonify(
            {
                "ok": False,
                "message": "请先配置站点同步令牌，删除后系统会自动同步站点数据。",
            }
        ), 400

    if request.form.get("site_base_url", "").strip() or request.form.get("site_seed_token", "").strip():
        try:
            save_site_sync_config(base_url, seed_token)
        except (OSError, ValueError) as exc:
            logger.exception("Failed to save Site sync configuration before deletion")
            return jsonify({"ok": False, "message": str(exc) or "无法保存站点同步配置。"}), 400

    with job_lock:
        if job_state["running"]:
            return jsonify({"ok": False, "message": "已有任务正在运行。"}), 409
        reset_job_state()
        job_state["running"] = True
        job_state["operation"] = "delete-channel"
        job_state["message"] = f"正在准备删除频道：{channel['channel_title']}。"

    try:
        worker = threading.Thread(
            target=run_delete_channel_job,
            args=(channel_id, str(channel["channel_title"]), base_url, seed_token),
            daemon=True,
        )
        worker.start()
    except Exception:
        logger.exception("Failed to start channel deletion job")
        with job_lock:
            if job_state["running"]:
                reset_job_state()
        return jsonify({"ok": False, "message": "无法启动删除任务。"}), 500
    return jsonify({"ok": True, "message": "删除任务已开始，正在同步站点数据。"}), 202

@app.get("/status")
def status():
    require_local_management()
    with job_lock:
        return jsonify(job_state)


@app.post("/client-ping")
def client_ping():
    require_local_management()
    client_id = get_client_id()
    if client_id:
        with active_clients_lock:
            active_clients[client_id] = time.monotonic()
        schedule_shutdown_check()
    return ("", 204)


@app.post("/client-close")
def client_close():
    require_local_management()
    client_id = get_client_id()
    if client_id:
        with active_clients_lock:
            active_clients.pop(client_id, None)
    schedule_shutdown_check()
    return ("", 204)



@app.post("/shutdown")
def shutdown():
    require_local_management()
    if is_index_job_running():
        logger.warning("Ignoring shutdown request while an index job is running")
        return jsonify({"ok": False, "message": "索引任务正在运行，任务完成后才能退出。"}), 409
    logger.info("Browser requested VTuber Song Finder Setup shutdown")
    threading.Timer(1.5, force_shutdown).start()
    return jsonify({"ok": True})



@app.get("/launcher")
def launcher():
    require_local_management()
    target = request.args.get("target", "/")
    if not target.startswith("/") or target.startswith("//"):
        target = "/"
    target_url = f"http://127.0.0.1:5001{target}"
    return Response(make_launcher_page("VTuber Song Finder Setup", target_url), mimetype="text/html")

@app.get("/shutdown-close")
def shutdown_close():
    require_local_management()
    if is_index_job_running():
        return Response("索引任务正在运行，任务完成后才能退出。", status=409, mimetype="text/plain")
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
    recent_rescan_days: int = DEFAULT_RECENT_RESCAN_DAYS,
) -> None:
    db: SongDatabase | None = None
    stats = IndexStats()
    try:
        db = SongDatabase(get_database_path())
        db.init_schema()
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
            recent_rescan_days=recent_rescan_days,
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
        if db is not None:
            db.close()


def run_delete_channel_job(
    channel_id: str,
    channel_title: str,
    site_base_url: str,
    site_seed_token: str,
) -> None:
    db: SongDatabase | None = None
    deleted: dict[str, object] | None = None
    try:
        db = SongDatabase(get_database_path())
        db.init_schema()
        deleted = db.delete_channel(channel_id)
        if deleted is None:
            finish_job(False, f"频道已不存在：{channel_title}", IndexStats())
            return
        add_log(
            f"本地已删除频道 {channel_title}："
            f"{deleted['videos']} 个视频、{deleted['songs']} 首歌曲、"
            f"{deleted['entries']} 个时间点。"
        )
    except Exception as exc:
        logger.exception("Channel deletion failed")
        finish_job(False, f"删除频道失败：{exc}", IndexStats())
        return
    finally:
        if db is not None:
            db.close()

    try:
        add_log("正在生成并上传站点完整快照，请稍候。")
        manifest = sync_database_to_site(
            get_database_path(),
            site_base_url,
            site_seed_token,
            get_app_dir() / "build" / "d1-seed",
            on_message=add_log,
        )
        tables = manifest.get("tables", {})
        finish_job(
            True,
            f"频道 {channel_title} 已删除，站点同步完成（{tables.get('channels', 0)} 个频道）。",
            IndexStats(),
        )
    except Exception as exc:
        logger.exception("Site resync after channel deletion failed")
        finish_job(
            False,
            f"频道 {channel_title} 已从本地删除，但站点同步失败：{exc}。"
            "可确认站点配置后重新导入快照。",
            IndexStats(),
        )


def reset_job_state() -> None:
    job_state.update(
        {
            "running": False,
            "done": False,
            "ok": False,
            "operation": "idle",
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


def read_saved_site_base_url() -> str:
    return get_site_base_url()


def read_saved_site_seed_token() -> str:
    return get_site_seed_token()


def normalize_site_base_url(value: str) -> str:
    from urllib.parse import urlparse

    base_url = value.strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("站点地址必须是完整的 http:// 或 https:// URL。")
    if parsed.query or parsed.fragment:
        raise ValueError("站点地址不能包含查询参数或片段。")
    return base_url


def save_site_sync_config(base_url: str, seed_token: str) -> None:
    base_url = normalize_site_base_url(base_url)
    if not seed_token or "\r" in seed_token or "\n" in seed_token:
        raise ValueError("站点同步令牌不能为空，且必须是单行文本。")
    write_env_values(
        {
            "SITE_BASE_URL": base_url,
            "SITE_SEED_TOKEN": seed_token,
        }
    )


def write_env_api_key(api_key: str) -> None:
    if not api_key or "\r" in api_key or "\n" in api_key:
        raise ValueError("API key must be a single non-empty line")
    write_env_values({"YOUTUBE_API_KEY": api_key})


def write_env_values(values: dict[str, str]) -> None:
    for key, value in values.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError("Invalid environment variable name")
        if not value or "\r" in value or "\n" in value:
            raise ValueError(f"{key} must be a single non-empty line")

    env_path = get_app_dir() / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    original = env_path.read_text(encoding="utf-8") if env_path.exists() else ""

    newline = "\r\n" if "\r\n" in original else "\n"
    assignments = {
        key: re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=")
        for key in values
    }
    lines = original.splitlines(keepends=True)
    updated: list[str] = []
    replaced = {key: False for key in values}
    for line in lines:
        match_key = next(
            (
                key
                for key, assignment in assignments.items()
                if assignment.match(line.rstrip("\r\n"))
            ),
            None,
        )
        if match_key is not None:
            if not replaced[match_key]:
                updated.append(f"{match_key}={values[match_key]}{newline}")
                replaced[match_key] = True
            continue
        updated.append(line)

    for key, value in values.items():
        if not replaced[key]:
            if updated and not "".join(updated).endswith(("\n", "\r")):
                updated.append(newline)
            updated.append(f"{key}={value}{newline}")
    with env_path.open("w", encoding="utf-8", newline="") as env_file:
        env_file.write("".join(updated))
    # python-dotenv intentionally does not override an existing process value.
    # Keep the running setup process in sync with the value just saved.
    os.environ.update(values)


def parse_positive_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or default)
    except ValueError:
        return default
    return max(parsed, 1)


def parse_nonnegative_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value or default)
    except ValueError:
        return default
    return max(parsed, 0)




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
