from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def safe_pdf_export(markdown_path: Path) -> Path | None:
    """Convert a Markdown file to PDF using pandoc if available.

    Returns the PDF path on success, None otherwise.
    """
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return None
    pdf_path = markdown_path.with_suffix(".pdf")
    try:
        subprocess.run(
            [pandoc, str(markdown_path), "-o", str(pdf_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return pdf_path
    except Exception:
        return None


def relative_path(path: Path | str | None, base: Path) -> str:
    """Return path relative to base, or the absolute path if not under base."""
    if not path:
        return "n/a"
    candidate = Path(path)
    try:
        return str(candidate.relative_to(base))
    except ValueError:
        return str(candidate)
