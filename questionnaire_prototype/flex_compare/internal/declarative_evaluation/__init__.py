"""Declarative evaluation package.

Provides trace-aware fitness (via MINERful's FitnessChecker) and precision-proxy
indicators for declarative process models (Declare / MINERful). For Declare, there is no
established standard precision metric — the proxies in this package are
deliberately labelled as such.
"""

from __future__ import annotations

from flex_compare.internal.declarative_evaluation.api import evaluate_declarative

__all__ = ["evaluate_declarative"]
