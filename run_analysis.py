"""Master runner for the chess research pipeline (Phases 1-3).

This script provides one entry point for running individual phases or all of
Phases 1-3 in sequence. These phases acquire games, run the Stockfish
analysis, and produce the cleaned `analysed_moves.csv` dataset.

Phases 4 (statistics) and 5 (visualisation) are done interactively in
Jupyter notebooks under `analysis/notebooks/` once
`data/processed/analysed_moves.csv` exists - see
`analysis/README.md`.

Examples:
    python run_analysis.py --phase 1
    python run_analysis.py --phase 2 --resume
    python run_analysis.py --phase all
"""

from __future__ import annotations

import argparse
import subprocess
import sys

import config
from src import utils


PHASE_TO_MODULE = {
    "1": "src.phase1_acquire",
    "2": "src.phase2_analyse",
    "3": "src.phase3_structure",
}


def build_phase_command(phase: str, args: argparse.Namespace) -> list[str]:
    """Translate master-runner options into a module command."""
    command = [sys.executable, "-m", PHASE_TO_MODULE[phase]]
    if phase == "1":
        if args.months:
            command.extend(["--months", *args.months])
        if args.target_per_band is not None:
            command.extend(["--target-per-band", str(args.target_per_band)])
        if args.band_targets_file is not None:
            command.extend(["--band-targets-file", str(args.band_targets_file)])
        if args.test_mode:
            command.append("--test-mode")
        if args.resume_existing:
            command.append("--resume-existing")
    if phase == "2":
        if args.resume:
            command.append("--resume")
        if args.max_games is not None:
            command.extend(["--max-games", str(args.max_games)])
        if args.max_games_per_band is not None:
            command.extend(["--max-games-per-band", str(args.max_games_per_band)])
        if args.depth is not None:
            command.extend(["--depth", str(args.depth)])
        if args.num_workers is not None:
            command.extend(["--num-workers", str(args.num_workers)])
        if args.game_ids_file is not None:
            command.extend(["--game-ids-file", str(args.game_ids_file)])
    return command


def run_phase(phase: str, args: argparse.Namespace) -> None:
    """Run one phase as a subprocess and stop on failure."""
    logger = utils.setup_logging("run_analysis", "run_analysis.log")
    command = build_phase_command(phase, args)
    logger.info("Running phase %s with command: %s", phase, " ".join(command))
    subprocess.run(command, check=True, cwd=config.BASE_DIR)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the master runner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=["1", "2", "3", "all"])
    parser.add_argument("--resume", action="store_true", help="Resume Phase 2 from checkpoint.")
    parser.add_argument("--months", nargs="+", help="Override months for Phase 1.")
    parser.add_argument("--target-per-band", type=int, help="Override Phase 1 target per band.")
    parser.add_argument(
        "--band-targets-file",
        type=str,
        help="JSON file of exact cumulative Phase 1 targets by band.",
    )
    parser.add_argument("--test-mode", action="store_true", help="Run Phase 1 in tiny-sample mode.")
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help="Reuse existing Phase 1 metadata and PGNs when running acquisition.",
    )
    parser.add_argument("--max-games", type=int, help="Limit Phase 2 to a test-sized number of games.")
    parser.add_argument("--max-games-per-band", type=int, help="Limit Phase 2 to this many games per rating band.")
    parser.add_argument("--depth", type=int, help="Override Phase 2 analysis depth.")
    parser.add_argument("--num-workers", type=int, help="Override Phase 2 worker count.")
    parser.add_argument("--game-ids-file", type=str, help="Limit Phase 2 to game IDs listed in a text file.")
    args = parser.parse_args(argv)

    try:
        if args.phase == "all":
            for phase in ["1", "2", "3"]:
                run_phase(phase, args)
        else:
            run_phase(args.phase, args)
    except subprocess.CalledProcessError as exc:
        logger = utils.setup_logging("run_analysis", "run_analysis.log")
        logger.exception("Pipeline runner failed: %s", exc)
        return exc.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
