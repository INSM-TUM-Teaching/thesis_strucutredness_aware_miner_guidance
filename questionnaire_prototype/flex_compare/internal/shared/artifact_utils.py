from __future__ import annotations

import io
import mimetypes
import zipfile
from pathlib import Path
from typing import Any, Dict, List


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def collect_artifacts(output_dir: Path) -> List[Dict[str, Any]]:
    """Walk output_dir and return a list of artifact dicts."""
    artifacts: List[Dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(output_dir))
        artifacts.append(
            {
                "name": rel,
                "path": str(path),
                "mime": _guess_mime(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return artifacts


def build_artifacts_zip(output_dir: Path, artifacts: List[Dict[str, Any]]) -> bytes:
    """Zip all artifact files into an in-memory bytes object."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for artifact in artifacts:
            abs_path = Path(artifact["path"])
            if abs_path.exists() and abs_path.is_file():
                zf.write(abs_path, arcname=artifact["name"])
    return buffer.getvalue()
