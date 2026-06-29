"""Fake miner that writes an invalid PNML — provokes a parse error in import_pnml."""
import sys
from pathlib import Path


def main():
    args = sys.argv[1:]
    outdir = None
    for i, a in enumerate(args):
        if a == "--out" and i + 1 < len(args):
            outdir = Path(args[i + 1])
            break
    if outdir is None:
        sys.exit(2)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "model.pnml").write_text("<?xml version='1.0'?>not-a-pnml-at-all")


if __name__ == "__main__":
    main()
