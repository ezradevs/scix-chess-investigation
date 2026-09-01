# Chess Time-Pressure Decision-Making Pipeline

This repository contains a full pipeline for investigating how time pressure
affects the *severity distribution* of decision-making errors across levels
of expertise, using chess as a large-scale naturalistic cognitive model
system.

**Project title:** "Investigating how time pressure modulates decision-making
error severity distributions across expertise levels: a large-scale chess
analysis"

**Scientific Research Question:** How does time pressure interact with player
rating bands to affect the *shape* of the centipawn loss (CPL) distribution
in a large-scale naturalistic chess dataset?

Chess is not the object of study here — it's used as a source of large
numbers of timed, high-stakes decisions made by people across a wide range of
skill levels, which makes it a useful proxy for studying the speed-accuracy
trade-off and expertise/automaticity under cognitive load.

## How the pipeline works

1. **Phase 1 (Acquisition)** downloads monthly Lichess PGN archives, streams
   them with `zstandard`, filters for rated 5+0 (blitz) games, and saves a
   stratified sample of games per rating band.
2. **Phase 2 (Engine analysis)** runs Stockfish on each move using
   `python-chess`'s `SimpleEngine`, records centipawn loss (CPL) for the move
   actually played vs the engine's best move, saves progress after every
   game, and can resume from a checkpoint after a crash.
3. **Phase 3 (Data structuring)** cleans the raw move-level data into the
   final analytical dataset (`data/processed/analysed_moves.csv`), applying
   exclusions (opening moves, low-clock moves, etc.) and deriving
   `time_pressure_bin` and `error_category`.
4. **Phase 4 (Statistical analysis)** and **Phase 5 (Visualisation)** are done
   interactively in Jupyter notebooks under
   [`analysis/`](analysis/README.md) — see that directory's
   README for the full analysis plan, hypotheses, results, and how to run the
   notebooks.

Phases 1-3 are run via `run_analysis.py` / `src/`. Phases 4-5 are notebooks
and do not require Stockfish.

## Project structure

```text
chess-pipeline/
  config.py             # central configuration: paths, rating bands, time pressure bins, error categories, engine settings
  run_analysis.py        # entry point for Phases 1-3
  requirements.txt
  src/
    __init__.py
    utils.py             # shared helpers (logging, directory setup, checkpoint I/O)
    phase1_acquire.py     # Phase 1: download + filter + sample games
    phase2_analyse.py      # Phase 2: Stockfish analysis with checkpointing
    phase3_structure.py     # Phase 3: clean + derive analytical dataset
    dashboard.py            # optional Flask dashboard for monitoring Phase 2 progress
  data/
    raw/                  # Phase 1 output: sampled PGNs per rating band + game metadata
    processed/            # Phase 2/3 output: raw_moves.csv, analysed_moves.csv, dataset_summary.json
  logs/                   # log files written by each phase
  analysis/       # Phases 4-5: statistical analysis and figures (see its own README)
    notebooks/
    results/
    figures/
```

`data/`, `logs/`, and the virtual environment are not checked into the
repository (see `.gitignore`) — they are created/populated when you run the
pipeline.

## Setup

Requires Python 3.10+ and [Stockfish](https://stockfishchess.org/) installed
and on your `PATH` (or update `STOCKFISH_PATH` in `config.py`) for Phases 1-2.
Phases 4-5 (the notebooks) only need the Python packages below — Stockfish is
not required to reproduce the statistical analysis if you already have
`analysed_moves.csv`.

```bash
cd chess-pipeline
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

To run the Phase 4-5 notebooks, also register a Jupyter kernel for this
environment:

```bash
python -m ipykernel install --user --name chess-analysis --display-name "Python 3 (chess-analysis)"
```

## Configuration

All important settings live in [`config.py`](config.py), including:

- `TIME_CONTROL = "300+0"`
- `TARGET_GAMES_PER_BAND = 4000`
- `STOCKFISH_PATH = "/usr/local/bin/stockfish"`
- `DEPTH = 18`
- `NUM_WORKERS = 2`
- `THREADS_PER_WORKER = 2`
- `RATING_BANDS`, `TIME_PRESSURE_BINS`, `ERROR_CATEGORIES` — the bands/bins/
  categories used throughout the analysis (see
  [`analysis/README.md`](analysis/README.md) for details)

Edit `config.py` first if you want to change paths, months, sample sizes, or
thresholds.

## Running the pipeline

### Phase 1: Acquisition

```bash
python run_analysis.py --phase 1
```

Test-sized run:

```bash
python run_analysis.py --phase 1 --test-mode --target-per-band 5
```

Outputs:

- `data/raw/band_1/` to `data/raw/band_5/` (sampled PGN games)
- `data/raw/game_metadata.csv`
- `logs/phase1_acquire.log`

### Phase 2: Engine analysis

This can take a long time — run it inside `tmux` or similar for a real run:

```bash
python run_analysis.py --phase 2
```

Resume after interruption:

```bash
python run_analysis.py --phase 2 --resume
```

Small verification run:

```bash
python run_analysis.py --phase 2 --max-games 5 --depth 10
```

Outputs:

- `data/processed/phase2_workers/worker_*.csv`
- `data/processed/raw_moves.csv`
- `data/processed/checkpoint.json`
- `logs/phase2_analyse.log`, `logs/phase2_worker_*.log`

### Phase 3: Structuring

```bash
python run_analysis.py --phase 3
```

Outputs:

- `data/processed/analysed_moves.csv` — the dataset used by all of
  `analysis/`
- `data/processed/dataset_summary.json`

### Phases 1-3 together

```bash
python run_analysis.py --phase all
```

For a real run, don't use `--phase all` until you're confident about Phase 1
sample sizes — Phase 2 can take a long time and Phase 3 will run
automatically once it finishes.

### Phases 4-5: Statistical analysis and figures

Once `data/processed/analysed_moves.csv` exists, switch to the notebooks:

```bash
jupyter notebook analysis/notebooks/
```

Run notebooks `01` through `08` in order. See
[`analysis/README.md`](analysis/README.md) for the full
analysis plan, hypotheses, and a summary of results.

## Monitoring dashboard

While Phase 2 is running, you can start a read-only dashboard in a separate
terminal:

```bash
python -m src.dashboard
```

Then open `http://localhost:5050` (or your machine's address if running
remotely). It shows overall and per-band progress, games/hour, estimated time
remaining, recent log entries, and CPU/memory usage.

## Recovery after a crash

1. Check `logs/phase2_analyse.log` and the worker logs in `logs/`.
2. Check `data/processed/checkpoint.json` to confirm the last completed game
   and counts per band.
3. Restart with:

```bash
python run_analysis.py --phase 2 --resume
```

Phase 2 writes results after each game, so recovery should only lose the game
that was being analysed at the moment of failure.

## Method notes

- Engine communication uses `python-chess`'s `SimpleEngine`, not the separate
  `stockfish` PyPI package.
- Mate scores are converted into large centipawn-like values so they can be
  compared consistently with normal evaluations.
- Opening moves 1-10 are excluded in Phase 3, since they're more likely to
  reflect memorised theory than genuine on-the-clock decision making.
- Moves with less than 2 seconds remaining are excluded to reduce pre-move
  and flagging noise.
- `capped_cpl` (CPL capped at 300) is used for all distributional analysis in
  Phases 4-5.

## Results

This repository ships without any data, results, or figures — `data/`,
`analysis/results/`, and `analysis/figures/` are all empty
until you run the pipeline yourself. Running Phases 1-3 followed by the
Phase 4-5 notebooks on your own sample will populate these directories with
your own dataset, statistical results, and figures.

For reference, the original run of this pipeline (on a stratified sample of
20,000 Lichess blitz games) found that the *general* shift toward
higher-severity errors under time pressure is real, but driven specifically
by growth of the blunder tail (not a uniform shift of the whole
distribution) — and that this effect was, if anything, **larger for
higher-rated players**, not lower-rated players as originally hypothesised.
See [`analysis/README.md`](analysis/README.md) for the full
hypotheses, methodology, results tables, figures, and limitations.
