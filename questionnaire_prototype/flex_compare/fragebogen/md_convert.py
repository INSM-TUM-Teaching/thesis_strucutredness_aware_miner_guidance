"""Round-trip converter between the questionnaire YAML configs and Markdown.

YAML stays the single source of truth the app loads and validates
(:mod:`flex_compare.fragebogen.config_loader` and
:mod:`flex_compare.fragebogen.annotations`). This module adds an editing
surface: export each YAML to a readable Markdown file, edit the Markdown, then
import it back to YAML. The import path never writes blind: it rebuilds the
data, dumps YAML, and runs the *existing* validators before replacing anything,
so a typo in the Markdown is caught instead of breaking the app.

Two scopes:

* ``items``       — ``config/*.yaml`` (structured / semi / loosely item catalogue)
* ``annotations`` — ``config/annotations/*.yaml`` (segment annotations)

Markdown encoding (deliberately strict, the parser relies on it)
---------------------------------------------------------------
* ``## key``  starts a top-level block (items: ``meta``/``stufe1``/``phase_t``/
  ``phase_e_gate``/``phase_e``; annotations: one block per log stem).
* ``### id``  starts a record inside a list/mapping block (an item, or an
  annotation entry). The header text is the record id / key.
* ``- key: <v>``  a scalar field. ``<v>`` is YAML flow syntax, so types
  (bool/int/null/str/list) survive a round-trip exactly.
* ``- key:`` with no value, followed by an indented ``| ... |`` table, encodes
  a list of uniform mappings (``scale``, ``segments``) or, when the first
  column header is ``@key``, a mapping of mappings (``phase_t_seed``).
* ``- key:`` with no value, followed by indented ``  - <v>`` bullets, encodes a
  nested mapping (``combination``) or a list (``rules``).

Comments are not stored in the Markdown. On import the CLI preserves the
existing YAML file's leading comment header verbatim.

CLI::

    python -m flex_compare.fragebogen.md_convert export [--scope all|items|annotations] [--class semi]
    python -m flex_compare.fragebogen.md_convert import [--scope all|items|annotations] [--class semi]

Export writes ``config/_markdown/<class>.md`` and
``config/annotations/_markdown/<class>.md``. Import reads them back.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from flex_compare.fragebogen import annotations as _annotations
from flex_compare.fragebogen import config_loader as _config_loader

# ── directory layout ──────────────────────────────────────────────────────────
_CONFIG_DIR = _config_loader.CONFIG_DIR
_ANNOTATIONS_DIR = _annotations.ANNOTATIONS_DIR
_ITEMS_MD_DIR = _CONFIG_DIR / "_markdown"
_ANNOTATIONS_MD_DIR = _ANNOTATIONS_DIR / "_markdown"

_KEY_COL = "@key"  # sentinel first-column header marking a mapping-of-mappings


# ── flow scalar helpers (types survive via YAML) ─────────────────────────────
def _flow(value: Any) -> str:
    """Encode a scalar / simple list as a single-line YAML flow string."""
    dumped = yaml.safe_dump(
        value, default_flow_style=True, allow_unicode=True,
        width=10 ** 9, sort_keys=False).strip()
    # safe_dump appends a document-end marker for some bare scalars; drop it.
    if dumped.endswith("\n..."):
        dumped = dumped[: -len("\n...")].strip()
    return dumped


def _unflow(text: str) -> Any:
    """Inverse of :func:`_flow`."""
    return yaml.safe_load(text)


def _is_record_list(value: Any) -> bool:
    return (isinstance(value, list) and len(value) > 0
            and all(isinstance(x, dict) for x in value))


def _is_mapping_of_mappings(value: Any) -> bool:
    return (isinstance(value, dict) and bool(value)
            and all(isinstance(v, dict) for v in value.values()))


def _is_plain_mapping(value: Any) -> bool:
    return (isinstance(value, dict)
            and all(not isinstance(v, (dict, list)) for v in value.values()))


# ── table encode / decode ─────────────────────────────────────────────────────
def _esc(cell: str) -> str:
    return cell.replace("\\", "\\\\").replace("|", "\\|")


def _unesc(cell: str) -> str:
    return cell.replace("\\|", "|").replace("\\\\", "\\")


def _split_row(line: str) -> list[str]:
    """Split a Markdown table row on unescaped pipes."""
    cells, buf, i = [], [], 0
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and i + 1 < len(inner):
            buf.append(inner[i:i + 2])
            i += 2
            continue
        if ch == "|":
            cells.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    cells.append("".join(buf))
    return [_unesc(c.strip()) for c in cells]


def _columns(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for row in rows:
        for k in row:
            if k not in cols:
                cols.append(k)
    return cols


def _render_table(rows: list[dict], key_col: str | None, indent: str) -> list[str]:
    data_cols = [c for c in _columns(rows) if c != key_col]
    header = ([key_col] if key_col else []) + data_cols
    out = [indent + "| " + " | ".join(_esc(c) for c in header) + " |",
           indent + "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        prefix = [str(row[_KEY_COL])] if key_col else []
        cells = prefix + [_flow(row[c]) if c in row else "" for c in data_cols]
        out.append(indent + "| " + " | ".join(_esc(c) for c in cells) + " |")
    return out


def _parse_table(lines: list[str]) -> tuple[list[dict] | dict, bool]:
    """Parse table ``lines`` (header, separator, rows). Returns (data, is_map)."""
    header = _split_row(lines[0])
    is_map = header and header[0] == _KEY_COL
    cols = header[1:] if is_map else header
    if is_map:
        out_map: dict[str, dict] = {}
        for line in lines[2:]:
            cells = _split_row(line)
            key = cells[0]
            out_map[key] = {c: _unflow(v) for c, v in zip(cols, cells[1:])
                            if v != ""}
        return out_map, True
    out_list: list[dict] = []
    for line in lines[2:]:
        cells = _split_row(line)
        out_list.append({c: _unflow(v) for c, v in zip(cols, cells)
                         if v != ""})
    return out_list, False


# ── field rendering ───────────────────────────────────────────────────────────
def _render_fields(d: dict, drop: tuple[str, ...] = ()) -> list[str]:
    out: list[str] = []
    for key, value in d.items():
        if key in drop:
            continue
        if _is_mapping_of_mappings(value):
            rows = [{_KEY_COL: k, **v} for k, v in value.items()]
            out.append(f"- {key}:")
            out.extend(_render_table(rows, _KEY_COL, "  "))
        elif _is_record_list(value):
            out.append(f"- {key}:")
            out.extend(_render_table(value, None, "  "))
        elif isinstance(value, dict):  # plain nested mapping (combination)
            out.append(f"- {key}:")
            for kk, vv in value.items():
                out.append(f"  - {kk}: {_flow(vv)}")
        elif isinstance(value, list) and not _is_record_list(value) \
                and any(isinstance(x, dict) for x in value):
            # mixed list (rules: str | {text, strength}) → bullets
            out.append(f"- {key}:")
            for elem in value:
                out.append(f"  - {_flow(elem)}")
        else:  # scalar, None, or list of scalars
            out.append(f"- {key}: {_flow(value)}")
    return out


def _parse_fields(lines: list[str]) -> dict:
    out: dict = {}
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if not stripped.startswith("- "):
            i += 1
            continue
        body = stripped[2:]
        key, sep, rest = body.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest:  # inline scalar
            out[key] = _unflow(rest)
            i += 1
            continue
        # block follows: gather indented lines (tables `|` or sub-bullets `-`)
        block: list[str] = []
        j = i + 1
        while j < n:
            nxt = lines[j]
            if nxt.strip() == "":
                j += 1
                continue
            if nxt.startswith("  ") and (nxt.strip().startswith("|")
                                         or nxt.strip().startswith("- ")):
                block.append(nxt)
                j += 1
            else:
                break
        if block and block[0].strip().startswith("|"):
            data, _ = _parse_table(block)
            out[key] = data
        elif block:  # sub-bullets
            sub_inline = [b.strip()[2:] for b in block]  # drop "- "
            # nested mapping (combination: kk: vv) vs list (rules)
            if all(":" in s and not s.lstrip().startswith(("{", "[", "'", '"'))
                   for s in sub_inline):
                nested: dict = {}
                for s in sub_inline:
                    kk, _, vv = s.partition(":")
                    nested[kk.strip()] = _unflow(vv.strip())
                out[key] = nested
            else:
                out[key] = [_unflow(s) for s in sub_inline]
        else:
            out[key] = None
        i = j
    return out


# ── items document ────────────────────────────────────────────────────────────
def items_to_markdown(doc: dict) -> str:
    out: list[str] = []
    for top_key, value in doc.items():
        out.append(f"## {top_key}")
        out.append("")
        if value is None:
            out.append("_null_")
            out.append("")
        elif isinstance(value, list):  # records (stufe1 / phase_t / phase_e)
            for entry in value:
                out.append(f"### {entry.get('id', '?')}")
                out.extend(_render_fields(entry, drop=("id",)))
                out.append("")
        else:  # plain mapping (meta / phase_e_gate)
            out.extend(_render_fields(value))
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def items_from_markdown(md: str) -> dict:
    doc: dict = {}
    for top_key, body in _split_sections(md, "## "):
        records, fields = _split_records(body)
        if records is not None:
            doc[top_key] = [{"id": rid, **_parse_fields(rlines)}
                            for rid, rlines in records]
        elif fields.strip() == "_null_":
            doc[top_key] = None
        else:
            doc[top_key] = _parse_fields(fields.splitlines())
    return doc


# ── annotations document ──────────────────────────────────────────────────────
def annotations_to_markdown(doc: dict) -> str:
    out: list[str] = []
    for stem, items in doc.items():
        out.append(f"## {stem}")
        out.append("")
        for item_id, entry in items.items():
            out.append(f"### {item_id}")
            out.extend(_render_fields(entry))
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def annotations_from_markdown(md: str) -> dict:
    doc: dict = {}
    for stem, body in _split_sections(md, "## "):
        records, _ = _split_records(body)
        doc[stem] = {rid: _parse_fields(rlines)
                     for rid, rlines in (records or [])}
    return doc


# ── section splitting ─────────────────────────────────────────────────────────
def _split_sections(md: str, marker: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    cur_key: str | None = None
    buf: list[str] = []
    for line in md.splitlines():
        if line.startswith(marker) and not line.startswith(marker + "#"):
            if cur_key is not None:
                sections.append((cur_key, "\n".join(buf)))
            cur_key = line[len(marker):].strip()
            buf = []
        elif cur_key is not None:
            buf.append(line)
    if cur_key is not None:
        sections.append((cur_key, "\n".join(buf)))
    return sections


def _split_records(body: str) -> tuple[list[tuple[str, list[str]]] | None, str]:
    """Split a block body into ``### id`` records, or return (None, body)."""
    if "### " not in body:
        return None, body
    records: list[tuple[str, list[str]]] = []
    cur_id: str | None = None
    buf: list[str] = []
    for line in body.splitlines():
        if line.startswith("### "):
            if cur_id is not None:
                records.append((cur_id, buf))
            cur_id = line[4:].strip()
            buf = []
        elif cur_id is not None:
            buf.append(line)
    if cur_id is not None:
        records.append((cur_id, buf))
    return records, body


# ── file IO + validation gate ─────────────────────────────────────────────────
def _leading_header(path: Path) -> str:
    """Return the leading comment/blank block of a YAML file, verbatim."""
    if not path.is_file():
        return ""
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "" or line.lstrip().startswith("#"):
            out.append(line)
        else:
            break
    text = "\n".join(out).rstrip()
    return text + "\n\n" if text else ""


def _dump_yaml(doc: dict) -> str:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True,
                          default_flow_style=False, width=100)


def _validate_items(path: Path) -> None:
    _config_loader._load_file(path)  # raises ConfigError on any problem


def _validate_annotations(path: Path) -> None:
    _annotations._load_file(path)  # raises AnnotationError on any problem


def _class_files(directory: Path, only: str | None) -> list[Path]:
    files = sorted(p for p in directory.glob("*.yaml"))
    if only:
        files = [p for p in files if p.stem == only]
    return files


# ── high-level export / import ────────────────────────────────────────────────
def export_items(only: str | None = None) -> list[Path]:
    _ITEMS_MD_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for yaml_path in _class_files(_CONFIG_DIR, only):
        doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        md_path = _ITEMS_MD_DIR / f"{yaml_path.stem}.md"
        md_path.write_text(items_to_markdown(doc), encoding="utf-8")
        written.append(md_path)
    return written


def export_annotations(only: str | None = None) -> list[Path]:
    _ANNOTATIONS_MD_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for yaml_path in _class_files(_ANNOTATIONS_DIR, only):
        doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        md_path = _ANNOTATIONS_MD_DIR / f"{yaml_path.stem}.md"
        md_path.write_text(annotations_to_markdown(doc), encoding="utf-8")
        written.append(md_path)
    return written


def _import_one(md_path: Path, yaml_path: Path, parse, validate) -> None:
    doc = parse(md_path.read_text(encoding="utf-8"))
    header = _leading_header(yaml_path)
    body = _dump_yaml(doc)
    tmp = yaml_path.with_suffix(".yaml.tmp")
    tmp.write_text(header + body, encoding="utf-8")
    try:
        validate(tmp)  # raises if the rebuilt YAML is invalid
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    if yaml_path.is_file():
        yaml_path.replace(yaml_path.with_suffix(".yaml.bak"))
    tmp.replace(yaml_path)


def import_items(only: str | None = None) -> list[Path]:
    written = []
    for md_path in sorted(_ITEMS_MD_DIR.glob("*.md")):
        if md_path.stem not in _config_loader.VALID_CLASSES:
            continue  # skip README.md and any non-class file
        if only and md_path.stem != only:
            continue
        yaml_path = _CONFIG_DIR / f"{md_path.stem}.yaml"
        _import_one(md_path, yaml_path, items_from_markdown, _validate_items)
        written.append(yaml_path)
    return written


def import_annotations(only: str | None = None) -> list[Path]:
    written = []
    for md_path in sorted(_ANNOTATIONS_MD_DIR.glob("*.md")):
        if md_path.stem not in _config_loader.VALID_CLASSES:
            continue  # skip README.md and any non-class file
        if only and md_path.stem != only:
            continue
        yaml_path = _ANNOTATIONS_DIR / f"{md_path.stem}.yaml"
        _import_one(md_path, yaml_path, annotations_from_markdown,
                    _validate_annotations)
        written.append(yaml_path)
    return written


# ── CLI ───────────────────────────────────────────────────────────────────────
def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="md_convert", description=__doc__)
    parser.add_argument("direction", choices=("export", "import"))
    parser.add_argument("--scope", choices=("all", "items", "annotations"),
                        default="all")
    parser.add_argument("--class", dest="cls", default=None,
                        help="restrict to one class stem (structured|semi|loosely)")
    args = parser.parse_args(argv)

    do_items = args.scope in ("all", "items")
    do_ann = args.scope in ("all", "annotations")
    written: list[Path] = []
    if args.direction == "export":
        if do_items:
            written += export_items(args.cls)
        if do_ann:
            written += export_annotations(args.cls)
        print(f"exported {len(written)} markdown file(s):")
    else:
        if do_items:
            written += import_items(args.cls)
        if do_ann:
            written += import_annotations(args.cls)
        print(f"imported {len(written)} yaml file(s) (validated):")
    for p in written:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
