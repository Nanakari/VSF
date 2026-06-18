from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
import time
import webbrowser

from flask import Flask, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from config import get_app_dir, get_database_path, get_resource_dir
from database import SongDatabase


PAGE_SIZE = 20
SHUTDOWN_DELAY_SECONDS = 3
AUTO_EXIT_ENABLED = bool(getattr(sys, "frozen", False))
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
    schedule_shutdown_if_idle()
    return ("", 204)


@app.route("/")
def index():
    channel_query = request.args.get("channel", "").strip()
    song_query = request.args.get("song", "").strip()
    artist_query = request.args.get("artist", "").strip()
    page = parse_page(request.args.get("page"))
    offset = (page - 1) * PAGE_SIZE

    db = SongDatabase(get_database_path())
    db.init_schema()
    try:
        channels = db.list_channels()
        groups = []
        if channel_query or song_query or artist_query:
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
        has_search=bool(channel_query or song_query or artist_query),
        index_url=url_for("index"),
        auto_exit_enabled=AUTO_EXIT_ENABLED,
    )


@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    if isinstance(error, HTTPException):
        return error
    logger.exception("Unhandled request error")
    return "Internal server error. See VTuberSongFinder.log.", 500


def parse_page(value: str | None) -> int:
    try:
        parsed = int(value or 1)
    except ValueError:
        return 1
    return max(parsed, 1)


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
        active_clients[client_id] = time.time()


def unregister_client(client_id: str) -> None:
    with active_clients_lock:
        active_clients.pop(client_id, None)


def has_active_clients() -> bool:
    with active_clients_lock:
        return bool(active_clients)


def schedule_shutdown_if_idle() -> None:
    global shutdown_timer
    if not AUTO_EXIT_ENABLED:
        return
    if has_active_clients():
        return
    if shutdown_timer and shutdown_timer.is_alive():
        return

    shutdown_timer = threading.Timer(SHUTDOWN_DELAY_SECONDS, shutdown_if_still_idle)
    shutdown_timer.daemon = True
    shutdown_timer.start()


def shutdown_if_still_idle() -> None:
    if not AUTO_EXIT_ENABLED:
        return
    if has_active_clients():
        return
    logger.info("No browser clients remain; exiting VTuber Song Finder")
    os._exit(0)


if __name__ == "__main__":
    url = "http://127.0.0.1:5000"
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
