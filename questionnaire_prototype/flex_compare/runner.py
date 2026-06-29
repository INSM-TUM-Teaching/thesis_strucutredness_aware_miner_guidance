"""Dispatch a :class:`MinerInstance` through the right adapter and cache the result.

Cache slot = ``"<type_id>__<stable_config_hash>"``: identical config under the
same registered ``MinerSpec.id`` (or inline-spec label) maps to the same
on-disk slot, so removing and re-adding a card with the same sliders is an
instant cache-hit. The hash is sha1 over a sort-keyed JSON dump so it stays
stable across Python processes (PYTHONHASHSEED-immune).

Every dispatch returns a :class:`RunOutcome` with a discriminator status the
UI maps to a status pill (``ok`` | ``timeout`` | ``nonzero`` |
``output_missing`` | ``parse_error``). Failures attach an ``error_summary``
plus an ``exec_log_path`` when the executable path produced one.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

from flex_compare.internal.shared.cache import result_cache
from flex_compare.internal.shared.registry import miner_registry
from flex_compare.internal.shared.registry.param_schema import ParamSpec
from flex_compare.internal.shared.paths import PROJECT_ROOT

from flex_compare import format_import
from flex_compare.format_import import ExecError
from flex_compare.state import MinerInstance


logger = logging.getLogger(__name__)


DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / ".flex_compare" / "runs"


# ── Cache key ────────────────────────────────────────────────────────────────
def stable_config_hash(config: dict) -> str:
    """Deterministic 8-char hex digest of ``config`` (PYTHONHASHSEED-immune)."""
    payload = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def slot_id(type_id: str, config: dict) -> str:
    """Cache slot for a ``(type, config)`` pair — ``<type>__<cfg_hash>``."""
    return f"{type_id}__{stable_config_hash(config)}"


def _type_id(instance: MinerInstance) -> str:
    """The stable ``type_id`` part of the cache slot.

    Registry-backed instances use the ``MinerSpec.id``; inline custom miners
    use a slugified version of the inline label so two ``custom-exec`` miners
    with different scripts never collide on the same slot.
    """
    if instance.spec_source == "registry":
        return instance.spec_id or "unknown"
    if instance.inline_spec:
        slug = "".join(
            c if c.isalnum() else "_" for c in instance.inline_spec.label.lower()
        ).strip("_") or "custom"
        return f"custom-{instance.inline_spec.runner_kind}-{slug}"
    return "unknown"


def _resolve_paradigm(instance: MinerInstance) -> str:
    if instance.spec_source == "registry":
        spec = miner_registry.get(instance.spec_id or "")
        return spec.paradigm if spec else ""
    if instance.inline_spec:
        return instance.inline_spec.paradigm
    return ""


# ── RunOutcome ───────────────────────────────────────────────────────────────
RunStatus = Literal["ok", "timeout", "nonzero", "output_missing", "parse_error", "cancelled"]


@dataclass(frozen=True)
class RunOutcome:
    status: RunStatus
    result: Optional[dict]
    error_summary: Optional[str] = None
    command: Optional[list] = None
    exec_log_path: Optional[Path] = None
    cache_hit: bool = False


def _import_entry_point(entry_point: str):
    """Resolve ``"module:function"`` → callable."""
    module_path, _, func_name = entry_point.partition(":")
    if not module_path or not func_name:
        raise ValueError(f"invalid entry_point {entry_point!r} — expected 'module:function'")
    module = importlib.import_module(module_path)
    func = getattr(module, func_name, None)
    if func is None:
        raise AttributeError(f"{module_path}.{func_name} not found")
    return func


# ── Dispatch ─────────────────────────────────────────────────────────────────
def run_instance(
    instance: MinerInstance,
    log_path: Path,
    output_root: Optional[Path] = None,
    force: bool = False,
    on_started=None,
    cancel_check=None,
) -> RunOutcome:
    """Run (or rehydrate from cache) one miner instance against ``log_path``.

    ``on_started(popen)`` is invoked once for executable-dispatch instances as
    soon as the subprocess has been spawned, so the UI can store a handle for
    cancellation. ``cancel_check()`` returns ``True`` if the run should be
    terminated; the executable loop polls it once per second.
    """
    log_path = Path(log_path)
    if not log_path.is_file():
        return RunOutcome(
            status="parse_error",
            result=None,
            error_summary=f"log file not found: {log_path}",
        )

    output_root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
    output_root.mkdir(parents=True, exist_ok=True)

    type_id = _type_id(instance)
    slot = slot_id(type_id, instance.config)
    log_id = result_cache.compute_log_id(log_path)

    if not force:
        hit = result_cache.lookup(slot, log_id)
        if hit is not None:
            try:
                return RunOutcome(
                    status="ok",
                    result=result_cache.rehydrate(hit),
                    cache_hit=True,
                )
            except Exception as exc:  # rehydrate failure should not block re-run
                logger.warning("cache rehydrate failed for %s/%s: %s", slot, log_id, exc)

    # Dispatch
    runner_kind = _resolve_runner_kind(instance)
    if runner_kind == "module":
        outcome = _dispatch_module(instance, log_path, output_root / slot)
    else:
        outcome = _dispatch_executable(instance, log_path, output_root / slot,
                                        on_started=on_started, cancel_check=cancel_check)

    if outcome.status != "ok" or outcome.result is None:
        return outcome

    try:
        result_cache.store(slot, log_id, outcome.result, source_log_path=str(log_path))
        rehydrated = result_cache.rehydrate(result_cache.lookup(slot, log_id))
    except Exception as exc:
        logger.warning("cache store failed for %s/%s: %s", slot, log_id, exc)
        rehydrated = outcome.result

    return RunOutcome(status="ok", result=rehydrated, cache_hit=False)


def _resolve_runner_kind(instance: MinerInstance) -> str:
    if instance.spec_source == "registry":
        spec = miner_registry.get(instance.spec_id or "")
        return spec.runner_kind if spec else "module"
    if instance.inline_spec:
        return instance.inline_spec.runner_kind
    return "module"


def _resolve_schema_for(instance: MinerInstance) -> tuple[ParamSpec, ...]:
    if instance.spec_source == "registry":
        spec = miner_registry.get(instance.spec_id or "")
        return spec.config_schema if spec else ()
    if instance.inline_spec:
        return instance.inline_spec.config_schema
    return ()


def _bundle_config_for_adapter(config: dict, schema: tuple[ParamSpec, ...]) -> dict:
    """Reshape ``config`` into adapter-call kwargs honouring ``ParamSpec.kwarg_bundle``.

    Schema entries with ``kwarg_bundle=None`` stay flat at the top level.
    Entries that share a non-``None`` ``kwarg_bundle`` are collected into a
    nested dict passed under that single kwarg. Config keys that have no
    matching ParamSpec stay flat (free-form inline ``config`` survives).
    """
    if not schema:
        return dict(config)
    bundled: dict[str, dict] = {}
    flat: dict = {}
    by_key = {p.key: p for p in schema}
    for key, value in config.items():
        spec = by_key.get(key)
        if spec and spec.kwarg_bundle:
            bundled.setdefault(spec.kwarg_bundle, {})[key] = value
        else:
            flat[key] = value
    flat.update(bundled)
    return flat


def _dispatch_module(instance: MinerInstance, log_path: Path, run_dir: Path) -> RunOutcome:
    if instance.spec_source == "registry":
        spec = miner_registry.get(instance.spec_id or "")
        if spec is None or not spec.entry_point:
            return RunOutcome(
                status="parse_error",
                result=None,
                error_summary=f"registry spec {instance.spec_id!r} has no entry_point",
            )
        entry_point = spec.entry_point
    else:
        if not instance.inline_spec or not instance.inline_spec.entry_point:
            return RunOutcome(
                status="parse_error",
                result=None,
                error_summary="inline custom-module spec has no entry_point",
            )
        entry_point = instance.inline_spec.entry_point

    try:
        func = _import_entry_point(entry_point)
    except (ImportError, AttributeError, ValueError) as exc:
        return RunOutcome(
            status="parse_error",
            result=None,
            error_summary=f"{type(exc).__name__}: {exc}",
        )

    schema = _resolve_schema_for(instance)
    adapter_kwargs = _bundle_config_for_adapter(instance.config, schema)

    # Inject registry-pinned kwargs (e.g. ``algorithm="heuristics"``) so one
    # shared adapter can back N registry entries — one per algorithm — without
    # N wrapper functions.
    if instance.spec_source == "registry":
        spec = miner_registry.get(instance.spec_id or "")
        if spec is not None:
            for key, value in spec.fixed_kwargs or ():
                adapter_kwargs.setdefault(key, value)

    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = func(
            log_path=str(log_path),
            output_root=str(run_dir),
            run_id=run_dir.name,
            bearbeiter="flex",
            export_pdf=False,
            preprocessing_note="",
            **adapter_kwargs,
        )
    except TypeError as exc:
        # Most commonly an adapter-signature mismatch — keep the trace short.
        return RunOutcome(
            status="parse_error",
            result=None,
            error_summary=f"adapter signature mismatch: {exc}",
        )
    except Exception as exc:
        return RunOutcome(
            status="parse_error",
            result=None,
            error_summary=f"{type(exc).__name__}: {exc}",
        )

    if not isinstance(result, dict):
        return RunOutcome(
            status="parse_error",
            result=None,
            error_summary=f"adapter returned {type(result).__name__}, expected dict",
        )
    if result.get("status") == "error":
        return RunOutcome(
            status="parse_error",
            result=None,
            error_summary=result.get("error_message") or "adapter reported status=error",
        )
    return RunOutcome(status="ok", result=result)


def _dispatch_executable(instance: MinerInstance, log_path: Path, run_dir: Path,
                          on_started=None, cancel_check=None) -> RunOutcome:
    if not instance.inline_spec:
        return RunOutcome(
            status="parse_error", result=None,
            error_summary="executable dispatch requires an inline_spec",
        )
    spec = instance.inline_spec
    if not spec.command_template or not spec.output_format or not spec.output_pattern:
        return RunOutcome(
            status="parse_error", result=None,
            error_summary="inline custom-exec spec missing command_template/output_format/output_pattern",
        )

    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        exec_result = format_import.run_executable(
            spec.command_template,
            instance.config,
            log_path,
            run_dir,
            timeout_sec=instance.timeout_sec,
            on_started=on_started,
            cancel_check=cancel_check,
        )
    except ExecError as exc:
        return RunOutcome(
            status=exc.status,
            result=None,
            error_summary=exc.summary,
            exec_log_path=exc.exec_log_path,
        )

    artifact_path = run_dir / spec.output_pattern
    if not artifact_path.is_file():
        return RunOutcome(
            status="output_missing",
            result=None,
            error_summary=f"{spec.output_pattern!r} not found in outdir",
            command=exec_result.command,
            exec_log_path=exec_result.exec_log_path,
        )

    try:
        result = format_import.import_by_format(
            spec.output_format,
            artifact_path,
            log_path,
            output_dir=run_dir,
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError, Exception) as exc:
        return RunOutcome(
            status="parse_error",
            result=None,
            error_summary=f"{type(exc).__name__}: {exc}",
            command=exec_result.command,
            exec_log_path=exec_result.exec_log_path,
        )

    result.setdefault("_imported", True)
    return RunOutcome(
        status="ok",
        result=result,
        command=exec_result.command,
        exec_log_path=exec_result.exec_log_path,
    )


# ── Metric extraction helper for the UI ──────────────────────────────────────
def extract_metrics(instance: MinerInstance, result: dict) -> dict:
    """Flat metric dict for a finished instance, marking imports as such."""
    from flex_compare.internal.shared.metrics.metric_proxies import extract_metrics_by_paradigm

    paradigm = _resolve_paradigm(instance)
    source = "imported" if result.get("_imported") else "native"
    metrics = extract_metrics_by_paradigm(paradigm, result, source=source)
    return metrics
