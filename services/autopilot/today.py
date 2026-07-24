"""Deterministic Today Queue aggregation for Autopilot."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from api.schemas.autopilot import (
    TodayFollowUpItem,
    TodayInterviewNudge,
    TodayOpportunityItem,
    TodayPacketGapItem,
    TodayQueueResponse,
)
from db.models import (
    Application,
    CoverLetter,
    Job,
    NetworkContact,
    ScoredOpportunity,
    User,
)
from pipeline.stages.overall_scorer import DIGEST_MIN_SCORE
from services.autopilot.state import get_app_autopilot

TOP_OPPS = 8


def build_today_queue(session: Session, user: User) -> TodayQueueResponse:
    today = date.today()

    opp_rows = (
        session.query(ScoredOpportunity, Job)
        .join(Job, ScoredOpportunity.job_id == Job.id)
        .filter(
            ScoredOpportunity.user_id == user.id,
            ScoredOpportunity.overall_score >= DIGEST_MIN_SCORE,
            ScoredOpportunity.user_feedback.is_(None),
        )
        .order_by(ScoredOpportunity.overall_score.desc())
        .limit(TOP_OPPS * 2)
        .all()
    )
    opportunities: list[TodayOpportunityItem] = []
    for opp, job in opp_rows:
        if job.is_stale:
            continue
        opportunities.append(
            TodayOpportunityItem(
                opportunity_id=str(opp.id),
                job_id=str(job.id),
                company=job.company,
                title=job.title,
                overall_score=float(opp.overall_score) if opp.overall_score is not None else None,
                url=job.url,
                is_stale=bool(job.is_stale),
                reason="high_score",
            )
        )
        if len(opportunities) >= TOP_OPPS:
            break

    follow_ups: list[TodayFollowUpItem] = []
    apps = (
        session.query(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .filter(
            Application.user_id == user.id,
            Application.status.in_(("applied", "interviewing")),
        )
        .all()
    )
    for application, job in apps:
        if application.follow_up_due and application.follow_up_due <= today and not application.followed_up_at:
            follow_ups.append(
                TodayFollowUpItem(
                    kind="application",
                    id=str(application.id),
                    label=f"{job.title} @ {job.company}",
                    company=job.company,
                    due=application.follow_up_due,
                    overdue=True,
                    detail="7-day application follow-up due",
                )
            )
        elif (
            application.second_follow_up_due
            and application.second_follow_up_due <= today
        ):
            follow_ups.append(
                TodayFollowUpItem(
                    kind="application",
                    id=str(application.id),
                    label=f"{job.title} @ {job.company}",
                    company=job.company,
                    due=application.second_follow_up_due,
                    overdue=True,
                    detail="14-day second follow-up due",
                )
            )

    contacts = (
        session.query(NetworkContact)
        .filter(
            NetworkContact.user_id == user.id,
            NetworkContact.status == "sent",
            NetworkContact.follow_up_due.isnot(None),
            NetworkContact.follow_up_due <= today,
        )
        .limit(20)
        .all()
    )
    for contact in contacts:
        follow_ups.append(
            TodayFollowUpItem(
                kind="network",
                id=str(contact.id),
                label=contact.person_name,
                company=contact.company,
                due=contact.follow_up_due,
                overdue=True,
                detail="LinkedIn outreach follow-up due",
            )
        )

    packet_gaps: list[TodayPacketGapItem] = []
    approved_apps = (
        session.query(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .filter(Application.user_id == user.id, Application.status.in_(("approved", "applied")))
        .order_by(Application.updated_at.desc())
        .limit(25)
        .all()
    )
    for application, job in approved_apps:
        missing: list[str] = []
        if not application.resume_version_id:
            missing.append("resume")
        letter = (
            session.query(CoverLetter)
            .filter_by(application_id=application.id)
            .first()
        )
        if letter is None or not (letter.body and letter.body.strip()):
            missing.append("cover_letter")
        cache = get_app_autopilot(application)
        pack = cache.get("message_pack") or {}
        messages = pack.get("messages") if isinstance(pack, dict) else None
        has_connect = False
        if isinstance(messages, list):
            has_connect = any(
                isinstance(m, dict) and m.get("key") == "connect" and m.get("body")
                for m in messages
            )
        if not has_connect:
            missing.append("connect_note")
        if missing:
            packet_gaps.append(
                TodayPacketGapItem(
                    application_id=str(application.id),
                    company=job.company,
                    title=job.title,
                    missing=missing,
                )
            )

    interview_nudges: list[TodayInterviewNudge] = []
    interviewing = (
        session.query(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .filter(Application.user_id == user.id, Application.status == "interviewing")
        .all()
    )
    for application, job in interviewing:
        interview_nudges.append(
            TodayInterviewNudge(
                application_id=str(application.id),
                company=job.company,
                title=job.title,
                sub_status=application.sub_status,
            )
        )

    return TodayQueueResponse(
        opportunities=opportunities,
        follow_ups=follow_ups,
        packet_gaps=packet_gaps[:15],
        interview_nudges=interview_nudges,
    )
