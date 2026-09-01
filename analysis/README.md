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

## Scientific Research Question

How does time pressure interact with player rating bands to affect the
*shape* of the centipawn loss (CPL) distribution in a large-scale naturalistic
chess dataset?

**Distributional framing** (the *shape* of the CPL distribution, not just its
mean) is what differentiates this project from prior chess/time-pressure
work. Descriptive stats, statistical tests, and the visualisations all
foreground shape (skewness, kurtosis, tail behaviour, error category
composition), not just central tendency.

## Hypotheses

**H1 (alternate hypothesis):** As time pressure increases, the distribution
of centipawn loss will shift toward higher-severity errors across all player
groups, with this shift being disproportionately pronounced in lower-rated
players compared to higher-rated players.

**H0 (null hypothesis):** The size of the shift in the CPL distribution caused
by time pressure does not depend on player rating — i.e. it is not
disproportionately larger for lower-rated players than for higher-rated
players.

### Results summary

- The "general shift toward higher-severity errors under pressure" part of H1
  is **supported**, but specifically via growth of the right-hand (blunder)
  tail of the distribution — the median/bulk of the distribution often moves
  in the *opposite* direction (slightly lower CPL) under pressure. This
  tail-vs-bulk distinction is important wherever this claim is discussed, to
  avoid an apparent contradiction.
- The "disproportionately pronounced in lower-rated players" part of H1 is
  **not supported** — we fail to reject H0. Cramér's V, Pearson's |r|, and the
  Bin1→2 KS D-statistic/Cohen's d all *increase* with rating band, i.e. the
  trend runs opposite to what H1 predicted (experts show the larger relative
  shift, not novices).
- The hypothesis wording is reported as originally proposed (not revised
  post-hoc), alongside the above results. The reversed-direction trend on the
  second part is discussed as a key finding in its own right — see
  Limitations and Discussion below for the cognitive-science framing (ceiling
  effect for novices vs. depletion of deliberate processing for experts).

## The dataset

**Input file:** `data/processed/analysed_moves.csv` (945,957 rows, ~43 MB),
produced by Phases 1-3 of the pipeline (see the top-level
[README](../README.md)). This file is not checked into the repository — run
Phases 1-3 (or supply your own equivalent dataset with the same columns) to
generate it before running these notebooks.

This is move-level data — **the analytical unit is the individual move**, not
the game. Each move played by each player appears as its own row.

### Columns

| Column | Type | Description |
|---|---|---|
| `game_id` | string | Lichess game ID. Multiple rows share a `game_id`. |
| `move_number` | int | Full-move number (1-indexed, as in PGN). Opening moves 1-10 already excluded. |
| `player_rating` | int | Rating of the player who made the move at the time of the game. |
| `rating_band` | int (1-5) | See rating band table below. |
| `time_remaining_pct` | float | % of the initial 300s clock remaining for that player at the time of the move. |
| `time_pressure_bin` | int (1-4) | See time pressure bin table below. |
| `game_phase` | string | e.g. `"Middlegame"`. Derived from move number (opening <=10, middlegame <=30, endgame >30; see `config.py`). |
| `raw_cpl` | int | Centipawn loss for this move, uncapped (best_eval - played_eval, mate scores converted to large CP equivalents). |
| `capped_cpl` | int | `raw_cpl` capped at 300. Used for all distributional analysis. |
| `error_category` | int (1-4) | Categorical bucket derived from `capped_cpl`. See error category table below. |

### Rating bands (from `config.py: RATING_BANDS`)

| Code | Label | Rating range |
|---|---|---|
| 1 | Novice | <1000 |
| 2 | Intermediate | 1000-1499 |
| 3 | Club Player | 1500-1999 |
| 4 | Advanced | 2000-2299 |
| 5 | Expert/Master | 2300+ |

### Time pressure bins (from `config.py: TIME_PRESSURE_BINS`)

Defined on `time_remaining_pct` (% of initial 300s clock remaining):

| Code | Label | Range |
|---|---|---|
| 1 | Minimal Pressure | >75% |
| 2 | Low Pressure | 50-75% |
| 3 | Moderate Pressure | 25-50% |
| 4 | High Pressure | <25% |

### Error categories (from `config.py: ERROR_CATEGORIES`, based on `capped_cpl`)

| Code | Label | CPL range |
|---|---|---|
| 1 | Inaccuracy | 0-10 |
| 2 | Minor Error | 11-50 |
| 3 | Major Error | 51-150 |
| 4 | Blunder | 151-300 |

These thresholds are a researcher-defined operationalisation and currently
lack explicit theoretical derivation from the literature — see Limitations.

### Exclusions already applied in Phase 3

- First 10 moves of each game (opening theory).
- Games ending before move 10.
- Moves with <2 seconds remaining on the clock.
- Games where the two players were not in the same rating band.
- Rows with missing values.

### Cell sizes (rating_band x time_pressure_bin)

| rating_band \ bin | 1 (Minimal) | 2 (Low) | 3 (Moderate) | 4 (High) |
|---|---|---|---|---|
| 1 (Novice) | 36,342 | 58,723 | 36,330 | 16,840 |
| 2 (Intermediate) | 52,951 | 62,014 | 37,142 | 16,530 |
| 3 (Club Player) | 66,963 | 65,568 | 39,942 | 20,131 |
| 4 (Advanced) | 66,217 | 65,911 | 46,692 | 27,055 |
| 5 (Expert/Master) | 71,892 | 63,610 | 55,079 | 40,025 |

All 20 cells are large (16,530-71,892 rows), so statistical power is high for
every planned test. With sample sizes this large, KS tests and chi-squared
tests will return very small p-values even for practically trivial
differences — **effect sizes (Cohen's d, KS D-statistic magnitude, Cramer's
V, Pearson's r) matter more than p-values here** and are emphasised
throughout.

## Analysis plan and notebooks

Run the notebooks in order. Each one reads `data/processed/analysed_moves.csv`
and/or the outputs of earlier notebooks, and writes its results to `results/`
and `figures/`.

| Notebook | Stage | What it does | Output |
|---|---|---|---|
| `01_descriptive_statistics.ipynb` | 4.1 | Mean, median, std, IQR, skewness, kurtosis, and error category proportions for each of the 20 (rating band x time pressure bin) cells. | `results/descriptive_stats.csv` |
| `02_exploratory_plots.ipynb` | - | Rough overlaid histograms of `capped_cpl` per rating band, across all 4 time pressure bins (full range, zoomed, log-scale). | `figures/exploratory_*.png` |
| `03_ks_tests.ipynb` | 4.2 | Kolmogorov-Smirnov tests between adjacent time pressure bins, within each rating band (15 comparisons, Bonferroni alpha = 0.0033). Primary test for distributional shape. | `results/ks_test_results.csv` |
| `04_chi_squared_tests.ipynb` | 4.3 | Chi-squared test of independence on error-category x time-pressure-bin contingency tables, one per rating band (5 comparisons, Bonferroni alpha = 0.01), plus Cramer's V. | `results/chi_squared_results.csv` |
| `05_ttests_cohens_d.ipynb` | 4.4/4.6 | Welch's t-tests and Cohen's d between adjacent time pressure bins, within each rating band (15 comparisons). | `results/ttest_cohens_d_results.csv` |
| `06_pearson_correlation.ipynb` | 4.5 | Pearson's r between `time_remaining_pct` and `capped_cpl`, per rating band (5 correlations, Bonferroni alpha = 0.01). | `results/pearson_correlation_results.csv` |
| `07_compilation_and_between_band.ipynb` | 4.7 | Compiles the above into within-band and between-band comparison tables — the key tables for evaluating the "disproportionate effect" half of the hypothesis. | `results/within_band_summary.csv`, `results/between_band_comparison.csv`, `results/band_level_summary.csv` |
| `08_report_figures.ipynb` | 5 | Report-quality figures: error category composition (stacked bars), CPL box plots, between-band effect size comparison, and Pearson's r by band. | `figures/*.png` |

### Stage 4.1 - Descriptive statistics

For `capped_cpl` within each (rating band x time pressure bin) cell:
mean, median, standard deviation, IQR, skewness, kurtosis, and the proportion
of moves in each error category.

### Stage 4.2 - Kolmogorov-Smirnov tests (primary test)

Pairwise between **adjacent** time pressure bins within each rating band:
Bin 1 vs 2, Bin 2 vs 3, Bin 3 vs 4 -> 3 comparisons x 5 rating bands = **15
comparisons total**. Bonferroni-corrected alpha = 0.0033 (0.05 / 15). This is
the primary test — it directly addresses the SRQ's distributional framing by
detecting shifts in *shape*, not just mean/location.

### Stage 4.3 - Chi-squared tests

One test per rating band, comparing `error_category` proportions across the
four time pressure bins (4x4 contingency table per band) -> **5 comparisons
total**. Bonferroni-corrected alpha = 0.01 (0.05 / 5). Complements the KS
tests by testing whether the *categorical composition* of errors changes
significantly under pressure, with Cramer's V as the effect size.

### Stage 4.4 - Pairwise t-tests

Welch's t-tests between adjacent time pressure bins within each rating band,
on mean `capped_cpl` -> 15 comparisons, same structure as the KS tests.
Welch's test (unequal variances) is used because the standard deviation of
`capped_cpl` changes substantially across bins within a band.

### Stage 4.5 - Pearson's r

Within each rating band (5 correlations total), correlate
`time_remaining_pct` with `capped_cpl` continuously (not binned). This gives
a monotonic relationship measure independent of bin boundary choices. A
negative r is expected (less time -> higher CPL), and H1 predicts |r| should
be larger (more negative) for lower-rated bands.

### Stage 4.6 - Cohen's d

Between adjacent time pressure bins within each rating band, on mean
`capped_cpl` -> 15 values, paired with the t-tests above as the effect-size
counterpart.

### Stage 4.7 - Between-band comparison

This is the step that directly answers the "disproportionate effect" half of
the hypothesis. The within-band tests above (4.2-4.6) each describe one
rating band in isolation; here they're compiled into a second-level
comparison:

- For each adjacent-bin transition (Bin 1->2, 2->3, 3->4), the **KS
  D-statistic** and **Cohen's d** are lined up across all 5 rating bands to
  look for a trend across bands.
- The 5 **Pearson's r** values (one per band) are directly comparable —
  compared by magnitude to see whether the time-pressure/CPL correlation is
  stronger (more negative) for lower bands (as H1 predicts) or higher bands
  (as the data actually show).

### Notes on the plan

- **ANOVA was deliberately not used** in this design.
- Within-band comparisons (4.2-4.6) test the core "time pressure shifts the
  distribution" claim (the first half of H1); the between-band comparison
  (4.7) tests the "disproportionate effect on lower-rated players" claim (the
  second half of H1).

## Known methodological considerations / limitations

These should actively shape how results are interpreted, not just be
mentioned in passing in a discussion section.

1. **CPL is position-dependent.** Identical CPL values carry different
   significance depending on game state (e.g. a 50cp loss in an equal, sharp
   middlegame vs a 50cp loss in a position that was already winning by +800).
2. **Error category thresholds (10/50/150/300) lack explicit theoretical
   derivation** from the literature — they are a researcher-defined
   operationalisation.
3. **Time pressure and game state are correlated, not independent.** The
   <2-second exclusion partially addresses extreme flagging noise but doesn't
   resolve this confound.
4. **Band 5 (2300+) has lower player diversity** on Lichess 5+0 — fewer
   distinct very-high-rated blitz players exist.
5. **Band 5 pseudoreplication.** The small pool of master-level players means
   the same individuals likely appear multiple times in the Band 5 sample, so
   individual player effects are likely less "diluted" in Band 5 than in the
   other bands.
6. **Player age is uncontrolled.** A 2300-rated 20-year-old and a 2300-rated
   60-year-old may respond to time pressure very differently
   (neuroplasticity, cognitive composure). Rating band conflates expertise
   with age-related cognitive factors.
7. **Stockfish's superhuman precision may generate "phantom errors"** in
   positions a human would treat as equivalent (e.g. distinguishing a +0.3
   move from the engine's preferred +0.5 move, both of which are "fine" for a
   human).
8. A Lichess blog post by jk_182 (2026), *"How the Evaluation and Clock impact
   Results of Blitz Games"*
   (https://lichess.org/@/jk_182/blog/how-the-evaluation-and-clock-impact-results-of-blitz-games/I2kRp2sk)
   gives naturalistic corroboration of the time-pressure/game-state confound
   within Lichess blitz data specifically. Not peer-reviewed — supporting
   texture only, not primary evidence.

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
