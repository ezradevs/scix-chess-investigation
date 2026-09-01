"""Lightweight Flask dashboard for Phase 2 monitoring.

The dashboard reads the Phase 2 checkpoint and log files, then displays progress
metrics in a simple auto-refreshing web page. It is read-only and safe to run
separately from the analysis process.

Run from the repository root:
    python -m src.dashboard
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template_string

import config
from src import utils


APP = Flask(__name__)
CPU_SNAPSHOT: tuple[int, int] | None = None


HTML_TEMPLATE = """
<!doctype html>
<html lang="en">

<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="{{ refresh_seconds }}">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Chess Pipeline Dashboard</title>
    <style>
        *,
        *::before,
        *::after {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #f0f2f5;
            color: #1a1a2e;
            padding: 32px 40px;
            line-height: 1.6;
            min-height: 100vh;
        }

        h1 {
            font-size: 1.75rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            color: #111827;
            margin-bottom: 4px;
        }

        body > p {
            font-size: 0.85rem;
            color: #6b7280;
            margin-bottom: 24px;
        }

        h2 {
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #6b7280;
            margin-bottom: 16px;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }

        .card {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 14px;
            padding: 24px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.03);
            transition: box-shadow 0.2s ease, transform 0.2s ease;
        }

        .card:hover {
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06), 0 8px 24px rgba(0, 0, 0, 0.06);
            transform: translateY(-2px);
        }

        .card p {
            font-size: 0.9rem;
            color: #374151;
            margin-bottom: 6px;
        }

        .bar {
            background: #e5e7eb;
            border-radius: 999px;
            overflow: hidden;
            height: 10px;
            margin-top: 6px;
            margin-bottom: 14px;
        }

        .fill {
            background: linear-gradient(90deg, #6366f1, #8b5cf6);
            height: 100%;
            border-radius: 999px;
            transition: width 0.6s cubic-bezier(0.22, 1, 0.36, 1);
        }

        ul {
            list-style: none;
            padding-left: 0;
        }

        ul li {
            padding: 6px 0;
            border-bottom: 1px solid #f3f4f6;
            font-size: 0.82rem;
        }

        ul li:last-child {
            border-bottom: none;
        }

        code {
            font-family: "SF Mono", "Fira Code", "Cascadia Code", Menlo, monospace;
            font-size: 0.82rem;
            background: #f3f4f6;
            color: #4b5563;
            padding: 2px 7px;
            border-radius: 6px;
        }

        @media (max-width: 640px) {
            body {
                padding: 20px 16px;
            }

            .grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>

<body>
    <h1>Phase 2 Monitoring Dashboard</h1>
    <p>Auto-refresh every {{ refresh_seconds }} seconds. Last checkpoint update: {{ checkpoint.updated_at or "N/A" }}
    </p>
    <div class="grid">
        <div class="card">
            <h2>Overall Progress</h2>
            <p>{{ checkpoint.total_games_completed }} / {{ target_games }} games analysed</p>
            <div class="bar">
                <div class="fill" style="width: {{ overall_progress_pct }}%;"></div>
            </div>
            <p>Speed: {{ games_per_hour }} games/hour</p>
            <p>Speed: {{ positions_per_second }} positions/second</p>
            <p>ETA: {{ eta_text }}</p>
            <p>Uptime: {{ uptime_text }}</p>
        </div>
        <div class="card">
            <h2>System Usage</h2>
            <p>CPU usage: {{ cpu_percent }}%</p>
            <p>Memory usage: {{ memory_percent }}%</p>
            <p>Load average: {{ load_average }}</p>
            <p>Current PID: <code>{{ pid }}</code></p>
        </div>
        <div class="card">
            <h2>Per-Band Progress</h2>
            {% for band in band_progress %}
            <p>Band {{ band.band }}: {{ band.completed }} / {{ band.target }}</p>
            <div class="bar">
                <div class="fill" style="width: {{ band.percent }}%;"></div>
            </div>
            {% endfor %}
        </div>
        <div class="card">
            <h2>Recent Log Entries</h2>
            <ul>
                {% for line in log_lines %}
                <li><code>{{ line }}</code></li>
                {% endfor %}
            </ul>
        </div>
    </div>
</body>

</html>
"""
def read_cpu_snapshot() -> tuple[int, int]:
    """Read aggregate CPU counters from `/proc/stat`."""
    with Path("/proc/stat").open("r", encoding="utf-8") as handle:
        first_line = handle.readline().strip().split()
    values = [int(part) for part in first_line[1:]]
    idle = values[3] + values[4]
    total = sum(values)
    return idle, total


def current_cpu_percent() -> float:
    """Estimate CPU usage using the delta between dashboard refreshes."""
    global CPU_SNAPSHOT
    current = read_cpu_snapshot()
    if CPU_SNAPSHOT is None:
        CPU_SNAPSHOT = current
        return 0.0

    prev_idle, prev_total = CPU_SNAPSHOT
    idle, total = current
    CPU_SNAPSHOT = current
    total_delta = max(total - prev_total, 1)
    idle_delta = max(idle - prev_idle, 0)
    return round((1 - idle_delta / total_delta) * 100, 2)


def current_memory_percent() -> float:
    """Read memory usage from `/proc/meminfo`."""
    meminfo = {}
    with Path("/proc/meminfo").open("r", encoding="utf-8") as handle:
        for line in handle:
            key, value = line.split(":", 1)
            meminfo[key] = int(value.strip().split()[0])
    total = meminfo.get("MemTotal", 1)
    available = meminfo.get("MemAvailable", 0)
    used = total - available
    return round((used / total) * 100, 2)


def format_duration(seconds: float | None) -> str:
    """Render a duration in a human-readable form."""
    if seconds is None:
        return "Unknown"
    total = int(max(seconds, 0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}h {minutes}m {secs}s"


def collect_log_lines() -> list[str]:
    """Read the newest lines from the Phase 2-related log files."""
    lines = []
    for log_path in sorted(config.LOG_DIR.glob("phase2*.log")):
        lines.extend(utils.tail_lines(log_path, config.LOG_TAIL_LINES))
    lines = sorted(lines)[-config.LOG_TAIL_LINES :]
    return lines


def load_checkpoint() -> dict:
    """Load the current checkpoint if it exists."""
    return utils.read_json(config.CHECKPOINT_JSON, utils.default_checkpoint())


@APP.route("/")
def home():
    """Render the monitoring dashboard."""
    checkpoint = load_checkpoint()
    target_games = checkpoint.get("target_games") or (config.TARGET_GAMES_PER_BAND * len(config.RATING_BANDS))
    completed = checkpoint.get("total_games_completed", 0)
    positions = checkpoint.get("total_positions_analysed", 0)

    started_at_text = checkpoint.get("started_at")
    started_at = None
    if started_at_text:
        started_at = datetime.fromisoformat(started_at_text)
    now = datetime.now(timezone.utc)
    elapsed_seconds = (now - started_at).total_seconds() if started_at else None
    games_per_hour = round((completed / elapsed_seconds) * 3600, 2) if elapsed_seconds and completed else 0.0
    positions_per_second = round(positions / elapsed_seconds, 2) if elapsed_seconds and positions else 0.0

    remaining_games = max(target_games - completed, 0)
    eta_seconds = (remaining_games / completed) * elapsed_seconds if elapsed_seconds and completed else None

    band_progress = []
    for band in sorted(config.RATING_BANDS):
        completed_band = checkpoint.get("games_completed_per_band", {}).get(str(band), 0)
        percent = round((completed_band / config.TARGET_GAMES_PER_BAND) * 100, 2)
        band_progress.append(
            {
                "band": band,
                "completed": completed_band,
                "target": config.TARGET_GAMES_PER_BAND,
                "percent": percent,
            }
        )

    return render_template_string(
        HTML_TEMPLATE,
        refresh_seconds=config.DASHBOARD_REFRESH_SECONDS,
        checkpoint=checkpoint,
        target_games=target_games,
        overall_progress_pct=round((completed / target_games) * 100, 2) if target_games else 0.0,
        games_per_hour=games_per_hour,
        positions_per_second=positions_per_second,
        eta_text=format_duration(eta_seconds),
        uptime_text=format_duration(elapsed_seconds),
        cpu_percent=current_cpu_percent(),
        memory_percent=current_memory_percent(),
        load_average=", ".join(f"{value:.2f}" for value in os.getloadavg()),
        pid=os.getpid(),
        band_progress=band_progress,
        log_lines=collect_log_lines(),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the dashboard."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    utils.setup_logging("dashboard", "dashboard.log")
    APP.run(host=config.DASHBOARD_HOST, port=config.DASHBOARD_PORT, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
