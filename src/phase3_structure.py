"""Phase 3: clean and structure engine output into the analytical dataset.

This script transforms `raw_moves.csv` into the final move-level dataset used
for statistics and visualisation. It assigns rating bands and time-pressure
bins, caps CPL, labels error severity, excludes opening and extreme flagging
moves, and writes summary counts for quality control.

Run from the repository root:
    python -m src.phase3_structure
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

import pandas as pd

import config
from src import utils


def assign_time_pressure_bin(value: float | None) -> int | None:
    """Map a time-remaining percentage to one of the four pressure bins."""
    if value is None or pd.isna(value):
        return None
    for bin_id, definition in config.TIME_PRESSURE_BINS.items():
        if value > definition["min_exclusive"] and value <= definition["max_inclusive"]:
            return bin_id
    return None


def assign_error_category(capped_cpl: float) -> int | None:
    """Map capped CPL to the project's error-severity categories."""
    for category_id, definition in config.ERROR_CATEGORIES.items():
        if definition["min"] <= capped_cpl <= definition["max"]:
            return category_id
    return None


def assign_game_phase(move_number: int) -> str:
    """Classify a move as opening, middlegame, or endgame."""
    if move_number <= config.OPENING_MAX_FULLMOVE:
        return "Opening"
    if move_number <= config.MIDDLEGAME_MAX_FULLMOVE:
        return "Middlegame"
    return "Endgame"


def validate_dataframe(frame: pd.DataFrame) -> dict[str, int]:
    """Count basic data-quality issues for the structured dataset."""
    issues = {
        "missing_rating_band": int(frame["rating_band"].isna().sum()),
        "missing_time_pressure_bin": int(frame["time_pressure_bin"].isna().sum()),
        "missing_error_category": int(frame["error_category"].isna().sum()),
        "negative_cpl": int((frame["raw_cpl"] < 0).sum()),
        "time_pct_over_100": int((frame["time_remaining_pct"] > 100).sum()),
        "time_seconds_negative": int((frame["time_remaining_seconds"] < 0).sum()),
    }
    return issues


def structure_dataset() -> dict[str, object]:
    """Build the cleaned analytical dataset and summary file."""
    logger = utils.setup_logging("phase3_structure", "phase3_structure.log")
    utils.ensure_directories()

    if not config.RAW_MOVES_CSV.exists():
        raise FileNotFoundError(f"Missing input file: {config.RAW_MOVES_CSV}")

    frame = pd.read_csv(config.RAW_MOVES_CSV)
    logger.info("Loaded %s raw move rows", len(frame))

    frame["player_rating"] = pd.to_numeric(frame["player_rating"], errors="coerce")
    frame["move_number"] = pd.to_numeric(frame["move_number"], errors="coerce")
    frame["raw_cpl"] = pd.to_numeric(frame["raw_cpl"], errors="coerce")
    frame["time_remaining_seconds"] = pd.to_numeric(frame["time_remaining_seconds"], errors="coerce")
    frame["time_remaining_pct"] = pd.to_numeric(frame["time_remaining_pct"], errors="coerce")

    frame["rating_band"] = frame["player_rating"].apply(utils.band_for_rating)
    frame["time_pressure_bin"] = frame["time_remaining_pct"].apply(assign_time_pressure_bin)
    frame["game_phase"] = frame["move_number"].astype(int).apply(assign_game_phase)
    frame["capped_cpl"] = frame["raw_cpl"].clip(lower=0, upper=config.MAX_CPL)
    frame["error_category"] = frame["capped_cpl"].apply(assign_error_category)

    exclusion_counts = Counter()
    opening_mask = frame["game_phase"] == "Opening"
    exclusion_counts["opening_moves_excluded"] = int(opening_mask.sum())
    frame = frame.loc[~opening_mask].copy()

    flagging_mask = frame["time_remaining_seconds"] < config.MIN_TIME_REMAINING_SECONDS
    exclusion_counts["flagging_moves_excluded"] = int(flagging_mask.sum())
    frame = frame.loc[~flagging_mask].copy()

    missing_mask = frame[
        [
            "player_rating",
            "rating_band",
            "time_remaining_pct",
            "time_pressure_bin",
            "raw_cpl",
            "capped_cpl",
            "error_category",
        ]
    ].isna().any(axis=1)
    exclusion_counts["rows_with_missing_values_excluded"] = int(missing_mask.sum())
    frame = frame.loc[~missing_mask].copy()

    frame["rating_band"] = frame["rating_band"].astype(int)
    frame["time_pressure_bin"] = frame["time_pressure_bin"].astype(int)
    frame["error_category"] = frame["error_category"].astype(int)
    frame["move_number"] = frame["move_number"].astype(int)
    frame["player_rating"] = frame["player_rating"].astype(int)

    validation_issues = validate_dataframe(frame)

    analysed_frame = frame[
        [
            "game_id",
            "move_number",
            "player_rating",
            "rating_band",
            "time_remaining_pct",
            "time_pressure_bin",
            "game_phase",
            "raw_cpl",
            "capped_cpl",
            "error_category",
        ]
    ].sort_values(["rating_band", "game_id", "move_number"])

    analysed_frame.to_csv(config.ANALYSED_MOVES_CSV, index=False)
    logger.info("Wrote structured dataset with %s rows", len(analysed_frame))

    cell_counts = (
        analysed_frame.groupby(["rating_band", "time_pressure_bin"])
        .size()
        .reset_index(name="count")
        .to_dict(orient="records")
    )
    summary = {
        "generated_at": utils.utc_now_iso(),
        "total_raw_rows": int(len(pd.read_csv(config.RAW_MOVES_CSV))),
        "total_analysed_rows": int(len(analysed_frame)),
        "exclusion_counts": dict(exclusion_counts),
        "validation_issues": validation_issues,
        "cell_counts": cell_counts,
        "rating_band_counts": analysed_frame["rating_band"].value_counts().sort_index().to_dict(),
        "time_pressure_counts": analysed_frame["time_pressure_bin"].value_counts().sort_index().to_dict(),
    }
    with config.DATASET_SUMMARY_JSON.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    logger.info("Wrote dataset summary to %s", config.DATASET_SUMMARY_JSON)
    return summary


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for Phase 3."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        structure_dataset()
    except Exception as exc:  # pragma: no cover - top-level safety
        logger = utils.setup_logging("phase3_structure", "phase3_structure.log")
        logger.exception("Phase 3 failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
