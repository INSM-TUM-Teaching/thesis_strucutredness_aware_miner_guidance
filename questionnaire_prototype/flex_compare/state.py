"""Versioned, atomic disk state for the flex_compare app.

The persisted shape lives at ``.flex_compare/state.json`` and carries:

* the currently selected log,
* the ARM thresholds the user picked,
* the ordered list of configured :class:`MinerInstance`s.

State is loaded once on app start and rewritten on every mutation. The
``version`` field gates schema migrations: unknown future versions raise
loudly (no silent field drop), older versions are walked through the
``_MIGRATORS`` chain. Add a new migrator + a frozen fixture every time the
schema changes.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Literal, Optional

from flex_compare.internal.shared.paths import PROJECT_ROOT
from flex_compare.internal.shared.registry.param_schema import ParamSpec


CURRENT_VERSION = 1
SPEC_SOURCES = ("registry", "inline")

_DEFAULT_STATE_DIR = PROJECT_ROOT / ".flex_compare"
_DEFAULT_STATE_FILE_NAME = "state.json"


class StateError(Exception):
    """Raised on schema-incompatible state files."""


# ── Inline spec (custom-module / custom-exec) ────────────────────────────────
@dataclass(frozen=True)
class InlineSpec:
    """Spec for a user-deployed miner that is NOT in the shared registry.

    ``runner_kind="module"`` reuses the entry-point dispatch path with a
    user-supplied ``module:function``; ``runner_kind="executable"`` runs an
    external command and ingests the result via :mod:`format_import`.
    """

    label: str
    paradigm: Literal["imperativ", "deklarativ", "hybrid"]
    runner_kind: Literal["module", "executable"]
    config_schema: tuple[ParamSpec, ...] = ()

    # module dispatch
    entry_point: Optional[str] = None
    # executable dispatch
    command_template: Optional[str] = None
    output_format: Optional[Literal["pnml", "declare-json", "bpmn"]] = None
    output_pattern: Optional[str] = None
    artifact_keys: tuple[Any, ...] = ()

    def to_jsonable(self) -> dict:
        d = asdict(self)
        d["config_schema"] = [asdict(p) for p in self.config_schema]
        return d

    @classmethod
    def from_jsonable(cls, raw: dict) -> "InlineSpec":
        schema = tuple(
            ParamSpec(**_normalise_paramspec_dict(p)) for p in raw.get("config_schema") or []
        )
        artifact_keys = tuple(raw.get("artifact_keys") or ())
        return cls(
            label=raw["label"],
            paradigm=raw["paradigm"],
            runner_kind=raw["runner_kind"],
            config_schema=schema,
            entry_point=raw.get("entry_point"),
            command_template=raw.get("command_template"),
            output_format=raw.get("output_format"),
            output_pattern=raw.get("output_pattern"),
            artifact_keys=artifact_keys,
        )


def _normalise_paramspec_dict(raw: dict) -> dict:
    """Coerce ParamSpec round-tripped through JSON back into a constructor dict.

    JSON has no tuples, so ``options`` and ``visible_when`` come back as nested
    lists. Convert them back to the tuple-of-tuples shape ParamSpec expects.
    """
    out = dict(raw)
    if isinstance(out.get("options"), list):
        out["options"] = tuple(tuple(o) for o in out["options"])
    if isinstance(out.get("visible_when"), list):
        out["visible_when"] = tuple(tuple(o) for o in out["visible_when"])
    return out


# ── Miner instance ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class MinerInstance:
    """One configured miner card in the app.

    ``spec_source="registry"`` looks the spec up by ``spec_id`` in the shared
    :data:`miners.shared.registry.miner_registry.REGISTRY`. ``"inline"`` carries
    its own :class:`InlineSpec` so the user can register a one-off custom miner
    without polluting the global registry.

    ``config`` matches the spec's ``config_schema`` — values keyed by
    ``ParamSpec.key``. The stored ``id`` is stable across sessions and serves
    as the dynamic-card index.
    """

    id: str
    spec_source: Literal["registry", "inline"]
    label: str
    config: dict
    spec_id: Optional[str] = None              # registry path
    inline_spec: Optional[InlineSpec] = None   # inline path
    timeout_sec: int = 600                     # for executable dispatch

    def to_jsonable(self) -> dict:
        return {
            "id": self.id,
            "spec_source": self.spec_source,
            "label": self.label,
            "config": dict(self.config),
            "spec_id": self.spec_id,
            "inline_spec": self.inline_spec.to_jsonable() if self.inline_spec else None,
            "timeout_sec": self.timeout_sec,
        }

    @classmethod
    def from_jsonable(cls, raw: dict) -> "MinerInstance":
        inline = raw.get("inline_spec")
        return cls(
            id=raw["id"],
            spec_source=raw["spec_source"],
            label=raw.get("label") or "",
            config=dict(raw.get("config") or {}),
            spec_id=raw.get("spec_id"),
            inline_spec=InlineSpec.from_jsonable(inline) if inline else None,
            timeout_sec=int(raw.get("timeout_sec") or 600),
        )


def new_instance_id() -> str:
    return f"inst_{uuid.uuid4().hex[:8]}"


# ── Top-level state ──────────────────────────────────────────────────────────
@dataclass
class FlexState:
    selected_log: Optional[str] = None
    arm_thresholds: dict = field(default_factory=lambda: {"temporal": 1.0, "existential": 1.0})
    instances: List[MinerInstance] = field(default_factory=list)
    version: int = CURRENT_VERSION

    def to_jsonable(self) -> dict:
        return {
            "version": self.version,
            "selected_log": self.selected_log,
            "arm_thresholds": dict(self.arm_thresholds),
            "instances": [i.to_jsonable() for i in self.instances],
        }

    @classmethod
    def from_jsonable(cls, raw: dict) -> "FlexState":
        raw = _migrate(raw)
        return cls(
            version=raw["version"],
            selected_log=raw.get("selected_log"),
            arm_thresholds=dict(raw.get("arm_thresholds") or {"temporal": 1.0, "existential": 1.0}),
            instances=[MinerInstance.from_jsonable(i) for i in raw.get("instances") or []],
        )


# ── Migrations ───────────────────────────────────────────────────────────────
# Future migrations append here. Each migrator takes the raw dict at version N
# and returns the raw dict at version N+1.
def _migrate_v0_to_v1(raw: dict) -> dict:
    """Pre-v1 files (no ``version`` field at all) are assumed to follow the
    v1 layout already — they just need a version stamp. If your project ever
    had a *real* v0 layout, this is where you would translate it."""
    out = dict(raw)
    out["version"] = 1
    return out


_MIGRATORS = {
    0: _migrate_v0_to_v1,
}


def _migrate(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise StateError(f"state must be a JSON object, got {type(raw).__name__}")
    version = raw.get("version", 0)
    if not isinstance(version, int):
        raise StateError(f"state.version must be an int, got {version!r}")
    if version > CURRENT_VERSION:
        raise StateError(
            f"state.version={version} is newer than CURRENT_VERSION={CURRENT_VERSION}; "
            "refusing to silently drop unknown fields. Upgrade the app or back up "
            "the state file before continuing."
        )
    while version < CURRENT_VERSION:
        migrator = _MIGRATORS.get(version)
        if migrator is None:
            raise StateError(
                f"no migrator from state.version={version} to {version + 1}"
            )
        raw = migrator(raw)
        version = raw["version"]
    return raw


# ── Disk I/O ─────────────────────────────────────────────────────────────────
_state_dir_override: Optional[Path] = None


def set_state_dir(path: Optional[Path]) -> None:
    """Override the state directory. Pass ``None`` to revert to the default."""
    global _state_dir_override
    _state_dir_override = Path(path) if path is not None else None


def state_dir() -> Path:
    return _state_dir_override or _DEFAULT_STATE_DIR


def state_file() -> Path:
    return state_dir() / _DEFAULT_STATE_FILE_NAME


def load() -> FlexState:
    """Load the on-disk state; returns a fresh ``FlexState()`` if no file exists."""
    path = state_file()
    if not path.is_file():
        return FlexState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StateError(f"state file at {path} is not valid JSON: {exc}") from exc
    return FlexState.from_jsonable(raw)


def save(state: FlexState) -> Path:
    """Atomically write ``state`` to disk (temp → rename)."""
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_jsonable(), indent=2, ensure_ascii=False)
    tmp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
    return path


# ── Mutation helpers (pure — caller persists) ────────────────────────────────
def add_instance(state: FlexState, instance: MinerInstance) -> FlexState:
    state.instances = list(state.instances) + [instance]
    return state


def remove_instance(state: FlexState, instance_id: str) -> FlexState:
    state.instances = [i for i in state.instances if i.id != instance_id]
    return state


def update_instance_config(state: FlexState, instance_id: str, config: dict) -> FlexState:
    new_list: list[MinerInstance] = []
    for inst in state.instances:
        if inst.id == instance_id:
            new_list.append(
                MinerInstance(
                    id=inst.id,
                    spec_source=inst.spec_source,
                    label=inst.label,
                    config=dict(config),
                    spec_id=inst.spec_id,
                    inline_spec=inst.inline_spec,
                    timeout_sec=inst.timeout_sec,
                )
            )
        else:
            new_list.append(inst)
    state.instances = new_list
    return state


def find_instance(state: FlexState, instance_id: str) -> Optional[MinerInstance]:
    for inst in state.instances:
        if inst.id == instance_id:
            return inst
    return None


def instance_ids(state: FlexState) -> Iterable[str]:
    return (i.id for i in state.instances)
