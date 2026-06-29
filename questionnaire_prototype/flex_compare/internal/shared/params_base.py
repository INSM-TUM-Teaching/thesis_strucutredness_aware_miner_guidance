from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BaseMinerParams:
    """Marker base class for all miner parameter dataclasses.

    Currently empty — acts as a shared type for isinstance checks and
    type annotations. Add common fields here as needed (e.g. random_seed,
    timeout_sec, verbose).
    """
    pass
