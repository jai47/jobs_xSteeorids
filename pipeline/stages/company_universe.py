"""
After scoring, upsert companies table from today's discovered jobs.
Tracks hiring momentum and visa-friendliness over time.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from db.models import Company


def update_company_universe(scored_jobs: list[dict], session: Session) -> None:
    """Upsert company records from scored job discoveries."""
    today = date.today()
    # Cache pending inserts so duplicate company names in the same batch
    # (e.g. Databricks IN + Databricks DE) update one row instead of colliding.
    pending: dict[str, Company] = {}

    for job in scored_jobs:
        name = (job.get("company") or "").strip()
        if not name:
            continue
        visa_score = job.get("score_visa")
        company = pending.get(name)
        if company is None:
            company = session.query(Company).filter_by(name=name).first()
            if company is not None:
                pending[name] = company

        if company is not None:
            company.ai_job_count = (company.ai_job_count or 0) + 1
            company.last_seen = today
            if visa_score is not None:
                if company.visa_score_avg is None:
                    company.visa_score_avg = float(visa_score)
                else:
                    company.visa_score_avg = company.visa_score_avg * 0.8 + visa_score * 0.2
                company.is_visa_friendly = company.visa_score_avg >= 60
        else:
            company = Company(
                name=name,
                country=job.get("country"),
                careers_url=job.get("url"),
                ats_type=job.get("source"),
                ai_job_count=1,
                first_seen=today,
                last_seen=today,
                visa_score_avg=float(visa_score) if visa_score is not None else None,
                is_visa_friendly=(visa_score or 0) >= 60,
            )
            session.add(company)
            pending[name] = company

    session.flush()
