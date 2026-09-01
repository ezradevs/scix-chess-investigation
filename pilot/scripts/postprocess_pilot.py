#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from run_pilot_analysis import build_findings_report, make_plots, run_validation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-csv', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--counters-json', required=True)
    parser.add_argument('--output-validation-json', required=True)
    parser.add_argument('--plots-dir', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()

    df = pd.read_csv(args.input_csv)
    validation = run_validation(df)
    plots = make_plots(df, Path(args.plots_dir))

    Path(args.output_validation_json).write_text(
        json.dumps({'validation': validation, 'plots': plots}, indent=2), encoding='utf-8'
    )

    counters = json.loads(Path(args.counters_json).read_text(encoding='utf-8'))
    report = build_findings_report(Path(args.manifest), counters, validation)
    Path(args.report).write_text(report + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
