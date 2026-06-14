"""User onboarding: resume upload, text extraction, and profile updates."""

from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path

import bcrypt
from docx import Document
from pdfminer.high_level import extract_text as pdf_extract_text
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas.resume import ParsedResumeOutput
from config import settings
from db.models import MasterResume, User
from llm.resume_parser import parse_resume_with_llm

ALLOWED_EXTENSIONS = {".pdf", ".docx"}


def ensure_seed_user(session: Session) -> User | None:
    """Create the initial dashboard user from env vars when the table is empty."""
    existing = session.scalar(select(User).limit(1))
    if existing is not None:
        return None

    if not settings.seed_user_email or not settings.seed_user_password:
        return None

    password_hash = bcrypt.hashpw(
        settings.seed_user_password.encode(),
        bcrypt.gensalt(),
    ).decode()
    user = User(
        name=settings.seed_user_name,
        email=settings.seed_user_email.lower(),
        dashboard_password=password_hash,
    )
    session.add(user)
    session.flush()
    return user


def extract_resume_text(content: bytes, filename: str) -> str:
    """Extract plain text from a PDF or DOCX resume."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix}. Use .pdf or .docx.")

    if suffix == ".pdf":
        text = pdf_extract_text(BytesIO(content))
    else:
        document = Document(BytesIO(content))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())

    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Could not extract text from the uploaded resume.")
    return cleaned


def user_has_active_resume(session: Session, user_id: uuid.UUID) -> bool:
    """Return whether the user has an active master resume."""
    resume = session.scalar(
        select(MasterResume)
        .where(MasterResume.user_id == user_id, MasterResume.is_active.is_(True))
        .limit(1)
    )
    return resume is not None


def _resume_storage_dir(user_id: uuid.UUID) -> Path:
    base = Path(settings.resume_storage_path) / str(user_id) / "masters"
    base.mkdir(parents=True, exist_ok=True)
    return base


def upload_master_resume(
    session: Session,
    user: User,
    filename: str,
    content: bytes,
) -> tuple[MasterResume, ParsedResumeOutput]:
    """Store resume file, parse with LLM, and update the user profile."""
    resume_text = extract_resume_text(content, filename)
    parsed = parse_resume_with_llm(resume_text, user.id, session)

    for existing in session.scalars(
        select(MasterResume).where(
            MasterResume.user_id == user.id,
            MasterResume.is_active.is_(True),
        )
    ):
        existing.is_active = False

    master_resume = MasterResume(
        user_id=user.id,
        filename=filename,
        raw_text=resume_text,
        parsed_json=parsed.model_dump(),
        is_active=True,
    )
    session.add(master_resume)
    session.flush()

    suffix = Path(filename).suffix.lower()
    storage_path = _resume_storage_dir(user.id) / f"{master_resume.id}{suffix}"
    storage_path.write_bytes(content)

    user.parsed_skills = parsed.skills
    user.years_experience = parsed.experience_years
    session.flush()
    return master_resume, parsed
