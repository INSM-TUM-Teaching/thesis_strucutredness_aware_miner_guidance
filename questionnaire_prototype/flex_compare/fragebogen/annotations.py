"""Hand-authored segment annotations for the Empirical (E) wizard.

The E wizard asks the evaluator to rate a discovered model per log against the
E-items (e.g. for Semi: "Are the fragments displayed correctly?"). To judge
this the evaluator needs an orientation for what the activity relationships of
that *specific* log look like (stable segments for semi, ordering/exclusion
relationships for loosely). These are ARM-style relations the model can be read
against, not a ground truth or a single correct model. They are not derivable
from the discovered model, so they are hand-authored here.

Annotations live in editable per-class YAML files under ``config/annotations/``
(one file per structuredness class, mirroring ``config/*.yaml``). Each file is a
mapping keyed by **log stem** (filename without ``.xes``, e.g.
``Log02_semiStructured``), then by **E-item id** (e.g. ``E-Sm-BQ-1``):

    Log02_semiStructured:
      E-Sm-BQ-1:
        segments:                      # semi: stable segments (name + activities)
          - name: "Stable core"
            activities: [Register, Check, Approve]
            note: "fixed ordering, no skips"   # optional
    Log03_looselyStructured:
      E-L-BQ-1:
        rules:                         # loosely: must-capture constraints (bullets)
          - "a before b"
          - "a and b never together"

An entry may carry ``segments`` (structured, for semi stable segments) and/or
``rules`` (bullet-point strings, for loosely must-capture constraints); at least
one is required.

The feature is additive and optional: a missing file, log stem, or item id all
mean "no annotation" and the wizard simply renders nothing extra. The loader is
deliberately lenient on *which* log stems / item ids appear (it does not check
them against the data dir or the questionnaire), so authoring stays low-friction;
it is strict only on the *shape* of each entry.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import yaml

ANNOTATIONS_DIR = Path(__file__).resolve().parent / "config" / "annotations"

# Relationship strength for a rule, strongest first. A direct succession (x
# immediately followed by y) is tighter than an eventual order (x somewhere
# before y), which is the distinction an evaluator must not blur: an eventual
# "b before c" can read as if b were directly before c. "note" is the untyped
# catch-all (e.g. "otherwise unordered"). The display layer ranks/labels these.
RULE_STRENGTHS = ("direct", "presence", "exclusion", "eventual", "note")
_DEFAULT_STRENGTH = "note"


class AnnotationError(ValueError):
    """Raised when an annotations YAML file is malformed."""


# ── cache ────────────────────────────────────────────────────────────────────
_lock = threading.Lock()
# stem -> item_id -> list[segment dict]
_cache: Optional[dict[str, dict[str, list[dict]]]] = None


def _annotations_dir() -> Path:
    return ANNOTATIONS_DIR


def reload() -> dict[str, dict[str, list[dict]]]:
    """Re-read every ``config/annotations/*.yaml`` and refresh the cache."""
    global _cache
    with _lock:
        _cache = _load_all(_annotations_dir())
        return _cache


def load() -> dict[str, dict[str, list[dict]]]:
    """Return the cached annotation map, loading on first use."""
    global _cache
    if _cache is None:
        return reload()
    return _cache


def segments_for(log_stem: str, item_id: str) -> list[dict]:
    """Return the annotated segments for ``log_stem`` + ``item_id``.

    Each segment is a validated dict ``{"name": str, "activities": list[str],
    "note": str | None}``. Returns ``[]`` when nothing is annotated.
    """
    return load().get(log_stem, {}).get(item_id, {}).get("segments", [])


def rules_for(log_stem: str, item_id: str) -> list[dict]:
    """Return the annotated relationship rules for ``log_stem`` + ``item_id``.

    Each rule is a dict ``{"text": str, "strength": str}`` where ``strength`` is
    one of :data:`RULE_STRENGTHS` (e.g. ``"direct"``, ``"eventual"``,
    ``"exclusion"``). Returns ``[]`` when nothing is annotated. The display layer
    orders these by strength.
    """
    return load().get(log_stem, {}).get(item_id, {}).get("rules", [])


# ── loading + validation ─────────────────────────────────────────────────────
def _load_all(annotations_dir: Path) -> dict[str, dict[str, dict]]:
    if not annotations_dir.is_dir():
        # Optional feature: no directory simply means no annotations.
        return {}
    out: dict[str, dict[str, dict]] = {}
    for path in sorted(annotations_dir.glob("*.yaml")):
        for stem, items in _load_file(path).items():
            # Later files win per (stem, item) but the per-class split means
            # collisions are not expected; merge rather than clobber the stem.
            out.setdefault(stem, {}).update(items)
    return out


def _load_file(path: Path) -> dict[str, dict[str, dict]]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover
        raise AnnotationError(f"{path.name}: invalid YAML — {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise AnnotationError(
            f"{path.name}: top level must be a mapping (log_stem -> ...).")

    out: dict[str, dict[str, dict]] = {}
    for stem, items in raw.items():
        if not isinstance(items, dict):
            raise AnnotationError(
                f"{path.name}: '{stem}' must map item ids to annotations.")
        per_item: dict[str, dict] = {}
        for item_id, entry in items.items():
            per_item[item_id] = _validate_entry(path, stem, item_id, entry)
        out[stem] = per_item
    return out


def _validate_entry(path: Path, stem: str, item_id: str, entry) -> dict:
    """Validate one annotation entry. An entry may carry ``segments``
    (structured name + activities, for semi stable segments) and/or ``rules``
    (bullet-point strings, for loosely must-capture constraints); at least one
    is required. Returns ``{"segments": [...], "rules": [...]}``."""
    if not isinstance(entry, dict):
        raise AnnotationError(
            f"{path.name}: '{stem}/{item_id}' must be a mapping with "
            f"'segments' and/or 'rules'.")
    segments_raw = entry.get("segments")
    rules_raw = entry.get("rules")
    if segments_raw is None and rules_raw is None:
        raise AnnotationError(
            f"{path.name}: '{stem}/{item_id}': must define 'segments' and/or "
            f"'rules'.")

    segments: list[dict] = []
    if segments_raw is not None:
        if not isinstance(segments_raw, list) or not segments_raw:
            raise AnnotationError(
                f"{path.name}: '{stem}/{item_id}': 'segments' must be a "
                f"non-empty list.")
        for idx, seg in enumerate(segments_raw):
            segments.append(_validate_segment(path, stem, item_id, idx, seg))

    rules: list[dict] = []
    if rules_raw is not None:
        if not isinstance(rules_raw, list) or not rules_raw:
            raise AnnotationError(
                f"{path.name}: '{stem}/{item_id}': 'rules' must be a "
                f"non-empty list.")
        for idx, rule in enumerate(rules_raw):
            rules.append(_validate_rule(path, stem, item_id, idx, rule))

    return {"segments": segments, "rules": rules}


def _validate_rule(path: Path, stem: str, item_id: str, idx: int, rule) -> dict:
    """A rule is either a bare string (untyped, ``strength="note"``) or a
    mapping ``{text, strength}`` where ``strength`` is one of
    :data:`RULE_STRENGTHS`. Returns the normalised ``{"text", "strength"}``."""
    where = f"{stem}/{item_id}: rules[{idx}]"
    if isinstance(rule, str):
        if not rule.strip():
            raise AnnotationError(f"{path.name}: '{where}' must be non-empty.")
        return {"text": rule.strip(), "strength": _DEFAULT_STRENGTH}
    if not isinstance(rule, dict):
        raise AnnotationError(
            f"{path.name}: '{where}' must be a string or a mapping with "
            f"'text' and optional 'strength'.")
    text = rule.get("text")
    if not isinstance(text, str) or not text.strip():
        raise AnnotationError(
            f"{path.name}: '{where}': 'text' must be a non-empty string.")
    strength = rule.get("strength", _DEFAULT_STRENGTH)
    if strength not in RULE_STRENGTHS:
        raise AnnotationError(
            f"{path.name}: '{where}': 'strength' must be one of "
            f"{RULE_STRENGTHS}, got {strength!r}.")
    return {"text": text.strip(), "strength": strength}


def _validate_segment(path: Path, stem: str, item_id: str, idx: int,
                      seg) -> dict:
    where = f"{stem}/{item_id}[{idx}]"
    if not isinstance(seg, dict):
        raise AnnotationError(f"{path.name}: '{where}' must be a mapping.")
    name = seg.get("name")
    if not isinstance(name, str) or not name.strip():
        raise AnnotationError(
            f"{path.name}: '{where}': 'name' must be a non-empty string.")
    activities = seg.get("activities")
    if not isinstance(activities, list) or not all(
            isinstance(a, str) for a in activities):
        raise AnnotationError(
            f"{path.name}: '{where}': 'activities' must be a list of strings.")
    note = seg.get("note")
    if note is not None and not isinstance(note, str):
        raise AnnotationError(
            f"{path.name}: '{where}': 'note' must be a string when set.")
    return {
        "name": name.strip(),
        "activities": list(activities),
        "note": (note.strip() if isinstance(note, str) and note.strip()
                 else None),
    }
