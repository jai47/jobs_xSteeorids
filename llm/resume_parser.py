"""Resume parsing via LLM with optional free heuristic fallback."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from api.schemas.resume import ParsedResumeOutput
from config import settings
from llm.client import LLMError, call_llm, parse_llm_json
from llm.resume_parser_heuristic import parse_resume_heuristic

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
    mode = (settings.resume_parser_mode or "auto").lower()
    if mode == "heuristic":
        parsed = parse_resume_heuristic(resume_text)
        log.info("Resume parsed with heuristic mode (no LLM)")
        return parsed

    prompt = RESUME_PARSE_PROMPT.format(resume_text=resume_text[:12000])
    try:
        return _parse_with_llm(prompt, user_id, session)
    except LLMError as exc:
        if mode == "llm":
            raise
        log.warning("LLM resume parse failed, using heuristic fallback: %s", exc)
        return parse_resume_heuristic(resume_text)


def _parse_with_llm(
    prompt: str,
    user_id: uuid.UUID,
    session: Session,
) -> ParsedResumeOutput:
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
