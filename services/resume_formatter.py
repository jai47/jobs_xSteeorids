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


# Mirrors resume_format/AI_Resume_Template_One_Page.tex — same document class,
# packages, and section typography, so the no-LLM fallback still matches the
# required one-page format even when no LLM key is configured.
LATEX_PREAMBLE = r"""\documentclass[a4paper,8pt]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{parskip}
\usepackage[scale=0.9,top=.4in,bottom=.4in]{geometry}
\usepackage{enumitem}
\usepackage{titlesec}
\usepackage{fontawesome5}
\usepackage[colorlinks=true,urlcolor=black,linkcolor=black,citecolor=black]{hyperref}
\titleformat{\section}{\Large\scshape\raggedright}{}{0em}{}[\titlerule]
\titlespacing{\section}{1pt}{2pt}{2pt}
\pagestyle{empty}
"""

# Canonical section order from the template — anything not in this map is
# dropped rather than appended, since the template has no room for extra
# sections (e.g. Summary/Objective/Profile).
CANONICAL_SECTION_ORDER = ["Skills", "Work Experience", "Education", "Projects", "Awards and Certifications"]

_SECTION_ALIASES = {
    "skills": "Skills",
    "technical skills": "Skills",
    "core competencies": "Skills",
    "languages": "Skills",
    "experience": "Work Experience",
    "work experience": "Work Experience",
    "professional experience": "Work Experience",
    "employment": "Work Experience",
    "education": "Education",
    "projects": "Projects",
    "certifications": "Awards and Certifications",
    "achievements": "Awards and Certifications",
    "awards and certifications": "Awards and Certifications",
}

_GITHUB_RE = re.compile(r"https?://(?:www\.)?github\.com/\S+", re.I)
_LINKEDIN_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/\S+", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")


def _extract_header_fields(contact: str, raw_text: str) -> dict[str, str]:
    """Pull email/phone/github/linkedin out of the contact line and full text."""
    fields: dict[str, str] = {}
    email_match = _EMAIL_RE.search(contact) or _EMAIL_RE.search(raw_text)
    if email_match:
        fields["email"] = email_match.group(0)
    phone_match = _PHONE_RE.search(contact) or _PHONE_RE.search(raw_text)
    if phone_match:
        fields["phone"] = phone_match.group(0).strip()
    github_match = _GITHUB_RE.search(raw_text)
    if github_match:
        fields["github"] = github_match.group(0).rstrip(".,)")
    linkedin_match = _LINKEDIN_RE.search(raw_text)
    if linkedin_match:
        fields["linkedin"] = linkedin_match.group(0).rstrip(".,)")
    return fields


def _group_by_canonical_section(struct: ResumeStructure) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for section in struct.sections:
        canonical = _SECTION_ALIASES.get(section.title.strip().lower())
        if canonical is None:
            continue
        grouped.setdefault(canonical, []).extend(section.lines)
    return grouped


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
    max_lines_per_section: int = 10,
) -> str:
    """Render a one-page LaTeX resume matching resume_format/AI_Resume_Template_One_Page.tex,
    without an LLM: only the template's five canonical sections are emitted, in
    the template's fixed order, with the same header/typography.

    max_lines_per_section is a truncation knob the caller can shrink (10 -> 6 -> 3)
    across retries if the compiled PDF still exceeds one page.
    """
    plain = _strip_markdown(raw_text)
    struct = parse_resume_sections(plain)
    name = _escape_latex(struct.name or "Resume")
    header_fields = _extract_header_fields(struct.contact, raw_text)

    header_segments = []
    if header_fields.get("email"):
        header_segments.append(rf"\faEnvelope\ {_escape_latex(header_fields['email'])}")
    if header_fields.get("phone"):
        header_segments.append(rf"\faMobile\ {_escape_latex(header_fields['phone'])}")
    if header_fields.get("github"):
        header_segments.append(rf"\href{{{header_fields['github']}}}{{\faGithub\ GitHub}}")
    if header_fields.get("linkedin"):
        header_segments.append(rf"\href{{{header_fields['linkedin']}}}{{\faLinkedin\ LinkedIn}}")

    body_parts: list[str] = [
        LATEX_PREAMBLE,
        r"\begin{document}",
        r"\begin{center}",
        rf"{{\Huge \textbf{{{name}}}}}\\[6pt]",
    ]
    if header_segments:
        body_parts.append(" $|$\n".join(header_segments))
    body_parts.append(r"\end{center}")
    if job_title and company:
        body_parts.append(
            rf"\small\textit{{Target: {_escape_latex(job_title)} @ {_escape_latex(company)}}}"
        )

    grouped = _group_by_canonical_section(struct)
    for canonical in CANONICAL_SECTION_ORDER:
        lines = grouped.get(canonical)
        if not lines:
            continue
        body_parts.append(rf"\section{{{canonical}}}")
        if canonical == "Skills":
            body_parts.append(_escape_latex(", ".join(lines[:max_lines_per_section])))
        else:
            body_parts.append(r"\begin{itemize}[leftmargin=2em,itemsep=2pt]")
            for line in lines[:max_lines_per_section]:
                body_parts.append(rf"\item {_escape_latex(line)}")
            body_parts.append(r"\end{itemize}")

    body_parts.append(r"\end{document}")
    return "\n".join(body_parts)
