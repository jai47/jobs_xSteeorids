"""Compile LaTeX resume source to PDF using tectonic."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def tectonic_available() -> bool:
    return shutil.which("tectonic") is not None


def compile_latex_to_pdf(latex_source: str) -> bytes:
    """Compile LaTeX source to PDF bytes. Raises RuntimeError on failure."""
    if not tectonic_available():
        raise RuntimeError("tectonic is not installed")

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = Path(tmpdir) / "resume.tex"
        tex_path.write_text(latex_source, encoding="utf-8")
        result = subprocess.run(
            ["tectonic", "--keep-logs", str(tex_path)],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        pdf_path = Path(tmpdir) / "resume.pdf"
        if result.returncode != 0 or not pdf_path.is_file():
            detail = (result.stderr or result.stdout or "LaTeX compilation failed").strip()
            log.warning("tectonic failed: %s", detail[:500])
            raise RuntimeError(detail)
        return pdf_path.read_bytes()
