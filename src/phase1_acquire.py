"""Phase 1: download and filter 5+0 Lichess games with stratified sampling.

This script streams `.pgn.zst` files from the Lichess open database without
fully extracting them to disk. It filters for rated 5+0 blitz games with valid
ratings, normal termination, clock comments, and at least 20 half-moves, then
saves sampled PGN files into rating-band folders.

Run from the repository root:
    python -m src.phase1_acquire
    python -m src.phase1_acquire --months 2026-01 2025-12
    python -m src.phase1_acquire --target-per-band 5 --test-mode
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import chess.pgn
import zstandard

import config
from src import utils


DOWNLOAD_DIR = config.RAW_DATA_DIR / "downloads"


@dataclass
class AcquisitionStats:
    """Track Phase 1 progress counters."""

    scanned_games: int = 0
    valid_games: int = 0
    files_processed: int = 0


def month_to_url(month: str) -> str:
    """Build the remote download URL for a monthly Lichess PGN archive."""
    return (
        f"{config.LICHESS_BASE_URL}"
        f"lichess_db_standard_rated_{month}.pgn.zst"
    )


def month_to_local_path(month: str) -> Path:
    """Return the local cache path for a monthly `.zst` archive."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return DOWNLOAD_DIR / f"lichess_db_standard_rated_{month}.pgn.zst"


def download_month_archive(month: str, logger) -> Path:
    """Download a monthly archive if it is not already cached locally."""
    target_path = month_to_local_path(month)
    if target_path.exists():
        logger.info("Using cached archive for %s at %s", month, target_path)
        return target_path

    url = month_to_url(month)
    logger.info("Downloading %s", url)
    try:
        with urllib.request.urlopen(url) as response, target_path.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
    except urllib.error.URLError as exc:
        if target_path.exists():
            target_path.unlink()
        raise RuntimeError(f"Failed to download {url}: {exc}") from exc

    logger.info("Finished downloading %s", target_path)
    return target_path


def game_has_clock_comments(game: chess.pgn.Game) -> bool:
    """Return True when at least one move contains a clock comment."""
    node = game
    while node.variations:
        node = node.variations[0]
        remaining, _ = utils.parse_clock_comment(node.comment)
        if remaining is not None:
            return True
    return False


def is_valid_rated_flag(rated_header: str | None, event_header: str | None = None) -> bool:
    """Interpret Lichess rated indicators conservatively.

    Some Lichess database exports omit the `Rated` tag but still mark the game as
    rated inside `Event`, for example `Rated Blitz game`.
    """
    if rated_header is not None and rated_header.strip().lower() in {"true", "yes", "rated"}:
        return True
    if event_header is not None and event_header.strip().lower().startswith("rated "):
        return True
    return False


def game_passes_filters(game: chess.pgn.Game) -> tuple[bool, str | None, int | None, int | None]:
    """Check whether a game matches all required acquisition filters."""
    headers = game.headers
    white_elo = utils.parse_int(headers.get("WhiteElo"))
    black_elo = utils.parse_int(headers.get("BlackElo"))
    if headers.get("TimeControl") != config.TIME_CONTROL:
        return False, None, white_elo, black_elo
    if white_elo is None or black_elo is None:
        return False, None, white_elo, black_elo
    if not is_valid_rated_flag(headers.get("Rated"), headers.get("Event")):
        return False, None, white_elo, black_elo
    if headers.get("Termination") != "Normal":
        return False, None, white_elo, black_elo
    if game.end().ply() < config.MIN_HALF_MOVES:
        return False, None, white_elo, black_elo
    if not game_has_clock_comments(game):
        return False, None, white_elo, black_elo
    band = utils.same_band_for_players(white_elo, black_elo)
    if band is None:
        return False, None, white_elo, black_elo
    return True, str(band), white_elo, black_elo


def rejection_reason(game: chess.pgn.Game) -> str:
    """Return the first filter reason that rejects a game."""
    headers = game.headers
    white_elo = utils.parse_int(headers.get("WhiteElo"))
    black_elo = utils.parse_int(headers.get("BlackElo"))

    if headers.get("TimeControl") != config.TIME_CONTROL:
        return "wrong_time_control"
    if white_elo is None or black_elo is None:
        return "missing_rating"
    if not is_valid_rated_flag(headers.get("Rated"), headers.get("Event")):
        return "not_rated"
    if headers.get("Termination") != "Normal":
        return "non_normal_termination"
    if game.end().ply() < config.MIN_HALF_MOVES:
        return "too_short"
    if not game_has_clock_comments(game):
        return "no_clock_data"
    if utils.same_band_for_players(white_elo, black_elo) is None:
        return "players_in_different_bands"
    return "accepted"


def save_game_to_band(game: chess.pgn.Game, band: str, game_id: str) -> Path:
    """Write a filtered game to its band-specific PGN folder."""
    band_dir = config.RAW_DATA_DIR / f"band_{band}"
    band_dir.mkdir(parents=True, exist_ok=True)
    target_path = band_dir / f"{utils.sanitise_filename(game_id)}.pgn"
    with target_path.open("w", encoding="utf-8") as handle:
        exporter = chess.pgn.FileExporter(handle)
        game.accept(exporter)
    return target_path


def quotas_met(collected_per_band: dict[str, int], target_by_band: dict[str, int]) -> bool:
    """Return True when every rating band has reached its sampling quota."""
    return all(
        collected_per_band[str(band)] >= target_by_band[str(band)]
        for band in config.RATING_BANDS
    )


def normalise_target_by_band(
    target_per_band: int,
    target_by_band: dict[str, int] | None,
) -> dict[str, int]:
    """Return a complete per-band target mapping.

    Phase 1 normally uses the same target for every band. For replacement
    acquisition we sometimes need exact per-band totals, so this helper merges
    user overrides with the default uniform target.
    """
    resolved = {str(band): target_per_band for band in config.RATING_BANDS}
    if target_by_band is None:
        return resolved
    for band in config.RATING_BANDS:
        key = str(band)
        if key in target_by_band:
            resolved[key] = int(target_by_band[key])
    return resolved


def stream_games_from_archive(archive_path: Path) -> Iterable[chess.pgn.Game]:
    """Yield games from a compressed PGN archive using streamed decompression."""
    with archive_path.open("rb") as compressed_file:
        decompressor = zstandard.ZstdDecompressor()
        with decompressor.stream_reader(compressed_file) as reader:
            text_stream = io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
            while True:
                game = chess.pgn.read_game(text_stream)
                if game is None:
                    break
                yield game


def acquire_games(
    months: list[str],
    target_per_band: int,
    logger,
    resume_existing: bool = False,
    target_by_band: dict[str, int] | None = None,
) -> dict[str, int]:
    """Download archives and collect sampled games across rating bands."""
    utils.ensure_directories()
    stats = AcquisitionStats()
    collected_per_band = {str(band): 0 for band in config.RATING_BANDS}
    resolved_targets = normalise_target_by_band(target_per_band, target_by_band)
    existing_ids = set()

    if resume_existing and config.RAW_METADATA_CSV.exists():
        with config.RAW_METADATA_CSV.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                game_id = row.get("game_id")
                band = row.get("band")
                if game_id and band in collected_per_band:
                    existing_ids.add(game_id)
                    collected_per_band[band] += 1

    logger.info("Starting Phase 1 acquisition for months: %s", ", ".join(months))
    logger.info("Resume existing acquisition state: %s", resume_existing)
    logger.info("Current collected counts: %s", collected_per_band)
    logger.info("Target counts by band: %s", resolved_targets)

    metadata_rows: list[dict[str, object]] = []
    for month in months:
        if quotas_met(collected_per_band, resolved_targets):
            break

        archive_path = download_month_archive(month, logger)
        stats.files_processed += 1
        logger.info("Scanning archive %s", archive_path.name)

        for game_index, game in enumerate(stream_games_from_archive(archive_path), start=1):
            stats.scanned_games += 1
            keep, band, white_elo, black_elo = game_passes_filters(game)

            if stats.scanned_games % 1000 == 0:
                logger.info(
                    "Scanned %s games. Collected so far: %s",
                    stats.scanned_games,
                    collected_per_band,
                )

            if not keep or band is None:
                continue
            if collected_per_band[band] >= resolved_targets[band]:
                continue

            fallback_id = f"{month}_{game_index}"
            game_id = utils.safe_game_id(game, fallback_id)
            if game_id in existing_ids:
                continue

            save_game_to_band(game, band, game_id)
            metadata_rows.append(
                {
                    "game_id": game_id,
                    "white_elo": white_elo,
                    "black_elo": black_elo,
                    "band": band,
                    "time_control": game.headers.get("TimeControl"),
                    "num_moves": game.end().ply(),
                    "termination": game.headers.get("Termination"),
                }
            )
            existing_ids.add(game_id)
            collected_per_band[band] += 1
            stats.valid_games += 1

            if len(metadata_rows) >= 100:
                utils.append_rows(
                    config.RAW_METADATA_CSV,
                    metadata_rows,
                    [
                        "game_id",
                        "white_elo",
                        "black_elo",
                        "band",
                        "time_control",
                        "num_moves",
                        "termination",
                    ],
                )
                metadata_rows.clear()

            if quotas_met(collected_per_band, resolved_targets):
                logger.info("All band quotas reached after %s scanned games.", stats.scanned_games)
                break

        logger.info(
            "Finished month %s. Scanned=%s, accepted=%s, counts=%s",
            month,
            stats.scanned_games,
            stats.valid_games,
            collected_per_band,
        )

    if metadata_rows:
        utils.append_rows(
            config.RAW_METADATA_CSV,
            metadata_rows,
            [
                "game_id",
                "white_elo",
                "black_elo",
                "band",
                "time_control",
                "num_moves",
                "termination",
            ],
        )

    missing_bands = [
        str(band)
        for band in config.RATING_BANDS
        if collected_per_band[str(band)] < resolved_targets[str(band)]
    ]
    if missing_bands:
        logger.warning(
            "Acquisition finished without filling all quotas. Missing bands: %s",
            ", ".join(missing_bands),
        )

    logger.info("Phase 1 complete. Final counts: %s", collected_per_band)
    return collected_per_band


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for Phase 1."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--months",
        nargs="+",
        default=None,
        help="Monthly archives to scan first, e.g. 2026-01 2025-12.",
    )
    parser.add_argument(
        "--target-per-band",
        type=int,
        default=config.TARGET_GAMES_PER_BAND,
        help="Target number of games to save per rating band.",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Collect a tiny sample to verify the pipeline end-to-end.",
    )
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help="Reuse existing Phase 1 metadata and already-saved PGNs instead of starting fresh.",
    )
    parser.add_argument(
        "--band-targets-file",
        type=str,
        help=(
            "Optional JSON file mapping rating-band numbers to exact cumulative "
            "targets, for example {'1': 4001, '2': 4003}."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the acquisition phase."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    logger = utils.setup_logging("phase1_acquire", "phase1_acquire.log")

    months = list(args.months) if args.months else list(config.MONTHS_TO_TRY)
    if args.test_mode:
        months = config.MONTHS_TO_TRY
        target_per_band = min(args.target_per_band, config.ACQUISITION_TEST_TARGET)
        logger.info("Running in test mode with target_per_band=%s", target_per_band)
    else:
        target_per_band = args.target_per_band

    target_by_band = None
    if args.band_targets_file:
        target_by_band = utils.read_json(Path(args.band_targets_file), None)
        if not isinstance(target_by_band, dict):
            raise ValueError("--band-targets-file must point to a JSON object.")

    try:
        acquire_games(
            months=months,
            target_per_band=target_per_band,
            logger=logger,
            resume_existing=args.resume_existing,
            target_by_band=target_by_band,
        )
    except KeyboardInterrupt:  # pragma: no cover - operator interrupt
        logger.warning("Phase 1 interrupted by operator. Existing collected games remain saved.")
        return 130
    except Exception as exc:  # pragma: no cover - top-level safety
        logger.exception("Phase 1 failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
