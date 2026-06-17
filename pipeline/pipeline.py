"""
Nightly pipeline. Runs all stages in sequence.
Zero LLM calls. Fully deterministic.
One stage failing does not abort the pipeline.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from db.models import Job, PipelineRun, ScoredOpportunity, User
from pipeline.sources.base import JobDict
from pipeline.sources.registry import fetch_all_sources_sync
from pipeline.stages.blacklist import apply_blacklist
from pipeline.stages.company_universe import update_company_universe
from pipeline.stages.dedup import deduplicate
from pipeline.stages.digest import generate_digest_for_user
from pipeline.stages.fit_scorer import score_fit
from pipeline.stages.liveness import schedule_liveness_verification
from pipeline.stages.overall_scorer import score_overall
from pipeline.stages.skill_gap import maybe_generate_skill_gap_reports
from pipeline.stages.visa_scorer import score_visa

log = logging.getLogger(__name__)

ScoredJobDict = dict[str, Any]


class PipelineAlreadyRunningError(Exception):
    """Raised when today's pipeline run is already in progress."""


def start_pipeline_run(session: Session) -> PipelineRun:
    """Create or reset today's run record before execution begins."""
    run_date = date.today()
    run = session.query(PipelineRun).filter_by(run_date=run_date).first()
    if run is not None and run.status == "running" and run.completed_at is None:
        raise PipelineAlreadyRunningError()
    if run is None:
        run = PipelineRun(
            run_date=run_date,
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        session.add(run)
    else:
        run.started_at = datetime.now(timezone.utc)
        run.status = "running"
        run.completed_at = None
        run.error_stage = None
        run.error_message = None
    session.commit()
    return run


class NightlyPipeline:
    """Orchestrates deterministic nightly job discovery and scoring."""

    def __init__(
        self,
        session: Session,
        users: list[User],
        *,
        fetch_fn: Callable[[], list[JobDict]] | None = None,
    ) -> None:
        self.session = session
        self.users = users
        self.fetch_fn = fetch_fn or fetch_all_sources_sync
        self.run: PipelineRun | None = None
        self._errors: list[str] = []

    def run_pipeline(self) -> PipelineRun:
        """Execute all pipeline stages and return the run record."""
        run_date = date.today()
        self.run = (
            self.session.query(PipelineRun).filter_by(run_date=run_date).first()
        )
        if self.run is None:
            self.run = PipelineRun(
                run_date=run_date,
                started_at=datetime.now(timezone.utc),
                status="running",
            )
            self.session.add(self.run)
        else:
            self.run.started_at = datetime.now(timezone.utc)
            self.run.status = "running"
            self.run.error_stage = None
            self.run.error_message = None
        self.session.commit()

        jobs: list[JobDict] = []
        try:
            jobs = self._run_stage("discover", self._discover)
            self.run.jobs_discovered = len(jobs)

            jobs = self._run_stage("deduplicate", lambda: self._deduplicate(jobs))
            self.run.jobs_after_dedup = len(jobs)

            self._run_stage("store_jobs", lambda: self._store_jobs(jobs))

            total_scored = 0
            total_top = 0
            universe_jobs: list[ScoredJobDict] = []

            for user in self.users:
                user_opps, scored_count, top_count = self._score_for_user(jobs, user)
                total_scored += scored_count
                total_top += top_count
                if user_opps:
                    universe_jobs.extend(user_opps)

            self.run.jobs_scored = total_scored
            self.run.top_opportunities = total_top

            schedule_liveness_verification(self.session)

            if universe_jobs:
                self._run_stage(
                    "company_universe",
                    lambda: update_company_universe(universe_jobs, self.session),
                )

            for user in self.users:
                self._run_stage(
                    "digest",
                    lambda u=user: self._generate_digest(u, jobs),
                )

            self._run_stage(
                "skill_gap",
                lambda: maybe_generate_skill_gap_reports(self.session, self.users),
            )

            self.run.status = "partial" if self._errors else "success"
        except Exception as exc:
            log.exception("Pipeline failed")
            self.run.status = "failed"
            self.run.error_message = str(exc)
        finally:
            self.run.completed_at = datetime.now(timezone.utc)
            if self._errors and self.run.status != "failed":
                self.run.error_message = "; ".join(self._errors[:3])
            self.session.commit()

        return self.run

    def _run_stage(self, stage: str, fn: Callable[[], Any]) -> Any:
        """Run a stage with fail-soft error handling."""
        try:
            return fn()
        except Exception as exc:
            message = f"{stage}: {exc}"
            log.exception("Stage %s failed", stage)
            self._errors.append(message)
            if self.run is not None:
                self.run.error_stage = stage
            return None

    def _discover(self) -> list[JobDict]:
        return self.fetch_fn()

    def _deduplicate(self, jobs: list[JobDict]) -> list[JobDict]:
        return deduplicate(jobs).jobs

    def _store_jobs(self, jobs: list[JobDict]) -> None:
        for job_dict in jobs:
            existing = (
                self.session.query(Job)
                .filter_by(source=job_dict["source"], external_id=job_dict["external_id"])
                .first()
            )
            if existing:
                existing.title = job_dict["title"]
                existing.company = job_dict["company"]
                existing.country = job_dict.get("country")
                existing.city = job_dict.get("city")
                existing.remote_type = job_dict.get("remote_type")
                existing.salary_display = job_dict.get("salary_display")
                existing.skills_required = job_dict.get("skills_required", [])
                existing.experience_min = job_dict.get("experience_min")
                existing.description = job_dict.get("description")
                existing.visa_keywords = job_dict.get("visa_keywords", [])
                existing.visa_mentioned = bool(job_dict.get("visa_keywords"))
                continue

            self.session.add(
                Job(
                    source=job_dict["source"],
                    external_id=job_dict["external_id"],
                    url=job_dict["url"],
                    company=job_dict["company"],
                    title=job_dict["title"],
                    country=job_dict.get("country"),
                    city=job_dict.get("city"),
                    remote_type=job_dict.get("remote_type"),
                    salary_display=job_dict.get("salary_display"),
                    visa_keywords=job_dict.get("visa_keywords", []),
                    visa_mentioned=bool(job_dict.get("visa_keywords")),
                    skills_required=job_dict.get("skills_required", []),
                    experience_min=job_dict.get("experience_min"),
                    description=job_dict.get("description"),
                    posted_at=job_dict.get("posted_at"),
                )
            )
        self.session.flush()

    def _score_for_user(
        self,
        jobs: list[JobDict],
        user: User,
    ) -> tuple[list[ScoredJobDict], int, int]:
        """Score jobs for one user and persist opportunities."""
        if not user.parsed_skills:
            log.warning("Skipping scoring for user %s: no parsed skills", user.email)
            return [], 0, 0

        user_jobs = apply_blacklist(jobs, user)
        scored_opportunities: list[ScoredJobDict] = []
        top_count = 0
        digest_date = date.today()

        for job_dict in user_jobs:
            scored = dict(job_dict)
            visa_result = score_visa(scored, user)
            scored.update(visa_result)

            fit_result = score_fit(scored, user)
            scored.update(fit_result)

            overall_result = score_overall(fit_result, visa_result)
            scored.update(overall_result)

            job_row = (
                self.session.query(Job)
                .filter_by(source=job_dict["source"], external_id=job_dict["external_id"])
                .one()
            )

            existing_opp = (
                self.session.query(ScoredOpportunity)
                .filter_by(job_id=job_row.id, user_id=user.id, digest_date=digest_date)
                .first()
            )
            if existing_opp:
                self._update_opportunity(existing_opp, scored)
            else:
                self.session.add(self._new_opportunity(job_row.id, user.id, digest_date, scored))

            scored_opportunities.append(scored)
            if scored.get("overall_score", 0) >= 70:
                top_count += 1

        self.session.flush()
        return scored_opportunities, len(scored_opportunities), top_count

    def _new_opportunity(
        self,
        job_id,
        user_id,
        digest_date: date,
        scored: ScoredJobDict,
    ) -> ScoredOpportunity:
        return ScoredOpportunity(
            job_id=job_id,
            user_id=user_id,
            digest_date=digest_date,
            score_skill_match=scored.get("score_skill_match"),
            score_role_match=scored.get("score_role_match"),
            score_experience=scored.get("score_experience"),
            score_country_pref=scored.get("score_country_pref"),
            score_remote_pref=scored.get("score_remote_pref"),
            score_fit=scored.get("score_fit"),
            score_visa=scored.get("score_visa"),
            visa_status=scored.get("visa_status"),
            visa_reasoning=scored.get("visa_reasoning"),
            overall_score=scored.get("overall_score"),
            classification=scored.get("classification"),
            fit_reasoning=scored.get("fit_reasoning"),
        )

    def _update_opportunity(self, opp: ScoredOpportunity, scored: ScoredJobDict) -> None:
        opp.score_skill_match = scored.get("score_skill_match")
        opp.score_role_match = scored.get("score_role_match")
        opp.score_experience = scored.get("score_experience")
        opp.score_country_pref = scored.get("score_country_pref")
        opp.score_remote_pref = scored.get("score_remote_pref")
        opp.score_fit = scored.get("score_fit")
        opp.score_visa = scored.get("score_visa")
        opp.visa_status = scored.get("visa_status")
        opp.visa_reasoning = scored.get("visa_reasoning")
        opp.overall_score = scored.get("overall_score")
        opp.classification = scored.get("classification")
        opp.fit_reasoning = scored.get("fit_reasoning")

    def _generate_digest(self, user: User, jobs: list[JobDict]) -> None:
        digest_date = date.today()
        rows = (
            self.session.query(ScoredOpportunity)
            .filter_by(user_id=user.id, digest_date=digest_date)
            .all()
        )
        if not rows:
            return

        job_ids = [row.job_id for row in rows]
        job_rows = self.session.query(Job).filter(Job.id.in_(job_ids)).all()
        jobs_by_id = {job.id: job for job in job_rows}

        opportunities = []
        for row in rows:
            job = jobs_by_id.get(row.job_id)
            if job is None:
                continue
            opportunities.append(
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

        metrics = {
            "discovered": self.run.jobs_discovered if self.run else 0,
            "after_dedup": self.run.jobs_after_dedup if self.run else 0,
            "scored": len(opportunities),
        }
        generate_digest_for_user(
            self.session,
            user,
            digest_date=digest_date,
            metrics=metrics,
            opportunities=opportunities,
        )


def run_nightly_pipeline(session: Session) -> PipelineRun:
    """Load active users and execute the nightly pipeline."""
    users = session.query(User).all()
    pipeline = NightlyPipeline(session, users)
    return pipeline.run_pipeline()
