from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from flex_compare.internal.shared.artifact_utils import build_artifacts_zip as _build_artifacts_zip
from flex_compare.internal.shared.artifact_utils import collect_artifacts as _collect_artifacts


def run_evaluation(
    *,
    log_path: Path,
    output_root: Path,
    run_id: Optional[str],
    bearbeiter: Optional[str],
    preprocessing_note: str = "",
    export_pdf: bool = False,
    support: float,
    confidence: float,
    coverage: float,
    trace_support: float,
    trace_confidence: float,
    trace_coverage: float,
    prune: str,
    minerful_dir: Optional[Path] = None,
    prune_ranking_by: Optional[str] = None,
    prune_hierarchy_by: Optional[str] = None,
    keep_constraints: bool = False,
    kb_ll_threads: Optional[int] = None,
    q_ll_threads: Optional[int] = None,
    foresee_distances: bool = False,
    show_mem_peak: bool = False,
    exclude_results_in: Optional[str] = None,
    stats_xml_out: Optional[str] = None,
) -> Dict[str, Any]:
    from flex_compare.internal.declarative_miner.evaluation import DiscoveryParams
    from flex_compare.internal.declarative_miner.pilot_sheet import generate_pilot_sheet
    from flex_compare.internal.shared.paths import PROJECT_ROOT

    start = time.perf_counter()
    log_path = Path(log_path)
    output_root = Path(output_root)
    if minerful_dir is None:
        minerful_dir = PROJECT_ROOT / "tools" / "MINERful"
    else:
        minerful_dir = Path(minerful_dir)

    try:
        params = DiscoveryParams(
            support=support,
            confidence=confidence,
            coverage=coverage,
            trace_support=trace_support,
            trace_confidence=trace_confidence,
            trace_coverage=trace_coverage,
            prune=prune,
            prune_ranking_by=(prune_ranking_by or None),
            prune_hierarchy_by=(prune_hierarchy_by or None),
            keep_constraints=keep_constraints,
            kb_ll_threads=kb_ll_threads,
            q_ll_threads=q_ll_threads,
            foresee_distances=foresee_distances,
            show_mem_peak=show_mem_peak,
            exclude_results_in=(exclude_results_in or None),
            stats_xml_out=(stats_xml_out or None),
        )

        base_kwargs = {
            "log_path": log_path,
            "output_root": output_root,
            "minerful_dir": minerful_dir,
            "run_id": run_id,
            "bearbeiter": bearbeiter,
            "params": params,
            "export_pdf": export_pdf,
            "preprocessing_note": preprocessing_note,
        }
        raw = generate_pilot_sheet(**base_kwargs)

        output_dir = Path(raw["output_dir"])
        markdown_path = Path(raw["markdown_path"])
        data_path = Path(raw["data_path"])

        markdown_content = markdown_path.read_text(encoding="utf-8")
        metrics = json.loads(data_path.read_text(encoding="utf-8"))
        viz_html_path = metrics.get("declare_visualization_path")
        viz_png_path = metrics.get("declare_visualization_png_path")
        viz_engine = metrics.get("declare_visualization_engine")
        viz_layout_applied = metrics.get("declare_visualization_layout_applied")
        viz_snapshot_stage = metrics.get("declare_visualization_snapshot_stage")
        visualization_error: str | None = metrics.get("declare_visualization_error")

        html_missing = (
            not isinstance(viz_html_path, str)
            or not viz_html_path
            or not Path(viz_html_path).exists()
        )
        png_missing = (
            not isinstance(viz_png_path, str)
            or not viz_png_path
            or not Path(viz_png_path).exists()
        )
        if html_missing or png_missing:
            raise RuntimeError(
                "declare-js outputs missing: expected both HTML and PNG visualization artifacts."
            )
        if viz_engine != "declare_js":
            raise RuntimeError(
                f"Unexpected visualization engine '{viz_engine}'. Expected 'declare_js'."
            )
        if viz_layout_applied != "auto_layout_via_gear":
            raise RuntimeError(
                "declare-js layout metadata mismatch: expected "
                "'declare_visualization_layout_applied=auto_layout_via_gear'."
            )
        if viz_snapshot_stage != "post_auto_layout":
            raise RuntimeError(
                "declare-js snapshot metadata mismatch: expected "
                "'declare_visualization_snapshot_stage=post_auto_layout'."
            )

        # Persist normalization/warnings to result artifacts.
        data_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

        if visualization_error:
            warning_lines = [
                "",
                "---",
                "",
                "## Visualization Notes",
                f"- Error: {visualization_error}",
            ]
            markdown_content = markdown_content + "\n" + "\n".join(warning_lines) + "\n"
            markdown_path.write_text(markdown_content, encoding="utf-8")

        artifacts = _collect_artifacts(output_dir)
        artifacts_zip = _build_artifacts_zip(output_dir, artifacts)
        wall_sec = time.perf_counter() - start

        return {
            "status": "success",
            "error_message": None,
            "runtime_wall_sec": round(wall_sec, 2),
            "log_name": log_path.stem,
            "log_path": str(log_path),
            "output_dir": str(output_dir),
            "markdown_path": str(markdown_path),
            "markdown_content": markdown_content,
            "data_path": str(data_path),
            "pdf_path": str(raw["pdf_path"]) if raw.get("pdf_path") else None,
            "metrics": metrics,
            "declare_visualization_path": metrics.get("declare_visualization_path"),
            "declare_visualization_png_path": metrics.get("declare_visualization_png_path"),
            "declare_visualization_engine": metrics.get("declare_visualization_engine"),
            "declare_visualization_kind": metrics.get("declare_visualization_kind"),
            "declare_visualization_layout_applied": metrics.get("declare_visualization_layout_applied"),
            "declare_visualization_snapshot_stage": metrics.get("declare_visualization_snapshot_stage"),
            "declare_visualization_error": metrics.get("declare_visualization_error"),
            "parameters": {
                "support": support,
                "confidence": confidence,
                "coverage": coverage,
                "trace_support": trace_support,
                "trace_confidence": trace_confidence,
                "trace_coverage": trace_coverage,
                "prune": prune,
                "prune_ranking_by": prune_ranking_by,
                "prune_hierarchy_by": prune_hierarchy_by,
                "keep_constraints": keep_constraints,
                "kb_ll_threads": kb_ll_threads,
                "q_ll_threads": q_ll_threads,
                "foresee_distances": foresee_distances,
                "show_mem_peak": show_mem_peak,
                "exclude_results_in": exclude_results_in,
                "stats_xml_out": stats_xml_out,
                "export_pdf": export_pdf,
                "preprocessing_note": preprocessing_note,
            },
            "artifacts": artifacts,
            "artifacts_zip_bytes": artifacts_zip,
            "artifacts_zip_name": f"{output_dir.name}.zip",
        }

    except Exception as exc:
        return {
            "status": "error",
            "error_message": str(exc),
            "error_traceback": traceback.format_exc(),
            "runtime_wall_sec": round(time.perf_counter() - start, 2),
        }
