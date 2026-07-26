"""Generate a strict single-page LaTeX resume via LLM, using the canonical
template in resume_format/AI_Resume_Template_One_Page.tex as the fixed
instruction — the LLM only fills in placeholders and repeats entry blocks,
it never invents a different document structure."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from llm.client import LLMError, call_llm, parse_llm_json

log = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent.parent / "resume_format" / "AI_Resume_Template_One_Page.tex"

# Markers that must survive in the LLM's output for it to count as "used the template"
# rather than free-styling a different document.
_TEMPLATE_FINGERPRINT = ("fontawesome5", "\\pagestyle{empty}")
_MAX_JOB_DESCRIPTION_CHARS = 2400
_MAX_RESUME_CHARS = 7500
_MAX_TEMPLATE_CHARS = 6500
_MAX_OUTPUT_TOKENS = 3000

LATEX_PROMPT_TEMPLATE = """
Fill this fixed one-page LaTeX resume for the specified job.

TARGET ROLE: {job_title} at {company}
JOB DESCRIPTION (rank relevance and keywords; never copy unsupported claims):
{job_description}

REQUIRED CONTACT (render directly below the name):
{contact_block}

CANDIDATE RESUME (the only source of candidate facts):
{tailored_markdown}

RULES:
- Copy the template structure/preamble. Replace or remove every placeholder.
- Header: full name only in Huge; then REQUIRED CONTACT icons. No Target/Applying line.
- Reorder Skills for the role. Keep 2-3 relevant jobs and 2-3 relevant projects.
- Truthfully tighten bullets around JD keywords; never invent facts or metrics.
- Company/role/school/degree/project/stack/date go in tabularx, NEVER in \\item.
- Each \\item is one complete achievement sentence; join wrapped source fragments.
- No Summary/Profile. Preserve template fonts/margins. Output exactly one page.
- Produce valid pdflatex with balanced braces and no unresolved placeholders.

--- TEMPLATE START ---
{template}
--- TEMPLATE END ---

Return ONLY JSON: {{"latex_source": "<the filled-in template as a full document>"}}
"""

OVERFLOW_SUFFIX = """

Your previous attempt FAILED validation: it either did not compile with pdflatex,
or it rendered MORE THAN ONE PAGE. Regenerate carefully:
- Drop the least relevant Work Experience entry (keep at most 2) and/or Project.
- Shorten every bullet to a single tight line.
- Keep the exact same template structure, packages, and spacing — do not shrink
  fonts or margins to force a fit.
- Huge title = full name ONLY. Contact icons on the next line only — never a
  "Target:" / "Applying for" job line under the name. Keep REQUIRED CONTACT icons.
- Ensure the LaTeX compiles with pdflatex (balanced braces, no bare "[" after \\\\).
- Never bullet a company, role, school, degree, project name, stack, or date.
It MUST compile and fit on one page.
"""


class LatexResumeOutput(BaseModel):
    latex_source: str = Field(min_length=20)


def _load_template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def _compact_text(text: str, max_chars: int) -> str:
    """Normalize whitespace and cap prompt input at a paragraph boundary."""
    compact = re.sub(r"[ \t]+", " ", (text or "").strip())
    compact = re.sub(r"\n{3,}", "\n\n", compact)
    if len(compact) <= max_chars:
        return compact
    cut = compact[:max_chars]
    boundary = max(cut.rfind("\n"), cut.rfind(". "))
    if boundary >= max_chars // 2:
        cut = cut[: boundary + 1]
    return cut.rstrip() + "\n[truncated]"


def _compact_template() -> str:
    """Remove comments/blank lines while retaining the canonical LaTeX skeleton."""
    lines = []
    for line in _load_template().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%"):
            continue
        lines.append(line.rstrip())
    return _compact_text("\n".join(lines), _MAX_TEMPLATE_CHARS)


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:latex|tex)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _format_contact_block(contact_fields: dict[str, str] | None) -> str:
    fields = contact_fields or {}
    lines: list[str] = []
    if fields.get("email"):
        lines.append(f"- EMAIL: {fields['email']}  →  \\faEnvelope\\ {fields['email']}")
    if fields.get("phone"):
        lines.append(f"- PHONE: {fields['phone']}  →  \\faMobile\\ {fields['phone']}")
    if fields.get("github"):
        url = fields["github"]
        if not url.lower().startswith(("http://", "https://")):
            url = f"https://{url}"
        lines.append(f"- GITHUB: {url}  →  \\href{{{url}}}{{\\faGithub\\ GitHub}}")
    if fields.get("linkedin"):
        url = fields["linkedin"]
        if not url.lower().startswith(("http://", "https://")):
            url = f"https://{url}"
        lines.append(f"- LINKEDIN: {url}  →  \\href{{{url}}}{{\\faLinkedin\\ LinkedIn}}")
    if not lines:
        return (
            "(No structured contact fields provided — extract email/phone/GitHub/LinkedIn "
            "from the candidate resume header if present.)"
        )
    return "\n".join(lines)


def _validate_output(raw: str) -> str:
    data = parse_llm_json(raw)
    output = LatexResumeOutput.model_validate(data)
    latex = _strip_code_fences(output.latex_source)
    if not latex.startswith("\\documentclass"):
        raise ValueError("Missing documentclass")
    if not any(marker in latex for marker in _TEMPLATE_FINGERPRINT):
        raise ValueError("Output does not follow the required resume template")
    return latex


def generate_latex_resume(
    tailored_markdown: str,
    job_title: str,
    company: str,
    user_id: uuid.UUID,
    session: Session,
    *,
    overflow_hint: bool = False,
    job_description: str = "",
    contact_fields: dict[str, str] | None = None,
) -> str:
    """Ask the LLM to fill the fixed one-page template with role-precise content."""
    prompt = LATEX_PROMPT_TEMPLATE.format(
        job_title=job_title or "Role",
        company=company or "Company",
        job_description=_compact_text(
            job_description, _MAX_JOB_DESCRIPTION_CHARS
        ) or "(Use the job title for relevance.)",
        contact_block=_format_contact_block(contact_fields),
        tailored_markdown=_compact_text(tailored_markdown, _MAX_RESUME_CHARS),
        template=_compact_template(),
    )
    if overflow_hint:
        prompt += OVERFLOW_SUFFIX

    log.info("LaTeX LLM prompt size: %s chars", len(prompt))
    raw = call_llm(
        prompt, "resume_latex", user_id, session, max_tokens=_MAX_OUTPUT_TOKENS
    )

    try:
        return _validate_output(raw)
    except Exception as first_exc:
        log.warning("LaTeX resume validation failed, retrying once: %s", first_exc)
        retry_prompt = (
            prompt
            + "\n\nReturn valid JSON with a complete latex_source string that follows "
            "the template exactly and includes the contact/communication line."
        )
        try:
            raw_retry = call_llm(
                retry_prompt,
                "resume_latex",
                user_id,
                session,
                max_tokens=_MAX_OUTPUT_TOKENS,
            )
            return _validate_output(raw_retry)
        except Exception as retry_exc:
            raise LLMError("Failed to generate LaTeX resume with LLM") from retry_exc
