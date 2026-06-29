"""High-level orchestration API for declarative evaluation.

Conformance is computed by MINERful's own ``MinerFulFitnessCheckStarter``
against the unmodified MINERful discovery JSON (no ``.decl`` translation).
Optional MINERful vacuity checker can be invoked alongside.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

from flex_compare.internal.declarative_evaluation.minerful_fitness import (
    minerful_jar_version,
    run_minerful_fitness_check,
)
from flex_compare.internal.declarative_evaluation.precision_proxies import compute_precision_proxies
from flex_compare.internal.declarative_evaluation.vacuity_minerful import minerful_available

_DECL_CONSTRAINT_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9\-_]*)\s*\[([^\]]*)\]")
_DECL_ACTIVITY_RE = re.compile(r"^\s*activity\s+(.+?)\s*$", re.IGNORECASE)


def _parse_decl_file(decl_path: Path) -> tuple[List[str], List[Dict[str, Any]]]:
    """Parse a ``.decl`` file. Read-only; takes externally-provided Declare
    specs as input."""
    if not decl_path.exists():
        return [], []
    activities: List[str] = []
    constraints: List[Dict[str, Any]] = []
    for line in decl_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m_act = _DECL_ACTIVITY_RE.match(stripped)
        if m_act:
            name = m_act.group(1).strip()
            if name:
                activities.append(name)
            continue
        m_con = _DECL_CONSTRAINT_RE.match(stripped)
        if m_con:
            template = m_con.group(1).strip()
            params = [p.strip() for p in m_con.group(2).split(",") if p.strip()]
            constraints.append({"template": template, "activities": params})
    return activities, constraints


def evaluate_declarative(
    *,
    log_path: Path,
    minerful_json_path: Path,
    fitness_csv_path: Path | None = None,
    use_minerful_vacuity: bool = False,
    activities: Sequence[str] | None = None,
    constraints: Sequence[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Run MINERful fitness check on a (log, MINERful-spec) pair.

    Optionally also run MINERful's vacuity checker. Computes precision proxies
    over the discovered constraints. Returns a result dict that the
    comparison_app and CLI render into reports.
    """
    log_path = Path(log_path)
    minerful_json_path = Path(minerful_json_path)
    if fitness_csv_path is None:
        fitness_csv_path = minerful_json_path.with_suffix(".fitness.csv")
    fitness_csv_path = Path(fitness_csv_path)

    fitness_summary = run_minerful_fitness_check(
        log_path=log_path,
        minerful_json_path=minerful_json_path,
        output_csv_path=fitness_csv_path,
    )

    # vacuity / non-vacuity are derived from the fitness result itself (single
    # source, discovered post-pruning constraint basis) — there is no separate
    # vacuity-checker invocation. ``use_minerful_vacuity`` is retained for API
    # compatibility (echoed into call_params) but no longer triggers the retired
    # Java POC checker.
    vacuity_result: Dict[str, Any] | None = None

    proxies = compute_precision_proxies(
        fitness_result=fitness_summary,
        constraints=constraints,
        activities=activities,
    )

    minerful_any_available = bool(fitness_summary.get("available"))

    return {
        "call_params": {
            "log_path": str(log_path),
            "minerful_json_path": str(minerful_json_path),
            "fitness_csv_path": str(fitness_csv_path),
            "use_minerful_vacuity": use_minerful_vacuity,
        },
        "versions": {
            "minerful_jar": minerful_jar_version()
            if minerful_any_available or use_minerful_vacuity
            else None,
        },
        "fitness": fitness_summary,
        "minerful": {
            "available": minerful_any_available,
            "vacuity": vacuity_result,
        },
        "precision_proxies": proxies,
    }
