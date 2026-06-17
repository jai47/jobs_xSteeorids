"""
Daily digest generation and persistence.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from db.models import DailyDigest, Job, ScoredOpportunity, User
from pipeline.stages.overall_scorer import DIGEST_MIN_SCORE

DIGEST_TEMPLATE = """
AI CAREER DIGEST — {date}

PIPELINE SUMMARY
  Jobs scanned:          {discovered}
  After deduplication:   {after_dedup}
  Scored:                {scored}
  Opportunities (≥70):   {top_count}

TRENDING COMPANIES THIS WEEK
{trending_companies}

BY COUNTRY
{country_breakdown}

TOP RECOMMENDATION
  {top_title} — {top_company}
  {top_location} | {top_remote}
  Score:   {top_score}/100  ({top_classification})
  Visa:    {top_visa_status} ({top_visa_score}/100)
  Salary:  {top_salary}
  Why:
    • {top_fit_reasoning}
    • {top_visa_reasoning}

TOP OPPORTUNITIES (score ≥ 70)
{opportunities_table}
""".strip()


def get_trending_companies(session: Session, limit: int = 5) -> list[tuple[str, int]]:
    """Return top companies by new job postings in the last 7 days."""
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    rows = (
        session.query(Job.company, func.count(Job.id).label("new_roles"))
        .filter(Job.created_at >= week_ago)
        .group_by(Job.company)
        .order_by(func.count(Job.id).desc())
        .limit(limit)
        .all()
    )
    return [(company, int(count)) for company, count in rows]


def _format_trending(trending: list[tuple[str, int]]) -> str:
    if not trending:
        return "  (no new postings this week)"
    return "\n".join(f"  {company}: {count} new roles" for company, count in trending)


def _format_country_breakdown(opportunities: list[dict]) -> str:
    counts: dict[str, int] = {}
    for opp in opportunities:
        country = (opp.get("country") or "Unknown").upper()
        counts[country] = counts.get(country, 0) + 1
    if not counts:
        return "  (none)"
    return "\n".join(f"  {country}: {count}" for country, count in sorted(counts.items()))


def _format_opportunities_table(opportunities: list[dict]) -> str:
    lines: list[str] = []
    for opp in sorted(opportunities, key=lambda item: item.get("overall_score", 0), reverse=True):
        score = opp.get("overall_score", 0)
        marker = "  " if score >= DIGEST_MIN_SCORE else "  [optional] "
        lines.append(
            f"{marker}{opp.get('title')} @ {opp.get('company')} "
            f"({opp.get('country') or '??'}) — {score}/100"
        )
    return "\n".join(lines) if lines else "  (none meeting threshold)"


def build_digest_content(
    *,
    digest_date: date,
    metrics: dict[str, int],
    opportunities: list[dict],
    trending: list[tuple[str, int]],
) -> str:
    """Render digest text from pipeline metrics and scored opportunities."""
    digest_eligible = [opp for opp in opportunities if opp.get("overall_score", 0) >= DIGEST_MIN_SCORE]
    optional = [
        opp
        for opp in opportunities
        if 60 <= opp.get("overall_score", 0) < DIGEST_MIN_SCORE
    ]
    display_opps = digest_eligible + optional
    top = max(opportunities, key=lambda item: item.get("overall_score", 0), default=None)

    if top is None:
        top_fields = {
            "top_title": "N/A",
            "top_company": "N/A",
            "top_location": "N/A",
            "top_remote": "N/A",
            "top_score": 0,
            "top_classification": "skip",
            "top_visa_status": "unknown",
            "top_visa_score": 0,
            "top_salary": "N/A",
            "top_fit_reasoning": "No opportunities scored today.",
            "top_visa_reasoning": "N/A",
        }
    else:
        top_fields = {
            "top_title": top.get("title", "N/A"),
            "top_company": top.get("company", "N/A"),
            "top_location": top.get("country") or "Unknown",
            "top_remote": top.get("remote_type") or "unknown",
            "top_score": top.get("overall_score", 0),
            "top_classification": top.get("classification", "skip"),
            "top_visa_status": top.get("visa_status", "unknown"),
            "top_visa_score": top.get("score_visa", 0),
            "top_salary": top.get("salary_display") or "Not listed",
            "top_fit_reasoning": top.get("fit_reasoning", ""),
            "top_visa_reasoning": top.get("visa_reasoning", ""),
        }

    return DIGEST_TEMPLATE.format(
        date=digest_date.isoformat(),
        discovered=metrics.get("discovered", 0),
        after_dedup=metrics.get("after_dedup", 0),
        scored=metrics.get("scored", 0),
        top_count=len(digest_eligible),
        trending_companies=_format_trending(trending),
        country_breakdown=_format_country_breakdown(display_opps),
        opportunities_table=_format_opportunities_table(display_opps),
        **top_fields,
    )


def save_daily_digest(
    session: Session,
    user: User,
    digest_date: date,
    content_text: str,
    metrics_json: dict[str, Any],
) -> DailyDigest:
    """Persist or replace the digest for a user on a given date."""
    existing = (
        session.query(DailyDigest)
        .filter_by(user_id=user.id, digest_date=digest_date)
        .first()
    )
    if existing:
        existing.content_text = content_text
        existing.metrics_json = metrics_json
        session.flush()
        return existing

    digest = DailyDigest(
        user_id=user.id,
        digest_date=digest_date,
        content_text=content_text,
        metrics_json=metrics_json,
    )
    session.add(digest)
    session.flush()
    return digest


def generate_digest_for_user(
    session: Session,
    user: User,
    *,
    digest_date: date,
    metrics: dict[str, int],
    opportunities: list[dict],
) -> DailyDigest:
    """Build and store a daily digest for one user."""
    trending = get_trending_companies(session)
    content = build_digest_content(
        digest_date=digest_date,
        metrics=metrics,
        opportunities=opportunities,
        trending=trending,
    )
    return save_daily_digest(
        session,
        user,
        digest_date,
        content,
        {**metrics, "top_count": len([o for o in opportunities if o.get("overall_score", 0) >= 70])},
    )


def opportunities_from_rows(rows: list[ScoredOpportunity], jobs_by_id: dict) -> list[dict]:
    """Convert scored opportunity ORM rows to digest-friendly dicts."""
    result: list[dict] = []
    for row in rows:
        job = jobs_by_id.get(row.job_id)
        if job is None:
            continue
        result.append(
            {
                "title": job.title,
                "company": job.company,
                "country": job.country,
                "remote_type": job.remote_type,
                "salary_display": job.salary_display,
                "overall_score": row.overall_score,
                "classification": row.classification,
                "visa_status": row.visa_status,
                "score_visa": row.score_visa,
                "fit_reasoning": row.fit_reasoning,
                "visa_reasoning": row.visa_reasoning,
            }
        )
    return result
