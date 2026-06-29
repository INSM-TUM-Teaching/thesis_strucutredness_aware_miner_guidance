"""MINERful fitness check via the project's own MinerFulFitnessCheckStarter.

All values returned by this module are either tool-emitted (read verbatim from
MINERful's CSV/stdout) or pure arithmetic on tool-emitted operands (quotients
where both numerator and denominator are tool-emitted counts). No conformance
logic in this layer.

Tool: ``minerful.MinerFulFitnessCheckStarter`` from
``tools/MINERful/MINERful.jar``.

CLI invoked:
    java -cp MINERful.jar:$LIBS minerful.MinerFulFitnessCheckStarter
        -iLF <log.xes> -iLE xes
        -iSF <minerful_spec.json> -iSE json
        -chkOut <out.csv>
        -d none

CSV header (semicolon-separated):
    Template;Constraint;Fitness;FullSatisfactions;VacuousSatisfactions;Violations;Avg-fitness;Trace-fit-ratio

Note: the per-constraint ``Fitness`` column emits a denormalized double
(``4.9E-324``) regardless of debug level — confirmed bug in MINERful's CSV
output. The wrapper drops this column. Per-constraint fitness is **not**
exposed; only the model-level ``Avg-fitness`` and ``Trace-fit-ratio`` (which
are correct in the CSV and stdout) are used as headline numbers.
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import subprocess
import time
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

from flex_compare.internal.shared.paths import PROJECT_ROOT

DEFAULT_MINERFUL_HOME = str(PROJECT_ROOT / "tools" / "MINERful")
_TIMEOUT_SECONDS = 300


def _resolve_home() -> Path:
    return Path(os.environ.get("MINERFUL_HOME", DEFAULT_MINERFUL_HOME))


def _jar_path() -> Path:
    return _resolve_home() / "MINERful.jar"


def _classpath() -> str:
    home = _resolve_home()
    parts: List[str] = []
    bin_dir = home / "bin"
    if bin_dir.is_dir():
        parts.append(str(bin_dir))
    jar = home / "MINERful.jar"
    if jar.is_file():
        parts.append(str(jar))
    lib_dir = home / "lib"
    if lib_dir.is_dir():
        for j in sorted(lib_dir.glob("*.jar")):
            parts.append(str(j))
    return ":".join(parts)


def minerful_fitness_available() -> bool:
    home = _resolve_home()
    if not home.is_dir():
        return False
    if not (home / "MINERful.jar").is_file():
        return False
    return True


def minerful_jar_version() -> str | None:
    jar = _jar_path()
    if not jar.is_file():
        return None
    try:
        h = hashlib.sha256(jar.read_bytes()).hexdigest()
        return f"sha256:{h[:16]}"
    except Exception:
        return None


_CONSTRAINT_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)\s*\(([^)]*)\)\s*$")
# MINERful prints decimals via Java's locale-default `String.format`, so values
# may use '.' (en-US) or ',' (de-DE) as the decimal separator. We extract each
# key independently so the pair-separator and decimal-separator can both be
# ',' without ambiguity. `_locale_float` normalises before parsing.
_AVG_FITNESS_RE = re.compile(r'"Avg\.fitness"\s*:\s*([-\d.,eE+]+)')
_TRACE_FIT_RATIO_RE = re.compile(r'"Trace-fit-ratio"\s*:\s*([-\d.,eE+]+)')


def _locale_float(value: str | None) -> float | None:
    """Parse a Java-formatted float, tolerating ',' or '.' as decimal sep.

    The capture regex above is intentionally permissive (matches a run of
    digits/'.'/','/'eE+-'), so the captured slice may include a trailing
    ',' or ';' from the pair separator in en-US output like
    ``"Avg.fitness": 0.83,``. Strip those before parsing.
    """
    if value is None:
        return None
    text = value.strip().rstrip(",;")
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_constraint_label(label: str) -> tuple[str, List[str]]:
    """Parse "AtMost1(b)" or "ChainResponse(a, b)" into (template, [activities])."""
    m = _CONSTRAINT_RE.match(label.strip())
    if not m:
        return label.strip(), []
    template = m.group(1)
    params = [p.strip() for p in m.group(2).split(",") if p.strip()]
    return template, params


def _parse_csv(csv_path: Path) -> tuple[List[Dict[str, Any]], Dict[str, float]]:
    """Read MINERful fitness CSV.

    Returns (per_constraint_rows, model_aggregates). The per-constraint Fitness
    column is dropped (broken in tool). Avg-fitness and Trace-fit-ratio are
    pulled from any row (tool emits them redundantly per-row).
    """
    rows: List[Dict[str, Any]] = []
    avg_fitness: float | None = None
    trace_fit_ratio: float | None = None

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for raw in reader:
            template_raw = (raw.get("Template") or "").strip()
            constraint_raw = (raw.get("Constraint") or "").strip()
            try:
                full = int(raw.get("FullSatisfactions") or 0)
                vac = int(raw.get("VacuousSatisfactions") or 0)
                vio = int(raw.get("Violations") or 0)
            except ValueError:
                continue
            parsed_avg = _locale_float(raw.get("Avg-fitness"))
            if parsed_avg is not None:
                avg_fitness = parsed_avg
            parsed_ratio = _locale_float(raw.get("Trace-fit-ratio"))
            if parsed_ratio is not None:
                trace_fit_ratio = parsed_ratio
            template_parsed, activities = _parse_constraint_label(constraint_raw)
            rows.append(
                {
                    "template": template_raw or template_parsed,
                    "constraint": constraint_raw,
                    "activities": activities,
                    "fully_satisfying_traces": full,
                    "vacuously_satisfying_traces": vac,
                    "violating_traces": vio,
                    "non_violating_traces": full + vac,
                }
            )
    aggregates = {
        "avg_fitness": avg_fitness,
        "trace_fit_ratio": trace_fit_ratio,
    }
    return rows, aggregates


def _derive_fitness_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tier-B derivation: pure arithmetic on MINERful per-constraint trace counts.

    Mutates each row in ``rows`` in place, adding the three per-constraint rate
    keys (``trace_full_satisfaction_rate``, ``trace_non_violation_rate``,
    ``trace_violation_rate``), and returns the model-level aggregates / sums /
    ``total_traces``. Separated from :func:`run_minerful_fitness_check` so the
    arithmetic can be unit-tested without invoking Java.

    Each row must carry the integer keys ``fully_satisfying_traces``,
    ``vacuously_satisfying_traces``, ``violating_traces`` and the derived
    ``non_violating_traces`` (== full + vacuous).

    ``total_traces`` is the max over rows of (full+vacuous+violating). MINERful
    evaluates every constraint over the whole log, so each row's three counts
    partition the trace set and that sum is constant (== |L|); the max is a
    defensive reduction that equals |L| whenever the partition invariant holds.
    """
    total_traces: int | None = None
    for row in rows:
        s = (
            row["fully_satisfying_traces"]
            + row["vacuously_satisfying_traces"]
            + row["violating_traces"]
        )
        if total_traces is None or s > total_traces:
            total_traces = s

    # Pure arithmetic on tool-emitted operands. Three rates per constraint:
    #  - trace_full_satisfaction_rate: strict fulfilment (constraint actually
    #    fired and held). Numerator FullSatisfactions.
    #  - trace_non_violation_rate: trace had no violation of this constraint
    #    (full or vacuous). Numerator FullSatisfactions + VacuousSatisfactions
    #    (== non_violating_traces). Closest to the legacy
    #    `conformant_traces_share` definition.
    #  - trace_violation_rate: trace violated the constraint at least once.
    #    Numerator Violations.
    for row in rows:
        if total_traces and total_traces > 0:
            row["trace_full_satisfaction_rate"] = (
                row["fully_satisfying_traces"] / total_traces
            )
            row["trace_non_violation_rate"] = row["non_violating_traces"] / total_traces
            row["trace_violation_rate"] = row["violating_traces"] / total_traces
        else:
            row["trace_full_satisfaction_rate"] = None
            row["trace_non_violation_rate"] = None
            row["trace_violation_rate"] = None
        # Per-constraint vacuity classification (trace-based, on the discovered
        # post-pruning constraint set — i.e. exactly the rows MINERful's
        # FitnessChecker kept after its threshold/subsumption-hierarchy pass).
        # A constraint is non-vacuously satisfied iff its activation fired and
        # held in at least one trace (Maggi/Di Ciccio): that is precisely
        # FullSatisfactions >= 1. Otherwise it is only-vacuously satisfied.
        row["non_vacuously_satisfied"] = row["fully_satisfying_traces"] >= 1

    full_rates = [
        r["trace_full_satisfaction_rate"] for r in rows
        if r["trace_full_satisfaction_rate"] is not None
    ]
    non_viol_rates = [
        r["trace_non_violation_rate"] for r in rows
        if r["trace_non_violation_rate"] is not None
    ]
    violation_rates = [
        r["trace_violation_rate"] for r in rows if r["trace_violation_rate"] is not None
    ]
    n_zero_viol = sum(1 for r in rows if r["violating_traces"] == 0)
    n_constraints = len(rows)

    # Sums over per-constraint trace counts. NOT log-wide event-level totals —
    # each summand counts (constraint, trace) pairs falling into the given
    # MINERful trace category. Each summand is tool-emitted (CSV column);
    # the sum itself is pure arithmetic.
    sum_full_satisfactions = sum(r["fully_satisfying_traces"] for r in rows)
    sum_vacuous_satisfactions = sum(r["vacuously_satisfying_traces"] for r in rows)
    sum_violations = sum(r["violating_traces"] for r in rows)

    # Vacuity rates over the discovered, post-pruning CONSTRAINT set (NOT over
    # (constraint, trace) pairs). Each discovered constraint partitions into
    # {only-vacuously satisfied} ∪ {non-vacuously satisfied} via the
    # per-constraint ``non_vacuously_satisfied`` flag set above, so by
    # construction non_vacuous_satisfaction_rate == 1 - vacuity_rate on the
    # same basis. Both rates and the non_vacuous classification share this one
    # source. Guarded on total_traces: with no traces the FullSatisfactions
    # count is uninformative (nothing was evaluated), so the rates are None
    # rather than a misleading 1.0.
    if n_constraints and total_traces:
        n_non_vacuous = sum(1 for r in rows if r["non_vacuously_satisfied"])
        non_vacuous_satisfaction_rate = n_non_vacuous / n_constraints
        vacuity_rate = (n_constraints - n_non_vacuous) / n_constraints
    else:
        non_vacuous_satisfaction_rate = None
        vacuity_rate = None

    model_aggregates = {
        "mean_trace_full_satisfaction_rate": mean(full_rates) if full_rates else None,
        "mean_trace_non_violation_rate": mean(non_viol_rates) if non_viol_rates else None,
        "mean_trace_violation_rate": mean(violation_rates) if violation_rates else None,
        "share_constraints_with_zero_violations": (
            n_zero_viol / n_constraints if n_constraints else None
        ),
    }
    return {
        "total_traces": total_traces,
        "n_constraints": n_constraints,
        "sum_full_satisfactions": sum_full_satisfactions,
        "sum_vacuous_satisfactions": sum_vacuous_satisfactions,
        "sum_violations": sum_violations,
        "vacuity_rate": vacuity_rate,
        "non_vacuous_satisfaction_rate": non_vacuous_satisfaction_rate,
        "model_aggregates": model_aggregates,
    }


def _parse_stdout_aggregates(stdout: str) -> Dict[str, float | None]:
    """Pull `{"Avg.fitness": ..., "Trace-fit-ratio": ...}` blob from stdout if present."""
    avg_match = _AVG_FITNESS_RE.search(stdout)
    ratio_match = _TRACE_FIT_RATIO_RE.search(stdout)
    return {
        "avg_fitness": _locale_float(avg_match.group(1)) if avg_match else None,
        "trace_fit_ratio": _locale_float(ratio_match.group(1)) if ratio_match else None,
    }


def _summarize_stderr(stderr: str, max_frames: int = 2) -> List[str]:
    """Pick the lines that actually identify a JVM crash.

    Java prints exception type + message on the first non-empty line, then a
    deepening stack trace. The deepest frame (last `at ...` line) alone is
    useless — it's almost always `Main.main`. We keep the first non-empty
    line plus the last few `at`-frames so the cause is visible in notes.
    """
    lines = [line for line in stderr.splitlines() if line.strip()]
    if not lines:
        return []
    head = lines[0].strip()
    at_frames = [line.strip() for line in lines if line.lstrip().startswith("at ")]
    tail = at_frames[-max_frames:] if at_frames else []
    picked: List[str] = [head]
    for frame in tail:
        if frame != head and frame not in picked:
            picked.append(frame)
    return picked


def _empty_summary(notes: List[str], extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "available": False,
        "tool": "minerful_fitness_checker",
        "tool_version": minerful_jar_version(),
        "fitness_metrics": {
            "avg_fitness": None,
            "trace_fit_ratio": None,
            "n_constraints_evaluated": 0,
            "n_traces_evaluated": None,
            "sum_full_satisfactions": None,
            "sum_vacuous_satisfactions": None,
            "sum_violations": None,
            "vacuity_rate": None,
            "non_vacuous_satisfaction_rate": None,
        },
        "per_constraint": [],
        "model_aggregates": {
            "mean_trace_full_satisfaction_rate": None,
            "mean_trace_non_violation_rate": None,
            "mean_trace_violation_rate": None,
            "share_constraints_with_zero_violations": None,
        },
        "raw_csv_path": None,
        "raw_stdout": "",
        "raw_stderr": "",
        "fitness_check_notes": list(notes),
        "fitness_runtime_sec": None,
    }
    if extra:
        base.update(extra)
    return base


def run_minerful_fitness_check(
    *,
    log_path: Path,
    minerful_json_path: Path,
    output_csv_path: Path,
) -> Dict[str, Any]:
    """Run MINERful fitness check on (log, spec) and parse the results.

    Returns a dict with keys ``available``, ``tool``, ``tool_version``,
    ``fitness_metrics``, ``per_constraint``, ``model_aggregates``,
    ``raw_csv_path``, ``raw_stdout``, ``fitness_check_notes``. On any failure
    (missing JAR, java error, parse failure) returns ``available=False`` with
    error details in ``fitness_check_notes``.
    """
    if not minerful_fitness_available():
        return _empty_summary(["MINERful jar not available"])

    cp = _classpath()
    if not cp:
        return _empty_summary(["empty classpath"])

    output_csv_path.parent.mkdir(parents=True, exist_ok=True)

    # MINERful's FitnessChecker re-applies *its own* pre-measurement pruning
    # (threshold + subsumption-hierarchy). Attempts to disable it via the
    # documented flags do not work cleanly: zero thresholds cause it to mark
    # *all* constraints as below-threshold (semantics is inverted: lower
    # threshold => fewer constraints kept), and `-prune none` triggers an NPE
    # downstream. We therefore accept the checker's defaults and surface the
    # resulting count gap (n_constraints_evaluated < n_constraints) as a note.
    cmd = [
        "java",
        "-Xmx4G",
        "-cp",
        cp,
        "minerful.MinerFulFitnessCheckStarter",
        "-iLF",
        str(log_path),
        "-iLE",
        "xes",
        "-iSF",
        str(minerful_json_path),
        "-iSE",
        "json",
        "-chkOut",
        str(output_csv_path),
        "-d",
        "none",
    ]

    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            cwd=str(_resolve_home()),
            check=False,
        )
    except FileNotFoundError as exc:
        return _empty_summary(
            [f"java binary not found: {exc}"],
            extra={"fitness_runtime_sec": time.perf_counter() - started},
        )
    except subprocess.TimeoutExpired as exc:
        return _empty_summary(
            [f"timeout after {_TIMEOUT_SECONDS}s"],
            extra={
                "raw_stdout": exc.stdout or "",
                "fitness_runtime_sec": time.perf_counter() - started,
            },
        )
    except Exception as exc:
        return _empty_summary(
            [f"subprocess failed: {exc}"],
            extra={"fitness_runtime_sec": time.perf_counter() - started},
        )
    fitness_runtime_sec = time.perf_counter() - started

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    if proc.returncode != 0 or not output_csv_path.is_file():
        notes = [f"exit code {proc.returncode}"]
        notes.extend(_summarize_stderr(stderr))
        if not output_csv_path.is_file():
            notes.append(f"CSV not produced at {output_csv_path}")
        return _empty_summary(
            notes,
            extra={
                "raw_stdout": stdout,
                "raw_stderr": stderr,
                "fitness_runtime_sec": fitness_runtime_sec,
            },
        )

    try:
        rows, csv_aggs = _parse_csv(output_csv_path)
    except Exception as exc:
        return _empty_summary(
            [f"CSV parse failed: {exc}"],
            extra={"raw_stdout": stdout, "fitness_runtime_sec": fitness_runtime_sec},
        )

    if not rows:
        return _empty_summary(
            ["CSV had no per-constraint rows"],
            extra={"raw_stdout": stdout, "fitness_runtime_sec": fitness_runtime_sec},
        )

    stdout_aggs = _parse_stdout_aggregates(stdout)
    avg_fitness = stdout_aggs.get("avg_fitness")
    if avg_fitness is None:
        avg_fitness = csv_aggs.get("avg_fitness")
    trace_fit_ratio = stdout_aggs.get("trace_fit_ratio")
    if trace_fit_ratio is None:
        trace_fit_ratio = csv_aggs.get("trace_fit_ratio")

    # n_traces_evaluated + all Tier-B quotients/sums: pure arithmetic on
    # tool-emitted counts. Extracted into _derive_fitness_metrics so the
    # arithmetic is unit-testable without a Java invocation.
    derived = _derive_fitness_metrics(rows)
    total_traces = derived["total_traces"]
    n_constraints = derived["n_constraints"]
    sum_full_satisfactions = derived["sum_full_satisfactions"]
    sum_vacuous_satisfactions = derived["sum_vacuous_satisfactions"]
    sum_violations = derived["sum_violations"]
    vacuity_rate = derived["vacuity_rate"]
    non_vacuous_satisfaction_rate = derived["non_vacuous_satisfaction_rate"]
    model_aggregates = derived["model_aggregates"]

    return {
        "available": True,
        "tool": "minerful_fitness_checker",
        "tool_version": minerful_jar_version(),
        "fitness_metrics": {
            "avg_fitness": avg_fitness,
            "trace_fit_ratio": trace_fit_ratio,
            "n_constraints_evaluated": n_constraints,
            "n_traces_evaluated": total_traces,
            "sum_full_satisfactions": sum_full_satisfactions,
            "sum_vacuous_satisfactions": sum_vacuous_satisfactions,
            "sum_violations": sum_violations,
            "vacuity_rate": vacuity_rate,
            "non_vacuous_satisfaction_rate": non_vacuous_satisfaction_rate,
        },
        "per_constraint": rows,
        "model_aggregates": model_aggregates,
        "raw_csv_path": str(output_csv_path),
        "raw_stdout": stdout,
        "raw_stderr": stderr,
        "fitness_check_notes": [],
        "fitness_runtime_sec": fitness_runtime_sec,
    }
