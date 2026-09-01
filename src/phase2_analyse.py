"""Phase 2: run depth-limited Stockfish analysis on filtered games.

This script analyses each filtered PGN game move-by-move using python-chess
`SimpleEngine`. Games are distributed across worker processes, each with its own
Stockfish instance. Results are written incrementally after every game so a
crash does not lose much work, and a checkpoint file allows clean resume.

Run from the repository root:
    python -m src.phase2_analyse
    python -m src.phase2_analyse --resume
    python -m src.phase2_analyse --max-games 5 --depth 10
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import multiprocessing as mp
import queue
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chess
import chess.engine
import chess.pgn

import config
from src import utils


RAW_MOVE_FIELDS = [
    "game_id",
    "band",
    "move_number",
    "player_color",
    "player_username",
    "player_rating",
    "position_fen",
    "best_eval_cp",
    "played_eval_cp",
    "raw_cpl",
    "time_remaining_seconds",
    "time_remaining_pct",
    "clock_comment",
]


@dataclass
class GameTask:
    """A unit of work given to one Phase 2 worker."""

    game_id: str
    band: str
    pgn_path: str
    defer_round: int = 0


class AnalysisTimeoutError(RuntimeError):
    """Raised when a single engine evaluation takes too long."""


def load_games_to_analyse(
    checkpoint: dict[str, Any],
    max_games: int | None,
    max_games_per_band: int | None,
    allowed_game_ids: set[str] | None,
) -> list[GameTask]:
    """Build the list of PGN games that still need analysis."""
    completed_ids = set(checkpoint.get("completed_game_ids", []))
    tasks: list[GameTask] = []
    selected_per_band = {str(band): 0 for band in config.RATING_BANDS}

    for band in sorted(config.RATING_BANDS):
        band_dir = config.RAW_DATA_DIR / f"band_{band}"
        if not band_dir.exists():
            continue
        for pgn_path in sorted(band_dir.glob("*.pgn")):
            game_id = pgn_path.stem
            if game_id in completed_ids:
                continue
            if allowed_game_ids is not None and game_id not in allowed_game_ids:
                continue
            if (
                max_games_per_band is not None
                and selected_per_band[str(band)] >= max_games_per_band
            ):
                continue
            tasks.append(
                GameTask(
                    game_id=game_id,
                    band=str(band),
                    pgn_path=str(pgn_path),
                )
            )
            selected_per_band[str(band)] += 1
            if max_games is not None and len(tasks) >= max_games:
                return tasks
    return tasks


def restart_engine(depth: int, logger) -> chess.engine.SimpleEngine:
    """Start and configure a fresh Stockfish engine process."""
    logger.info("Starting Stockfish engine at %s", config.STOCKFISH_PATH)
    engine = chess.engine.SimpleEngine.popen_uci(
        config.STOCKFISH_PATH,
        timeout=config.ENGINE_TIMEOUT_SECONDS,
    )
    engine.configure({"Hash": config.HASH_MB, "Threads": config.THREADS_PER_WORKER})
    logger.info(
        "Configured engine with Hash=%s MB, Threads=%s, depth=%s",
        config.HASH_MB,
        config.THREADS_PER_WORKER,
        depth,
    )
    return engine


def analyse_position(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    mover: chess.Color,
    depth: int,
    game_token: str,
) -> int:
    """Evaluate a position from the point of view of the player who moved."""
    previous_handler = signal.getsignal(signal.SIGALRM)

    def _timeout_handler(signum, frame):  # pragma: no cover - signal-driven
        raise AnalysisTimeoutError(
            f"Engine analysis exceeded {config.ENGINE_TIMEOUT_SECONDS} seconds."
        )

    try:
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, config.ENGINE_TIMEOUT_SECONDS)
        info = engine.analyse(board, chess.engine.Limit(depth=depth), game=game_token)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)

    score = info["score"]
    return utils.score_to_cp(score, mover)


def analyse_single_game(
    engine: chess.engine.SimpleEngine,
    task: GameTask,
    depth: int,
) -> tuple[list[dict[str, Any]], int]:
    """Analyse one PGN game and return move rows plus analysed-position count."""
    with Path(task.pgn_path).open("r", encoding="utf-8") as handle:
        game = chess.pgn.read_game(handle)
    if game is None:
        raise ValueError(f"Could not parse game file {task.pgn_path}")

    board = game.board()
    rows: list[dict[str, Any]] = []
    analysed_positions = 0
    game_token = task.game_id

    mainline_nodes = list(game.mainline())
    for ply_index, node in enumerate(mainline_nodes, start=1):
        if board.is_game_over():
            break

        move = node.move
        mover = board.turn
        position_fen = board.fen()
        player_color = "white" if mover == chess.WHITE else "black"
        player_username = game.headers.get("White" if mover == chess.WHITE else "Black", "")
        player_rating = utils.parse_int(
            game.headers.get("WhiteElo" if mover == chess.WHITE else "BlackElo")
        )
        time_seconds, clock_comment = utils.parse_clock_comment(node.comment)

        best_eval_cp = analyse_position(engine, board, mover, depth, game_token)
        analysed_positions += 1

        board.push(move)
        if board.is_game_over():
            continue

        played_eval_cp = analyse_position(engine, board, mover, depth, game_token)
        analysed_positions += 1

        raw_cpl = max(0, best_eval_cp - played_eval_cp)
        rows.append(
            {
                "game_id": task.game_id,
                "band": task.band,
                "move_number": (ply_index + 1) // 2,
                "player_color": player_color,
                "player_username": player_username,
                "player_rating": player_rating,
                "position_fen": position_fen,
                "best_eval_cp": best_eval_cp,
                "played_eval_cp": played_eval_cp,
                "raw_cpl": raw_cpl,
                "time_remaining_seconds": time_seconds,
                "time_remaining_pct": utils.time_remaining_pct(time_seconds),
                "clock_comment": clock_comment,
            }
        )

    return rows, analysed_positions


def worker_process(
    worker_id: int,
    task_queue: mp.Queue,
    result_queue: mp.Queue,
    depth: int,
) -> None:
    """Worker entry point: own one Stockfish process and analyse whole games."""
    logger = utils.setup_logging(f"phase2_worker_{worker_id}", f"phase2_worker_{worker_id}.log")
    worker_csv = config.PHASE2_WORKER_DIR / f"worker_{worker_id}.csv"
    engine = None

    try:
        engine = restart_engine(depth=depth, logger=logger)
        while True:
            task_payload = task_queue.get()
            if task_payload is None:
                break
            task = GameTask(**task_payload)
            result_queue.put(
                {
                    "type": "status",
                    "worker_id": worker_id,
                    "status": f"Analysing {task.game_id}",
                    "game_id": task.game_id,
                    "band": task.band,
                    "updated_at": utils.utc_now_iso(),
                }
            )

            attempts = 0
            while attempts < 3:
                try:
                    rows, analysed_positions = analyse_single_game(engine, task, depth)
                    utils.append_rows(worker_csv, rows, RAW_MOVE_FIELDS)
                    result_queue.put(
                        {
                            "type": "completed",
                            "worker_id": worker_id,
                            "game_id": task.game_id,
                            "band": task.band,
                            "positions": analysed_positions,
                            "rows": len(rows),
                            "updated_at": utils.utc_now_iso(),
                        }
                    )
                    break
                except (
                    AnalysisTimeoutError,
                    chess.engine.EngineTerminatedError,
                    chess.engine.EngineError,
                    OSError,
                ) as exc:
                    attempts += 1
                    logger.warning(
                        "Engine failure while processing %s (attempt %s/3): %s",
                        task.game_id,
                        attempts,
                        exc,
                    )
                    if engine is not None:
                        try:
                            engine.quit()
                        except Exception:
                            pass
                    engine = restart_engine(depth=depth, logger=logger)
                    if attempts >= 3:
                        result_queue.put(
                            {
                                "type": "deferred",
                                "worker_id": worker_id,
                                "task": task.__dict__,
                                "error": str(exc),
                                "updated_at": utils.utc_now_iso(),
                            }
                        )
                except Exception as exc:
                    logger.exception("Unexpected error while processing %s", task.game_id)
                    result_queue.put(
                        {
                            "type": "deferred",
                            "worker_id": worker_id,
                            "task": task.__dict__,
                            "error": str(exc),
                            "updated_at": utils.utc_now_iso(),
                        }
                    )
                    break
    finally:
        if engine is not None:
            try:
                engine.quit()
            except Exception:
                logger.warning("Engine did not exit cleanly for worker %s", worker_id)


def load_checkpoint(resume: bool) -> dict[str, Any]:
    """Load the Phase 2 checkpoint, or start a new one when not resuming."""
    checkpoint = utils.read_json(config.CHECKPOINT_JSON, utils.default_checkpoint())
    checkpoint.setdefault("completed_game_ids", [])
    checkpoint.setdefault("failed_games", [])
    checkpoint.setdefault("deferred_games", [])
    checkpoint.setdefault("worker_status", {})
    checkpoint.setdefault("recent_games", [])

    if not resume:
        checkpoint = utils.default_checkpoint()
        checkpoint["completed_game_ids"] = []
        checkpoint["failed_games"] = []
        checkpoint["deferred_games"] = []
    return checkpoint


def save_checkpoint(checkpoint: dict[str, Any]) -> None:
    """Persist the current checkpoint to disk."""
    checkpoint["updated_at"] = utils.utc_now_iso()
    utils.atomic_write_json(config.CHECKPOINT_JSON, checkpoint)


def merge_worker_outputs(logger) -> None:
    """Merge per-worker CSV files into the canonical raw_moves.csv file."""
    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for worker_csv in sorted(config.PHASE2_WORKER_DIR.glob("worker_*.csv")):
        with worker_csv.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                key = (row["game_id"], row["move_number"], row["player_color"])
                rows_by_key[key] = row

    if not rows_by_key:
        logger.warning("No worker output files found to merge.")
        return

    with config.RAW_MOVES_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_MOVE_FIELDS)
        writer.writeheader()
        for key in sorted(
            rows_by_key,
            key=lambda item: (item[0], int(item[1]), item[2]),
        ):
            writer.writerow(rows_by_key[key])
    logger.info("Merged %s analysed move rows into %s", len(rows_by_key), config.RAW_MOVES_CSV)


def run_analysis(
    resume: bool,
    max_games: int | None,
    max_games_per_band: int | None,
    depth: int,
    num_workers: int,
    game_ids_file: str | None,
) -> dict[str, Any]:
    """Coordinate worker processes, checkpoint updates, and final output merge."""
    logger = utils.setup_logging("phase2_analyse", "phase2_analyse.log")
    utils.ensure_directories()
    checkpoint = load_checkpoint(resume=resume)
    allowed_game_ids = None
    if game_ids_file:
        with Path(game_ids_file).open("r", encoding="utf-8") as handle:
            allowed_game_ids = {
                line.strip()
                for line in handle
                if line.strip() and not line.strip().startswith("#")
            }
        logger.info(
            "Restricting Phase 2 to %s game IDs from %s",
            len(allowed_game_ids),
            game_ids_file,
        )
    tasks = load_games_to_analyse(
        checkpoint=checkpoint,
        max_games=max_games,
        max_games_per_band=max_games_per_band,
        allowed_game_ids=allowed_game_ids,
    )

    if not resume:
        for worker_csv in config.PHASE2_WORKER_DIR.glob("worker_*.csv"):
            worker_csv.unlink()
        if config.RAW_MOVES_CSV.exists():
            config.RAW_MOVES_CSV.unlink()

    checkpoint["analysis_depth"] = depth
    checkpoint["num_workers"] = num_workers
    checkpoint["target_games"] = len(tasks) + checkpoint.get("total_games_completed", 0)
    save_checkpoint(checkpoint)

    if not tasks:
        logger.info("No games remaining to analyse.")
        merge_worker_outputs(logger)
        return checkpoint

    started_at = time.time()
    if num_workers <= 1:
        logger.info("Running Phase 2 in single-process mode.")
        engine = restart_engine(depth=depth, logger=logger)
        worker_csv = config.PHASE2_WORKER_DIR / "worker_0.csv"
        pending_tasks = collections.deque(tasks)
        remaining = len(tasks)
        try:
            while pending_tasks:
                task = pending_tasks.popleft()
                attempts = 0
                while attempts < 3:
                    try:
                        remaining -= 1
                        rows, analysed_positions = analyse_single_game(engine, task, depth)
                        utils.append_rows(worker_csv, rows, RAW_MOVE_FIELDS)
                        checkpoint["worker_status"]["0"] = {
                            "type": "completed",
                            "worker_id": 0,
                            "game_id": task.game_id,
                            "band": task.band,
                            "positions": analysed_positions,
                            "rows": len(rows),
                            "updated_at": utils.utc_now_iso(),
                        }
                        checkpoint["completed_game_ids"].append(task.game_id)
                        checkpoint["last_completed_game_id_per_band"][task.band] = task.game_id
                        checkpoint["games_completed_per_band"][task.band] += 1
                        checkpoint["total_games_completed"] += 1
                        checkpoint["total_positions_analysed"] += analysed_positions
                        checkpoint["recent_games"].append(
                            {
                                "game_id": task.game_id,
                                "band": task.band,
                                "positions": analysed_positions,
                                "completed_at": utils.utc_now_iso(),
                            }
                        )
                        checkpoint["recent_games"] = checkpoint["recent_games"][-10:]
                        elapsed = max(time.time() - started_at, 1.0)
                        logger.info(
                            "Completed %s (%s remaining). Total games=%s, positions=%s, %.2f games/hour, %.2f positions/second",
                            task.game_id,
                            remaining,
                            checkpoint["total_games_completed"],
                            checkpoint["total_positions_analysed"],
                            checkpoint["total_games_completed"] / elapsed * 3600.0,
                            checkpoint["total_positions_analysed"] / elapsed,
                        )
                        save_checkpoint(checkpoint)
                        break
                    except (
                        AnalysisTimeoutError,
                        chess.engine.EngineTerminatedError,
                        chess.engine.EngineError,
                        OSError,
                    ) as exc:
                        attempts += 1
                        remaining += 1
                        logger.warning(
                            "Engine failure while processing %s in single-process mode (attempt %s/3): %s",
                            task.game_id,
                            attempts,
                            exc,
                        )
                        try:
                            engine.quit()
                        except Exception:
                            pass
                        engine = restart_engine(depth=depth, logger=logger)
                        if attempts >= 3:
                            remaining += 1
                            deferred_task = GameTask(
                                game_id=task.game_id,
                                band=task.band,
                                pgn_path=task.pgn_path,
                                defer_round=task.defer_round + 1,
                            )
                            if deferred_task.defer_round > config.MAX_DEFERRED_ROUNDS:
                                checkpoint["failed_games"].append(
                                    {
                                        "type": "failed",
                                        "worker_id": 0,
                                        "game_id": task.game_id,
                                        "band": task.band,
                                        "error": str(exc),
                                        "updated_at": utils.utc_now_iso(),
                                    }
                                )
                                remaining -= 1
                                logger.error(
                                    "Deferred-game limit reached for %s after %s rounds.",
                                    task.game_id,
                                    deferred_task.defer_round - 1,
                                )
                            else:
                                checkpoint["deferred_games"].append(
                                    {
                                        "game_id": task.game_id,
                                        "band": task.band,
                                        "defer_round": deferred_task.defer_round,
                                        "updated_at": utils.utc_now_iso(),
                                        "error": str(exc),
                                    }
                                )
                                pending_tasks.append(deferred_task)
                                logger.warning(
                                    "Deferring %s to the back of the queue (round %s/%s).",
                                    task.game_id,
                                    deferred_task.defer_round,
                                    config.MAX_DEFERRED_ROUNDS,
                                )
                            save_checkpoint(checkpoint)
                            break
        finally:
            engine.quit()
    else:
        task_queue: mp.Queue = mp.Queue()
        result_queue: mp.Queue = mp.Queue()
        pending_tasks = collections.deque(tasks)
        active_tasks = 0

        workers = [
            mp.Process(
                target=worker_process,
                args=(worker_id, task_queue, result_queue, depth),
                name=f"phase2-worker-{worker_id}",
            )
            for worker_id in range(num_workers)
        ]

        for worker in workers:
            worker.start()

        remaining = len(tasks)
        for _ in range(min(num_workers, len(pending_tasks))):
            task_queue.put(pending_tasks.popleft().__dict__)
            active_tasks += 1

        while remaining > 0 and active_tasks > 0:
            try:
                message = result_queue.get(timeout=config.PHASE2_WORKER_POLL_SECONDS)
            except queue.Empty:
                for worker in workers:
                    checkpoint["worker_status"][str(worker.pid)] = {
                        "alive": worker.is_alive(),
                        "updated_at": utils.utc_now_iso(),
                    }
                save_checkpoint(checkpoint)
                continue

            message_type = message["type"]
            worker_id = str(message["worker_id"])
            checkpoint["worker_status"][worker_id] = message

            if message_type == "status":
                logger.info("Worker %s: %s", worker_id, message["status"])
            elif message_type == "completed":
                remaining -= 1
                active_tasks -= 1
                game_id = message["game_id"]
                band = message["band"]
                checkpoint["completed_game_ids"].append(game_id)
                checkpoint["last_completed_game_id_per_band"][band] = game_id
                checkpoint["games_completed_per_band"][band] += 1
                checkpoint["total_games_completed"] += 1
                checkpoint["total_positions_analysed"] += message["positions"]
                checkpoint["recent_games"].append(
                    {
                        "game_id": game_id,
                        "band": band,
                        "positions": message["positions"],
                        "completed_at": message["updated_at"],
                    }
                )
                checkpoint["recent_games"] = checkpoint["recent_games"][-10:]
                elapsed = max(time.time() - started_at, 1.0)
                games_per_hour = checkpoint["total_games_completed"] / elapsed * 3600.0
                positions_per_second = checkpoint["total_positions_analysed"] / elapsed
                logger.info(
                    "Completed %s (%s remaining). Total games=%s, positions=%s, %.2f games/hour, %.2f positions/second",
                    game_id,
                    remaining,
                    checkpoint["total_games_completed"],
                    checkpoint["total_positions_analysed"],
                    games_per_hour,
                    positions_per_second,
                )
                save_checkpoint(checkpoint)
            elif message_type == "deferred":
                active_tasks -= 1
                task = GameTask(**message["task"])
                deferred_task = GameTask(
                    game_id=task.game_id,
                    band=task.band,
                    pgn_path=task.pgn_path,
                    defer_round=task.defer_round + 1,
                )
                if deferred_task.defer_round > config.MAX_DEFERRED_ROUNDS:
                    remaining -= 1
                    checkpoint["failed_games"].append(
                        {
                            "type": "failed",
                            "worker_id": worker_id,
                            "game_id": task.game_id,
                            "band": task.band,
                            "error": message["error"],
                            "updated_at": message["updated_at"],
                        }
                    )
                    logger.error(
                        "Worker %s exhausted deferred retries for game %s. Marking failed.",
                        worker_id,
                        task.game_id,
                    )
                else:
                    checkpoint["deferred_games"].append(
                        {
                            "game_id": task.game_id,
                            "band": task.band,
                            "defer_round": deferred_task.defer_round,
                            "updated_at": message["updated_at"],
                            "error": message["error"],
                        }
                    )
                    pending_tasks.append(deferred_task)
                    logger.warning(
                        "Worker %s deferred game %s to the back of the queue (round %s/%s).",
                        worker_id,
                        task.game_id,
                        deferred_task.defer_round,
                        config.MAX_DEFERRED_ROUNDS,
                    )
                save_checkpoint(checkpoint)

            while pending_tasks and active_tasks < num_workers:
                task_queue.put(pending_tasks.popleft().__dict__)
                active_tasks += 1

        for worker in workers:
            task_queue.put(None)
        for worker in workers:
            worker.join()

    merge_worker_outputs(logger)
    save_checkpoint(checkpoint)
    return checkpoint


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for Phase 2."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint.json.")
    parser.add_argument(
        "--max-games",
        type=int,
        default=None,
        help="Limit analysis to a small number of games for testing.",
    )
    parser.add_argument(
        "--max-games-per-band",
        type=int,
        default=None,
        help="Limit analysis to at most this many games from each rating band.",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=config.DEPTH,
        help="Stockfish search depth to use.",
    )
    parser.add_argument(
        "--num-workers",
        type=int,
        default=config.NUM_WORKERS,
        help="Override the number of Phase 2 worker processes.",
    )
    parser.add_argument(
        "--game-ids-file",
        type=str,
        default=None,
        help="Optional text file listing game IDs to analyse, one per line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for Phase 2."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        run_analysis(
            resume=args.resume,
            max_games=args.max_games,
            max_games_per_band=args.max_games_per_band,
            depth=args.depth,
            num_workers=args.num_workers,
            game_ids_file=args.game_ids_file,
        )
    except Exception as exc:  # pragma: no cover - top-level safety
        logger = utils.setup_logging("phase2_analyse", "phase2_analyse.log")
        logger.exception("Phase 2 failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    sys.exit(main())
