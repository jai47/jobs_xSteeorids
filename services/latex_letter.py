"""LaTeX cover letter PDF template."""

from __future__ import annotations

from services.resume_formatter import _escape_latex


def build_letter_latex(
    *,
    applicant_name: str,
    company: str,
    job_title: str,
    body: str,
) -> str:
    paragraphs = [p.strip() for p in body.replace("\r\n", "\n").split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [line.strip() for line in body.splitlines() if line.strip()]
    body_latex = "\n\n".join(_escape_latex(p) for p in paragraphs)

    return rf"""\documentclass[11pt]{{article}}
\usepackage[margin=1in]{{geometry}}
\usepackage[T1]{{fontenc}}
\usepackage[utf8]{{inputenc}}
\usepackage{{parskip}}
\pagestyle{{empty}}
\begin{{document}}
\noindent {_escape_latex(applicant_name)}\\

\vspace{{0.5em}}
\noindent Re: {_escape_latex(job_title)} at {_escape_latex(company)}

\vspace{{1em}}
{body_latex}
\end{{document}}
"""
