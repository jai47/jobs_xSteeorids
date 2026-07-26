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

    def _looks_like_contact(line: str) -> bool:
        lower = line.lower().strip()
        # Local-format meta lines contain "@ company" but are not contact info.
        if lower.startswith(("tailored for", "applying for", "target:")):
            return False
        has_email = bool(_EMAIL_RE.search(line))
        has_phone = bool(_PHONE_RE.search(line))
        has_link = "linkedin" in lower or "github" in lower or lower.startswith(("http://", "https://"))
        return has_email or has_phone or has_link or ("|" in line and (has_email or has_phone or has_link))

    # Prefer a real person name for the title — never promote a phone/email line.
    # Uppercase names are common on resumes; only reject known section headers.
    name_idx = 0
    for i, line in enumerate(non_empty[:4]):
        cleaned = line.strip().rstrip(":").lower()
        if _looks_like_contact(line):
            continue
        if cleaned in SECTION_HEADERS:
            continue
        if cleaned.startswith(("tailored for", "applying for", "target:")):
            continue
        name_idx = i
        break
    struct.name = non_empty[name_idx].strip()
    if _looks_like_contact(struct.name) or struct.name.strip().rstrip(":").lower() in SECTION_HEADERS:
        struct.name = "Resume"

    idx = name_idx + 1
    # Skip meta "Tailored for …" lines before the real contact row.
    while idx < len(non_empty):
        lower = non_empty[idx].strip().lower()
        if lower.startswith(("tailored for", "applying for", "target:")):
            idx += 1
            continue
        break
    if idx < len(non_empty) and _looks_like_contact(non_empty[idx]):
        struct.contact = non_empty[idx].strip()
        idx += 1

    current: ResumeSection | None = None
    for line in non_empty[idx:]:
        stripped = line.strip()
        if not stripped or stripped in {"•", "-", "*"}:
            continue
        lower = stripped.lower()
        if lower.startswith(("tailored for", "applying for", "target:")):
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
\usepackage{tabularx}
\usepackage{array}
\usepackage{enumitem}
\usepackage{titlesec}
\usepackage{fontawesome5}
\usepackage[colorlinks=true,urlcolor=black,linkcolor=black,citecolor=black]{hyperref}
\newcolumntype{C}{>{\centering\arraybackslash}X}
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

_GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w.\-/]+", re.I)
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/[\w.\-/]+", re.I)


def _as_url(value: str) -> str:
    """Resume text often omits the scheme; hyperref needs an absolute URL."""
    return value if value.lower().startswith(("http://", "https://")) else f"https://{value}"
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")


def _extract_header_fields(
    contact: str,
    raw_text: str,
    *,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Pull email/phone/github/linkedin out of the contact line and full text."""
    fields: dict[str, str] = {}
    email_match = _EMAIL_RE.search(contact) or _EMAIL_RE.search(raw_text)
    if email_match:
        fields["email"] = email_match.group(0)
    phone_match = _PHONE_RE.search(contact) or _PHONE_RE.search(raw_text)
    if phone_match:
        fields["phone"] = phone_match.group(0).strip()
    github_match = _GITHUB_RE.search(contact) or _GITHUB_RE.search(raw_text)
    if github_match:
        fields["github"] = github_match.group(0).rstrip(".,)")
    linkedin_match = _LINKEDIN_RE.search(contact) or _LINKEDIN_RE.search(raw_text)
    if linkedin_match:
        fields["linkedin"] = linkedin_match.group(0).rstrip(".,)")
    if overrides:
        for key, value in overrides.items():
            if value and not fields.get(key):
                fields[key] = value.strip()
    return fields


def merge_contact_overrides(*sources: str) -> dict[str, str]:
    """Union contact fields from master resume, tailored markdown, user email, etc."""
    merged: dict[str, str] = {}
    for source in sources:
        if not source:
            continue
        chunk = _extract_header_fields("", source)
        for key, value in chunk.items():
            if value and not merged.get(key):
                merged[key] = value
    return merged


_BULLET_PREFIXES = ("–", "—", "•", "▪", "‣", "·")

_DATE_TOKEN = (
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{2,4}"
    r"|\d{1,2}/\d{4}|\d{4}"
)
_DATE_RANGE_RE = re.compile(
    rf"^(?:{_DATE_TOKEN})\s*(?:–|—|-{{1,2}}|to|until)\s*"
    rf"(?:{_DATE_TOKEN}|present|current|now|ongoing|date)\.?$",
    re.I,
)
_SINGLE_DATE_RE = re.compile(rf"^(?:{_DATE_TOKEN})\.?$", re.I)

_ROLE_HINTS = (
    "engineer", "developer", "intern", "manager", "analyst", "scientist",
    "designer", "consultant", "lead", "architect", "specialist", "researcher",
    "administrator", "associate", "director", "officer", "freelance", "trainee",
)
_ORG_HINTS = ("university", "institute", "college", "school", "academy", "polytechnic")

_SKILL_LABEL_RE = re.compile(r"^([A-Z][A-Za-z0-9 /&+.-]{2,40}):\s*(.+)$")


@dataclass
class ResumeEntry:
    """One job / degree / project: a bold heading, optional role line, date, bullets."""

    heading: str = ""
    subheading: str = ""
    date: str = ""
    bullets: list[str] = field(default_factory=list)


def _is_date_line(line: str) -> bool:
    return bool(_DATE_RANGE_RE.match(line) or _SINGLE_DATE_RE.match(line))


def _is_bullet_line(line: str) -> bool:
    return line.startswith(_BULLET_PREFIXES)


def _strip_bullet_prefix(line: str) -> str:
    return re.sub(r"^[–—•▪‣·\-\*]+\s*", "", line).strip()


def _looks_like_role(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in _ROLE_HINTS)


def _looks_like_org(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in _ORG_HINTS)


def parse_section_entries(lines: list[str]) -> list[ResumeEntry]:
    """Group flat resume lines into entries.

    Text extracted from PDFs arrives flattened and often wrapped mid-sentence,
    with dates interleaved from a second column. Dashed lines are achievements;
    plain lines are headings; lines starting lowercase continue the previous
    achievement instead of becoming their own bullet.
    """
    entries: list[ResumeEntry] = []
    current: ResumeEntry | None = None
    pending_date = ""

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        if _is_date_line(line):
            if current is not None and not current.date:
                current.date = line
            else:
                pending_date = line
            continue

        if _is_bullet_line(line):
            text = _strip_bullet_prefix(line)
            if not text:
                continue
            if current is None:
                current = ResumeEntry()
                entries.append(current)
            current.bullets.append(text)
            continue

        # Wrapped continuation of the previous achievement.
        if current is not None and current.bullets and line[:1].islower():
            current.bullets[-1] = f"{current.bullets[-1].rstrip()} {line}"
            continue

        # Continuation of a heading that wrapped before any bullets existed.
        if current is not None and not current.bullets and line[:1].islower():
            if current.subheading:
                current.subheading = f"{current.subheading.rstrip()} {line}"
            else:
                current.heading = f"{current.heading.rstrip()} {line}"
            continue

        if current is None or current.bullets:
            current = ResumeEntry(heading=line, date=pending_date)
            pending_date = ""
            entries.append(current)
        elif not current.subheading:
            current.subheading = line
        else:
            current.subheading = f"{current.subheading}, {line}"

    return entries


def _orient_entry(entry: ResumeEntry, canonical: str) -> ResumeEntry:
    """Put the organisation on the bold line and the role/degree underneath."""
    if not entry.subheading:
        return entry

    if canonical == "Work Experience":
        if _looks_like_role(entry.heading) and not _looks_like_role(entry.subheading):
            entry.heading, entry.subheading = entry.subheading, entry.heading
    elif canonical == "Education":
        if not _looks_like_org(entry.heading) and _looks_like_org(entry.subheading):
            entry.heading, entry.subheading = entry.subheading, entry.heading
    return entry


def _render_entry(entry: ResumeEntry, *, bullet_budget: int) -> tuple[list[str], int]:
    """Render one entry as a header row plus achievement bullets."""
    parts: list[str] = []
    heading = entry.heading.strip()
    subheading = entry.subheading.strip()

    # "Project | Tech, Stack" -> bold name, italic stack.
    if "|" in heading and not subheading:
        name, _, stack = heading.partition("|")
        heading = name.strip()
        subheading = stack.strip()

    if heading or entry.date:
        parts.append(r"\begin{tabularx}{\linewidth}{@{}Xr@{}}")
        parts.append(
            rf"\textbf{{{_escape_latex(heading)}}} & {_escape_latex(entry.date)}\\"
        )
        if subheading:
            parts.append(rf"\textit{{{_escape_latex(subheading)}}} & \\")
        parts.append(r"\end{tabularx}")
    elif subheading:
        parts.append(rf"\textit{{{_escape_latex(subheading)}}}")

    used = 0
    bullets = [b for b in entry.bullets if b.strip()][:bullet_budget]
    if bullets:
        parts.append(r"\begin{itemize}[leftmargin=1.4em,itemsep=1pt,topsep=2pt,parsep=0pt]")
        for bullet in bullets:
            parts.append(rf"\item {_escape_latex(bullet.strip())}")
            used += 1
        parts.append(r"\end{itemize}")

    return parts, used


def _render_skills(lines: list[str], max_lines: int) -> list[str]:
    """Render skills as labelled rows (Languages: ...) instead of one blob."""
    parts: list[str] = []
    labelled: list[tuple[str, str]] = []
    loose: list[str] = []

    for line in lines[:max_lines]:
        cleaned = _strip_bullet_prefix(line)
        if not cleaned:
            continue
        match = _SKILL_LABEL_RE.match(cleaned)
        if match:
            labelled.append((match.group(1).strip(), match.group(2).strip()))
        elif labelled:
            label, value = labelled[-1]
            labelled[-1] = (label, f"{value} {cleaned}")
        else:
            loose.append(cleaned)

    if loose:
        parts.append(_escape_latex(", ".join(loose)))
    for label, value in labelled:
        parts.append(
            rf"\textbf{{{_escape_latex(label)}:}} {_escape_latex(value.rstrip(', '))}\\"
        )
    return parts


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
    contact_overrides: dict[str, str] | None = None,
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
    header_fields = _extract_header_fields(
        struct.contact, raw_text, overrides=contact_overrides
    )

    header_segments = []
    if header_fields.get("email"):
        header_segments.append(rf"\faEnvelope\ {_escape_latex(header_fields['email'])}")
    if header_fields.get("phone"):
        header_segments.append(rf"\faMobile\ {_escape_latex(header_fields['phone'])}")
    if header_fields.get("github"):
        header_segments.append(
            rf"\href{{{_as_url(header_fields['github'])}}}{{\faGithub\ GitHub}}"
        )
    if header_fields.get("linkedin"):
        header_segments.append(
            rf"\href{{{_as_url(header_fields['linkedin'])}}}{{\faLinkedin\ LinkedIn}}"
        )

    body_parts: list[str] = [
        LATEX_PREAMBLE,
        r"\begin{document}",
        r"\begin{tabularx}{\linewidth}{@{}C@{}}",
        rf"{{\Huge \textbf{{{name}}}}}\\[6pt]",
    ]
    if header_segments:
        body_parts.append(" $|$\n".join(header_segments))
    body_parts.append(r"\end{tabularx}")
    # No "Target: role @ company" line — the template's only subheading is the
    # contact/communication row (email | phone | GitHub | LinkedIn).

    grouped = _group_by_canonical_section(struct)
    for canonical in CANONICAL_SECTION_ORDER:
        lines = grouped.get(canonical)
        if not lines:
            continue
        body_parts.append(rf"\section{{{canonical}}}")

        if canonical == "Skills":
            body_parts.extend(_render_skills(lines, max_lines_per_section))
            continue

        if canonical == "Awards and Certifications":
            body_parts.append(r"\begin{itemize}[leftmargin=1.4em,itemsep=1pt,topsep=2pt,parsep=0pt]")
            for line in lines[:max_lines_per_section]:
                cleaned = _strip_bullet_prefix(line)
                if cleaned:
                    body_parts.append(rf"\item {_escape_latex(cleaned)}")
            body_parts.append(r"\end{itemize}")
            continue

        entries = [
            _orient_entry(entry, canonical) for entry in parse_section_entries(lines)
        ]
        remaining = max_lines_per_section
        for entry in entries:
            if remaining <= 0 and not entry.heading:
                continue
            rendered, used = _render_entry(entry, bullet_budget=max(remaining, 0))
            body_parts.extend(rendered)
            remaining -= used

    body_parts.append(r"\end{document}")
    return "\n".join(body_parts)
