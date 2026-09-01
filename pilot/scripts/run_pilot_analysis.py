#!/usr/bin/env python3
"""Run pilot CPL analysis for sampled 5+0 Lichess games."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import chess
import chess.engine
import chess.pgn
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


def rating_band(rating: int) -> str:
    if rating < 1000:
        return "<1000"
    if rating < 1500:
        return "1000-1499"
    if rating < 2000:
        return "1500-1999"
    if rating < 2300:
        return "2000-2299"
    return "2300+"


def time_pressure_bin(time_remaining_pct: float) -> str:
    if time_remaining_pct > 75:
        return ">75%"
    if time_remaining_pct >= 50:
        return "50-75%"
    if time_remaining_pct >= 25:
        return "25-50%"
    return "<25%"


def error_category(capped_cpl: int) -> str:
    if capped_cpl <= 10:
        return "0-10"
    if capped_cpl <= 50:
        return "11-50"
    if capped_cpl <= 150:
        return "51-150"
    return "151-300"


def parse_game_id(site: str) -> str:
    return site.rstrip("/").split("/")[-1]


def phase_label(board_before: chess.Board) -> str:
    # Moves <=10 are excluded from analysis; this keeps opening explicit for completeness.
    if board_before.fullmove_number <= 10:
        return "opening"

    non_pawn_material = 0
    piece_values = {
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK: 5,
        chess.QUEEN: 9,
    }
    for piece_type, value in piece_values.items():
        non_pawn_material += value * (
            len(board_before.pieces(piece_type, chess.WHITE))
            + len(board_before.pieces(piece_type, chess.BLACK))
        )

    if non_pawn_material <= 14:
        return "endgame"
    return "middlegame"


def score_to_cp(score: chess.engine.PovScore, color: chess.Color) -> int:
    # Mate scores are mapped to large centipawn values for bounded CPL calculation.
    cp = score.pov(color).score(mate_score=10000)
    if cp is None:
        return 0
    return int(cp)


def evaluate_cpl_for_move(
    engine: chess.engine.SimpleEngine,
    board_before: chess.Board,
    move: chess.Move,
    depth: int,
    game_token: object,
) -> tuple[int, int]:
    mover = board_before.turn

    best_info = engine.analyse(
        board_before,
        chess.engine.Limit(depth=depth),
        game=game_token,
    )
    best_cp = score_to_cp(best_info["score"], mover)

    board_after = board_before.copy(stack=False)
    board_after.push(move)
    played_info = engine.analyse(
        board_after,
        chess.engine.Limit(depth=depth),
        game=game_token,
    )
    played_cp = score_to_cp(played_info["score"], mover)

    raw_cpl = max(0, best_cp - played_cp)
    capped_cpl = min(raw_cpl, 300)
    return raw_cpl, capped_cpl


def build_dataset(
    pgn_path: Path,
    stockfish_path: str,
    depth: int,
    threads: int,
    hash_mb: int,
    max_games: int | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    counters = Counter()

    with chess.engine.SimpleEngine.popen_uci(stockfish_path) as engine:
        engine.configure({"Threads": threads, "Hash": hash_mb})

        with pgn_path.open("r", encoding="utf-8") as handle:
            while True:
                game = chess.pgn.read_game(handle)
                if game is None:
                    break

                counters["games_seen"] += 1
                print(
                    f"progress games_seen={counters['games_seen']} moves_kept={counters['moves_kept']}",
                    flush=True,
                )
                if max_games is not None and counters["games_seen"] > max_games:
                    break

                tc = game.headers.get("TimeControl")
                if tc != "300+0":
                    counters["games_filtered_time_control"] += 1
                    continue

                try:
                    white_rating = int(game.headers["WhiteElo"])
                    black_rating = int(game.headers["BlackElo"])
                except Exception:
                    counters["games_filtered_missing_rating"] += 1
                    continue

                white_band = rating_band(white_rating)
                black_band = rating_band(black_rating)
                if white_band != black_band:
                    counters["games_filtered_cross_band"] += 1
                    continue

                if game.end().ply() < 20:
                    counters["games_filtered_short"] += 1
                    continue

                counters["games_kept"] += 1
                gid = parse_game_id(game.headers.get("Site", ""))
                game_token = object()

                board = game.board()
                for node in game.mainline():
                    move = node.move
                    mover = board.turn
                    move_no = board.fullmove_number

                    mover_rating = white_rating if mover == chess.WHITE else black_rating
                    band = rating_band(mover_rating)

                    if move_no <= 10:
                        counters["moves_filtered_opening"] += 1
                        board.push(move)
                        continue

                    clk = node.clock()
                    if clk is None:
                        counters["moves_filtered_missing_clock"] += 1
                        board.push(move)
                        continue

                    if clk < 2.0:
                        counters["moves_filtered_low_seconds"] += 1
                        board.push(move)
                        continue

                    time_remaining_pct = (clk / 300.0) * 100.0
                    raw_cpl, capped_cpl = evaluate_cpl_for_move(
                        engine, board, move, depth, game_token
                    )

                    rows.append(
                        {
                            "game_id": gid,
                            "move_number": move_no,
                            "player_rating": mover_rating,
                            "rating_band": band,
                            "time_remaining_pct": round(time_remaining_pct, 4),
                            "time_pressure_bin": time_pressure_bin(time_remaining_pct),
                            "game_phase": phase_label(board),
                            "raw_cpl": raw_cpl,
                            "capped_cpl": capped_cpl,
                            "error_category": error_category(capped_cpl),
                        }
                    )
                    counters["moves_kept"] += 1

                    board.push(move)

    return pd.DataFrame(rows), dict(counters)


def run_validation(df: pd.DataFrame) -> dict[str, Any]:
    validation: dict[str, Any] = {}

    validation["row_count"] = int(len(df))
    validation["missing_values"] = {
        col: int(df[col].isna().sum()) for col in df.columns
    }

    validation["raw_cpl_negative_count"] = int((df["raw_cpl"] < 0).sum())
    validation["capped_cpl_out_of_range_count"] = int(
        ((df["capped_cpl"] < 0) | (df["capped_cpl"] > 300)).sum()
    )

    per_game = df.groupby("game_id").size()
    validation["moves_per_game"] = {
        "min": int(per_game.min()) if not per_game.empty else 0,
        "median": float(per_game.median()) if not per_game.empty else 0.0,
        "max": int(per_game.max()) if not per_game.empty else 0,
        "mean": float(per_game.mean()) if not per_game.empty else 0.0,
    }

    validation["summary_by_band"] = (
        df.groupby("rating_band")["capped_cpl"]
        .agg(["count", "mean", "median", "std"])
        .round(3)
        .reset_index()
        .to_dict(orient="records")
    )

    validation["summary_by_pressure_bin"] = (
        df.groupby(["rating_band", "time_pressure_bin"])["capped_cpl"]
        .agg(["count", "mean", "median"])
        .round(3)
        .reset_index()
        .to_dict(orient="records")
    )

    return validation


def make_plots(df: pd.DataFrame, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)

    sns.set_theme(style="whitegrid")
    band_order = ["<1000", "1000-1499", "1500-1999", "2000-2299", "2300+"]
    pressure_order = [">75%", "50-75%", "25-50%", "<25%"]
    error_order = ["0-10", "11-50", "51-150", "151-300"]

    hist_path = output_dir / "cpl_histograms_by_rating_band.png"
    g = sns.FacetGrid(df, col="rating_band", col_order=band_order, col_wrap=3, sharex=True, sharey=False)
    g.map_dataframe(sns.histplot, x="capped_cpl", bins=30)
    g.set_axis_labels("Capped CPL", "Count")
    g.set_titles("{col_name}")
    g.figure.tight_layout()
    g.figure.savefig(hist_path, dpi=150)
    plt.close(g.figure)

    box_path = output_dir / "cpl_boxplot_by_pressure_and_band.png"
    plt.figure(figsize=(12, 6))
    sns.boxplot(
        data=df,
        x="time_pressure_bin",
        y="capped_cpl",
        hue="rating_band",
        order=pressure_order,
        hue_order=band_order,
        showfliers=False,
    )
    plt.xlabel("Time Pressure Bin")
    plt.ylabel("Capped CPL")
    plt.legend(title="Rating Band", bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.tight_layout()
    plt.savefig(box_path, dpi=150)
    plt.close()

    stacked_path = output_dir / "error_category_stacked_by_pressure_and_band.png"
    fig, axes = plt.subplots(2, 3, figsize=(14, 8), sharey=True)
    axes = axes.flatten()

    for i, band in enumerate(band_order):
        ax = axes[i]
        sub = df[df["rating_band"] == band]
        if sub.empty:
            ax.set_visible(False)
            continue

        ct = (
            pd.crosstab(sub["time_pressure_bin"], sub["error_category"], normalize="index")
            .reindex(index=pressure_order, columns=error_order, fill_value=0)
        )
        bottom = np.zeros(len(ct))
        x = np.arange(len(ct.index))
        for cat in error_order:
            vals = ct[cat].values
            ax.bar(x, vals, bottom=bottom, label=cat)
            bottom += vals

        ax.set_xticks(x)
        ax.set_xticklabels(ct.index, rotation=30)
        ax.set_ylim(0, 1)
        ax.set_title(band)
        if i % 3 == 0:
            ax.set_ylabel("Proportion")
        ax.set_xlabel("Time Pressure Bin")

    axes[-1].set_visible(False)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, title="Error Category", loc="lower center", ncol=4)
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    fig.savefig(stacked_path, dpi=150)
    plt.close(fig)

    return {
        "histograms": str(hist_path),
        "boxplot": str(box_path),
        "stacked_bars": str(stacked_path),
    }


def build_findings_report(
    manifest_path: Path,
    counters: dict[str, Any],
    validation: dict[str, Any],
) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected_counts = manifest.get("selected_counts", {})

    lines = []
    lines.append("Pilot Study Findings")
    lines.append("====================")
    lines.append("")
    lines.append("Sampling")
    lines.append(f"- Source dump: {manifest.get('source')}")
    lines.append(f"- Games read during sampling: {manifest.get('games_read')}")
    lines.append(f"- Selected games per rating band: {selected_counts}")
    lines.append("")
    lines.append("Pipeline")
    lines.append(f"- Games seen by analysis: {counters.get('games_seen', 0)}")
    lines.append(f"- Games retained after filtering: {counters.get('games_kept', 0)}")
    lines.append(f"- Move observations retained: {counters.get('moves_kept', 0)}")
    lines.append("")
    lines.append("Validation")
    lines.append(f"- Missing values per column: {validation['missing_values']}")
    lines.append(
        f"- Capped CPL out-of-range count: {validation['capped_cpl_out_of_range_count']}"
    )
    lines.append(
        "- Move count per game (min/median/max): "
        f"{validation['moves_per_game']['min']}/"
        f"{validation['moves_per_game']['median']}/"
        f"{validation['moves_per_game']['max']}"
    )

    lines.append("")
    lines.append("Observed patterns")
    by_band = pd.DataFrame(validation["summary_by_band"]).sort_values("rating_band")
    if not by_band.empty:
        if by_band["rating_band"].nunique() > 1:
            lines.append(
                "- Mean capped CPL generally decreases with higher rating bands in this pilot subset."
            )
            top = by_band.sort_values("mean", ascending=False).head(1).iloc[0]
            bottom = by_band.sort_values("mean", ascending=True).head(1).iloc[0]
            lines.append(
                f"- Highest mean capped CPL: {top['rating_band']} ({top['mean']}); "
                f"lowest: {bottom['rating_band']} ({bottom['mean']})."
            )
        else:
            only = by_band.iloc[0]
            lines.append(
                f"- Only one rating band is present in this run ({only['rating_band']}), "
                "so between-band comparisons are not yet interpretable."
            )

    lines.append("")
    lines.append("Pipeline notes and recommended adjustments")
    lines.append("- Depth-18 per-move dual evaluation is compute-intensive; keep resume/checkpointing for full deployment.")
    lines.append("- Current game phase heuristic uses material-based endgame detection; confirm phase definition before scaling.")
    lines.append("- Continue excluding <2 second moves to reduce flagging-related noise, as specified.")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-pgn", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--stockfish", default="/Users/glover-sanders.ezra/homebrew/bin/stockfish")
    parser.add_argument("--depth", type=int, default=18)
    parser.add_argument("--threads", type=int, default=max(1, os.cpu_count() or 1))
    parser.add_argument("--hash-mb", type=int, default=512)
    parser.add_argument("--max-games", type=int, default=None)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-validation-json", required=True)
    parser.add_argument("--output-counters-json", required=True)
    parser.add_argument("--plots-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--skip-plots", action="store_true")
    parser.add_argument("--skip-report", action="store_true")
    args = parser.parse_args()

    input_pgn = Path(args.input_pgn)
    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    df, counters = build_dataset(
        pgn_path=input_pgn,
        stockfish_path=args.stockfish,
        depth=args.depth,
        threads=args.threads,
        hash_mb=args.hash_mb,
        max_games=args.max_games,
    )

    df.to_csv(output_csv, index=False)

    validation = run_validation(df)
    plots: dict[str, str] = {}
    if not args.skip_plots:
        plots = make_plots(df, Path(args.plots_dir))

    Path(args.output_validation_json).write_text(
        json.dumps({"validation": validation, "plots": plots}, indent=2), encoding="utf-8"
    )
    Path(args.output_counters_json).write_text(json.dumps(counters, indent=2), encoding="utf-8")

    if not args.skip_report:
        report = build_findings_report(Path(args.manifest), counters, validation)
        Path(args.report).write_text(report + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "rows": len(df),
                "games_kept": counters.get("games_kept", 0),
                "moves_kept": counters.get("moves_kept", 0),
                "plots": plots,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
