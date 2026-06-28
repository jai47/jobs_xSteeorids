"""Structure plain resume text and render professional LaTeX without LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SECTION_HEADERS = {
    "career objective",
    "objective",
    "summary",
    "professional summary",
    "profile",
    "experience",
    "work experience",
    "professional experience",
    "employment",
    "education",
    "skills",
    "technical skills",
    "core competencies",
    "projects",
    "certifications",
    "achievements",
    "languages",
    "interests",
    "volunteer",
}


@dataclass
class ResumeSection:
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class ResumeStructure:
    name: str = ""
    contact: str = ""
    sections: list[ResumeSection] = field(default_factory=list)


def _is_section_header(line: str) -> bool:
    cleaned = line.strip().rstrip(":").lower()
    if cleaned in SECTION_HEADERS:
        return True
    if line.isupper() and 3 <= len(line.strip()) <= 40 and line.count(" ") <= 4:
        return True
    return False


def _normalize_bullet(line: str) -> str:
    return re.sub(r"^[•\-\*\u2022]\s*", "", line.strip())


def parse_resume_sections(text: str) -> ResumeStructure:
    """Split raw resume text into name, contact, and sections."""
    lines = [line.rstrip() for line in text.splitlines()]
    non_empty = [line for line in lines if line.strip()]

    struct = ResumeStructure()
    if not non_empty:
        return struct

    struct.name = non_empty[0].strip()
    idx = 1
    if idx < len(non_empty) and (
        "@" in non_empty[idx]
        or re.search(r"\+?\d[\d\s\-()]{7,}", non_empty[idx])
        or "|" in non_empty[idx]
        or "linkedin" in non_empty[idx].lower()
    ):
        struct.contact = non_empty[idx].strip()
        idx += 1

    current: ResumeSection | None = None
    for line in non_empty[idx:]:
        stripped = line.strip()
        if not stripped or stripped in {"•", "-", "*"}:
            continue
        if _is_section_header(stripped):
            title = stripped.rstrip(":").strip()
            if title.isupper():
                title = title.title()
            current = ResumeSection(title=title)
            struct.sections.append(current)
            continue
        cleaned = _normalize_bullet(stripped)
        if not cleaned:
            continue
        if current is None:
            current = ResumeSection(title="Profile")
            struct.sections.append(current)
        current.lines.append(cleaned)

    return struct


def format_tailored_markdown(
    raw_text: str,
    *,
    job_title: str,
    company: str,
    ai_tailored: bool = False,
) -> str:
    """Build readable markdown from raw resume text."""
    struct = parse_resume_sections(raw_text)
    parts: list[str] = []

    if ai_tailored:
        parts.append(f"# {struct.name or 'Resume'}")
    else:
        parts.append(f"# {struct.name or 'Resume'}")
        parts.append(
            f"*Tailored for **{job_title}** @ **{company}*** "
            f"(formatted locally — configure an LLM key in Settings for AI rewriting)"
        )

    if struct.contact:
        parts.append(struct.contact)

    for section in struct.sections:
        parts.append(f"\n## {section.title}")
        for line in section.lines:
            if line.startswith(("- ", "* ")):
                parts.append(line)
            else:
                parts.append(f"- {line}")

    return "\n".join(parts).strip()


def _escape_latex(text: str) -> str:
    replacements = (
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
    )
    result = text
    for char, escaped in replacements:
        result = result.replace(char, escaped)
    return result


LATEX_PREAMBLE = r"""\documentclass[10pt,letterpaper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[margin=0.5in, top=0.45in, bottom=0.45in]{geometry}
\usepackage{enumitem}
\usepackage{titlesec}
\usepackage{hyperref}
\hypersetup{hidelinks}
\pagenumbering{gobble}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0pt}
\titlespacing{\section}{0pt}{0.35em}{0.15em}
\titleformat{\section}{\large\bfseries\uppercase}{}{0em}{}[\titlerule]
"""


def _strip_markdown(text: str) -> str:
    """Convert markdown resume back to plain text for section parsing."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith("#"):
            lines.append(stripped.lstrip("#").strip().upper())
            continue
        if stripped.startswith(("- ", "* ")):
            lines.append("• " + stripped[2:].strip())
            continue
        stripped = re.sub(r"\*([^*]+)\*", r"\1", stripped)
        lines.append(stripped)
    return "\n".join(lines)


def build_structured_latex(
    raw_text: str,
    *,
    job_title: str = "",
    company: str = "",
) -> str:
    """Render a professional single-page LaTeX resume from plain or markdown text."""
    plain = _strip_markdown(raw_text)
    struct = parse_resume_sections(plain)
    name = _escape_latex(struct.name or "Resume")
    contact = _escape_latex(struct.contact)

    body_parts: list[str] = [
        LATEX_PREAMBLE,
        r"\begin{document}",
        rf"\begin{{center}}",
        rf"{{\Huge\bfseries {name}}}\\[0.15em]",
    ]
    if contact:
        body_parts.append(rf"\small {contact}\\")
    if job_title and company:
        body_parts.append(
            rf"\small\textit{{Target: {_escape_latex(job_title)} @ {_escape_latex(company)}}}\\"
        )
    body_parts.append(r"\end{center}")
    body_parts.append(r"\vspace{0.2em}")

    for section in struct.sections:
        body_parts.append(rf"\section{{{_escape_latex(section.title)}}}")
        if len(section.lines) == 1 and len(section.lines[0]) > 80:
            body_parts.append(_escape_latex(section.lines[0]) + r"\\")
        else:
            body_parts.append(r"\begin{itemize}[leftmargin=*, nosep, topsep=0pt]")
            for line in section.lines[:12]:
                body_parts.append(rf"\item {_escape_latex(line)}")
            body_parts.append(r"\end{itemize}")

    body_parts.append(r"\end{document}")
    return "\n".join(body_parts)
