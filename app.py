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

from config import get_app_dir, get_database_path, get_resource_dir
from database import SongDatabase


PAGE_SIZE = 20
SHUTDOWN_DELAY_SECONDS = 3
AUTO_EXIT_ENABLED = bool(getattr(sys, "frozen", False))
SCHEMA_LOCK = threading.Lock()
SCHEMA_READY = False
active_clients: dict[str, float] = {}
active_clients_lock = threading.Lock()
shutdown_timer: threading.Timer | None = None


def get_log_path() -> Path:
    candidates = [
        get_app_dir() / "logs" / "app.log",
        Path(os.getenv("LOCALAPPDATA", Path.home())) / "VTuberSongFinder" / "logs" / "app.log",
    ]
    for candidate in candidates:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    return Path.home() / "VTuberSongFinder-app.log"


LOG_PATH = get_log_path()


def setup_logging() -> None:
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
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


@app.post("/client-ping")
def client_ping():
    client_id = get_client_id()
    if client_id:
        register_client(client_id)
    return ("", 204)


@app.post("/client-close")
def client_close():
    client_id = get_client_id()
    if client_id:
        unregister_client(client_id)
    schedule_shutdown_check()
    return ("", 204)



@app.post("/shutdown")
def shutdown():
    logger.info("Browser requested VTuber Song Finder shutdown")
    threading.Timer(1.5, force_shutdown).start()
    return {"ok": True}



@app.get("/launcher")
def launcher():
    target = request.args.get("target", "/")
    if not target.startswith("/") or target.startswith("//"):
        target = "/"
    target_url = f"http://127.0.0.1:5000{target}"
    return Response(make_launcher_page("VTuber Song Finder", target_url), mimetype="text/html")

@app.get("/shutdown-close")
def shutdown_close():
    logger.info("Browser requested VTuber Song Finder shutdown page")
    threading.Timer(1.0, force_shutdown).start()
    return Response(make_close_page("VTuber Song Finder"), mimetype="text/html")

@app.get("/setup")
def open_setup():
    if not ensure_peer_app("VTuberSongFinderSetup.exe", 5001, "indexer_app.py"):
        return (
            "更新工具启动失败，请确认 VTuberSongFinderSetup.exe 与主程序位于同一目录，"
            f"并查看日志：{LOG_PATH}",
            503,
        )
    return redirect("http://127.0.0.1:5001/")




@app.route("/")
def index():
    channel_query = request.args.get("channel", "").strip()
    song_query = request.args.get("song", "").strip()
    artist_query = request.args.get("artist", "").strip()
    page = parse_page(request.args.get("page"))
    offset = (page - 1) * PAGE_SIZE

    has_search_query = bool(channel_query or song_query or artist_query)

    db = SongDatabase(get_database_path())
    ensure_database_ready(db)
    try:
        channels = db.list_channels() if not has_search_query else []
        groups = []
        if has_search_query:
            groups = db.search_grouped(
                channel_query=channel_query or None,
                song_query=song_query or None,
                artist_query=artist_query or None,
                limit=PAGE_SIZE + 1,
                offset=offset,
            )
        stats = db.get_stats()
    finally:
        db.close()

    has_next = len(groups) > PAGE_SIZE
    groups = groups[:PAGE_SIZE]
    single_result_open = page == 1 and not has_next and len(groups) == 1
    cross_channel_mode = not channel_query

    return render_template(
        "index.html",
        channel_query=channel_query,
        song_query=song_query,
        artist_query=artist_query,
        page=page,
        page_size=PAGE_SIZE,
        has_next=has_next,
        single_result_open=single_result_open,
        cross_channel_mode=cross_channel_mode,
        channels=channels,
        groups=groups,
        stats=stats,
        has_search=has_search_query,
        index_url=url_for("index"),
        auto_exit_enabled=AUTO_EXIT_ENABLED,
        setup_url=url_for("open_setup"),
    )


@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    if isinstance(error, HTTPException):
        return error
    logger.exception("Unhandled request error")
    return "Internal server error. See VTuberSongFinder.log.", 500


def ensure_database_ready(db: SongDatabase) -> None:
    global SCHEMA_READY
    if SCHEMA_READY:
        return
    with SCHEMA_LOCK:
        if not SCHEMA_READY:
            db.init_schema()
            SCHEMA_READY = True


def parse_page(value: str | None) -> int:
    try:
        parsed = int(value or 1)
    except ValueError:
        return 1
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


def get_client_id() -> str:
    data = request.get_json(silent=True) or {}
    return str(data.get("client_id") or request.form.get("client_id") or "").strip()


def register_client(client_id: str) -> None:
    with active_clients_lock:
        active_clients[client_id] = time.monotonic()
    schedule_shutdown_check()


def unregister_client(client_id: str) -> None:
    with active_clients_lock:
        active_clients.pop(client_id, None)
    schedule_shutdown_check()


def has_active_clients() -> bool:
    with active_clients_lock:
        return bool(active_clients)


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
    if has_active_clients():
        schedule_shutdown_check()
        return
    logger.info("No browser clients remain; exiting VTuber Song Finder")
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
    logger.info("Exiting VTuber Song Finder by browser request")
    os._exit(0)

if __name__ == "__main__":
    url = "http://127.0.0.1:5000/"
    logger.info("Starting VTuber Song Finder")
    logger.info("Application directory: %s", get_app_dir())
    logger.info("Database path: %s", get_database_path())
    logger.info("Log path: %s", LOG_PATH)
    logger.info("Local URL: %s", url)
    try:
        open_browser_later(url)
        app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
    except Exception:
        logger.exception("Failed to start VTuber Song Finder")
        raise


