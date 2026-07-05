"""
Store-stage job enrichment: archetype, salary, fingerprint, repost link.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from db.models import Job
from pipeline.stages.fx_rates import normalise_salary_usd
from pipeline.stages.repost import description_hash, find_repost, job_fingerprint
from pipeline.stages.salary_parser import parse_salary
from pipeline.sources.base import JobDict
from skills.archetypes import classify_archetype


def enrich_job_row(session: Session, job: Job, job_dict: JobDict | None = None) -> None:
    """Apply deterministic enrichment to a Job ORM row (fail-soft)."""
    try:
        title = job.title
        description = job.description or (job_dict.get("description") if job_dict else None)
        salary_display = job.salary_display or (job_dict.get("salary_display") if job_dict else None)
        country = job.country or (job_dict.get("country") if job_dict else None)

        job.archetype = classify_archetype(title, description)
        job.dedup_fingerprint = job_fingerprint(job)
        job.description_hash = description_hash(description)

        parsed = parse_salary(salary_display, description, job_country=country)
        if parsed:
            job.salary_min = parsed.salary_min
            job.salary_max = parsed.salary_max
            job.salary_currency = parsed.salary_currency
            job.salary_period = parsed.salary_period
            job.salary_currency_assumed = parsed.currency_assumed
            job.salary_usd_min = normalise_salary_usd(
                session, amount=parsed.salary_min, currency=parsed.salary_currency
            )
            job.salary_usd_max = normalise_salary_usd(
                session, amount=parsed.salary_max, currency=parsed.salary_currency
            )

        if job_dict and not job.repost_of_job_id:
            fp = job.dedup_fingerprint
            if fp:
                match = find_repost(
                    session,
                    fingerprint=fp,
                    description=description,
                    source=job.source,
                    posted_at=job.posted_at,
                    exclude_job_id=job.id,
                )
                if match and str(match.original_job_id) != str(job.id):
                    job.repost_of_job_id = match.original_job_id
    except Exception:
        # Fail-soft per pipeline contract — caller logs if needed.
        pass


def enrich_job_dict_for_store(session: Session, job_dict: JobDict) -> JobDict:
    """Pre-compute enrichment fields on a JobDict before insert (optional)."""
    job_dict = dict(job_dict)
    job_dict["_fingerprint"] = job_fingerprint(job_dict)
    job_dict["_archetype"] = classify_archetype(job_dict.get("title"), job_dict.get("description"))
    return job_dict
