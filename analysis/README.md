# Phase 4 & 5: Statistical Analysis and Visualisation

This directory contains the statistical analysis and figures for the project:

**"Investigating how time pressure modulates decision-making error severity
distributions across expertise levels: a large-scale chess analysis."**

Chess is used here as a **naturalistic cognitive model system** — the goal is
not to study chess as a game, but to use a large dataset of timed,
high-stakes decisions to investigate how time pressure affects
decision-making quality across different levels of expertise. The theoretical
grounding is dual-process cognitive theory, speed-accuracy trade-off theory,
and expertise/automaticity research.

## Directory layout

```text
analysis/
  README.md           # this file
  notebooks/          # Jupyter notebooks for Phase 4 (stats) and Phase 5 (figures), run in order 01-08
  results/            # exported CSVs of statistical results
  figures/            # exported plots (histograms, box plots, stacked bars, line plots)
```

## Running the notebooks

From the repository root, with the virtual environment active (see the
top-level [README](../README.md) for setup):

```bash
python -m ipykernel install --user --name chess-analysis --display-name "Python 3 (chess-analysis)"
jupyter notebook analysis/notebooks/
```

Run notebooks `01` through `08` in order — each one depends on the CSVs
written by earlier notebooks. All notebooks load the dataset with:

```python
import pandas as pd

df = pd.read_csv("../../data/processed/analysed_moves.csv")
```

so they expect to be run from within `analysis/notebooks/`.
