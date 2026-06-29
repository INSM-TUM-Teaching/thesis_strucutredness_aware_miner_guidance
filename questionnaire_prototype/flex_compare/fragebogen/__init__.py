"""Fragebogen scoring — YAML-driven T+E architecture.

The questionnaire is configured in editable per-class YAML files under
``config/`` (:mod:`flex_compare.fragebogen.config_loader`). Each class file
declares two scored blocks: **Phase T** (binary Ja/Nein, theoretical) and
**Phase E** (0/1/2 + n.z., empirical), plus an optional **Phase E gate** for
Semi-Structured.

Modules:
* :mod:`flex_compare.fragebogen.items`           — flattens the YAML into the
  ``ITEMS`` catalogue the UI consumes.
* :mod:`flex_compare.fragebogen.phase_t`         — theoretical (Ja/Nein) Fit
  from the per-miner ``phase_t_seed`` and persisted answers.
* :mod:`flex_compare.fragebogen.phase_t_answers` — per-cell Phase-T answer
  persistence (``.miner_cache/phase_t_eval/``).
* :mod:`flex_compare.fragebogen.phase_e`         — empirical (0/1/2 + n.z.)
  Fit from persisted run-based scores.
* :mod:`flex_compare.fragebogen.phase_e_answers` — per-cell Phase-E answer
  persistence (``.miner_cache/phase_e_eval/``).
* :mod:`flex_compare.fragebogen.combine`         — reports T-Fit and E-Fit
  side by side (Doc §5 leaves A×B open).
"""
