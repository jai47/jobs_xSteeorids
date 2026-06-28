"""Generate a strict single-page LaTeX resume via LLM."""

from __future__ import annotations

import logging
import re
import uuid

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from llm.client import LLMError, call_llm, parse_llm_json

log = logging.getLogger(__name__)

LATEX_PROMPT = """
You are a LaTeX resume expert. Produce ONE complete, compilable LaTeX document on a STRICT SINGLE PAGE.

JOB TITLE: {job_title}
COMPANY: {company}

TAILORED RESUME (markdown):
{tailored_markdown}

Use this EXACT structure (adapt content only):
\\documentclass[10pt,letterpaper]{{article}}
\\usepackage[utf8]{{inputenc}}, \\usepackage[T1]{{fontenc}}
\\usepackage[margin=0.5in]{{geometry}}, \\usepackage{{enumitem}}, \\usepackage{{titlesec}}, \\usepackage{{hyperref}}
\\pagenumbering{{gobble}}
\\begin{{document}}
\\begin{{center}}
{{\\Huge\\bfseries NAME}}\\\\[0.15em]
\\small email | phone | linkedin
\\end{{center}}
\\section{{SUMMARY}} ...
\\section{{EXPERIENCE}} ...
\\section{{SKILLS}} ...
\\section{{EDUCATION}} ...
\\end{{document}}

RULES:
1. MUST fit ONE page — tight margins, compact itemize with nosep.
2. Escape LaTeX specials: \\&, \\%, \\$, \\#, \\_.
3. Do NOT invent facts not in the tailored resume.
4. Professional typography — section rules, consistent spacing.
5. Return ONLY JSON: {{"latex_source": "<full document>"}}
"""


class LatexResumeOutput(BaseModel):
    latex_source: str = Field(min_length=20)


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:latex|tex)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def build_fallback_latex(job_title: str, company: str, tailored_markdown: str) -> str:
    """Build a minimal single-page LaTeX document without LLM."""
    body_lines = []
    for line in tailored_markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            body_lines.append("\\vspace{0.25em}")
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            title = _escape_latex(stripped.lstrip("# ").strip())
            if level == 1:
                body_lines.append(f"{{\\Large\\textbf{{{title}}}}}\\\\")
            else:
                body_lines.append(f"\\textbf{{{title}}}\\\\")
            continue
        if stripped.startswith(("- ", "* ", "• ")):
            item = _escape_latex(stripped.lstrip("-*• ").strip())
            body_lines.append(f"\\item {item}")
            continue
        body_lines.append(_escape_latex(stripped) + "\\\\")

    items_block = ""
    if any("\\item" in line for line in body_lines):
        items_block = "\\begin{itemize}[leftmargin=*, nosep]\n" + "\n".join(
            line for line in body_lines if line.startswith("\\item")
        ) + "\n\\end{itemize}\n"
        prose_lines = [line for line in body_lines if not line.startswith("\\item")]
    else:
        prose_lines = body_lines

    body = "\n".join(prose_lines)
    if items_block:
        body = body + "\n" + items_block

    return f"""\\documentclass[10pt,a4paper]{{article}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[T1]{{fontenc}}
\\usepackage[margin=0.55in]{{geometry}}
\\usepackage{{enumitem}}
\\usepackage{{titlesec}}
\\pagenumbering{{gobble}}
\\setlength{{\\parindent}}{{0pt}}
\\setlength{{\\parskip}}{{0.25em}}
\\titleformat{{\\section}}{{\\normalsize\\bfseries}}{{}}{{0em}}{{}}[\\titlerule]
\\titlespacing{{\\section}}{{0pt}}{{0.4em}}{{0.2em}}
\\begin{{document}}
\\begin{{center}}
{{\\LARGE\\textbf{{Tailored Resume}}}}\\\\[0.2em]
\\textit{{{_escape_latex(job_title)} @ {_escape_latex(company)}}}
\\end{{center}}
\\vspace{{0.3em}}
{body}
\\end{{document}}
"""


def _escape_latex(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    result = text
    for char, escaped in replacements.items():
        result = result.replace(char, escaped)
    return result


def generate_latex_resume(
    tailored_markdown: str,
    job_title: str,
    company: str,
    user_id: uuid.UUID,
    session: Session,
) -> str:
    """Ask the LLM for a strict single-page LaTeX resume."""
    prompt = LATEX_PROMPT.format(
        job_title=job_title or "Role",
        company=company or "Company",
        tailored_markdown=(tailored_markdown or "")[:12000],
    )
    raw = call_llm(prompt, "resume_latex", user_id, session, max_tokens=4096)

    try:
        data = parse_llm_json(raw)
        output = LatexResumeOutput.model_validate(data)
        latex = _strip_code_fences(output.latex_source)
        if not latex.startswith("\\documentclass"):
            raise ValueError("Missing documentclass")
        return latex
    except Exception as first_exc:
        log.warning("LaTeX resume validation failed, retrying once: %s", first_exc)
        retry_prompt = prompt + "\n\nReturn valid JSON with a complete latex_source string."
        try:
            raw_retry = call_llm(
                retry_prompt,
                "resume_latex",
                user_id,
                session,
                max_tokens=4096,
            )
            data = parse_llm_json(raw_retry)
            output = LatexResumeOutput.model_validate(data)
            latex = _strip_code_fences(output.latex_source)
            if not latex.startswith("\\documentclass"):
                raise ValueError("Missing documentclass")
            return latex
        except Exception as retry_exc:
            raise LLMError("Failed to generate LaTeX resume with LLM") from retry_exc
