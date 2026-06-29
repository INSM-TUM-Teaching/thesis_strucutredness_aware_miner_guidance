"""Standard-format model imports for the ``custom-exec`` miner path.

Reads a pre-mined model from PNML / MINERful-native JSON / BPMN and assembles
a result dict shaped like the native ``run_evaluation`` adapters'. Metrics that
can be derived from the imported model alone are populated; everything that
needs *discovery-internal* information (process-tree depth, CFC, flower
detection) is left at ``None`` and flagged via ``source="imported"`` in
:func:`miners.shared.metrics.metric_proxies.extract_metrics_by_paradigm`.

Declare-JSON dialect: the v1 importer accepts **MINERful's native JSON**
(``{"processSchema": {"constraints": [...]}, "activities": [...]}``) only.
Foreign dialects (RuM, ConDec, generic Declare4Py) raise a clear
``ValueError`` with the convert-to-MINERful hint — the schemas are similar
enough to fool a fuzzy parser, so we fail loud rather than silently.
"""
from __future__ import annotations

import json
import logging
import re
import shlex
import shutil
import subprocess
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)

OutputFormat = Literal["pnml", "declare-json", "bpmn"]

# Truncate captured stdout/stderr to keep the UI usable. Java miners can dump
# MB of logs; we keep the head + tail and drop the middle.
_EXEC_LOG_MAX_BYTES = 256 * 1024
_EXEC_LOG_HEAD_TAIL_BYTES = _EXEC_LOG_MAX_BYTES // 2


# ── Subprocess dispatch ──────────────────────────────────────────────────────
class ExecError(Exception):
    """Wraps any non-``ok`` outcome from :func:`run_executable`."""

    def __init__(self, status: str, summary: str, exec_log_path: Optional[Path] = None):
        super().__init__(summary)
        self.status = status
        self.summary = summary
        self.exec_log_path = exec_log_path


@dataclass(frozen=True)
class ExecResult:
    command: list[str]
    exit_code: int
    duration_sec: float
    exec_log_path: Path


def _format_template(template: str, params: dict, log_path: Path, output_dir: Path) -> str:
    """Substitute ``{log}``/``{outdir}``/``{<param>}`` in ``template``.

    Plain ``str.replace`` instead of ``str.format`` so JSON-shaped values
    containing braces pass through unscathed.
    """
    text = template.replace("{log}", str(log_path)).replace("{outdir}", str(output_dir))
    for key, value in params.items():
        text = text.replace("{" + key + "}", str(value))
    # Surface any leftover ``{key}`` placeholders as a hard error rather than
    # passing them to the executable verbatim.
    leftover = re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", text)
    if leftover:
        raise ExecError(
            "parse_error",
            f"unsubstituted command placeholder(s): {sorted(set(leftover))}",
        )
    return text


def _truncate_for_log(text: str) -> str:
    if len(text) <= _EXEC_LOG_MAX_BYTES:
        return text
    head = text[:_EXEC_LOG_HEAD_TAIL_BYTES]
    tail = text[-_EXEC_LOG_HEAD_TAIL_BYTES:]
    return f"{head}\n…[{len(text) - _EXEC_LOG_MAX_BYTES} bytes elided]…\n{tail}"


def run_executable(
    template: str,
    params: dict,
    log_path: Path,
    output_dir: Path,
    timeout_sec: int = 600,
    on_started=None,
    cancel_check=None,
) -> ExecResult:
    """Run an external miner; capture stdout+stderr to ``<output_dir>/_exec.log``.

    ``on_started(popen)`` is invoked once the process has been spawned, giving
    the caller a handle for cooperative cancellation. ``cancel_check()``
    returns ``True`` to request termination; the loop polls it once per second
    and ``.terminate()``s the process if it ever flips. Raises
    :class:`ExecError` with a ``status`` discriminator on every failure mode
    (``timeout`` | ``nonzero`` | ``cancelled``).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    formatted = _format_template(template, params, log_path, output_dir)
    tokens = shlex.split(formatted)
    if not tokens:
        raise ExecError("parse_error", "empty command after substitution")

    exec_log = output_dir / "_exec.log"
    start = time.monotonic()
    proc = subprocess.Popen(
        tokens, shell=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if on_started is not None:
        try:
            on_started(proc)
        except Exception:  # callback failure should never abort the run
            logger.exception("on_started callback raised; continuing")

    deadline = start + max(timeout_sec, 1)
    cancelled = False
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            stdout, stderr = proc.communicate()
            captured = (stdout or "") + ("\n--- stderr ---\n" + (stderr or "") if stderr else "")
            exec_log.write_text(_truncate_for_log(captured), encoding="utf-8")
            raise ExecError(
                "timeout", f"timed out after {timeout_sec}s",
                exec_log_path=exec_log,
            )
        if cancel_check is not None and cancel_check():
            cancelled = True
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            break
        try:
            proc.wait(timeout=min(1.0, remaining))
            break
        except subprocess.TimeoutExpired:
            continue

    stdout, stderr = proc.communicate()
    duration = time.monotonic() - start
    captured = (stdout or "") + ("\n--- stderr ---\n" + (stderr or "") if stderr else "")
    exec_log.write_text(_truncate_for_log(captured), encoding="utf-8")

    if cancelled:
        raise ExecError("cancelled", "cancelled by user", exec_log_path=exec_log)
    if proc.returncode != 0:
        raise ExecError(
            "nonzero",
            f"exit code {proc.returncode} — see _exec.log",
            exec_log_path=exec_log,
        )
    return ExecResult(
        command=tokens,
        exit_code=proc.returncode,
        duration_sec=duration,
        exec_log_path=exec_log,
    )


# ── PNML import (imperative metrics) ─────────────────────────────────────────
def _render_petri_png(net, im, fm, dest: Path) -> Optional[Path]:
    try:
        import pm4py  # local import — pm4py is heavy

        pm4py.save_vis_petri_net(net, im, fm, str(dest))
        return dest if dest.is_file() else None
    except Exception as exc:  # rendering is optional — never block the import
        logger.warning("petri-net rendering failed: %s", exc)
        return None


def import_pnml(pnml_path: Path, log_path: Path, output_dir: Optional[Path] = None,
                conformance_method: str = "token_replay") -> dict:
    """Load a PNML, replay against the log, and return a result-dict.

    Populates ``petri_net_path`` (copied), ``replay_fitness``, ``etc_precision``,
    ``soundness_passed``; everything else is left to the paradigm fallback in
    ``extract_metrics_by_paradigm(..., source="imported")``.
    """
    import pm4py  # local import — pm4py is heavy
    from flex_compare.internal.imperative_miner.evaluation import (
        _extract_fitness_precision,
        _extract_soundness,
    )

    pnml_path = Path(pnml_path)
    if not pnml_path.is_file():
        raise FileNotFoundError(f"PNML not found: {pnml_path}")

    target_dir = Path(output_dir) if output_dir is not None else pnml_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    # Copy the PNML into the output dir so the cache picks it up via
    # the artifact-allowlist by paradigm.
    pnml_dest = target_dir / "model.pnml"
    if pnml_path.resolve() != pnml_dest.resolve():
        shutil.copy2(pnml_path, pnml_dest)

    net, im, fm = pm4py.read_pnml(str(pnml_dest))
    log = pm4py.read_xes(str(log_path))

    fp = _extract_fitness_precision(log, net, im, fm, method=conformance_method)
    sd = _extract_soundness(net, im, fm)

    png_path = _render_petri_png(net, im, fm, target_dir / "petri_net.png")

    return {
        "status": "success",
        "log_path": str(log_path),
        "output_dir": str(target_dir),
        "petri_net_path": str(png_path) if png_path else None,
        "model_pnml_path": str(pnml_dest),
        "imported_from": "pnml",
        "metrics": {
            "replay_fitness": fp.get("fitness_primary"),
            "etc_precision": fp.get("precision"),
            "soundness_passed": sd.get("is_sound"),
            "is_wf_net": sd.get("is_wf_net"),
            "conformance_method": conformance_method,
        },
    }


# ── BPMN import (delegates to PNML pathway after conversion) ─────────────────
def import_bpmn(bpmn_path: Path, log_path: Path, output_dir: Optional[Path] = None,
                conformance_method: str = "token_replay") -> dict:
    import pm4py

    bpmn_path = Path(bpmn_path)
    if not bpmn_path.is_file():
        raise FileNotFoundError(f"BPMN not found: {bpmn_path}")

    target_dir = Path(output_dir) if output_dir is not None else bpmn_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    bpmn_graph = pm4py.read_bpmn(str(bpmn_path))
    net, im, fm = pm4py.convert_to_petri_net(bpmn_graph)
    pnml_dest = target_dir / "model.pnml"
    pm4py.write_pnml(net, im, fm, str(pnml_dest))

    out = import_pnml(pnml_dest, log_path, output_dir=target_dir,
                      conformance_method=conformance_method)
    out["imported_from"] = "bpmn"
    return out


# ── MINERful-native Declare-JSON import (declarative metrics) ────────────────
_MINERFUL_TOP_KEYS = {"processSchema", "tasksList", "tasks"}  # any of these → MINERful native
_FOREIGN_DIALECT_HINTS = {
    "ruleSets",   # RuM
    "model",      # ConDec exports
    "Declare",    # generic Declare4Py
}


def _looks_minerful_native(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    if "processSchema" in payload and isinstance(payload["processSchema"], dict):
        return "constraints" in payload["processSchema"]
    return False


def import_declare_json(json_path: Path, log_path: Path,
                        output_dir: Optional[Path] = None) -> dict:
    """Load a MINERful-native Declare-JSON file and return a result-dict.

    Computes ``constraint_density`` (constraints per activity) and
    ``constraint_variability`` (distinct templates / total constraints) directly
    from the JSON. ``vacuity_rate`` and ``non_vacuous_satisfaction_rate`` need a
    MINERful Java subprocess and are intentionally left ``None`` — v1 surfaces
    them as ``n/a`` rather than spinning up MINERful per imported model.
    """
    json_path = Path(json_path)
    if not json_path.is_file():
        raise FileNotFoundError(f"Declare-JSON not found: {json_path}")

    raw = json.loads(json_path.read_text(encoding="utf-8"))
    if not _looks_minerful_native(raw):
        raise ValueError(
            "dialect not supported — convert to MINERful JSON "
            "(expected {'processSchema': {'constraints': [...]}})"
        )

    schema = raw.get("processSchema") or {}
    constraints = schema.get("constraints") or []
    activities = (
        raw.get("activities")
        or raw.get("tasksList")
        or sorted({
            param
            for c in constraints
            for param in _flatten_parameters(c.get("parameters"))
        })
    )

    n_constraints = len(constraints)
    n_activities = max(len(activities), 1)
    templates = Counter(c.get("template") for c in constraints if c.get("template"))
    n_distinct_templates = len(templates)

    target_dir = Path(output_dir) if output_dir is not None else json_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    json_dest = target_dir / "model.json"
    if json_path.resolve() != json_dest.resolve():
        shutil.copy2(json_path, json_dest)

    return {
        "status": "success",
        "log_path": str(log_path),
        "output_dir": str(target_dir),
        "declare_visualization_path": None,        # no declare.js renderer in v1 import path
        "declare_visualization_png_path": None,
        "model_json_path": str(json_dest),
        "imported_from": "declare-json",
        "metrics": {
            "constraint_density": (n_constraints / n_activities) if n_constraints else 0.0,
            "constraint_variability": (n_distinct_templates / n_constraints) if n_constraints else None,
            "n_constraints": n_constraints,
            "n_activities": len(activities),
            "n_distinct_templates": n_distinct_templates,
            # vacuity_rate, non_vacuous_satisfaction_rate, constraint_consistency
            # require MINERful subprocess → left None for the paradigm fallback.
            "json_path": str(json_dest),
        },
    }


def _flatten_parameters(params: Any) -> list[str]:
    if isinstance(params, list):
        out: list[str] = []
        for item in params:
            out.extend(_flatten_parameters(item))
        return out
    if isinstance(params, str):
        return [params]
    return []


# ── Dispatch by output format ────────────────────────────────────────────────
def import_by_format(
    output_format: OutputFormat,
    artifact_path: Path,
    log_path: Path,
    output_dir: Optional[Path] = None,
    conformance_method: str = "token_replay",
) -> dict:
    if output_format == "pnml":
        return import_pnml(artifact_path, log_path, output_dir=output_dir,
                           conformance_method=conformance_method)
    if output_format == "bpmn":
        return import_bpmn(artifact_path, log_path, output_dir=output_dir,
                           conformance_method=conformance_method)
    if output_format == "declare-json":
        return import_declare_json(artifact_path, log_path, output_dir=output_dir)
    raise ValueError(f"unsupported output_format: {output_format!r}")


def paradigm_for_format(output_format: OutputFormat) -> str:
    """Default paradigm mapping for an output format."""
    if output_format in ("pnml", "bpmn"):
        return "imperativ"
    if output_format == "declare-json":
        return "deklarativ"
    raise ValueError(f"unsupported output_format: {output_format!r}")
