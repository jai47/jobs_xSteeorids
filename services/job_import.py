"""Import a job posting from the Chrome extension (any page)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from api.deps import APIError
from api.schemas.network import JobImportRequest, JobImportResponse
from db.models import Job, ScoredOpportunity, User
from pipeline.stages.overall_scorer import DIGEST_MIN_SCORE


def _normalize_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned.startswith("http://") and not cleaned.startswith("https://"):
        cleaned = "https://" + cleaned
    return cleaned.split("#")[0][:1000]


def import_job_from_extension(
    session: Session,
    user: User,
    payload: JobImportRequest,
) -> JobImportResponse:
    url = _normalize_url(payload.url)
    existing = session.query(Job).filter_by(url=url).first()
    if existing is None:
        external_id = hashlib.sha1(url.encode("utf-8")).hexdigest()[:24]
        # Avoid unique (source, external_id) collisions across users
        external_id = f"{external_id}-{str(user.id)[:8]}"
        job = Job(
            id=uuid.uuid4(),
            source=(payload.source or "extension_import")[:80],
            external_id=external_id,
            url=url,
            company=payload.company.strip()[:200],
            title=payload.title.strip()[:300],
            description=(payload.description or "").strip() or None,
            city=(payload.location or "").strip() or None,
            posted_at=date.today(),
            is_active=True,
            is_stale=False,
        )
        session.add(job)
        session.flush()
    else:
        job = existing
        if payload.description and not job.description:
            job.description = payload.description.strip()

    # Soft score so it appears in Today / Opportunities without full pipeline
    skills = set(s.lower() for s in (user.parsed_skills or []))
    desc = (job.description or "").lower()
    title = (job.title or "").lower()
    hits = sum(1 for s in skills if s and (s in desc or s in title))
    score = min(95.0, max(float(DIGEST_MIN_SCORE), 45.0 + hits * 5.0))

    opp = (
        session.query(ScoredOpportunity)
        .filter_by(job_id=job.id, user_id=user.id, digest_date=date.today())
        .first()
    )
    if opp is None:
        opp = ScoredOpportunity(
            id=uuid.uuid4(),
            job_id=job.id,
            user_id=user.id,
            overall_score=score,
            score_fit=score,
            classification="extension_import",
            fit_reasoning="Imported via Chrome extension job aggregator.",
            digest_date=date.today(),
            created_at=datetime.now(timezone.utc),
        )
        session.add(opp)
    else:
        if opp.user_feedback is None:
            opp.overall_score = max(float(opp.overall_score or 0), score)

    session.flush()
    return JobImportResponse(
        job_id=str(job.id),
        opportunity_id=str(opp.id),
        company=job.company,
        title=job.title,
        url=job.url,
        overall_score=float(opp.overall_score) if opp.overall_score is not None else None,
        message="Job saved. Open Opportunities or Today to approve and build an Apply Packet.",
    )
