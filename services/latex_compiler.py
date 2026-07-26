"""Compile LaTeX resume source to PDF using whichever engine is installed.

Prefers tectonic (self-contained), then falls back to a local TeX
installation (pdflatex / xelatex from MacTeX / TeX Live).
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

log = logging.getLogger(__name__)

# Order of preference. tectonic auto-fetches packages; pdflatex/xelatex use the
# local TeX tree. The template compiles cleanly under all three.
_ENGINES = ("tectonic", "pdflatex", "xelatex")


def available_engine() -> str | None:
    """Return the first available LaTeX engine, or None if none is installed."""
    for engine in _ENGINES:
        if shutil.which(engine):
            return engine
    return None


def tectonic_available() -> bool:
    """Back-compat name: True when *any* LaTeX engine is available for compilation."""
    return available_engine() is not None


def count_pdf_pages(pdf_bytes: bytes) -> int:
    """Return the page count of a rendered PDF, used to enforce one-page resumes."""
    from pdfminer.pdfpage import PDFPage

    return len(list(PDFPage.get_pages(BytesIO(pdf_bytes))))


def _build_command(engine: str, tex_path: Path) -> list[str]:
    if engine == "tectonic":
        return ["tectonic", "--keep-logs", str(tex_path)]
    # pdflatex / xelatex: run non-interactively and stop on first error.
    return [
        engine,
        "-interaction=nonstopmode",
        "-halt-on-error",
        tex_path.name,
    ]


def _normalize_legacy_template_source(source: str) -> str:
    """Repair a legacy template ambiguity.

    A line beginning with ``[...`` immediately after ``\\`` is parsed by TeX
    as the optional vertical-space argument to the line break. Older cached
    resume sources can still contain this placeholder pattern.
    """
    return re.sub(r"(\\\\)\s*\n(\s*)(?=\[)", r"\1{}\n\2", source)


def compile_latex_to_pdf(latex_source: str) -> bytes:
    """Compile LaTeX source to PDF bytes. Raises RuntimeError on failure."""
    engine = available_engine()
    if engine is None:
        raise RuntimeError("No LaTeX engine installed (tectonic, pdflatex, or xelatex)")

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = Path(tmpdir) / "resume.tex"
        tex_path.write_text(_normalize_legacy_template_source(latex_source), encoding="utf-8")
        result = subprocess.run(
            _build_command(engine, tex_path),
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        pdf_path = Path(tmpdir) / "resume.pdf"
        if not pdf_path.is_file():
            detail = (result.stdout or result.stderr or "LaTeX compilation failed").strip()
            log.warning("%s failed: %s", engine, detail[-500:])
            raise RuntimeError(detail)
        return pdf_path.read_bytes()
