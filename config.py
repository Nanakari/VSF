from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return PROJECT_DIR


def get_resource_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return PROJECT_DIR


DEFAULT_DB_PATH = get_app_dir() / "vtuber_songs.sqlite3"


def load_config() -> None:
    """Load environment variables from .env when present."""
    load_dotenv(get_app_dir() / ".env")
    load_dotenv()


def get_youtube_api_key() -> str:
    load_config()
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "YOUTUBE_API_KEY is not set. Copy .env.example to .env and fill in your API key."
        )
    return api_key


def get_database_path(db_path: str | None = None) -> Path:
    if db_path:
        return Path(db_path).expanduser().resolve()
    return DEFAULT_DB_PATH
