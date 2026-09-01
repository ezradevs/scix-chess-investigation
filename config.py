"""Central configuration for the chess decision-making pipeline.

All scripts import settings from this file so paths, thresholds, and engine
parameters stay consistent across the project.
"""

from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
LOG_DIR = BASE_DIR / "logs"
TMP_DIR = DATA_DIR / "tmp"


RAW_METADATA_CSV = RAW_DATA_DIR / "game_metadata.csv"
RAW_MOVES_CSV = PROCESSED_DATA_DIR / "raw_moves.csv"
ANALYSED_MOVES_CSV = PROCESSED_DATA_DIR / "analysed_moves.csv"
DATASET_SUMMARY_JSON = PROCESSED_DATA_DIR / "dataset_summary.json"
CHECKPOINT_JSON = PROCESSED_DATA_DIR / "checkpoint.json"
PHASE2_WORKER_DIR = PROCESSED_DATA_DIR / "phase2_workers"


LICHESS_BASE_URL = "https://database.lichess.org/standard/"
MONTHS_TO_TRY = [
    "2026-01",
    "2025-12",
    "2025-11",
    "2025-10",
    "2025-09",
    "2025-08",
]

TARGET_GAMES_PER_BAND = 4000
ACQUISITION_TEST_TARGET = 5
TIME_CONTROL = "300+0"
MIN_HALF_MOVES = 20
INITIAL_TIME_SECONDS = 300


RATING_BANDS = {
    1: {"label": "Novice", "min": None, "max": 999},
    2: {"label": "Intermediate", "min": 1000, "max": 1499},
    3: {"label": "Club Player", "min": 1500, "max": 1999},
    4: {"label": "Advanced", "min": 2000, "max": 2299},
    5: {"label": "Expert/Master", "min": 2300, "max": None},
}


TIME_PRESSURE_BINS = {
    1: {"label": "Minimal Pressure", "min_exclusive": 75.0, "max_inclusive": 100.0},
    2: {"label": "Low Pressure", "min_exclusive": 50.0, "max_inclusive": 75.0},
    3: {"label": "Moderate Pressure", "min_exclusive": 25.0, "max_inclusive": 50.0},
    4: {"label": "High Pressure", "min_exclusive": -1.0, "max_inclusive": 25.0},
}


ERROR_CATEGORIES = {
    1: {"label": "Inaccuracy", "min": 0, "max": 10},
    2: {"label": "Minor Error", "min": 11, "max": 50},
    3: {"label": "Major Error", "min": 51, "max": 150},
    4: {"label": "Blunder", "min": 151, "max": 300},
}


OPENING_MAX_FULLMOVE = 10
MIDDLEGAME_MAX_FULLMOVE = 30
MIN_TIME_REMAINING_SECONDS = 2
MAX_CPL = 300


STOCKFISH_PATH = "/usr/local/bin/stockfish"
DEPTH = 18
HASH_MB = 512
NUM_WORKERS = 2
THREADS_PER_WORKER = 2
TEST_ENGINE_DEPTH = 10
ENGINE_TIMEOUT_SECONDS = 300
MAX_DEFERRED_ROUNDS = 5


CHECKPOINT_FLUSH_EVERY_GAMES = 1
LOG_TAIL_LINES = 10
DASHBOARD_HOST = "0.0.0.0"
DASHBOARD_PORT = 5050
DASHBOARD_REFRESH_SECONDS = 30


ANALYSIS_ROLLING_WINDOW_GAMES = 100
PHASE2_WORKER_POLL_SECONDS = 2


TEST_SAMPLE_GAMES = 5
