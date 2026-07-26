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

LATEX_PROMPT_TEMPLATE = """
You are filling in a fixed LaTeX resume template with a real candidate's tailored resume content.

JOB TITLE: {job_title}
COMPANY: {company}

TAILORED RESUME (source of truth for all facts — markdown):
{tailored_markdown}

Below is the EXACT LaTeX template you must fill in. Copy it verbatim — same
\\documentclass, packages, geometry, \\titleformat, and section order — and only:
1. Replace every bracketed placeholder (e.g. [FULL NAME], [EMAIL], [COMPANY NAME],
   [START DATE -- END DATE]) with real content from the tailored resume above.
2. Repeat the "Work Experience" company/itemize block once per real job in the
   source (most recent/relevant first). Use 2-3 jobs — drop the least relevant
   ones rather than shrinking the font to fit more.
3. Repeat "Projects" and "Awards and Certifications" bullets similarly (2-3 each).
4. If a header field has no source data (e.g. no GitHub or LinkedIn URL given),
   remove that specific "$|$"-joined segment entirely rather than leaving a
   bracket or an empty link.
5. Do NOT add a Summary/Objective/Profile section — this template has none.
6. Never invent facts, dates, numbers, or employers not present in the source resume.
7. The compiled document MUST be exactly ONE page. If content is long, shorten
   bullet wording and drop the least relevant entries — do NOT shrink fonts,
   margins, or spacing below what the template already specifies.
8. The Huge title line MUST contain ONLY the candidate's full name — never phone,
   email, LinkedIn, GitHub, or other contact text. Put those only on the contact
   line with \\faEnvelope / \\faMobile / \\faGithub / \\faLinkedin.
9. Output must be valid pdflatex that compiles without errors. Never leave
   unresolved brackets like [FULL NAME]. Never put a line starting with "["
   immediately after "\\\\" (wrap such text in \\mbox{{...}} if needed).
10. NEVER put a company name, job title, employer, school, degree, project name,
   tech stack, or date inside an \\item. Those belong ONLY in the tabularx header
   block (bold company/school/project + right-aligned date, italic role/degree).
   \\item is reserved for achievement sentences.
11. Each \\item must be ONE complete sentence. The source resume text may be
   wrapped mid-sentence across lines — join those fragments back into a single
   \\item instead of emitting a bullet per line fragment.

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
- Huge title = full name ONLY. Contact icons on the next line only.
- Ensure the LaTeX compiles with pdflatex (balanced braces, no bare "[" after \\\\).
- Never bullet a company, role, school, degree, project name, stack, or date.
It MUST compile and fit on one page.
"""


class LatexResumeOutput(BaseModel):
    latex_source: str = Field(min_length=20)


def _load_template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:latex|tex)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


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
) -> str:
    """Ask the LLM to fill the fixed one-page template with real resume content."""
    prompt = LATEX_PROMPT_TEMPLATE.format(
        job_title=job_title or "Role",
        company=company or "Company",
        tailored_markdown=(tailored_markdown or "")[:12000],
        template=_load_template(),
    )
    if overflow_hint:
        prompt += OVERFLOW_SUFFIX

    raw = call_llm(prompt, "resume_latex", user_id, session, max_tokens=4096)

    try:
        return _validate_output(raw)
    except Exception as first_exc:
        log.warning("LaTeX resume validation failed, retrying once: %s", first_exc)
        retry_prompt = prompt + "\n\nReturn valid JSON with a complete latex_source string that follows the template exactly."
        try:
            raw_retry = call_llm(retry_prompt, "resume_latex", user_id, session, max_tokens=4096)
            return _validate_output(raw_retry)
        except Exception as retry_exc:
            raise LLMError("Failed to generate LaTeX resume with LLM") from retry_exc
