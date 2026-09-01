"""Shared helper utilities for the chess pipeline.

This module centralises logging, filesystem setup, checkpoint handling,
clock-comment parsing, and small chess-specific conversions used by multiple
pipeline phases.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import chess
import chess.engine

import config


CLOCK_PATTERN = re.compile(r"\[%clk\s+(\d+):(\d{2}):(\d{2})\]")
SANITISE_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def ensure_directories() -> None:
    """Create all required project directories if they do not exist."""
    for path in [
        config.RAW_DATA_DIR,
        config.PROCESSED_DATA_DIR,
        config.LOG_DIR,
        config.TMP_DIR,
        config.PHASE2_WORKER_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
    for band in config.RATING_BANDS:
        (config.RAW_DATA_DIR / f"band_{band}").mkdir(parents=True, exist_ok=True)


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def setup_logging(name: str, log_filename: str) -> logging.Logger:
    """Create a logger that writes to both the terminal and a log file."""
    ensure_directories()
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(processName)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(config.LOG_DIR / log_filename)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    logger.propagate = False
    return logger


def read_json(path: Path, default: Any) -> Any:
    """Read a JSON file, returning a default value if it does not exist."""
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON atomically to reduce the chance of checkpoint corruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(tmp_path, path)


def append_rows(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> int:
    """Append rows to a CSV file and create the header when needed."""
    rows = list(rows)
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def parse_int(value: Any) -> int | None:
    """Safely convert a value to int, returning None if conversion fails."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def band_for_rating(rating: int | float | None) -> int | None:
    """Return the configured band number for a rating."""
    if rating is None:
        return None
    rating_int = int(rating)
    for band, definition in config.RATING_BANDS.items():
        minimum = definition["min"]
        maximum = definition["max"]
        if minimum is not None and rating_int < minimum:
            continue
        if maximum is not None and rating_int > maximum:
            continue
        return band
    return None


def same_band_for_players(white_elo: int | None, black_elo: int | None) -> int | None:
    """Return the shared band when both players are in the same rating band."""
    white_band = band_for_rating(white_elo)
    black_band = band_for_rating(black_elo)
    if white_band is None or black_band is None or white_band != black_band:
        return None
    return white_band


def parse_clock_comment(comment: str | None) -> tuple[int | None, str | None]:
    """Extract remaining time in seconds from a PGN clock comment."""
    if not comment:
        return None, None
    match = CLOCK_PATTERN.search(comment)
    if not match:
        return None, None
    hours, minutes, seconds = (int(part) for part in match.groups())
    total_seconds = hours * 3600 + minutes * 60 + seconds
    return total_seconds, match.group(0)


def time_remaining_pct(seconds: int | None) -> float | None:
    """Convert remaining seconds into a percentage of the initial clock."""
    if seconds is None:
        return None
    return round((seconds / config.INITIAL_TIME_SECONDS) * 100.0, 4)


def score_to_cp(score: chess.engine.PovScore, pov_color: chess.Color) -> int:
    """Convert an engine score to a centipawn-like integer from one side's view."""
    player_score = score.pov(pov_color)
    if player_score.is_mate():
        mate_distance = player_score.mate()
        if mate_distance is None:
            return 0
        sign = 1 if mate_distance > 0 else -1
        return sign * (10000 - abs(mate_distance) * 10)
    cp_value = player_score.score()
    return int(cp_value) if cp_value is not None else 0


def safe_game_id(game: chess.pgn.Game, fallback: str) -> str:
    """Build a stable game identifier from PGN headers."""
    site = game.headers.get("Site", "").strip()
    if "lichess.org/" in site:
        return site.rsplit("/", 1)[-1]
    return fallback


def sanitise_filename(value: str) -> str:
    """Make a string safe to use as part of a filename."""
    return SANITISE_PATTERN.sub("_", value).strip("._") or "unknown"


@dataclass
class Stopwatch:
    """Simple timer utility used for progress reporting."""

    started_at: float

    @classmethod
    def start(cls) -> "Stopwatch":
        return cls(started_at=time.time())

    def elapsed_seconds(self) -> float:
        return time.time() - self.started_at


@contextmanager
def change_cwd(path: Path):
    """Temporarily change the working directory."""
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def default_checkpoint() -> dict[str, Any]:
    """Return the empty checkpoint structure used by Phase 2 and dashboard."""
    return {
        "started_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "last_completed_game_id_per_band": {str(band): None for band in config.RATING_BANDS},
        "games_completed_per_band": {str(band): 0 for band in config.RATING_BANDS},
        "total_games_completed": 0,
        "total_positions_analysed": 0,
        "worker_status": {},
        "recent_games": [],
    }


def tail_lines(path: Path, limit: int) -> list[str]:
    """Read the last few lines of a log file."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        lines = handle.readlines()
    return [line.rstrip("\n") for line in lines[-limit:]]
