"""Resume parsing via a single LLM call."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from api.schemas.resume import ParsedResumeOutput
from llm.client import LLMError, call_llm, parse_llm_json

log = logging.getLogger(__name__)

RESUME_PARSE_PROMPT = """
You are a resume parser. Extract structured data from this resume text.

Resume text:
{resume_text}

Return ONLY valid JSON, no markdown fences, no preamble:
{{
  "skills": ["list of technical skills found"],
  "experience_years": <integer>,
  "previous_titles": ["list of job titles held"],
  "education": ["list of degrees"],
  "languages": ["spoken languages found"]
}}

Rules:
- Only include skills explicitly mentioned in the resume.
- For experience_years, calculate from earliest job date to latest.
- Do not infer or guess anything not stated.
"""


def parse_resume_with_llm(
    resume_text: str,
    user_id: uuid.UUID,
    session: Session,
) -> ParsedResumeOutput:
    """Extract structured profile fields from resume text."""
    prompt = RESUME_PARSE_PROMPT.format(resume_text=resume_text[:12000])
    raw = call_llm(prompt, "resume_parsing", user_id, session)

    try:
        data = parse_llm_json(raw)
        return ParsedResumeOutput.model_validate(data)
    except Exception as first_exc:
        log.warning("Resume parse validation failed, retrying once: %s", first_exc)
        retry_prompt = (
            prompt
            + "\n\nReturn valid JSON matching the required schema."
        )
        try:
            raw_retry = call_llm(retry_prompt, "resume_parsing", user_id, session)
            data = parse_llm_json(raw_retry)
            return ParsedResumeOutput.model_validate(data)
        except Exception as retry_exc:
            raise LLMError("Failed to parse resume with LLM") from retry_exc
