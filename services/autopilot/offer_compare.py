"""Compare offer-stage applications."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from api.deps import APIError, LLMError
from api.schemas.autopilot import OfferCompareRequest, OfferCompareResponse, OfferCompareRow
from db.models import Application, Job, User
from llm.offer_compare import generate_offer_compare
from services.llm_generation_guard import enforce_daily_generation_guard


def compare_offers(
    session: Session,
    user: User,
    payload: OfferCompareRequest,
) -> OfferCompareResponse:
    rows: list[OfferCompareRow] = []
    contexts: list[dict] = []
    for raw_id in payload.application_ids:
        try:
            app_id = uuid.UUID(str(raw_id))
        except ValueError as exc:
            raise APIError(422, f"Invalid application_id: {raw_id}", "VALIDATION_ERROR") from exc
        application = session.get(Application, app_id)
        if application is None or application.user_id != user.id:
            raise APIError(404, f"Application not found: {raw_id}", "NOT_FOUND")
        if application.status not in {"offer", "accepted", "interviewing"}:
            raise APIError(
                422,
                f"Application {raw_id} must be interviewing/offer/accepted to compare",
                "VALIDATION_ERROR",
            )
        job = session.get(Job, application.job_id)
        if job is None:
            raise APIError(404, "Job not found", "NOT_FOUND")
        rows.append(
            OfferCompareRow(
                application_id=str(application.id),
                company=job.company,
                title=job.title,
                status=application.status or "",
                salary_display=job.salary_display,
                remote_type=job.remote_type,
                country=job.country,
                visa_mentioned=bool(job.visa_mentioned),
                notes=application.notes,
            )
        )
        contexts.append(
            {
                "company": job.company,
                "title": job.title,
                "status": application.status,
                "salary_display": job.salary_display,
                "remote_type": job.remote_type,
                "country": job.country,
                "visa_mentioned": bool(job.visa_mentioned),
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
            }
        )

    enforce_daily_generation_guard(session, user.id)
    try:
        raw = generate_offer_compare(
            offers=contexts,
            candidate_name=user.name,
            preferred_countries=list(user.preferred_countries or []),
            user_id=user.id,
            session=session,
        )
        return OfferCompareResponse(
            rows=rows,
            summary=str(raw.get("summary") or "Compare compensation, location, and visa risk carefully."),
            negotiation_bullets=[
                str(b) for b in (raw.get("negotiation_bullets") or []) if str(b).strip()
            ][:8],
        )
    except (LLMError, Exception):
        companies = ", ".join(r.company for r in rows)
        return OfferCompareResponse(
            rows=rows,
            summary=f"Side-by-side view of {companies}. Weigh total comp, visa, remote fit, and growth.",
            negotiation_bullets=[
                "Ask for total compensation breakdown (base, bonus, equity).",
                "Clarify visa/relocation support in writing.",
                "Compare remote expectations and on-site frequency.",
            ],
        )
