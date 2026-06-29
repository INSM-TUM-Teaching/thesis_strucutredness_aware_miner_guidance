from __future__ import annotations

import argparse
import datetime as dt
import getpass
from pathlib import Path
from typing import Dict

from flex_compare.internal.experiment_reports import build_report_output_dir
from flex_compare.internal.fusion_miner.evaluation import DEFAULT_FUSION_PARAMS
from flex_compare.internal.fusion_miner.evaluation import DEFAULT_HEURISTICS_PARAMS
from flex_compare.internal.fusion_miner.evaluation import FusionParams
from flex_compare.internal.fusion_miner.evaluation import HeuristicsParams
from flex_compare.internal.fusion_miner.evaluation import run_safe_evaluation


def _build_markdown(
    *,
    log_path: Path,
    output_dir: Path,
    run: Dict[str, Any],
    preprocessing_note: str | None,
    bearbeiter: str,
    date_str: str,
) -> str:
    _ = output_dir, preprocessing_note  # intentionally unused in dummy report mode
    return f"""# FusionMINERful Report (Dummy)

The previous report export is intentionally disabled and replaced with placeholder text.

- Run ID: {run.get("run_id")}
- Date: {date_str}
- Author: {bearbeiter}
- Log: {log_path.name}
- Status: {run.get("exit_status")}

Note: the report export will be fully re-implemented later.
"""


def generate_pilot_sheet(
    *,
    log_path: Path,
    output_root: Path,
    run_id: str | None,
    bearbeiter: str | None,
    heuristics: HeuristicsParams = DEFAULT_HEURISTICS_PARAMS,
    fusion: FusionParams = DEFAULT_FUSION_PARAMS,
    java_headless: bool = False,
    export_pdf: bool = False,
    preprocessing_note: str | None = None,
    precision_valid_samples: int | None = None,
    precision_seed: int | None = None,
    precision_k: int | None = None,
) -> Dict[str, Path | None]:
    if not log_path.exists():
        raise FileNotFoundError(f"Log file not found: {log_path}")

    run_id_val = run_id or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    bearbeiter_val = bearbeiter or getpass.getuser()
    date_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out_dir = build_report_output_dir(output_root, log_path.stem, "fusionminerful")
    out_dir.mkdir(parents=True, exist_ok=True)

    from flex_compare.internal.fusion_miner.evaluation import (
        DEFAULT_PRECISION_K,
        DEFAULT_PRECISION_SEED,
        DEFAULT_PRECISION_VALID_SAMPLES,
    )

    run = run_safe_evaluation(
        log_path=log_path,
        output_dir=out_dir,
        run_id=run_id_val,
        heuristics=heuristics,
        fusion=fusion,
        java_headless=java_headless,
        precision_valid_samples=(
            precision_valid_samples
            if precision_valid_samples is not None
            else DEFAULT_PRECISION_VALID_SAMPLES
        ),
        precision_seed=(
            precision_seed if precision_seed is not None else DEFAULT_PRECISION_SEED
        ),
        precision_k=precision_k if precision_k is not None else DEFAULT_PRECISION_K,
    )
    markdown = _build_markdown(
        log_path=log_path,
        output_dir=out_dir,
        run=run,
        preprocessing_note=preprocessing_note,
        bearbeiter=bearbeiter_val,
        date_str=date_str,
    )
    markdown_path = out_dir / "ergebnisbericht.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    pdf_path = None
    return {
        "output_dir": out_dir,
        "markdown_path": markdown_path,
        "pdf_path": pdf_path,
        "data_path": out_dir / "result_data.json",
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run headless FusionMINERful and write thesis-grade artifacts.")
    parser.add_argument("--log-path", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[2] / "Experimente")
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--bearbeiter", type=str, default=None)
    parser.add_argument("--java-headless", dest="java_headless", action="store_true", default=False)
    parser.add_argument("--java-desktop-render", dest="java_headless", action="store_false")
    parser.add_argument("--export-pdf", action="store_true")
    parser.add_argument("--preprocessing-note", type=str, default="")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    generate_pilot_sheet(
        log_path=args.log_path,
        output_root=args.output_root,
        run_id=args.run_id,
        bearbeiter=args.bearbeiter,
        java_headless=args.java_headless,
        export_pdf=args.export_pdf,
        preprocessing_note=args.preprocessing_note,
    )


if __name__ == "__main__":
    main()
