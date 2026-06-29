from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from flex_compare.internal.fusion_miner.evaluation import FusionParams
from flex_compare.internal.fusion_miner.evaluation import HeuristicsParams
from flex_compare.internal.shared.artifact_utils import build_artifacts_zip as _build_artifacts_zip
from flex_compare.internal.shared.artifact_utils import collect_artifacts as _collect_artifacts


# UI-side ParamSpec keys (compact, used in the Configure panel) → dataclass
# field names on HeuristicsParams / FusionParams. The runner bundles config
# entries under their UI keys; the adapter must translate before instantiating
# the params dataclasses.
_HEURISTICS_UI_TO_FIELD: Dict[str, str] = {
    "noise": "relative_to_best_threshold",
    "depend": "dependency_threshold",
    "l1l": "l1l_threshold",
    "l2l": "l2l_threshold",
    "long_dist": "long_distance_threshold",
    "all_connected": "use_all_connected_heuristics",
    "long_dist_dep": "use_long_distance_dependency",
    "unique_se": "use_unique_start_end_tasks",
}
_FUSION_UI_TO_FIELD: Dict[str, str] = {
    "alpha": "declare_alpha",
    "decl_support": "declare_support",
    "entropy": "activity_entropy",
    "resilience": "resilience",
    "im_fitness": "im_fitness",
    "size": "size_multiplicator",
    "cut": "cut",
    "prune": "prune",
    "negative": "negative",
    "check_model": "check_model",
}
_HEURISTICS_BOOL_FIELDS = {
    "use_all_connected_heuristics",
    "use_long_distance_dependency",
    "use_unique_start_end_tasks",
}
_FUSION_BOOL_FIELDS = {"cut", "prune", "negative", "check_model"}


def _coerce_toggle(value: Any) -> bool:
    """Dash checklist toggles arrive as ``['on']`` / ``[]`` — coerce to bool."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        return "on" in value
    return bool(value)


def _translate_bundle(raw: Dict[str, Any],
                      ui_to_field: Dict[str, str],
                      bool_fields: set) -> Dict[str, Any]:
    """Map UI ParamSpec keys to dataclass field names; coerce toggle bools."""
    out: Dict[str, Any] = {}
    for key, value in raw.items():
        target = ui_to_field.get(key, key)
        if target in bool_fields:
            value = _coerce_toggle(value)
        out[target] = value
    return out


def run_evaluation(
    *,
    log_path: Path,
    output_root: Path,
    run_id: Optional[str],
    bearbeiter: Optional[str],
    preprocessing_note: str,
    export_pdf: bool,
    heuristics: Optional[HeuristicsParams] = None,
    fusion: Optional[FusionParams] = None,
    java_headless: bool = False,
    precision_valid_samples: Optional[int] = None,
    precision_seed: Optional[int] = None,
    precision_k: Optional[int] = None,
) -> Dict[str, Any]:
    from flex_compare.internal.fusion_miner.evaluation import DEFAULT_FUSION_PARAMS
    from flex_compare.internal.fusion_miner.evaluation import DEFAULT_HEURISTICS_PARAMS
    from flex_compare.internal.fusion_miner.evaluation import DEFAULT_PRECISION_K
    from flex_compare.internal.fusion_miner.evaluation import DEFAULT_PRECISION_SEED
    from flex_compare.internal.fusion_miner.evaluation import DEFAULT_PRECISION_VALID_SAMPLES
    from flex_compare.internal.fusion_miner.pilot_sheet import generate_pilot_sheet

    start = time.perf_counter()
    log_path = Path(log_path)
    output_root = Path(output_root)
    if isinstance(heuristics, dict):
        heuristics = HeuristicsParams(**_translate_bundle(
            heuristics, _HEURISTICS_UI_TO_FIELD, _HEURISTICS_BOOL_FIELDS))
    if isinstance(fusion, dict):
        fusion = FusionParams(**_translate_bundle(
            fusion, _FUSION_UI_TO_FIELD, _FUSION_BOOL_FIELDS))
    eff_heuristics = heuristics or DEFAULT_HEURISTICS_PARAMS
    eff_fusion = fusion or DEFAULT_FUSION_PARAMS
    eff_precision_samples = (
        precision_valid_samples
        if precision_valid_samples is not None
        else DEFAULT_PRECISION_VALID_SAMPLES
    )
    eff_precision_seed = (
        precision_seed if precision_seed is not None else DEFAULT_PRECISION_SEED
    )
    eff_precision_k = precision_k if precision_k is not None else DEFAULT_PRECISION_K
    try:
        raw = generate_pilot_sheet(
            log_path=log_path,
            output_root=output_root,
            run_id=run_id,
            bearbeiter=bearbeiter,
            heuristics=eff_heuristics,
            fusion=eff_fusion,
            java_headless=java_headless,
            preprocessing_note=preprocessing_note,
            export_pdf=export_pdf,
            precision_valid_samples=eff_precision_samples,
            precision_seed=eff_precision_seed,
            precision_k=eff_precision_k,
        )
        output_dir = Path(raw["output_dir"])
        markdown_path = Path(raw["markdown_path"])
        data_path = Path(raw["data_path"])
        markdown_content = markdown_path.read_text(encoding="utf-8")
        run_data = json.loads(data_path.read_text(encoding="utf-8"))
        artifacts = _collect_artifacts(output_dir)
        artifacts_zip = _build_artifacts_zip(output_dir, artifacts)

        return {
            "status": "success",
            "error_message": None,
            "runtime_wall_sec": round(time.perf_counter() - start, 2),
            "log_name": Path(log_path).stem,
            "log_path": str(log_path),
            "output_dir": str(output_dir),
            "markdown_path": str(markdown_path),
            "markdown_content": markdown_content,
            "data_path": str(data_path),
            "pdf_path": str(raw["pdf_path"]) if raw.get("pdf_path") else None,
            # Flat parameters mirror imp/decl so result_cache writes a populated
            # parameters.json and the validation tool can fingerprint the run's
            # discovery config uniformly. The two LOCKED Phase B knobs
            # (activity_entropy, dependency_threshold) lead; the rest follow.
            "parameters": {
                "activity_entropy": eff_fusion.activity_entropy,
                "dependency_threshold": eff_heuristics.dependency_threshold,
                "relative_to_best_threshold": eff_heuristics.relative_to_best_threshold,
                "l1l_threshold": eff_heuristics.l1l_threshold,
                "l2l_threshold": eff_heuristics.l2l_threshold,
                "long_distance_threshold": eff_heuristics.long_distance_threshold,
                "declare_alpha": eff_fusion.declare_alpha,
                "declare_support": eff_fusion.declare_support,
                "resilience": eff_fusion.resilience,
                "im_fitness": eff_fusion.im_fitness,
                "size_multiplicator": eff_fusion.size_multiplicator,
                "precision_valid_samples": eff_precision_samples,
                "precision_seed": eff_precision_seed,
                "precision_k": eff_precision_k,
                "export_pdf": export_pdf,
                "preprocessing_note": preprocessing_note,
            },
            "run_data": run_data,
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
