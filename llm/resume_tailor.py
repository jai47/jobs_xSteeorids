"""Resume tailoring via a single LLM call on opportunity approval."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from api.schemas.resume import TailoredResumeOutput
from llm.client import LLMError, call_llm, parse_llm_json

log = logging.getLogger(__name__)

TAILOR_PROMPT = """
You are a resume tailoring expert. Given a master resume and a job description,
produce a tailored version of the resume optimised for this specific job.

MASTER RESUME:
{resume_text}

JOB DESCRIPTION:
{job_description}

RULES (STRICTLY ENFORCED):
1. NEVER add a job title, company name, or date not present in the master resume.
2. NEVER add a skill that does not appear anywhere in the master resume text.
3. NEVER invent a project, certification, metric, or publication.
4. If a required skill is absent from the resume, list it in skill_gaps. Do NOT fabricate it.
5. Reorder and rephrase existing bullets to front-load relevant experience.
6. Improve keyword density by using exact terms from the job description where truthful.

Return ONLY valid JSON, no markdown fences, no preamble:
{{
  "tailored_markdown": "<full tailored resume in markdown>",
  "json_resume": {{<JSON Resume schema 1.0.0>}},
  "ats_score_before": <integer 0-100>,
  "ats_score_after": <integer 0-100>,
  "keywords_added": ["list of keywords from JD now in resume"],
  "skill_gaps": ["required skills absent from master resume"]
}}
"""


def tailor_resume_for_job(
    resume_text: str,
    job_description: str,
    user_id: uuid.UUID,
    session: Session,
) -> TailoredResumeOutput:
    """Tailor a master resume for a specific job description."""
    prompt = TAILOR_PROMPT.format(
        resume_text=resume_text[:12000],
        job_description=(job_description or "No job description provided.")[:12000],
    )
    raw = call_llm(prompt, "resume_tailoring", user_id, session, max_tokens=4096)

    try:
        data = parse_llm_json(raw)
        return TailoredResumeOutput.model_validate(data)
    except Exception as first_exc:
        log.warning("Resume tailor validation failed, retrying once: %s", first_exc)
        retry_prompt = prompt + "\n\nReturn valid JSON matching the required schema."
        try:
            raw_retry = call_llm(
                retry_prompt,
                "resume_tailoring",
                user_id,
                session,
                max_tokens=4096,
            )
            data = parse_llm_json(raw_retry)
            return TailoredResumeOutput.model_validate(data)
        except Exception as retry_exc:
            raise LLMError("Failed to tailor resume with LLM") from retry_exc
