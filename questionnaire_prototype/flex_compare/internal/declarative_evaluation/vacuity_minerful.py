"""Optional MINERful Java-bridge.

``non_vacuous_satisfaction_rate`` and ``vacuity_rate`` are NO LONGER sourced
from a separate Java vacuity checker. Both are derived — from one source, on
one constraint basis — by :mod:`minerful_fitness` out of the
``MinerFulFitnessCheckStarter`` per-constraint ``FullSatisfactions`` counts
over the discovered, post-pruning constraint set. Use
:func:`non_vacuous_satisfaction_rate_from_fitness` to read the rate off a
fitness result.

Why the Java vacuity checker was retired: ``minerful.MinerFulVacuityChecker``
is, per its own usage banner, proof-of-concept code ("not yet part of the
MINERful framework … use it for testing purposes only"). It (a) checks a
*hard-coded* set of placeholder-activity constraints (``SequenceResponse21(a,
b,x)``, ``AtLeast1(a)``, ``Init(a)``, ``End(a)``) — NOT the discovered
constraint set, so it can never satisfy the canonical reference-set
definition; and (b) cannot parse our XES logs: its
``XesLogParser(LOG_SPECIFIED)`` throws, the ``catch`` falls back to a
``StringLogParser`` that reads the raw XML text character-by-character, and the
run dies with a ``NullPointerException`` at
``ConstraintsFitnessEvaluator.runOnLog`` (confirmed on real logs). It is not
Python-fixable. :func:`run_vacuity_check` therefore raises loudly instead of
silently returning ``None``.

:func:`run_fitness_check` (independent fitness cross-check via
``minerful.MinerFulFitnessCheckStarter``) is unaffected and still defensive.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from flex_compare.internal.shared.paths import PROJECT_ROOT

DEFAULT_MINERFUL_HOME = str(PROJECT_ROOT / "tools" / "MINERful")
_TIMEOUT_SECONDS = 120


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


def minerful_available() -> bool:
    home = _resolve_home()
    if not home.is_dir():
        return False
    if not (home / "MINERful.jar").is_file() and not (home / "bin").is_dir():
        return False
    return True


def minerful_version() -> str | None:
    if not minerful_available():
        return None
    jar = _jar_path()
    if jar.is_file():
        try:
            h = hashlib.sha256(jar.read_bytes()).hexdigest()
            return f"sha256:{h[:16]}"
        except Exception:
            return None
    return None


def _run_java(
    main_class: str,
    args: List[str],
    *,
    cwd: Path | None = None,
) -> Dict[str, Any]:
    if not minerful_available():
        return {"available": False, "error": "MINERful not available", "raw_stdout": "", "raw_stderr": ""}

    cp = _classpath()
    if not cp:
        return {"available": False, "error": "empty classpath", "raw_stdout": "", "raw_stderr": ""}

    cmd = ["java", "-Xmx4G", "-classpath", cp, main_class, *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            cwd=str(cwd or _resolve_home()),
            check=False,
        )
    except FileNotFoundError as exc:
        return {"available": False, "error": f"java binary not found: {exc}", "raw_stdout": "", "raw_stderr": ""}
    except subprocess.TimeoutExpired as exc:
        return {"available": False, "error": f"timeout after {_TIMEOUT_SECONDS}s", "raw_stdout": exc.stdout or "", "raw_stderr": exc.stderr or ""}
    except Exception as exc:
        return {"available": False, "error": f"subprocess failed: {exc}", "raw_stdout": "", "raw_stderr": ""}

    return {
        "available": proc.returncode == 0,
        "returncode": proc.returncode,
        "raw_stdout": proc.stdout or "",
        "raw_stderr": proc.stderr or "",
        "error": None if proc.returncode == 0 else f"exit code {proc.returncode}",
    }


def _try_parse_json(text: str) -> Any | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    for line in text.splitlines()[::-1]:
        line = line.strip()
        if line.startswith("{") or line.startswith("["):
            try:
                return json.loads(line)
            except Exception:
                continue
    return None


_VACUITY_LINE_RE = re.compile(
    r"(?P<template>[A-Za-z]+)\s*\(?\[?\s*(?P<params>[^\]\)]+)\]?\)?\s*[:=]\s*(?P<status>[A-Za-z\-\s]+)"
)
_RATE_RE = re.compile(r"non[-_\s]?vacuous(?:ly)?[^\d]*([0-9]*\.?[0-9]+)", re.IGNORECASE)


def _parse_vacuity_output(stdout: str) -> Dict[str, Any]:
    parsed = _try_parse_json(stdout)
    per_constraint: List[Dict[str, Any]] = []
    non_vacuous_rate: float | None = None

    if isinstance(parsed, dict):
        items = (
            parsed.get("constraints")
            or parsed.get("vacuity")
            or parsed.get("results")
            or parsed.get("items")
        )
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = item.get("constraint") or item.get("name") or item.get("template")
                status = item.get("status") or item.get("state")
                non_vac = item.get("non_vacuous")
                if non_vac is None and isinstance(status, str):
                    non_vac = "non" in status.lower() and "vac" in status.lower()
                per_constraint.append({"constraint": str(name), "non_vacuous": bool(non_vac), "status": status})
        rate_val = parsed.get("non_vacuous_satisfaction_rate") or parsed.get("nonVacuousRate")
        if isinstance(rate_val, (int, float)):
            non_vacuous_rate = float(rate_val)

    if not per_constraint:
        for line in stdout.splitlines():
            m = _VACUITY_LINE_RE.search(line)
            if not m:
                continue
            status = m.group("status").strip().lower()
            non_vac = "non" in status and "vac" in status
            per_constraint.append(
                {
                    "constraint": f"{m.group('template')}[{m.group('params').strip()}]",
                    "non_vacuous": bool(non_vac),
                    "status": status,
                }
            )

    if non_vacuous_rate is None:
        m = _RATE_RE.search(stdout)
        if m:
            try:
                val = float(m.group(1))
                non_vacuous_rate = val if val <= 1.0 else val / 100.0
            except Exception:
                pass

    if non_vacuous_rate is None and per_constraint:
        total = len(per_constraint)
        if total:
            non_vacuous_rate = sum(1 for c in per_constraint if c["non_vacuous"]) / total

    return {
        "non_vacuous_satisfaction_rate": non_vacuous_rate,
        "per_constraint": per_constraint,
    }


_FITNESS_RE = re.compile(
    r"fitness[^\d\n]*?([0-9]*\.?[0-9]+)", re.IGNORECASE
)


def _parse_fitness_output(stdout: str) -> Dict[str, Any]:
    parsed = _try_parse_json(stdout)
    fitness: float | None = None
    if isinstance(parsed, dict):
        for key in ("fitness", "log_fitness", "trace_fitness"):
            val = parsed.get(key)
            if isinstance(val, (int, float)):
                fitness = float(val)
                break

    if fitness is None:
        for line in stdout.splitlines()[::-1]:
            m = _FITNESS_RE.search(line)
            if m:
                try:
                    fitness = float(m.group(1))
                except Exception:
                    continue
                break

    return {"fitness": fitness}


def non_vacuous_satisfaction_rate_from_fitness(
    fitness_result: Dict[str, Any] | None,
) -> float | None:
    """Read ``non_vacuous_satisfaction_rate`` off a fitness-check result.

    This is the canonical, single source for the rate: it is derived by
    :mod:`minerful_fitness` from the ``MinerFulFitnessCheckStarter``
    per-constraint ``FullSatisfactions`` counts, on the discovered
    post-pruning constraint set — the same basis (and the algebraic complement
    ``1 - vacuity_rate``) as ``vacuity_rate``. Returns ``None`` only when the
    fitness check itself did not run / produced no constraints (a failure
    already surfaced via the fitness result's ``fitness_check_notes``); it
    never fabricates a value.
    """
    if not fitness_result:
        return None
    return (fitness_result.get("fitness_metrics") or {}).get(
        "non_vacuous_satisfaction_rate"
    )


def run_vacuity_check(log_path: Path, decl_path: Path | None = None) -> Dict[str, Any]:
    """Retired. The Java vacuity POC is unusable on our logs and on the wrong
    constraint basis — see the module docstring. Raises loudly rather than
    silently returning ``None``; use
    :func:`non_vacuous_satisfaction_rate_from_fitness` instead."""
    raise RuntimeError(
        "minerful.MinerFulVacuityChecker is a proof-of-concept that checks "
        "hard-coded placeholder constraints and crashes (NullPointerException) "
        "on XES logs; non_vacuous_satisfaction_rate is now derived from the "
        "MinerFulFitnessCheckStarter result. Call "
        "non_vacuous_satisfaction_rate_from_fitness(fitness_result) instead."
    )


def run_fitness_check(log_path: Path, decl_path: Path) -> Dict[str, Any]:
    raw = _run_java(
        "minerful.MinerFulFitnessCheckStarter",
        ["-iLF", str(log_path), "-iMF", str(decl_path)],
    )
    if not raw["available"]:
        return {"available": False, "error": raw.get("error"), "raw_stdout": raw.get("raw_stdout", "")}

    parsed = _parse_fitness_output(raw["raw_stdout"])
    return {
        "available": True,
        "fitness": parsed["fitness"],
        "raw_stdout": raw["raw_stdout"],
    }
