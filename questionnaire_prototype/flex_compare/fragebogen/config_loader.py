"""Load + validate the YAML questionnaire configuration (T+E architecture).

The Fragebogen item catalogue lives in editable per-class YAML files under
:mod:`flex_compare.fragebogen` ``/config/``: one file per structuredness class
(``structured.yaml``, ``semi.yaml``, ``loosely.yaml``). Each file declares the
class ``meta``, a ``stufe1`` capability/routing block (ungescort), the
``phase_t`` items (theoretical, binary Ja/Nein), an optional ``phase_e_gate``
(Semi only), and the ``phase_e`` items (empirical, 0/1/2).

Schema (per class file)
-----------------------
``meta`` :
    ``class`` (structured|semi|loosely), ``phase_t_max`` (int = #T-Items),
    ``phase_e_max`` (int = sum of E item maxima, i.e. 2 × #E-Items),
    ``combination`` (must carry ``mode``, optional ``borderline_margin``),
    free ``label`` / ``status`` / ``source`` strings.

``stufe1`` :
    Capability/routing questions (ungescort). Each entry needs ``id`` +
    ``question``; free-form otherwise.

``phase_t`` :
    Theoretical items. Each needs ``id`` (must start with ``T-``), ``axis``,
    ``title``, ``question``, ``doku_hint``, ``scale`` (exactly the two anchors
    ``ja`` and ``nein``), ``allow_nz`` (bool), ``split_candidate`` (bool),
    plus optional ``phase_t_seed`` (per-miner ``{value: ja|nein|nz|null,
    note: str}``).

``phase_e_gate`` :
    Optional. Either ``null`` (no gate) or a mapping with ``id``, ``question``,
    ``scale`` (ja/nein), ``scored: false``.

``phase_e`` :
    Empirical items. Each needs ``id`` (must start with ``E-``), ``axis``,
    ``title``, ``question``, ``route``, ``scale`` (exactly the three 2/1/0
    anchors), ``allow_nz`` (bool), optional ``metric_keys`` (list[str]),
    optional ``gate_zero_on_no`` (Semi only), optional ``zone_kind``
    (stable|flexible, Semi only).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import yaml

CONFIG_DIR = Path(__file__).resolve().parent / "config"

VALID_CLASSES = ("structured", "semi", "loosely")
_T_SCORES = {"ja", "nein"}
_E_SCORES = {0, 1, 2}
_NZ = "nz"
_T_VALUES_WITH_NZ = _T_SCORES | {_NZ}


class ConfigError(ValueError):
    """Raised when a questionnaire YAML file is missing or malformed."""


# ── cache ────────────────────────────────────────────────────────────────────
_lock = threading.Lock()
_cache: Optional[dict[str, dict]] = None


def _config_dir() -> Path:
    return CONFIG_DIR


def reload() -> dict[str, dict]:
    """Re-read every ``config/*.yaml`` from disk and refresh the cache."""
    global _cache
    with _lock:
        _cache = _load_all(_config_dir())
        return _cache


def load() -> dict[str, dict]:
    """Return the cached class-keyed config map, loading on first use."""
    global _cache
    if _cache is None:
        return reload()
    return _cache


# ── loading + validation ─────────────────────────────────────────────────────
def _load_all(config_dir: Path) -> dict[str, dict]:
    if not config_dir.is_dir():
        raise ConfigError(f"Config directory missing: {config_dir}")
    out: dict[str, dict] = {}
    for path in sorted(config_dir.glob("*.yaml")):
        cfg = _load_file(path)
        cls = cfg["meta"]["class"]
        if cls in out:
            raise ConfigError(
                f"Duplicate class definition '{cls}' "
                f"({path.name} conflicts with an earlier file).")
        out[cls] = cfg
    return out


def _load_file(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover
        raise ConfigError(f"{path.name}: invalid YAML — {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name}: top level must be a mapping.")

    _validate_meta(path, raw.get("meta"))
    stufe1 = _validate_stufe1(path, raw.get("stufe1"))
    phase_t = _validate_phase_t(path, raw.get("phase_t"))
    phase_e_gate = _validate_phase_e_gate(path, raw.get("phase_e_gate"))
    phase_e = _validate_phase_e(path, raw.get("phase_e"))

    # Cross-check: per-class id namespace is disjoint between phases.
    seen: set[str] = set()
    for item in phase_t + phase_e:
        if item["id"] in seen:
            raise ConfigError(
                f"{path.name}: id '{item['id']}' appears in both phase_t and phase_e.")
        seen.add(item["id"])

    return {
        "meta": raw["meta"],
        "stufe1": stufe1,
        "phase_t": phase_t,
        "phase_e_gate": phase_e_gate,
        "phase_e": phase_e,
    }


def _validate_meta(path: Path, meta) -> None:
    if not isinstance(meta, dict):
        raise ConfigError(f"{path.name}: 'meta' is missing or not a mapping.")
    cls = meta.get("class")
    if cls not in VALID_CLASSES:
        raise ConfigError(
            f"{path.name}: meta.class = {cls!r}, expected one of "
            f"{VALID_CLASSES}.")
    for key in ("phase_t_max", "phase_e_max"):
        if not isinstance(meta.get(key), int):
            raise ConfigError(f"{path.name}: meta.{key} must be an int.")
    comb = meta.get("combination")
    if not isinstance(comb, dict):
        raise ConfigError(
            f"{path.name}: meta.combination is missing or not a mapping.")
    if comb.get("mode") not in ("separate", "weighted"):
        raise ConfigError(
            f"{path.name}: meta.combination.mode must be 'separate' or "
            f"'weighted' (equal weight per item).")


def _validate_stufe1(path: Path, stufe1) -> list[dict]:
    if stufe1 is None:
        return []
    if not isinstance(stufe1, list):
        raise ConfigError(f"{path.name}: 'stufe1' must be a list.")
    for entry in stufe1:
        if (not isinstance(entry, dict) or "id" not in entry
                or "question" not in entry):
            raise ConfigError(
                f"{path.name}: every stufe1 entry needs 'id' and 'question'.")
    return stufe1


# ── phase T ──────────────────────────────────────────────────────────────────
def _validate_phase_t(path: Path, phase_t) -> list[dict]:
    if not isinstance(phase_t, list) or not phase_t:
        raise ConfigError(f"{path.name}: 'phase_t' must be a non-empty list.")
    seen: set[str] = set()
    out: list[dict] = []
    for item in phase_t:
        if not isinstance(item, dict):
            raise ConfigError(f"{path.name}: phase_t entry is not a mapping.")
        item_id = item.get("id")
        if not item_id or not item_id.startswith("T-"):
            raise ConfigError(
                f"{path.name}: phase_t id '{item_id}' must start with 'T-'.")
        if item_id in seen:
            raise ConfigError(f"{path.name}: duplicate phase_t id '{item_id}'.")
        seen.add(item_id)
        for field in ("axis", "title", "question", "doku_hint"):
            if not item.get(field):
                raise ConfigError(
                    f"{path.name}: phase_t '{item_id}' missing '{field}'.")
        if not isinstance(item.get("allow_nz"), bool):
            raise ConfigError(
                f"{path.name}: phase_t '{item_id}': allow_nz must be a bool.")
        if not isinstance(item.get("split_candidate", False), bool):
            raise ConfigError(
                f"{path.name}: phase_t '{item_id}': split_candidate must be a "
                f"bool.")
        _validate_t_scale(path, item_id, item.get("scale"))
        _validate_phase_t_seed(path, item_id, item.get("phase_t_seed"),
                               item.get("allow_nz", False))
        _validate_optional_str(path, item_id, "measure", item.get("measure"))
        out.append({**item, "phase": "T"})
    return out


def _validate_t_scale(path: Path, item_id: str, scale) -> None:
    if not isinstance(scale, list):
        raise ConfigError(
            f"{path.name}: phase_t '{item_id}': 'scale' must be a list.")
    values = []
    for row in scale:
        if (not isinstance(row, dict) or "value" not in row
                or "label" not in row):
            raise ConfigError(
                f"{path.name}: phase_t '{item_id}': every scale row needs "
                f"'value' and 'label'.")
        values.append(row["value"])
    if set(values) != _T_SCORES:
        raise ConfigError(
            f"{path.name}: phase_t '{item_id}': scale must cover exactly "
            f"{sorted(_T_SCORES)}, found {values}.")


def _validate_phase_t_seed(path: Path, item_id: str, seed,
                           allow_nz: bool) -> None:
    if seed is None:
        return
    if not isinstance(seed, dict):
        raise ConfigError(
            f"{path.name}: phase_t '{item_id}': phase_t_seed must be a mapping "
            f"(miner_id -> {{value, note}}).")
    allowed = _T_VALUES_WITH_NZ if allow_nz else _T_SCORES
    for miner_id, entry in seed.items():
        if not isinstance(entry, dict) or "value" not in entry:
            raise ConfigError(
                f"{path.name}: phase_t '{item_id}': phase_t_seed['{miner_id}']"
                f" needs 'value' (ja/nein"
                f"{'/nz' if allow_nz else ''} or null).")
        value = entry["value"]
        if value is None:
            continue
        if value not in allowed:
            extra = " (n.z. requires allow_nz: true)" if value == _NZ else ""
            raise ConfigError(
                f"{path.name}: phase_t '{item_id}': "
                f"phase_t_seed['{miner_id}'].value = {value!r}; "
                f"allowed: {sorted(allowed)} or null{extra}.")


# ── phase E ──────────────────────────────────────────────────────────────────
def _validate_phase_e_gate(path: Path, gate) -> Optional[dict]:
    if gate is None:
        return None
    if not isinstance(gate, dict):
        raise ConfigError(f"{path.name}: phase_e_gate must be a mapping or null.")
    for field in ("id", "question"):
        if not gate.get(field):
            raise ConfigError(
                f"{path.name}: phase_e_gate missing '{field}'.")
    if gate.get("scored", False) is not False:
        raise ConfigError(
            f"{path.name}: phase_e_gate.scored must be false (gate is "
            f"ungescort).")
    _validate_t_scale(path, gate["id"], gate.get("scale"))
    return gate


def _validate_phase_e(path: Path, phase_e) -> list[dict]:
    if not isinstance(phase_e, list) or not phase_e:
        raise ConfigError(f"{path.name}: 'phase_e' must be a non-empty list.")
    seen: set[str] = set()
    out: list[dict] = []
    for item in phase_e:
        if not isinstance(item, dict):
            raise ConfigError(f"{path.name}: phase_e entry is not a mapping.")
        item_id = item.get("id")
        if not item_id or not item_id.startswith("E-"):
            raise ConfigError(
                f"{path.name}: phase_e id '{item_id}' must start with 'E-'.")
        if item_id in seen:
            raise ConfigError(f"{path.name}: duplicate phase_e id '{item_id}'.")
        seen.add(item_id)
        for field in ("axis", "title", "question", "route"):
            if not item.get(field):
                raise ConfigError(
                    f"{path.name}: phase_e '{item_id}' missing '{field}'.")
        if not isinstance(item.get("allow_nz"), bool):
            raise ConfigError(
                f"{path.name}: phase_e '{item_id}': allow_nz must be a bool.")
        _validate_e_scale(path, item_id, item.get("scale"))
        _validate_metric_keys(path, item_id, item.get("metric_keys"))
        zone_kind = item.get("zone_kind")
        if zone_kind not in (None, "stable", "flexible"):
            raise ConfigError(
                f"{path.name}: phase_e '{item_id}': zone_kind must be "
                f"stable|flexible|null, got {zone_kind!r}.")
        if not isinstance(item.get("gate_zero_on_no", False), bool):
            raise ConfigError(
                f"{path.name}: phase_e '{item_id}': gate_zero_on_no must "
                f"be a bool.")
        _validate_optional_str(path, item_id, "measure", item.get("measure"))
        out.append({**item, "phase": "E"})
    return out


def _validate_optional_str(path: Path, item_id: str, field: str, value) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"{path.name}: item '{item_id}': '{field}' must be a non-empty "
            f"string when set, got {value!r}.")


def _validate_e_scale(path: Path, item_id: str, scale) -> None:
    if not isinstance(scale, list):
        raise ConfigError(
            f"{path.name}: phase_e '{item_id}': 'scale' must be a list.")
    scores = []
    for row in scale:
        if (not isinstance(row, dict) or "score" not in row
                or "label" not in row):
            raise ConfigError(
                f"{path.name}: phase_e '{item_id}': every scale row needs "
                f"'score' and 'label'.")
        scores.append(row["score"])
    if set(scores) != _E_SCORES:
        raise ConfigError(
            f"{path.name}: phase_e '{item_id}': scale must cover exactly "
            f"{sorted(_E_SCORES, reverse=True)}, found {scores}.")


def _validate_metric_keys(path: Path, item_id: str, metric_keys) -> None:
    if metric_keys is None:
        return
    if not isinstance(metric_keys, list) or not all(
            isinstance(k, str) for k in metric_keys):
        raise ConfigError(
            f"{path.name}: item '{item_id}': metric_keys must be a list of "
            f"strings.")
