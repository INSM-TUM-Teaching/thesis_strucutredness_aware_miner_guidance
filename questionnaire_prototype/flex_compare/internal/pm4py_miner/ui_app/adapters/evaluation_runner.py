from __future__ import annotations

"""Adapter between the flex_compare UI and the generic pm4py discovery backend.

Supports the full Petri-net family (heuristics / alpha / alpha_plus /
inductive / ilp / genetic) and the two declarative outputs
(``declare`` / ``log_skeleton``). For declarative outputs no Petri net is
rendered — the constraint payload lands in ``declarative_model_path`` and
the metrics row carries ``constraint_density``/``constraint_variability``
for the declarative metric proxy.
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
    algorithm: str = "heuristics",
    dependency_threshold: float = 0.5,
    and_threshold: float = 0.65,
    loop_two_threshold: float = 0.5,
    noise_threshold: float = 0.0,
    disable_fallthroughs: Any = False,
    ilp_alpha: float = 1.0,
    population_size: int = 500,
    generations: int = 100,
    crossover_rate: float = 1.0,
    mutation_rate: float = 0.01,
    min_support_ratio: Optional[float] = None,
    min_confidence_ratio: Optional[float] = None,
    conformance_method: str = "alignments",
    preprocessing_note: str = "",
    export_pdf: bool = False,
) -> Dict[str, Any]:
    """Run the pm4py evaluation pipeline and return a normalised result dict."""
    from flex_compare.internal.pm4py_miner.evaluation import (
        DECLARATIVE_ALGORITHMS, generate_report,
    )

    # UI toggles arrive as Dash checklist values (``["on"]`` / ``[]``); accept
    # either that or a plain bool so the adapter can be called from tests too.
    disable_fallthroughs = bool(
        disable_fallthroughs
        if isinstance(disable_fallthroughs, bool)
        else (disable_fallthroughs and "on" in disable_fallthroughs)
    )

    start = time.perf_counter()
    log_path = Path(log_path)
    output_root = Path(output_root)
    try:
        raw = generate_report(
            log_path=log_path,
            output_root=output_root,
            run_id=run_id,
            bearbeiter=bearbeiter,
            algorithm=algorithm,
            dependency_threshold=dependency_threshold,
            and_threshold=and_threshold,
            loop_two_threshold=loop_two_threshold,
            noise_threshold=noise_threshold,
            disable_fallthroughs=disable_fallthroughs,
            ilp_alpha=ilp_alpha,
            population_size=population_size,
            generations=generations,
            crossover_rate=crossover_rate,
            mutation_rate=mutation_rate,
            min_support_ratio=min_support_ratio,
            min_confidence_ratio=min_confidence_ratio,
            conformance_method=conformance_method,
            preprocessing_note=preprocessing_note,
            export_pdf=export_pdf,
        )
        wall_sec = time.perf_counter() - start

        markdown_path = Path(raw["markdown_path"])
        markdown_content = markdown_path.read_text(encoding="utf-8")

        row = raw["row"]
        if row.get("error"):
            return {
                "status": "error",
                "error_message": row["error"],
                "runtime_wall_sec": round(wall_sec, 2),
            }

        is_declarative = algorithm in DECLARATIVE_ALGORITHMS
        result: Dict[str, Any] = {
            "status": "success",
            "error_message": None,
            "runtime_wall_sec": round(wall_sec, 2),
            "log_name": log_path.stem,
            "log_path": str(log_path),
            "output_dir": str(raw["output_dir"]),
            "markdown_path": str(raw["markdown_path"]),
            "data_path": str(raw["data_path"]) if raw.get("data_path") else None,
            "markdown_content": markdown_content,
            "pdf_path": str(raw["pdf_path"]) if raw.get("pdf_path") else None,
            "metrics": row,
            "log_stats": raw["log_stats"],
            "parameters": {
                "algorithm": algorithm,
                "dependency_threshold": dependency_threshold,
                "and_threshold": and_threshold,
                "loop_two_threshold": loop_two_threshold,
                "noise_threshold": noise_threshold,
                "disable_fallthroughs": disable_fallthroughs,
                "ilp_alpha": ilp_alpha,
                "population_size": population_size,
                "generations": generations,
                "crossover_rate": crossover_rate,
                "mutation_rate": mutation_rate,
                "min_support_ratio": min_support_ratio,
                "min_confidence_ratio": min_confidence_ratio,
                "conformance_method": conformance_method,
                "export_pdf": export_pdf,
                "preprocessing_note": preprocessing_note,
            },
        }

        if is_declarative:
            decl_json_path = (
                Path(raw["declarative_model_path"])
                if raw.get("declarative_model_path") else None
            )
            result["declare_model_json_path"] = (
                str(decl_json_path) if decl_json_path else None
            )
            # Render the constraint set with declare-js so the UI iframe shows
            # the model. ``log_skeleton`` constraints are not declare-js
            # templates and produce zero renderable lines — swallow that as a
            # soft skip rather than failing the run.
            result["declare_visualization_path"] = None
            result["declare_visualization_png_path"] = None
            result["declare_visualization_engine"] = None
            if decl_json_path and algorithm == "declare":
                try:
                    from flex_compare.internal.declarative_miner.visualize_declare_js import (
                        render_declare_js_html_from_pm4py_json,
                    )
                    html_out = Path(raw["output_dir"]) / "declare_visualization.html"
                    render_declare_js_html_from_pm4py_json(
                        json_path=decl_json_path,
                        html_output_path=html_out,
                        title=f"pm4-declare — {log_path.stem}",
                    )
                    result["declare_visualization_path"] = str(html_out)
                    result["declare_visualization_engine"] = "declare_js"
                except Exception as exc:  # noqa: BLE001
                    result["declare_visualization_error"] = str(exc)
        else:
            result["petri_net_path"] = (
                str(raw["petri_net_path"]) if raw.get("petri_net_path") else None
            )

        return result
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "error_message": str(exc),
            "error_traceback": traceback.format_exc(),
            "runtime_wall_sec": round(time.perf_counter() - start, 2),
        }
