#!/usr/bin/env python3
"""Standalone Heuristics-Miner executable — a reference "custom-exec" miner.

This script is the worked example for the ``custom-exec`` extension path (see
``docs/add_custom_miner.md``). It is a fully external miner: it takes an XES log on
the command line, runs pm4py's Heuristics Miner, and writes a PNML model into an
output directory. flex_compare never imports this file — it only invokes it as a
subprocess and reads the ``model.pnml`` it leaves behind.

Contract expected by ``flex_compare.format_import.run_executable``:

* Input  — an XES event log, passed as ``--log <path>``.
* Output — a Petri net written to ``<outdir>/model.pnml`` (``--out <outdir>``).
* Exit code 0 on success; non-zero (with a message on stderr) on failure.

Register it in the app with:

    command_template : python <this file> --log {log} --out {outdir}
                       --dependency-threshold {dependency_threshold}
    output_format    : pnml
    output_pattern   : model.pnml
    paradigm         : imperativ
    config (JSON)    : {"dependency_threshold": 0.5}

The ``{dependency_threshold}`` placeholder is filled from the miner card's
``config``; drop it from the template to fall back to the pm4py default.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover a Petri net with pm4py's Heuristics Miner and write PNML.",
    )
    parser.add_argument("--log", required=True, help="path to the input XES event log")
    parser.add_argument("--out", required=True, help="output directory for model.pnml")
    parser.add_argument("--dependency-threshold", type=float, default=0.5,
                        help="Heuristics Miner dependency threshold (default: 0.5)")
    parser.add_argument("--and-threshold", type=float, default=0.65,
                        help="Heuristics Miner AND threshold (default: 0.65)")
    parser.add_argument("--loop-two-threshold", type=float, default=0.5,
                        help="Heuristics Miner length-two-loop threshold (default: 0.5)")
    args = parser.parse_args(argv)

    log_path = Path(args.log)
    if not log_path.is_file():
        print(f"log file not found: {log_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Heavy import kept inside main so ``--help`` stays instant.
    import pm4py

    log = pm4py.read_xes(str(log_path))
    net, im, fm = pm4py.discover_petri_net_heuristics(
        log,
        dependency_threshold=args.dependency_threshold,
        and_threshold=args.and_threshold,
        loop_two_threshold=args.loop_two_threshold,
    )

    pnml_path = out_dir / "model.pnml"
    pm4py.write_pnml(net, im, fm, str(pnml_path))
    print(f"wrote {pnml_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
