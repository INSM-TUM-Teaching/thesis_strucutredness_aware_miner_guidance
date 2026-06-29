"""Entropy-based precision via the Entropia tool (Polyvyanyy et al., 2020).

This module is the thesis's **primary BQ-2 indicator** wrapper. ETC-Precision
is retained as a secondary cross-check (see
``miners/imperative_miner/evaluation.py`` and the fusion miner's
``quality_metrics.etc_precision``). The motivation for the switch — ETC
producing vacuously-high values on Flower-fragments and τ-skip-heavy models —
is documented in the Obsidian vault (Methodology note "BQ-2 metric switch").

Reference:
    Polyvyanyy, A., Solti, A., Weidlich, M., Di Ciccio, C., Mendling, J.
    *Monotone Precision and Recall for Comparing Executions and
    Specifications of Dynamic Systems.* ACM TOSEM (2020).

The tool itself is a Java CLI shipped via the ``jbpt/codebase`` GitHub
project (subdirectory ``jbpt-pm/entropia/``). See ``tools/entropia/README.md``
for download instructions and the rationale for the classpath layout.

CLI invoked (silent mode, partial trace matching):

.. code-block:: text

    java -cp <classpath> org.jbpt.pm.tools.QualityMeasuresCLI \\
        -pmp -s -rel=<log.xes> -ret=<model.pnml>

The classpath is reconstructed from local artefacts only — the Eclipse
JarRsrcLoader fat JAR ``jbpt-pm-entropia-1.8.jar`` does not pass nested
``Rsrc-Class-Path`` entries through when invoked with ``java -cp``, so we
explicitly add each extracted dependency JAR plus the externals
(``AcceptingPetriNet.jar``, ``trove4j``, ``automaton``, ``eigenvalue``).

PNML preprocessing
==================

ProM's accepting-Petri-net PNML output is not directly Entropia-compatible.
The wrapper rewrites the PNML in two ways before invocation:

1. **Silent transitions.** ProM marks invisible transitions with
   ``toolspecific activity="$invisible$"`` but still writes a non-empty
   ``<name><text>tau from tree</text></name>``. Entropia treats any
   non-empty name as an observable label and therefore retains
   ``"tau from tree"`` as a visible symbol — the intersection with the
   log goes empty and precision collapses to ~0. We replace the name text
   with the empty string for invisible transitions.
2. **The ``+`` suffix.** ProM appends ``+`` to observable activity labels
   in the accepting-Petri-net PNML (so ``a`` in the log appears as ``a+``
   in the net). Without stripping, the model and log share no alphabet
   symbols and the language intersection is empty.

Both rewrites are confined to ``<transition>`` blocks via regex, so they
do not perturb ``<place>`` names that happen to share label text with
transitions.

Failure modes
=============

The function returns an :class:`EntropyPrecisionResult` for every input;
exceptions are caught and surfaced as ``status="failed"`` or ``"timeout"``
so that batch callers can continue processing other (miner, log) pairs.
``NaN`` is a valid Entropia output (e.g. when the model's reachable
language is empty after preprocessing) and is preserved as
``precision=float('nan')`` with ``status="success"`` — the caller is
responsible for downstream interpretation.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

from flex_compare.internal.shared.paths import PROJECT_ROOT as _REPO_ROOT

_ENTROPIA_DIR = _REPO_ROOT / "tools" / "entropia"
_PROM_PKGS = _REPO_ROOT / "tools" / "ProM" / "packages"

# Default JAR paths — overridable via env vars for reproducibility runs.
DEFAULT_ENTROPIA_JAR = _ENTROPIA_DIR / "jbpt-pm-entropia-1.8.jar"
DEFAULT_ENTROPIA_EXTRACTED = _ENTROPIA_DIR / "extracted"
DEFAULT_EIGENVALUE_JAR = _ENTROPIA_DIR / "eigenvalue-0.1.1.jar"

# These three live in the existing ProM/MINERful install; pinned versions
# match what the fusion miner reports in its package_versions manifest.
DEFAULT_ACCEPTING_PNET_JAR = (
    _PROM_PKGS / "acceptingpetrinet-6.11.196" / "AcceptingPetriNet.jar"
)
DEFAULT_TROVE_JAR = _PROM_PKGS / "basicutils-6.12.1" / "lib" / "trove4j-3.0.3.jar"
DEFAULT_AUTOMATON_JAR = (
    _PROM_PKGS / "declareminerful-6.9.76" / "lib" / "automaton-1.12-1.jar"
)

_ENTROPIA_MAIN_CLASS = "org.jbpt.pm.tools.QualityMeasuresCLI"
_DEFAULT_LOG_FILE = _REPO_ROOT / "results" / "entropy_precision.log"

# Default JVM heap. Entropia's eigenvalue computation is memory-heavy on
# larger logs; 4 GB matches the fusion miner's default and was sufficient
# for the structured/semi/loosely logs in the thesis dataset.
_DEFAULT_JVM_XMX = "4G"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EntropyPrecisionResult:
    """One Entropia invocation outcome.

    ``precision`` is ``None`` when the tool did not produce a parseable
    result; it can also be ``float('nan')`` when Entropia legitimately
    returns ``NaN`` (e.g. degenerate language intersection). Callers should
    distinguish the two via :func:`math.isnan`.
    """

    precision: Optional[float]
    mode: Literal["partial", "exact"]
    runtime_seconds: float
    tool_version: str
    jar_path: str
    cli_args: list[str]
    raw_stdout: str
    raw_stderr: str
    status: Literal["success", "failed", "timeout", "not_applicable"]
    failure_reason: Optional[str] = None
    pnml_path: Optional[str] = None
    xes_path: Optional[str] = None
    # Recall is supported by Entropia's -pmpr / -empr flags but BQ-2 only
    # needs precision. The field is reserved for future expansion.
    recall: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = asdict(self)
        # NaN is not JSON-serializable; emit as string so log files remain
        # parseable. Callers that need the float value should read
        # ``.precision`` directly, not the dict view.
        if isinstance(d.get("precision"), float) and math.isnan(d["precision"]):
            d["precision"] = "NaN"
        return d


# ---------------------------------------------------------------------------
# PNML preprocessing
# ---------------------------------------------------------------------------

_SILENT_ACTIVITY_TOKEN = '$invisible$'

# Match exactly the inner <name><text>...</text></name> of a single <transition>
# block. The DOTALL flag lets the inner content span newlines (some ProM
# exports pretty-print, others emit a single line). We deliberately avoid
# touching <place> name texts, which can share label text with transitions in
# the fusion miner's PNMLs (e.g. "a+ -[1]-> replacement source 2").
_TRANSITION_BLOCK_RE = re.compile(
    r"<transition\b[^>]*>.*?</transition>", re.DOTALL
)
_NAME_TEXT_RE = re.compile(
    r"(<name>\s*<text>)([^<]*)(</text>\s*</name>)", re.DOTALL
)


def _preprocess_pnml(src: Path, dst: Path) -> dict[str, int]:
    """Rewrite a ProM PNML for Entropia compatibility.

    Returns a small audit dict with ``silenced`` (count of invisible
    transitions normalized to empty labels) and ``stripped`` (count of
    visible transition labels whose trailing ``+`` was removed). The dict
    is logged alongside each Entropia invocation for transparency.
    """
    content = src.read_text(encoding="utf-8", errors="replace")
    counters: dict[str, int] = {"silenced": 0, "stripped": 0}

    def fix_transition(match: re.Match[str]) -> str:
        block = match.group(0)
        is_silent = _SILENT_ACTIVITY_TOKEN in block

        def fix_name(name_match: re.Match[str]) -> str:
            prefix, label, suffix = name_match.group(1), name_match.group(2), name_match.group(3)
            if is_silent:
                if label:
                    counters["silenced"] += 1
                return f"{prefix}{suffix}"
            if label.endswith("+"):
                counters["stripped"] += 1
                return f"{prefix}{label[:-1]}{suffix}"
            return name_match.group(0)

        return _NAME_TEXT_RE.sub(fix_name, block)

    fixed = _TRANSITION_BLOCK_RE.sub(fix_transition, content)
    dst.write_text(fixed, encoding="utf-8")
    return counters


# ---------------------------------------------------------------------------
# Classpath construction
# ---------------------------------------------------------------------------

class EntropiaSetupError(RuntimeError):
    """Raised when required JARs cannot be located on disk."""


def _build_classpath(
    *,
    jar_path: Path = DEFAULT_ENTROPIA_JAR,
    extracted_dir: Path = DEFAULT_ENTROPIA_EXTRACTED,
    eigenvalue_jar: Path = DEFAULT_EIGENVALUE_JAR,
    accepting_pnet_jar: Path = DEFAULT_ACCEPTING_PNET_JAR,
    trove_jar: Path = DEFAULT_TROVE_JAR,
    automaton_jar: Path = DEFAULT_AUTOMATON_JAR,
) -> list[str]:
    """Assemble the Entropia classpath from local artefacts.

    Raises :class:`EntropiaSetupError` if any required JAR is missing —
    callers should catch this and surface a clear message instead of
    letting a cryptic ``ClassNotFoundException`` propagate from Java.
    """
    missing: list[str] = []
    for required in (jar_path, eigenvalue_jar, accepting_pnet_jar, trove_jar, automaton_jar):
        if not required.is_file():
            missing.append(str(required))
    if not extracted_dir.is_dir():
        missing.append(f"{extracted_dir}/ (run: unzip jbpt-pm-entropia-*.jar -d <extracted_dir>)")

    if missing:
        raise EntropiaSetupError(
            "Entropia setup incomplete — missing artefacts:\n  - "
            + "\n  - ".join(missing)
            + "\nSee tools/entropia/README.md for download/extract steps."
        )

    extracted_jars = sorted(str(p) for p in extracted_dir.glob("*.jar"))
    # Order matters only insofar as Java picks the first matching class on
    # the classpath; we put the fat JAR first so its
    # QualityMeasuresCLI is found, then deps. trove/automaton/eigenvalue
    # last keeps shadowing risk minimal.
    return [
        str(jar_path),
        *extracted_jars,
        str(accepting_pnet_jar),
        str(trove_jar),
        str(automaton_jar),
        str(eigenvalue_jar),
    ]


def _tool_version_from_jar(jar_path: Path) -> str:
    """Extract the Entropia version from the JAR filename.

    We parse the filename rather than the tool's stdout banner because the
    banner is locale-dependent and the filename is the authoritative
    identifier used in the GitHub release directory.
    """
    m = re.search(r"jbpt-pm-entropia-([0-9.]+)\.jar$", jar_path.name)
    return m.group(1) if m else "unknown"


# ---------------------------------------------------------------------------
# Invocation logging
# ---------------------------------------------------------------------------

def _log_invocation(log_file: Path, payload: dict[str, Any]) -> None:
    """Append one JSON-line audit record per Entropia invocation.

    The log lives at ``results/entropy_precision.log`` by default. Each line
    is a self-contained JSON record so the file can be ingested via
    ``jq`` or ``pandas.read_json(..., lines=True)`` for reproducibility
    audits. Missing parent dirs are created lazily.
    """
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except OSError as exc:
        # Logging must never break the wrapper. A warning to stderr is the
        # most we can do; the caller still receives the full result object.
        logger.warning("Could not write entropy_precision log %s: %s", log_file, exc)


# ---------------------------------------------------------------------------
# stdout parsing
# ---------------------------------------------------------------------------

_PRECISION_LINE_RE = re.compile(r"Precision:\s*([0-9eE.+\-]+|NaN)\.?")


def _parse_precision(stdout: str, *, silent: bool) -> Optional[float]:
    """Extract the precision float from Entropia stdout.

    With ``-s``/silent mode the entire stdout is the value (one token —
    either a float literal or the word ``NaN``). Without silent mode the
    relevant value appears on a trailing ``Precision: <value>.`` line.
    Both forms are accepted so smoke-test runs (which omit ``-s`` for
    diagnostics) still parse.
    """
    stripped = stdout.strip()
    if silent and stripped:
        candidate = stripped.splitlines()[-1].strip().rstrip(".")
        if candidate.lower() == "nan":
            return float("nan")
        try:
            return float(candidate)
        except ValueError:
            pass  # fall through to the verbose-line search

    match = _PRECISION_LINE_RE.search(stdout)
    if not match:
        return None
    # The numeric character class is greedy and may consume the trailing
    # sentence-ending period that Entropia prints after the value
    # (``Precision: 0.42.``). Strip it before float-parsing.
    token = match.group(1).rstrip(".")
    if token.lower() == "nan":
        return float("nan")
    try:
        return float(token)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_entropy_precision(
    pnml_path: Path,
    xes_path: Path,
    *,
    jar_path: Path = DEFAULT_ENTROPIA_JAR,
    mode: Literal["partial", "exact"] = "partial",
    timeout_seconds: int = 300,
    silent: bool = True,
    log_file: Path = _DEFAULT_LOG_FILE,
    java_bin: str = "java",
    jvm_xmx: str = _DEFAULT_JVM_XMX,
) -> EntropyPrecisionResult:
    """Run Entropia on one (PNML, XES) pair and return a typed result.

    The function never raises; subprocess errors are returned as
    ``status="failed"`` so batch callers can continue with remaining
    pairs. ``status="not_applicable"`` is reserved for callers that want
    to record a pair as out-of-scope (e.g. declarative models, which have
    no PNML) via :func:`make_not_applicable`.

    Parameters
    ----------
    pnml_path : Path
        Discovered Petri net (ProM PNML format is supported via on-the-fly
        preprocessing — see module docstring).
    xes_path : Path
        Event log in XES.
    jar_path : Path
        Override for the Entropia fat JAR. The version string in the
        filename is propagated to ``EntropyPrecisionResult.tool_version``.
    mode : {"partial", "exact"}
        ``partial`` invokes ``-pmp`` (Polyvyanyy & Kalenkova ICPM 2019,
        polynomial); ``exact`` invokes ``-emp`` (Polyvyanyy et al. TOSEM
        2020, worst-case exponential). Default is ``partial`` — the
        recommended mode for batch evaluation.
    timeout_seconds : int
        Subprocess timeout. On expiry the result is returned with
        ``status="timeout"`` and the partial stdout (if any) preserved.
    silent : bool
        Pass ``-s`` to Entropia for terse numeric output. Disable only
        when diagnosing parser/preprocessor issues.
    log_file : Path
        JSON-lines audit log destination.
    """
    start = time.perf_counter()
    pnml_path = Path(pnml_path)
    xes_path = Path(xes_path)
    tool_version = _tool_version_from_jar(jar_path)

    if mode not in ("partial", "exact"):
        raise ValueError(f"mode must be 'partial' or 'exact', got {mode!r}")

    # --- Validate inputs early ---
    if not pnml_path.is_file():
        return _emit_failure(
            log_file, pnml_path, xes_path, jar_path, mode, tool_version,
            cli_args=[], start=start,
            reason=f"pnml_not_found: {pnml_path}",
        )
    if not xes_path.is_file():
        return _emit_failure(
            log_file, pnml_path, xes_path, jar_path, mode, tool_version,
            cli_args=[], start=start,
            reason=f"xes_not_found: {xes_path}",
        )

    # --- Build classpath ---
    try:
        classpath_entries = _build_classpath(jar_path=jar_path)
    except EntropiaSetupError as exc:
        return _emit_failure(
            log_file, pnml_path, xes_path, jar_path, mode, tool_version,
            cli_args=[], start=start,
            reason=f"setup_error: {exc}",
        )

    # --- Preprocess PNML in a temp file (caller's PNML is never mutated) ---
    with tempfile.NamedTemporaryFile(
        suffix=".pnml", prefix="entropia_", delete=False
    ) as tmp:
        preprocessed = Path(tmp.name)
    try:
        preprocess_counts = _preprocess_pnml(pnml_path, preprocessed)
    except (OSError, UnicodeError) as exc:
        preprocessed.unlink(missing_ok=True)
        return _emit_failure(
            log_file, pnml_path, xes_path, jar_path, mode, tool_version,
            cli_args=[], start=start,
            reason=f"pnml_preprocess_error: {exc}",
        )

    flag = "-pmp" if mode == "partial" else "-emp"
    cli_args = [
        java_bin,
        f"-Xmx{jvm_xmx}",
        "-cp",
        os.pathsep.join(classpath_entries),
        _ENTROPIA_MAIN_CLASS,
        flag,
        f"-rel={xes_path}",
        f"-ret={preprocessed}",
    ]
    if silent:
        cli_args.append("-s")

    stdout, stderr = "", ""
    try:
        completed = subprocess.run(
            cli_args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        runtime = time.perf_counter() - start

        if completed.returncode != 0:
            result = EntropyPrecisionResult(
                precision=None,
                mode=mode,
                runtime_seconds=runtime,
                tool_version=tool_version,
                jar_path=str(jar_path),
                cli_args=cli_args,
                raw_stdout=stdout,
                raw_stderr=stderr,
                status="failed",
                failure_reason=(
                    f"nonzero_exit: rc={completed.returncode}; "
                    f"stderr_head={stderr.strip().splitlines()[0] if stderr.strip() else '(empty)'}"
                ),
                pnml_path=str(pnml_path),
                xes_path=str(xes_path),
            )
        else:
            precision = _parse_precision(stdout, silent=silent)
            if precision is None:
                result = EntropyPrecisionResult(
                    precision=None,
                    mode=mode,
                    runtime_seconds=runtime,
                    tool_version=tool_version,
                    jar_path=str(jar_path),
                    cli_args=cli_args,
                    raw_stdout=stdout,
                    raw_stderr=stderr,
                    status="failed",
                    failure_reason="parse_error: no precision value in stdout",
                    pnml_path=str(pnml_path),
                    xes_path=str(xes_path),
                )
            else:
                result = EntropyPrecisionResult(
                    precision=precision,
                    mode=mode,
                    runtime_seconds=runtime,
                    tool_version=tool_version,
                    jar_path=str(jar_path),
                    cli_args=cli_args,
                    raw_stdout=stdout,
                    raw_stderr=stderr,
                    status="success",
                    pnml_path=str(pnml_path),
                    xes_path=str(xes_path),
                )
    except subprocess.TimeoutExpired as exc:
        runtime = time.perf_counter() - start
        # TimeoutExpired's stdout/stderr can be bytes or str depending on
        # Python version; normalize to str so the log file stays
        # JSON-line clean.
        def _to_text(b: object) -> str:
            if isinstance(b, (bytes, bytearray)):
                return b.decode("utf-8", errors="replace")
            if isinstance(b, str):
                return b
            return ""

        stdout = _to_text(exc.stdout)
        stderr = _to_text(exc.stderr)
        result = EntropyPrecisionResult(
            precision=None,
            mode=mode,
            runtime_seconds=runtime,
            tool_version=tool_version,
            jar_path=str(jar_path),
            cli_args=cli_args,
            raw_stdout=stdout,
            raw_stderr=stderr,
            status="timeout",
            failure_reason=f"timeout_after_{timeout_seconds}s",
            pnml_path=str(pnml_path),
            xes_path=str(xes_path),
        )
    except OSError as exc:
        runtime = time.perf_counter() - start
        result = EntropyPrecisionResult(
            precision=None,
            mode=mode,
            runtime_seconds=runtime,
            tool_version=tool_version,
            jar_path=str(jar_path),
            cli_args=cli_args,
            raw_stdout=stdout,
            raw_stderr=stderr,
            status="failed",
            failure_reason=f"subprocess_oserror: {exc}",
            pnml_path=str(pnml_path),
            xes_path=str(xes_path),
        )
    finally:
        preprocessed.unlink(missing_ok=True)

    _log_invocation(log_file, {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool_version": tool_version,
        "mode": mode,
        "pnml_path": str(pnml_path),
        "xes_path": str(xes_path),
        "preprocess_counts": preprocess_counts,
        "status": result.status,
        "precision": (
            "NaN" if result.precision is not None and math.isnan(result.precision)
            else result.precision
        ),
        "runtime_seconds": result.runtime_seconds,
        "failure_reason": result.failure_reason,
    })
    return result


def make_not_applicable(
    *,
    reason: str,
    mode: Literal["partial", "exact"] = "partial",
    pnml_path: Optional[Path] = None,
    xes_path: Optional[Path] = None,
    jar_path: Path = DEFAULT_ENTROPIA_JAR,
) -> EntropyPrecisionResult:
    """Build a ``status="not_applicable"`` result without running anything.

    Used by the batch runner for declarative (decl) pairs: MINERful emits
    a Declare constraint set (or its materialized DOT finite automaton),
    not a Petri net, so Entropia simply does not apply. Recording these
    pairs explicitly keeps the comparison table honest about coverage.
    """
    return EntropyPrecisionResult(
        precision=None,
        mode=mode,
        runtime_seconds=0.0,
        tool_version=_tool_version_from_jar(jar_path),
        jar_path=str(jar_path),
        cli_args=[],
        raw_stdout="",
        raw_stderr="",
        status="not_applicable",
        failure_reason=reason,
        pnml_path=str(pnml_path) if pnml_path else None,
        xes_path=str(xes_path) if xes_path else None,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _emit_failure(
    log_file: Path,
    pnml_path: Path,
    xes_path: Path,
    jar_path: Path,
    mode: Literal["partial", "exact"],
    tool_version: str,
    *,
    cli_args: list[str],
    start: float,
    reason: str,
) -> EntropyPrecisionResult:
    runtime = time.perf_counter() - start
    result = EntropyPrecisionResult(
        precision=None,
        mode=mode,
        runtime_seconds=runtime,
        tool_version=tool_version,
        jar_path=str(jar_path),
        cli_args=cli_args,
        raw_stdout="",
        raw_stderr="",
        status="failed",
        failure_reason=reason,
        pnml_path=str(pnml_path),
        xes_path=str(xes_path),
    )
    _log_invocation(log_file, {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool_version": tool_version,
        "mode": mode,
        "pnml_path": str(pnml_path),
        "xes_path": str(xes_path),
        "status": "failed",
        "precision": None,
        "runtime_seconds": runtime,
        "failure_reason": reason,
    })
    return result


# ---------------------------------------------------------------------------
# CLI: a small smoke-test driver
# ---------------------------------------------------------------------------

def _smoke_main() -> int:
    """Run a one-pair regression check.

    Pair: ``Log01_structured`` (fus) — chosen because it's the smallest
    structured log with a known ETC value of ~0.93. We expect entropy
    precision to land in the same Score-3 band (≥ 0.80); anything below
    that flags either a preprocessing regression or a JAR/classpath
    breakage in the environment.
    """
    log = _REPO_ROOT / "data" / "with-case-ids" / "Log01_structured.xes"
    model = (
        _REPO_ROOT
        / "Experimente"
        / "structured"
        / "Log01_structured"
        / "fusionminerful"
        / "assets"
        / "raw"
        / "model.pnml"
    )
    if not log.is_file() or not model.is_file():
        print(f"smoke test inputs missing:\n  log={log}\n  model={model}", file=sys.stderr)
        return 2

    result = compute_entropy_precision(model, log, mode="partial", silent=True)
    print(json.dumps(result.to_dict(), indent=2, default=str))
    if result.status != "success":
        return 1
    if result.precision is None or math.isnan(result.precision) or result.precision < 0.80:
        print(
            f"smoke test failed: expected precision >= 0.80, got {result.precision}",
            file=sys.stderr,
        )
        return 1
    print(f"smoke OK: partial entropy precision = {result.precision}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "smoke":
        raise SystemExit(_smoke_main())
    print(
        "usage: python -m miners.shared.entropy_precision smoke",
        file=sys.stderr,
    )
    raise SystemExit(2)
