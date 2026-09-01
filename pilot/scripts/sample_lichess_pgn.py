#!/usr/bin/env python3
"""Sample balanced 5+0 Lichess games from a PGN stream on stdin."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

import chess.pgn


BAND_ORDER = ["<1000", "1000-1499", "1500-1999", "2000-2299", "2300+"]


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


def extract_game_id(site: str) -> str:
    return site.rstrip("/").split("/")[-1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games-per-band", type=int, default=40)
    parser.add_argument("--max-games-read", type=int, default=700000)
    parser.add_argument("--seed", type=int, default=20260303)
    parser.add_argument(
        "--band-mode",
        choices=["same_band_only", "average_rating"],
        default="same_band_only",
        help="How to assign a game to a rating band.",
    )
    parser.add_argument("--output-pgn", required=True)
    parser.add_argument("--output-manifest", required=True)
    args = parser.parse_args()

    random.seed(args.seed)

    target = {band: args.games_per_band for band in BAND_ORDER}
    selected: dict[str, list[chess.pgn.Game]] = {band: [] for band in BAND_ORDER}
    seen_ids: set[str] = set()

    stats = Counter()
    games_read = 0

    while games_read < args.max_games_read:
        game = chess.pgn.read_game(sys.stdin)
        if game is None:
            break

        games_read += 1
        stats["games_read"] += 1
        if games_read % 10000 == 0:
            progress = {b: len(selected[b]) for b in BAND_ORDER}
            print(
                f"progress games_read={games_read} selected={progress}",
                file=sys.stderr,
                flush=True,
            )

        if game.headers.get("TimeControl") != "300+0":
            stats["filtered_time_control"] += 1
            continue

        white_elo = game.headers.get("WhiteElo")
        black_elo = game.headers.get("BlackElo")
        site = game.headers.get("Site", "")

        if not white_elo or not black_elo or not site:
            stats["filtered_missing_headers"] += 1
            continue

        try:
            white_rating = int(white_elo)
            black_rating = int(black_elo)
        except ValueError:
            stats["filtered_bad_rating"] += 1
            continue

        gid = extract_game_id(site)
        if gid in seen_ids:
            stats["filtered_duplicate_id"] += 1
            continue

        white_band = rating_band(white_rating)
        black_band = rating_band(black_rating)
        if args.band_mode == "same_band_only":
            # Proposal requirement for the full study.
            if white_band != black_band:
                stats["filtered_cross_band"] += 1
                continue
            band = white_band
        else:
            avg_rating = int(round((white_rating + black_rating) / 2.0))
            band = rating_band(avg_rating)

        if game.end().ply() < 20:
            stats["filtered_short_game"] += 1
            continue

        if len(selected[band]) >= target[band]:
            stats["filtered_quota_full"] += 1
            continue

        selected[band].append(game)
        seen_ids.add(gid)
        stats[f"selected_{band}"] += 1

        if all(len(selected[b]) >= target[b] for b in BAND_ORDER):
            break

    output_path = Path(args.output_pgn)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest_games = []
    with output_path.open("w", encoding="utf-8") as out:
        for band in BAND_ORDER:
            for game in selected[band]:
                out.write(str(game))
                out.write("\n\n")
                manifest_games.append(
                    {
                        "game_id": extract_game_id(game.headers.get("Site", "")),
                        "site": game.headers.get("Site"),
                        "date": game.headers.get("Date"),
                        "white": game.headers.get("White"),
                        "black": game.headers.get("Black"),
                        "white_elo": int(game.headers["WhiteElo"]),
                        "black_elo": int(game.headers["BlackElo"]),
                        "rating_band": band,
                        "time_control": game.headers.get("TimeControl"),
                    }
                )

    manifest = {
        "source": "Lichess monthly standard rated dump stream",
        "selection_time_control": "300+0",
        "band_mode": args.band_mode,
        "games_read": games_read,
        "selected_counts": {band: len(selected[band]) for band in BAND_ORDER},
        "target_per_band": args.games_per_band,
        "stats": dict(stats),
        "games": manifest_games,
    }

    manifest_path = Path(args.output_manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({"selected_counts": manifest["selected_counts"], "games_read": games_read}, indent=2))


if __name__ == "__main__":
    main()
