"""Generic pm4py discovery miner — extensibility PoC for the comparison app.

Any pm4py algorithm that yields a Petri net is evaluated through the imperative
miner's metric path, producing results directly comparable to the ``imp`` miner.
"""

from .evaluation import ALGORITHM_LABELS, evaluate_log, generate_report

__all__ = ["ALGORITHM_LABELS", "evaluate_log", "generate_report"]
