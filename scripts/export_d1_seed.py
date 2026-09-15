from __future__ import annotations

import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_DIR / "vtuber_songs.sqlite3"
OUTPUT_DIR = PROJECT_DIR / "build" / "d1-seed"
sys.path.insert(0, str(PROJECT_DIR))

from site_sync import export_d1_seed


def export_seed() -> None:
    export_d1_seed(DATABASE_PATH, OUTPUT_DIR, on_message=print)


if __name__ == "__main__":
    export_seed()
