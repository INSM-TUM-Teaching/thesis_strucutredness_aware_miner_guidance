from __future__ import annotations

"""
Thin adapter between the Streamlit UI and the existing result-report backend.

Calls generate_pilot_sheet() once and normalises its return value into a
flat RunResult dict that is easy for the UI to render. No PM4Py logic lives
here — everything is delegated to the existing imperative_miner package.
"""

import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional


def run_evaluation(
    *,
    log_path: Path,
    output_root: Path,
    run_id: Optional[str],
    bearbeiter: Optional[str],
    noise_threshold: float,
    conformance_method: str,
    preprocessing_note: str,
    export_pdf: bool,
) -> Dict[str, Any]:
    """
    Run the full evaluation pipeline and return a normalised result dict.

    The function calls generate_pilot_sheet() exactly once. All metrics,
    file paths, and log statistics come from that single call — there is no
    risk of parameter drift between what ends up in the result report and what
    the UI displays.

    Returns a dict with at minimum:
        status          "success" | "error"
        error_message   str | None
        runtime_wall_sec float
    On success, all additional fields documented in RunResult are populated.
    """
    # Import here so that import errors surface as UI error messages,
    # not as module-level crashes on startup.
    from flex_compare.internal.imperative_miner.pilot_sheet import generate_pilot_sheet

    start = time.perf_counter()
    log_path = Path(log_path)
    output_root = Path(output_root)

    try:
        raw = generate_pilot_sheet(
            log_path=log_path,
            output_root=output_root,
            run_id=run_id,
            bearbeiter=bearbeiter,
            noise_threshold=noise_threshold,
            conformance_method=conformance_method,
            preprocessing_note=preprocessing_note,
            export_pdf=export_pdf,
        )
        wall_sec = time.perf_counter() - start

        markdown_path = Path(raw["markdown_path"])
        markdown_content = markdown_path.read_text(encoding="utf-8")

        return {
            "status": "success",
            "error_message": None,
            "runtime_wall_sec": round(wall_sec, 2),
            "log_name": log_path.stem,
            "log_path": str(log_path),
            "output_dir": str(raw["output_dir"]),
            "markdown_path": str(raw["markdown_path"]),
            "data_path": str(raw["data_path"]) if raw.get("data_path") else None,
            "excel_path": str(raw["excel_path"]) if raw.get("excel_path") else None,
            "markdown_content": markdown_content,
            "pdf_path": str(raw["pdf_path"]) if raw.get("pdf_path") else None,
            "process_tree_path": str(raw["process_tree_path"]) if raw.get("process_tree_path") else None,
            "petri_net_path": str(raw["petri_net_path"]) if raw.get("petri_net_path") else None,
            "petri_net_pnml_path": str(raw["petri_net_pnml_path"]) if raw.get("petri_net_pnml_path") else None,
            "bpmn_path": str(raw["bpmn_path"]) if raw.get("bpmn_path") else None,
            # result_align is computed with the user-selected conformance_method —
            # the same method used to produce the report artefacts.
            "metrics": raw["result_align"],
            "metrics_token": raw["result_token"],
            "log_stats": raw["log_stats"],
            "parameters": {
                "noise_threshold": noise_threshold,
                "conformance_method": conformance_method,
                "export_pdf": export_pdf,
                "preprocessing_note": preprocessing_note,
            },
        }

    except Exception as exc:
        return {
            "status": "error",
            "error_message": str(exc),
            "error_traceback": traceback.format_exc(),
            "runtime_wall_sec": round(time.perf_counter() - start, 2),
        }
