"""Fake miner that writes a minimal but valid PNML."""
import sys
from pathlib import Path


PNML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<pnml>
  <net id="n1" type="http://www.pnml.org/version-2009/grammar/pnmlcoremodel">
    <name><text>fake</text></name>
    <page id="p1">
      <place id="p_start"><name><text>start</text></name><initialMarking><text>1</text></initialMarking></place>
      <place id="p_mid"><name><text>mid</text></name></place>
      <place id="p_end"><name><text>end</text></name></place>
      <transition id="t_a"><name><text>A</text></name></transition>
      <transition id="t_b"><name><text>B</text></name></transition>
      <arc id="a1" source="p_start" target="t_a"/>
      <arc id="a2" source="t_a" target="p_mid"/>
      <arc id="a3" source="p_mid" target="t_b"/>
      <arc id="a4" source="t_b" target="p_end"/>
    </page>
    <finalmarkings><marking><place idref="p_end"><text>1</text></place></marking></finalmarkings>
  </net>
</pnml>
"""


def main():
    # Args layout: --log <log> --out <outdir>
    args = sys.argv[1:]
    outdir = None
    for i, a in enumerate(args):
        if a == "--out" and i + 1 < len(args):
            outdir = Path(args[i + 1])
            break
    if outdir is None:
        print("missing --out", file=sys.stderr)
        sys.exit(2)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "model.pnml").write_text(PNML_TEMPLATE)
    print("wrote model.pnml")


if __name__ == "__main__":
    main()
