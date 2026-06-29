"""Per-log disk cache for miner results + per-log survey persistence.

Layout under ``<repo>/.miner_cache/``::

    results/
      <log_id>/
        <miner>/
          result_data.json   # full UI-rehydrate payload, JSON-safe
          parameters.json    # redundant copy of the parameters subdict
          cache_meta.json    # {log_id, miner, stored_at, source_log_path,
                             #  source_log_stem, cache_version}
          artifacts/         # copied artifact files (markdown, pngs, pdf, …)
    surveys/
      <log_id>.json          # qualitative survey state, explicit-save only

`log_id` is `f"{sanitize(stem)}__{sha1(file_bytes)[:8]}"` to avoid stem
collisions between logs that happen to share a filename.

The ``MINERS`` membership set is the canonical registry's ``miner_ids()`` and
controls which slots ``iter_cached_results`` walks. ``store``/``lookup`` no
longer enforce membership: flex_compare creates additional slots of the form
``"<type>__<cfg_hash>"`` per configured instance, which would not be valid
``MinerSpec`` ids but still belong in the cache. Legacy comparison_app calls
pass one of the registered ids and behave unchanged.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from flex_compare.internal.shared.paths import PROJECT_ROOT
from flex_compare.internal.shared.registry import miner_registry

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
CACHE_VERSION = 1

_DEFAULT_CACHE_ROOT = PROJECT_ROOT / ".miner_cache"

_RESULTS_SUBDIR = "results"
_SURVEYS_SUBDIR = "surveys"
_CHARACTERISTIC_EVAL_SUBDIR = "characteristic_eval"
_ARTIFACTS_SUBDIR = "artifacts"

_RESULT_DATA_FILE = "result_data.json"
_PARAMETERS_FILE = "parameters.json"
_CACHE_META_FILE = "cache_meta.json"
_MARKDOWN_FILENAME = "ergebnisbericht.md"

# Membership/iteration set of *registered* miners — derived from the central
# registry so a new built-in miner is registered in one place. Used by
# ``iter_cached_results`` to skip foreign slots. ``store``/``lookup`` accept
# any non-empty string so flex_compare can park per-instance slots
# (``"<type>__<cfg_hash>"``) here without polluting the registry.
MINERS = miner_registry.miner_ids()

# Allowlist of result-dict keys whose values are filesystem paths to artifacts
# that must be copied into the cache. Tuples denote nested-dict lookups
# (analogue to comparison_app/app.py:_SURVEY_IMAGE_KEYS).
ARTIFACT_PATH_KEYS: dict[str, list[Any]] = {
    "imp": [
        "markdown_path",
        "data_path",
        "pdf_path",
        "petri_net_path",
        "petri_net_pnml_path",
        "process_tree_path",
        "bpmn_path",
    ],
    "decl": [
        "markdown_path",
        "data_path",
        "pdf_path",
        "declare_visualization_path",
        "declare_visualization_png_path",
        # MINERful constraint spec the SF-2 ARM-coverage reads — cached so the
        # coverage survives regeneration/cleanup of the original Experimente file.
        ("metrics", "json_path"),
    ],
    "fus": [
        "markdown_path",
        "data_path",
        "pdf_path",
        ("run_data", "hybrid_rendered_png_path"),
        ("run_data", "pnwa_rendered_png_path"),
        # Model JSONs the SF-2 ARM-coverage reads (PNWA net preferred) — cached so
        # the coverage survives regeneration/cleanup of the originals.
        ("run_data", "hybrid_model_path"),
        ("run_data", "pnwa_model_path"),
    ],
    # The pm4py family is registered per-algorithm now (pm4-heuristics,
    # pm4-alpha, …) and each spec carries its own ``artifact_keys`` —
    # ``_resolve_artifact_keys`` honours ``MinerSpec.artifact_keys`` so we
    # don't need a per-algorithm entry here.
}

# Default artifact-key allowlist for slots created by flex_compare instances.
# Paradigm-driven: a slot whose ``type_id`` (the prefix before ``__``) is not in
# ``ARTIFACT_PATH_KEYS`` falls back to one of these by ``runner.spec.paradigm``.
ARTIFACT_PATH_KEYS_BY_PARADIGM: dict[str, list[Any]] = {
    "imperativ": list(ARTIFACT_PATH_KEYS["imp"]),
    "deklarativ": list(ARTIFACT_PATH_KEYS["decl"]),
    "hybrid": list(ARTIFACT_PATH_KEYS["fus"]),
}

# ── Module-level state ───────────────────────────────────────────────────────
_lock = threading.Lock()
# (resolved_path_str, mtime_ns, size_bytes) -> short_hash
_log_hash_cache: dict[tuple[str, int, int], str] = {}
_cache_root_override: Optional[Path] = None


# ── Public configuration helpers ─────────────────────────────────────────────
def set_cache_root(path: Optional[Path]) -> None:
    """Override the cache root. Pass ``None`` to revert to the default.

    Intended for tests; production code should rely on the default.
    """
    global _cache_root_override
    _cache_root_override = Path(path) if path is not None else None
    _log_hash_cache.clear()


def cache_root() -> Path:
    return _cache_root_override or _DEFAULT_CACHE_ROOT


def _results_root() -> Path:
    return cache_root() / _RESULTS_SUBDIR


def _surveys_root() -> Path:
    return cache_root() / _SURVEYS_SUBDIR


def _characteristic_eval_root() -> Path:
    return cache_root() / _CHARACTERISTIC_EVAL_SUBDIR


# ── log_id ───────────────────────────────────────────────────────────────────
_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _sanitize(text: str) -> str:
    cleaned = _SANITIZE_RE.sub("_", text or "").strip("_")
    return cleaned or "log"


def _short_hash(log_path: Path) -> str:
    resolved = log_path.resolve()
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise FileNotFoundError(f"log file not accessible: {resolved}") from exc

    key = (str(resolved), stat.st_mtime_ns, stat.st_size)
    cached = _log_hash_cache.get(key)
    if cached is not None:
        return cached

    digest = hashlib.sha1(resolved.read_bytes()).hexdigest()[:8]
    _log_hash_cache[key] = digest
    return digest


def compute_log_id(log_path: Path) -> str:
    """Stable id for a log file. Stems collide; content hashes don't."""
    p = Path(log_path)
    stem = _sanitize(p.stem)
    return f"{stem}__{_short_hash(p)}"


# ── Atomic store / cleanup ───────────────────────────────────────────────────
@dataclass(frozen=True)
class CachedRun:
    miner: str
    log_id: str
    dir: Path

    @property
    def result_data_path(self) -> Path:
        return self.dir / _RESULT_DATA_FILE

    @property
    def parameters_path(self) -> Path:
        return self.dir / _PARAMETERS_FILE

    @property
    def meta_path(self) -> Path:
        return self.dir / _CACHE_META_FILE

    @property
    def artifacts_dir(self) -> Path:
        return self.dir / _ARTIFACTS_SUBDIR


def _miner_dir(log_id: str, miner: str) -> Path:
    return _results_root() / log_id / miner


def _cleanup_orphans() -> None:
    """Delete leftover ``*.tmp-*`` and ``*.old-*`` directories."""
    root = _results_root()
    if not root.exists():
        return
    for log_dir in root.iterdir():
        if not log_dir.is_dir():
            continue
        for entry in log_dir.iterdir():
            name = entry.name
            if (".tmp-" in name or ".old-" in name) and entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)


_orphan_cleanup_done = False


def _ensure_orphan_cleanup() -> None:
    global _orphan_cleanup_done
    if _orphan_cleanup_done:
        return
    with _lock:
        if _orphan_cleanup_done:
            return
        try:
            _cleanup_orphans()
        finally:
            _orphan_cleanup_done = True


def _is_jsonable(value: Any) -> bool:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_jsonable(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_jsonable(v) for k, v in value.items())
    return False


def _strip_unjsonable(value: Any) -> Any:
    """Return a JSON-safe deep copy. Bytes/Path/etc. become strings or are dropped."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                continue
            cleaned = _strip_unjsonable(v)
            if isinstance(v, (bytes, bytearray)):
                continue
            out[k] = cleaned
        return out
    if isinstance(value, (list, tuple, set)):
        return [_strip_unjsonable(v) for v in value if not isinstance(v, (bytes, bytearray))]
    return str(value)


def _get_nested(obj: Any, path: Any) -> Optional[str]:
    if isinstance(path, str):
        if isinstance(obj, dict):
            value = obj.get(path)
        else:
            return None
    elif isinstance(path, (tuple, list)):
        value = obj
        for key in path:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
    else:
        return None
    if value is None:
        return None
    text = str(value)
    return text or None


def _set_nested(obj: dict, path: Any, value: Optional[str]) -> None:
    if isinstance(path, str):
        if value is None:
            obj.pop(path, None)
        else:
            obj[path] = value
        return
    if not isinstance(path, (tuple, list)) or not path:
        return
    cursor = obj
    for key in path[:-1]:
        nxt = cursor.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[key] = nxt
        cursor = nxt
    last = path[-1]
    if value is None:
        cursor.pop(last, None)
    else:
        cursor[last] = value


def _copy_artifact(src_path: str, dest_root: Path, artifacts_dir: Path) -> Optional[str]:
    """Copy file at src_path into ``artifacts_dir`` and return its path
    relative to ``dest_root``. Returns ``None`` on missing/error."""
    try:
        src = Path(src_path)
    except Exception as exc:
        logger.warning("artifact path coercion failed for %r: %s", src_path, exc)
        return None
    if not src.is_file():
        return None
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    dest = artifacts_dir / src.name
    if dest.exists():
        # Disambiguate by uuid suffix to avoid collisions between miners.
        dest = artifacts_dir / f"{src.stem}-{uuid.uuid4().hex[:8]}{src.suffix}"
    shutil.copy2(src, dest)
    try:
        return str(dest.relative_to(dest_root))
    except ValueError:
        return str(dest)


def _resolve_artifact_keys(miner: str) -> list[Any]:
    """Artifact-key allowlist for ``miner``.

    Resolution order:
      1. Legacy per-miner dict (``imp`` / ``decl`` / ``fus`` / ``pm4``).
      2. flex_compare slot prefix (``"<type>__<cfg_hash>"`` → ``<type>``).
      3. ``MinerSpec.artifact_keys`` from the registry — each pm4py-* entry
         declares its own artifact set (``declare_model_json_path`` for the
         declarative algos, ``petri_net_path`` for the Petri-net algos).
      4. Paradigm-derived default (matches MinerSpec.paradigm against the
         imp/decl/fus paradigm tables — last-ditch generic shape).
    """
    if miner in ARTIFACT_PATH_KEYS:
        return ARTIFACT_PATH_KEYS[miner]
    type_id = miner.split("__", 1)[0]
    if type_id in ARTIFACT_PATH_KEYS:
        return ARTIFACT_PATH_KEYS[type_id]
    spec = miner_registry.get(type_id)
    if spec is not None:
        if spec.artifact_keys:
            return list(spec.artifact_keys)
        paradigm_keys = ARTIFACT_PATH_KEYS_BY_PARADIGM.get(spec.paradigm)
        if paradigm_keys:
            return paradigm_keys
    return []


def store(miner: str, log_id: str, result: dict, *, source_log_path: Optional[str] = None) -> CachedRun:
    """Atomically (over)write the cache entry for ``(miner, log_id)``.

    Side effect: copies allowed artifact files into ``<entry>/artifacts/``
    and rewrites the corresponding result-dict path fields to point at the
    cached copies. The on-disk ``result_data.json`` reflects the rewritten
    paths; the input ``result`` dict is **not** mutated.
    """
    if not miner:
        raise ValueError("miner must be a non-empty string")
    if not log_id:
        raise ValueError("log_id must be a non-empty string")
    if not isinstance(result, dict):
        raise TypeError("result must be a dict")

    _ensure_orphan_cleanup()

    target = _miner_dir(log_id, miner)
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)

    suffix = uuid.uuid4().hex[:8]
    tmp_dir = parent / f"{miner}.tmp-{suffix}"
    old_dir = parent / f"{miner}.old-{suffix}"

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True)
    artifacts_dir = tmp_dir / _ARTIFACTS_SUBDIR
    artifacts_dir.mkdir()

    rewritten = deepcopy(result)
    rewritten = _strip_unjsonable(rewritten) or {}

    artifact_keys = _resolve_artifact_keys(miner)

    # Copy allowlisted artifact files and rewrite paths.
    for path_spec in artifact_keys:
        src_path = _get_nested(rewritten, path_spec)
        if not src_path:
            continue
        rel = _copy_artifact(src_path, tmp_dir, artifacts_dir)
        if rel is None:
            _set_nested(rewritten, path_spec, None)
        else:
            _set_nested(rewritten, path_spec, str((tmp_dir / rel)))

    # Rewrite paths again to be relative to the *final* target dir, since the
    # tmp dir name will change when we rename. We persist relative paths in
    # the JSON and resolve them at rehydrate-time.
    relative_paths: dict[str, Optional[str]] = {}
    for path_spec in artifact_keys:
        abs_path = _get_nested(rewritten, path_spec)
        if not abs_path:
            continue
        try:
            rel = str(Path(abs_path).relative_to(tmp_dir))
        except ValueError:
            rel = abs_path
        # Store relative paths as-is in JSON; rehydrate adds the absolute prefix.
        _set_nested(rewritten, path_spec, rel)
        relative_paths[".".join(path_spec) if isinstance(path_spec, tuple) else path_spec] = rel

    # Strip from_cache — UI-only flag, not part of cached state.
    rewritten.pop("from_cache", None)

    parameters = rewritten.get("parameters") or {}

    meta = {
        "log_id": log_id,
        "miner": miner,
        "stored_at": datetime.now().isoformat(timespec="seconds"),
        "source_log_path": source_log_path or rewritten.get("log_path"),
        "source_log_stem": Path(source_log_path or rewritten.get("log_path") or "").stem or None,
        "cache_version": CACHE_VERSION,
    }

    (tmp_dir / _RESULT_DATA_FILE).write_text(
        json.dumps(rewritten, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_dir / _PARAMETERS_FILE).write_text(
        json.dumps(_strip_unjsonable(parameters) or {}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_dir / _CACHE_META_FILE).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── Atomic swap ──
    with _lock:
        if target.exists():
            os.rename(target, old_dir)
        os.rename(tmp_dir, target)

    # Best-effort cleanup of the previous version.
    if old_dir.exists():
        shutil.rmtree(old_dir, ignore_errors=True)

    return CachedRun(miner=miner, log_id=log_id, dir=target)


def lookup(miner: str, log_id: str) -> Optional[CachedRun]:
    """Return the cache entry for ``(miner, log_id)`` or ``None`` if missing
    or if its ``cache_version`` does not match ``CACHE_VERSION``."""
    if not miner or not log_id:
        return None
    _ensure_orphan_cleanup()
    target = _miner_dir(log_id, miner)
    meta_path = target / _CACHE_META_FILE
    data_path = target / _RESULT_DATA_FILE
    if not (meta_path.is_file() and data_path.is_file()):
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if meta.get("cache_version") != CACHE_VERSION:
        return None
    return CachedRun(miner=miner, log_id=log_id, dir=target)


def rehydrate(entry: CachedRun) -> dict:
    """Reconstruct a result-dict from a cached entry.

    Path fields are restored to absolute paths inside the cache directory,
    so downstream code (Dash UI, downloads) can read them as-is.

    The returned dict does **not** contain ``from_cache``; the caller must
    set it explicitly to ``True`` (cache-load path) or ``False`` (after a
    fresh run that just wrote into the cache).
    """
    raw = json.loads(entry.result_data_path.read_text(encoding="utf-8"))
    miner = entry.miner

    for path_spec in _resolve_artifact_keys(miner):
        rel = _get_nested(raw, path_spec)
        if not rel:
            continue
        abs_path = entry.dir / rel
        _set_nested(raw, path_spec, str(abs_path))

    md_path = raw.get("markdown_path")
    if md_path:
        try:
            raw["markdown_content"] = Path(md_path).read_text(encoding="utf-8")
        except OSError:
            raw.setdefault("markdown_content", "")

    raw.pop("from_cache", None)
    return raw


def build_artifacts_zip(entry: CachedRun) -> bytes:
    """Lazily build an artifacts ZIP from a cached entry's artifacts/ dir."""
    from flex_compare.internal.shared.artifact_utils import (
        build_artifacts_zip as _build,
        collect_artifacts as _collect,
    )

    artifacts_dir = entry.artifacts_dir
    if not artifacts_dir.is_dir():
        return b""
    artifacts = _collect(artifacts_dir)
    return _build(artifacts_dir, artifacts)


def iter_cached_results() -> Iterator[tuple[str, str, dict, dict]]:
    """Yield (log_id, miner, meta, rehydrated_result) for every entry in the
    cache. Skips entries whose ``cache_version`` does not match
    ``CACHE_VERSION`` or whose JSON files fail to load.

    Walks only *registered* miner ids (``MINERS``) so flex_compare's
    per-instance slots do not pollute legacy comparison_app surfaces.
    """
    root = _results_root()
    if not root.exists():
        return
    _ensure_orphan_cleanup()
    for log_dir in sorted(root.iterdir()):
        if not log_dir.is_dir():
            continue
        log_id = log_dir.name
        for miner_dir in sorted(log_dir.iterdir()):
            if not miner_dir.is_dir():
                continue
            miner = miner_dir.name
            if miner not in MINERS:
                continue
            entry = lookup(miner, log_id)
            if entry is None:
                continue
            try:
                meta = json.loads(entry.meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            try:
                result = rehydrate(entry)
            except (OSError, json.JSONDecodeError):
                continue
            yield log_id, miner, meta, result


def clear(*, miner: Optional[str] = None, log_id: Optional[str] = None) -> int:
    """Remove cached results. Returns the number of entries deleted."""
    root = _results_root()
    if not root.exists():
        return 0
    deleted = 0
    if log_id and miner:
        target = _miner_dir(log_id, miner)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            deleted += 1
        return deleted
    if log_id:
        target = root / log_id
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            deleted += 1
        return deleted
    for log_dir in list(root.iterdir()):
        if not log_dir.is_dir():
            continue
        if miner:
            t = log_dir / miner
            if t.exists():
                shutil.rmtree(t, ignore_errors=True)
                deleted += 1
        else:
            shutil.rmtree(log_dir, ignore_errors=True)
            deleted += 1
    return deleted


# ── Survey persistence ───────────────────────────────────────────────────────
def _survey_path(log_id: str) -> Path:
    return _surveys_root() / f"{log_id}.json"


def save_survey(survey_state: Optional[dict], log_id: str) -> Path:
    """Atomically persist the survey state for ``log_id``.

    Stores only domain fields — ``dirty`` and other UI-only flags are dropped.
    """
    if not log_id:
        raise ValueError("Cannot save survey without log_id")
    state = survey_state or {}
    payload = {
        "log_id": log_id,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "rubric_version": state.get("rubric_version"),
        "miners": _strip_unjsonable(state.get("miners") or {}),
        "results": _strip_unjsonable(state.get("results") or {}),
    }

    target = _survey_path(log_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
    return target


def load_survey(log_id: str) -> Optional[dict]:
    """Return the persisted survey payload for ``log_id`` or ``None``."""
    if not log_id:
        return None
    path = _survey_path(log_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ── Characteristic-eval persistence ──────────────────────────────────────────
def _characteristic_path(characteristic_id: str) -> Path:
    return _characteristic_eval_root() / f"{characteristic_id}.json"


def save_characteristic(state: Optional[dict], characteristic_id: str) -> Path:
    """Atomically persist the characteristic-eval state for ``characteristic_id``.

    Stores only domain fields — ``dirty`` and other UI-only flags are dropped.
    """
    if not characteristic_id:
        raise ValueError("Cannot save characteristic without characteristic_id")
    state = state or {}
    payload = {
        "characteristic_id": characteristic_id,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "class": state.get("class"),
        "axis": state.get("axis"),
        "type": state.get("type"),
        "contrast": state.get("contrast"),
        "name": state.get("name"),
        "grade_question": state.get("grade_question"),
        "proxy": _strip_unjsonable(state.get("proxy") or {}),
        "observations": _strip_unjsonable(state.get("observations") or []),
        "final_decision": state.get("final_decision"),
        "single_or_multi": state.get("single_or_multi"),
        "final_justification": state.get("final_justification"),
        "new_formulation": state.get("new_formulation"),
        "evidence_level": state.get("evidence_level"),
    }

    target = _characteristic_path(characteristic_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
    return target


def load_characteristic(characteristic_id: str) -> Optional[dict]:
    """Return the persisted characteristic-eval payload or ``None``."""
    if not characteristic_id:
        return None
    path = _characteristic_path(characteristic_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def iter_characteristic_evaluations() -> Iterator[tuple[str, dict]]:
    """Yield ``(characteristic_id, payload)`` for every persisted eval, sorted."""
    root = _characteristic_eval_root()
    if not root.is_dir():
        return
    for path in sorted(root.glob("*.json")):
        cid = path.stem
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        yield cid, payload


# ── Per-model "evaluation completed" flag ─────────────────────────────────────
# A small side store keyed by "<log_id>::<miner>" → ISO timestamp. Marks a model's
# Bewertungsbogen as reviewed/finished (green chip in /validation), independent of
# the dimension-keyed observation files. Lives at the cache root so it is not
# picked up by the characteristic_eval glob above.
def _models_completed_path() -> Path:
    return cache_root() / "models_completed.json"


def load_completed_models() -> set[tuple[str, str]]:
    """The set of ``(log_id, miner)`` models marked as completed."""
    path = _models_completed_path()
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    out: set[tuple[str, str]] = set()
    for key in (data or {}):
        if isinstance(key, str) and "::" in key:
            log_id, miner = key.split("::", 1)
            out.add((log_id, miner))
    return out


def is_model_completed(log_id: str, miner: str) -> bool:
    return (log_id, miner) in load_completed_models()


def set_model_completed(log_id: str, miner: str, done: bool = True) -> bool:
    """Mark/unmark ``(log_id, miner)`` as completed. Returns the new state."""
    if not log_id or not miner:
        raise ValueError("set_model_completed needs log_id and miner")
    path = _models_completed_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    key = f"{log_id}::{miner}"
    if done:
        data[key] = datetime.now().isoformat(timespec="seconds")
    else:
        data.pop(key, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return done


# ── Per-model free-text summary ───────────────────────────────────────────────
# A side store keyed by "<log_id>::<miner>" → free text: the rater's general
# observations / closing summary for one model, independent of the per-dimension
# cells. Lives at the cache root (not picked up by the characteristic_eval glob).
def _model_summaries_path() -> Path:
    return cache_root() / "model_summaries.json"


def load_model_summaries() -> dict[tuple[str, str], str]:
    """``{(log_id, miner) -> summary text}`` for every model with a saved summary."""
    path = _model_summaries_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[tuple[str, str], str] = {}
    for key, val in (data or {}).items():
        if isinstance(key, str) and "::" in key and isinstance(val, str):
            log_id, miner = key.split("::", 1)
            out[(log_id, miner)] = val
    return out


def load_model_summary(log_id: str, miner: str) -> str:
    """The saved free-text summary for ``(log_id, miner)`` (empty string if none)."""
    return load_model_summaries().get((log_id, miner), "")


def save_model_summary(log_id: str, miner: str, text: str) -> None:
    """Persist (or clear, when blank) the free-text summary for a model."""
    if not log_id or not miner:
        raise ValueError("save_model_summary needs log_id and miner")
    path = _model_summaries_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    key = f"{log_id}::{miner}"
    if (text or "").strip():
        data[key] = text
    else:
        data.pop(key, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
