from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
from pathlib import Path
from typing import Any, Dict

from flex_compare.internal.experiment_reports import build_report_output_dir
from flex_compare.internal.declarative_miner.evaluation import DEFAULT_DISCOVERY_PARAMS
from flex_compare.internal.declarative_miner.evaluation import DiscoveryParams
from flex_compare.internal.declarative_miner.evaluation import T_LANG_VERSION
from flex_compare.internal.declarative_miner.evaluation import T_LANG_VALUES
from flex_compare.internal.declarative_miner.evaluation import evaluate_log_with_minerful
from flex_compare.internal.declarative_miner.evaluation import make_report_row
from flex_compare.internal.declarative_miner.visualize_declare_js import render_declare_js_html
from flex_compare.internal.declarative_miner.visualize_declare_js import render_declare_js_png
from flex_compare.internal.shared.formatting import checkbox as _checkbox
from flex_compare.internal.shared.formatting import fmt_bool_ja_nein as _fmt_bool_ja_nein
from flex_compare.internal.shared.formatting import fmt_bool_yes_no as _fmt_yes_no
from flex_compare.internal.shared.formatting import fmt_number as _fmt_number_base
from flex_compare.internal.shared.pdf_export import relative_path as _relative_base
from flex_compare.internal.shared.pdf_export import safe_pdf_export as _safe_pdf_export


def _fmt_number(value: Any, digits: int = 6) -> str:
    return _fmt_number_base(value, digits=digits)


def _relative(path: Path, base: Path) -> str:
    return _relative_base(path, base)


def _build_markdown(
    *,
    run_id: str,
    date_str: str,
    bearbeiter: str,
    log_path: Path,
    result: Dict[str, Any],
    output_md_dir: Path,
    declare_viz_path: str | None,
    declare_viz_png_path: str | None,
    declare_viz_error: str | None,
    declare_viz_engine: str | None,
    declare_viz_kind: str | None,
) -> str:
    notes = result.get("model_validation_notes") or []
    if not notes:
        notes = ["-"]

    constraints_per_type = result.get("constraints_per_type", {})
    if constraints_per_type:
        cpt_lines = [
            f"  - {template}: {count}" for template, count in constraints_per_type.items()
        ]
    else:
        cpt_lines = ["  - n/a"]

    report_row = make_report_row(result)
    report_line = (
        f"| {report_row['Log']} | {report_row['Miner']} | {report_row['Model generated']} | "
        f"{report_row['Discovery (s)']} | {report_row['#Activities']} | {report_row['#Constraints']} | "
        f"{report_row['#Constraint types']} | {report_row['Negative constraints']} | {report_row['Size']} | "
        f"{report_row['Density']} | {report_row['Separability']} | {report_row['Constraint Variability']} | "
        f"{report_row['Fitness']} | {report_row['Precision']} | {report_row['Generalisation']} | "
        f"{report_row['fitness_check_executed']} | {report_row['n_constraints_evaluated']} | "
        f"{report_row['n_traces_evaluated']} | {report_row['avg_fitness']} | "
        f"{report_row['trace_fit_ratio']} | {report_row['mean_trace_full_satisfaction_rate']} | "
        f"{report_row['mean_trace_non_violation_rate']} | {report_row['mean_trace_violation_rate']} | "
        f"{report_row['share_constraints_with_zero_violations']} |"
    )

    used_cli = result.get("used_cli_parameters", {})
    lit_ctx = result.get("literature_thresholds_context", {})
    if declare_viz_png_path:
        viz_line = f"![Declare Model]({_relative(Path(declare_viz_png_path), output_md_dir)})"
    else:
        viz_line = f"_Visualization not generated_: {declare_viz_error or 'n/a'}"
    fitness_check_notes = result.get("fitness_check_notes") or []
    if not fitness_check_notes:
        fitness_check_notes = ["n/a"]
    fitness_summary = result.get("fitness_summary") or {}
    per_constraint = fitness_summary.get("per_constraint") or []
    # Top-N by violating_traces (desc), for drill-down in the report
    top_violating = sorted(
        per_constraint,
        key=lambda r: (r.get("violating_traces") or 0),
        reverse=True,
    )[:10]

    return f"""# MINERful Results Report

## 1. Run Metadata
- Run ID: {run_id}
- Date: {date_str}
- Author: {bearbeiter}
- Log name: {log_path.stem}
- Log path: {log_path}

---

## 2. Input / Setup
- Miner: MINERful
- minerful_version: {result.get("minerful_version", "unknown")}
- T_lang_version: {result.get("T_lang_version", T_LANG_VERSION)}
- T_lang_values ({len(result.get("T_lang_values", T_LANG_VALUES))}): {", ".join(result.get("T_lang_values", T_LANG_VALUES))}
- used_cli_parameters:
  - support: {used_cli.get("support")}
  - confidence: {used_cli.get("confidence")}
  - coverage: {used_cli.get("coverage")}
  - trace_support: {used_cli.get("trace_support")}
  - trace_confidence: {used_cli.get("trace_confidence")}
  - trace_coverage: {used_cli.get("trace_coverage")}
  - prune: {used_cli.get("prune")}
- literature_thresholds_context:
  - support: {lit_ctx.get("support", "n/a")}
  - confidence: {lit_ctx.get("confidence", "n/a")}
  - interest_factor: {lit_ctx.get("interest_factor", "n/a")}
- preprocessing_note: {result.get("preprocessing_note") or "n/a"}
- advanced_cli_parameters:
  - prune_ranking_by: {used_cli.get("prune_ranking_by") or "n/a"}
  - prune_hierarchy_by: {used_cli.get("prune_hierarchy_by") or "n/a"}
  - keep_constraints: {_fmt_yes_no(used_cli.get("keep_constraints"))}
  - kb_ll_threads: {used_cli.get("kb_ll_threads") if used_cli.get("kb_ll_threads") is not None else "n/a"}
  - q_ll_threads: {used_cli.get("q_ll_threads") if used_cli.get("q_ll_threads") is not None else "n/a"}
  - foresee_distances: {_fmt_yes_no(used_cli.get("foresee_distances"))}
  - show_mem_peak: {_fmt_yes_no(used_cli.get("show_mem_peak"))}
  - exclude_results_in: {used_cli.get("exclude_results_in") or "n/a"}
  - stats_xml_out: {used_cli.get("stats_xml_out") or "n/a"}

---

## 3. Model Generation + Validation
- Model generated:
  - {_checkbox(bool(result.get("model_generated")))} yes
  - {_checkbox(not bool(result.get("model_generated")))} no
- model_validation_status: {result.get("model_validation_status", "invalid")}
- Discovery time (s): {_fmt_number(result.get("discovery_runtime_sec"))}
- JSON Output: {result.get("json_path") or "n/a"}
- CSV Output: {result.get("csv_path") or "n/a"}
- DOT Output: {result.get("dot_path") or "n/a"}
- Declare visualization (interactive): {declare_viz_path or "n/a"}
- Declare visualization (report image): {declare_viz_png_path or "n/a"}
- Visualization engine: {declare_viz_engine or "n/a"}
- Visualization type: {declare_viz_kind or "n/a"}
- Layout preparation: {result.get("declare_visualization_layout_applied") or "n/a"}
- Snapshot stage: {result.get("declare_visualization_snapshot_stage") or "n/a"}
- model_validation_notes:
{chr(10).join(f"  - {note}" for note in notes)}

### Visualization ({(declare_viz_kind or "n/a").upper()})
{viz_line}

---

## 4. Structure and Complexity Metrics
- #Activities: {result.get("n_activities", "n/a")}
- #Constraints: {result.get("n_constraints", "n/a")}
- #Constraint types: {result.get("n_constraint_types", "n/a")}
- #Constraints per type:
{chr(10).join(cpt_lines)}
- Negative constraints present: {_fmt_bool_ja_nein(result.get("negative_constraints_present"))}
- Size = |A| + |C|: {_fmt_number(result.get("size"))}
- Density = max_k (|C_k| / |A_k|): {_fmt_number(result.get("density"))}
- Separability = |Comp(G)| / (|A| + |C|): {_fmt_number(result.get("separability"))}
- Constraint Variability = max component entropy: {_fmt_number(result.get("constraint_variability"))}

### Compact Table
| Log | Miner | Model generated | Discovery (s) | #Activities | #Constraints | #Constraint types | Negative constraints | Size | Density | Separability | Constraint Variability | Fitness | Precision | Generalization | fitness_check_executed | n_constraints_evaluated | n_traces_evaluated | avg_fitness | trace_fit_ratio | mean_trace_full_satisfaction_rate | mean_trace_non_violation_rate | mean_trace_violation_rate | share_constraints_with_zero_violations |
|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
{report_line}

---

## 5. Quality metrics (intentionally n/a in v1)
- Fitness: n/a
- Precision: n/a
- Generalization: n/a

---

## 6. MINERful Fitness Check (official tool)

Conformance via `minerful.MinerFulFitnessCheckStarter` from `tools/MINERful/MINERful.jar`. Model input is the unmodified MINERful discovery JSON (`-iSE json`). Tool: `{result.get("fitness_tool") or "n/a"}`, tool version: `{result.get("fitness_tool_version") or "n/a"}`.

### Tool-emitted headline values
- Fitness check executed: {_fmt_yes_no(result.get("fitness_check_executed"))}
- Avg fitness (model): {_fmt_number(result.get("avg_fitness"))}
- Trace-fit-ratio: {_fmt_number(result.get("trace_fit_ratio"))}
- Constraints evaluated: {_fmt_number(result.get("n_constraints_evaluated"))}
- Traces evaluated: {_fmt_number(result.get("n_traces_evaluated"))}

### Derived ratios
_Pure reporting ratios — numerator and denominator are both tool-emitted counts from the CSV (`FullSatisfactions`, `VacuousSatisfactions`, `Violations`). No conformance logic in the app._
- Mean trace full satisfaction rate (strict): {_fmt_number(result.get("mean_trace_full_satisfaction_rate"))}
- Mean trace non-violation rate (= conformance): {_fmt_number(result.get("mean_trace_non_violation_rate"))}
- Mean trace violation rate: {_fmt_number(result.get("mean_trace_violation_rate"))}
- Share constraints with zero violations: {_fmt_number(result.get("share_constraints_with_zero_violations"))}

### Top constraints by violations (max. 10)
| Template | Constraint | FullSat | VacSat | Violations | trace_full_satisfaction_rate | trace_non_violation_rate | trace_violation_rate |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(
    f"| {c.get('template') or 'n/a'} | {c.get('constraint') or 'n/a'} | "
    f"{c.get('fully_satisfying_traces')} | {c.get('vacuously_satisfying_traces')} | "
    f"{c.get('violating_traces')} | {_fmt_number(c.get('trace_full_satisfaction_rate'))} | "
    f"{_fmt_number(c.get('trace_non_violation_rate'))} | {_fmt_number(c.get('trace_violation_rate'))} |"
    for c in top_violating
) if top_violating else "| n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |"}

### Notes from the fitness check
{chr(10).join(f"  - {note}" for note in fitness_check_notes)}

---

## 7. Notes
- Scope: only core metrics and declarative complexity metrics (v1).
- Cross-paradigm quality metrics are deliberately not computed in this iteration.
"""


def generate_pilot_sheet(
    *,
    log_path: Path,
    output_root: Path,
    minerful_dir: Path,
    run_id: str | None,
    bearbeiter: str | None,
    params: DiscoveryParams,
    export_pdf: bool,
    preprocessing_note: str | None = None,
    report_subdir: str = "minerful",
) -> Dict[str, Path | None]:
    if not log_path.exists():
        raise FileNotFoundError(f"Log file not found: {log_path}")

    run_id_val = run_id or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    bearbeiter_val = bearbeiter or getpass.getuser()
    date_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    out_dir = build_report_output_dir(output_root, log_path.stem, report_subdir)
    assets_dir = out_dir / "assets"
    specs_dir = assets_dir / "specifications"
    automata_dir = assets_dir / "automata"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = evaluate_log_with_minerful(
        log_path=log_path,
        minerful_dir=minerful_dir,
        output_spec_dir=specs_dir,
        output_automata_dir=automata_dir,
        params=params,
    )
    result["preprocessing_note"] = (preprocessing_note or "").strip()

    visuals_dir = assets_dir / "visuals"
    declare_viz_path: str | None = None
    declare_viz_png_path: str | None = None
    declare_viz_error: str | None = None
    declare_viz_engine: str | None = None
    declare_viz_kind: str | None = None
    declare_viz_layout_applied: str | None = None
    declare_viz_snapshot_stage: str | None = None

    try:
        csv_path = Path(result["csv_path"])
        html_path = visuals_dir / "declare_model_declare_js.html"
        png_path = visuals_dir / "declare_model_declare_js.png"
        render_declare_js_html(
            csv_path=csv_path,
            html_output_path=html_path,
            title=f"Declare Model: {log_path.stem}",
        )
        render_declare_js_png(
            html_path=html_path,
            png_output_path=png_path,
        )
        declare_viz_path = str(html_path)
        declare_viz_png_path = str(png_path)
        declare_viz_engine = "declare_js"
        declare_viz_kind = "html+png"
        declare_viz_layout_applied = "auto_layout_via_gear"
        declare_viz_snapshot_stage = "post_auto_layout"
        result["declare_visualization_layout_applied"] = declare_viz_layout_applied
        result["declare_visualization_snapshot_stage"] = declare_viz_snapshot_stage
    except Exception as exc:
        declare_viz_error = f"declare-js rendering failed: {exc}"
        # Strict policy: declare-js is the only allowed visualization.
        raise RuntimeError(declare_viz_error) from exc

    markdown = _build_markdown(
        run_id=run_id_val,
        date_str=date_str,
        bearbeiter=bearbeiter_val,
        log_path=log_path,
        result=result,
        output_md_dir=out_dir,
        declare_viz_path=declare_viz_path,
        declare_viz_png_path=declare_viz_png_path,
        declare_viz_error=declare_viz_error,
        declare_viz_engine=declare_viz_engine,
        declare_viz_kind=declare_viz_kind,
    )

    markdown_path = out_dir / "ergebnisbericht.md"
    markdown_path.write_text(markdown, encoding="utf-8")

    data_path = out_dir / "result_data.json"
    if declare_viz_path is not None:
        result["declare_visualization_path"] = declare_viz_path
    if declare_viz_png_path is not None:
        result["declare_visualization_png_path"] = declare_viz_png_path
    if declare_viz_error is not None:
        result["declare_visualization_error"] = declare_viz_error
    if declare_viz_engine is not None:
        result["declare_visualization_engine"] = declare_viz_engine
    if declare_viz_kind is not None:
        result["declare_visualization_kind"] = declare_viz_kind
    if declare_viz_layout_applied is not None:
        result["declare_visualization_layout_applied"] = declare_viz_layout_applied
    if declare_viz_snapshot_stage is not None:
        result["declare_visualization_snapshot_stage"] = declare_viz_snapshot_stage

    data_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    pdf_path = _safe_pdf_export(markdown_path) if export_pdf else None

    return {
        "output_dir": out_dir,
        "markdown_path": markdown_path,
        "pdf_path": pdf_path,
        "data_path": data_path,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a MINERful result report (v1 core metrics)."
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        required=True,
        help="Path to input XES log.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("Experimente"),
        help="Root directory for generated experiment reports.",
    )
    parser.add_argument(
        "--minerful-dir",
        type=Path,
        default=Path("tools/MINERful"),
        help="Path to MINERful directory.",
    )
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--bearbeiter", type=str, default=None)
    parser.add_argument("--preprocessing-note", type=str, default=None)
    parser.add_argument("--support", type=float, default=DEFAULT_DISCOVERY_PARAMS.support)
    parser.add_argument("--confidence", type=float, default=DEFAULT_DISCOVERY_PARAMS.confidence)
    parser.add_argument("--coverage", type=float, default=DEFAULT_DISCOVERY_PARAMS.coverage)
    parser.add_argument("--trace-support", type=float, default=DEFAULT_DISCOVERY_PARAMS.trace_support)
    parser.add_argument("--trace-confidence", type=float, default=DEFAULT_DISCOVERY_PARAMS.trace_confidence)
    parser.add_argument("--trace-coverage", type=float, default=DEFAULT_DISCOVERY_PARAMS.trace_coverage)
    parser.add_argument("--prune", type=str, default=DEFAULT_DISCOVERY_PARAMS.prune)
    parser.add_argument("--prune-ranking-by", type=str, default=DEFAULT_DISCOVERY_PARAMS.prune_ranking_by)
    parser.add_argument("--prune-hierarchy-by", type=str, default=DEFAULT_DISCOVERY_PARAMS.prune_hierarchy_by)
    parser.add_argument("--keep-constraints", action="store_true")
    parser.add_argument("--kb-ll-threads", type=int, default=DEFAULT_DISCOVERY_PARAMS.kb_ll_threads)
    parser.add_argument("--q-ll-threads", type=int, default=DEFAULT_DISCOVERY_PARAMS.q_ll_threads)
    parser.add_argument("--foresee-distances", action="store_true")
    parser.add_argument("--show-mem-peak", action="store_true")
    parser.add_argument("--exclude-results-in", type=str, default=DEFAULT_DISCOVERY_PARAMS.exclude_results_in)
    parser.add_argument("--stats-xml-out", type=str, default=DEFAULT_DISCOVERY_PARAMS.stats_xml_out)
    parser.add_argument("--export-pdf", action="store_true")
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    params = DiscoveryParams(
        support=args.support,
        confidence=args.confidence,
        coverage=args.coverage,
        trace_support=args.trace_support,
        trace_confidence=args.trace_confidence,
        trace_coverage=args.trace_coverage,
        prune=args.prune,
        prune_ranking_by=args.prune_ranking_by,
        prune_hierarchy_by=args.prune_hierarchy_by,
        keep_constraints=args.keep_constraints,
        kb_ll_threads=args.kb_ll_threads,
        q_ll_threads=args.q_ll_threads,
        foresee_distances=args.foresee_distances,
        show_mem_peak=args.show_mem_peak,
        exclude_results_in=args.exclude_results_in,
        stats_xml_out=args.stats_xml_out,
    )

    outputs = generate_pilot_sheet(
        log_path=args.log_path,
        output_root=args.output_root,
        minerful_dir=args.minerful_dir,
        run_id=args.run_id,
        bearbeiter=args.bearbeiter,
        params=params,
        export_pdf=args.export_pdf,
        preprocessing_note=args.preprocessing_note,
    )

    print(f"Results report generated in: {outputs['output_dir']}")
    print(f"Markdown: {outputs['markdown_path']}")
    print(f"Data: {outputs['data_path']}")
    if outputs["pdf_path"] is None:
        print("PDF: not generated")
    else:
        print(f"PDF: {outputs['pdf_path']}")


if __name__ == "__main__":
    main()
