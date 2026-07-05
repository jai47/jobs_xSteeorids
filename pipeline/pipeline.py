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
from pipeline.progress import append_progress, reset_progress
from pipeline.sources.base import JobDict
from pipeline.sources.registry import fetch_all_sources_sync
from pipeline.stages.blacklist import apply_blacklist
from pipeline.stages.company_universe import update_company_universe
from pipeline.stages.dedup import deduplicate
from pipeline.stages.digest import generate_digest_for_user
from pipeline.stages.fit_scorer import score_fit
from pipeline.stages.fx_rates import refresh_fx_rates
from pipeline.stages.job_enrichment import enrich_job_row
from pipeline.stages.liveness import schedule_liveness_verification
from pipeline.stages.legitimacy_rules import evaluate_legitimacy
from pipeline.stages.overall_scorer import score_overall
from pipeline.stages.overall_scorer import DIGEST_MIN_SCORE
from pipeline.stages.skill_gap import maybe_generate_skill_gap_reports
from pipeline.stages.visa_scorer import score_visa
from services.onboarding import sync_user_skills_from_resume, user_has_active_resume

log = logging.getLogger(__name__)

ScoredJobDict = dict[str, Any]


class PipelineAlreadyRunningError(Exception):
    """Raised when today's pipeline run is already in progress."""


def start_pipeline_run(session: Session) -> PipelineRun:
    """Create or reset today's run record before execution begins."""
    from pipeline.runner import is_background_pipeline_running

    run_date = date.today()
    run = session.query(PipelineRun).filter_by(run_date=run_date).first()
    if run is not None and run.status == "running" and run.completed_at is None:
        if is_background_pipeline_running():
            raise PipelineAlreadyRunningError()
        log.warning("Recovering stale pipeline run for %s", run_date)
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc)
        if not run.error_message:
            run.error_message = "Run interrupted before completion"
        session.flush()

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
        run.current_stage = None
        run.progress_log = []
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
        reset_progress(self.session, self.run)
        append_progress(self.session, self.run, stage="starting", message="Pipeline run started")

        jobs: list[JobDict] = []
        try:
            jobs = self._run_stage("discover", self._discover)
            self.run.jobs_discovered = len(jobs)
            self.session.commit()
            append_progress(
                self.session,
                self.run,
                stage="discover",
                message=f"Discovered {len(jobs)} jobs from job boards",
            )

            jobs = self._run_stage("deduplicate", lambda: self._deduplicate(jobs))
            self.run.jobs_after_dedup = len(jobs)
            self.session.commit()
            append_progress(
                self.session,
                self.run,
                stage="deduplicate",
                message=f"{len(jobs)} jobs after deduplication",
            )

            self._run_stage("store_jobs", lambda: self._store_jobs(jobs))
            append_progress(
                self.session,
                self.run,
                stage="store_jobs",
                message=f"Stored {len(jobs)} jobs in database",
            )

            total_scored = 0
            total_top = 0
            universe_jobs: list[ScoredJobDict] = []

            for user in self.users:
                append_progress(
                    self.session,
                    self.run,
                    stage="score",
                    message=f"Scoring jobs for {user.email}...",
                )
                user_opps, scored_count, top_count = self._score_for_user(jobs, user)
                total_scored += scored_count
                total_top += top_count
                if user_opps:
                    universe_jobs.extend(
                        opp
                        for opp in user_opps
                        if opp.get("overall_score", 0) >= DIGEST_MIN_SCORE
                    )
                append_progress(
                    self.session,
                    self.run,
                    stage="score",
                    message=(
                        f"Scored {scored_count} jobs for {user.email} "
                        f"({top_count} with score ≥ {int(DIGEST_MIN_SCORE)})"
                    ),
                )

            self.run.jobs_scored = total_scored
            self.run.top_opportunities = total_top
            self.session.commit()

            append_progress(
                self.session,
                self.run,
                stage="liveness",
                message="Scheduling background liveness checks on job URLs...",
            )
            schedule_liveness_verification(self.session)

            if universe_jobs:
                self._run_stage(
                    "company_universe",
                    lambda: update_company_universe(universe_jobs, self.session),
                )

            self._run_stage("legitimacy", self._apply_legitimacy_flags)

            for user in self.users:
                append_progress(
                    self.session,
                    self.run,
                    stage="digest",
                    message=f"Generating daily digest for {user.email}...",
                )
                self._run_stage(
                    "digest",
                    lambda u=user: self._generate_digest(u, jobs),
                )

            self._run_stage(
                "skill_gap",
                lambda: maybe_generate_skill_gap_reports(self.session, self.users),
            )

            self.run.status = "partial" if self._errors else "success"
            append_progress(
                self.session,
                self.run,
                stage="complete",
                message=f"Pipeline finished with status: {self.run.status}",
            )
        except Exception as exc:
            log.exception("Pipeline failed")
            self.run.status = "failed"
            self.run.error_message = str(exc)
            append_progress(
                self.session,
                self.run,
                stage="complete",
                message=f"Pipeline failed: {exc}",
                level="error",
            )
        finally:
            self.run.completed_at = datetime.now(timezone.utc)
            if self._errors and self.run.status != "failed":
                self.run.error_message = "; ".join(self._errors[:3])
            self.session.commit()

        return self.run

    def _run_stage(self, stage: str, fn: Callable[[], Any]) -> Any:
        """Run a stage with fail-soft error handling."""
        if self.run is not None:
            append_progress(
                self.session,
                self.run,
                stage=stage,
                message=f"Starting {stage}...",
            )
        try:
            return fn()
        except Exception as exc:
            message = f"{stage}: {exc}"
            log.exception("Stage %s failed", stage)
            self._errors.append(message)
            if self.run is not None:
                self.run.error_stage = stage
                append_progress(
                    self.session,
                    self.run,
                    stage=stage,
                    message=message,
                    level="error",
                )
            return None

    def _discover(self) -> list[JobDict]:
        def on_progress(message: str) -> None:
            if self.run is not None:
                append_progress(self.session, self.run, stage="discover", message=message)

        if self.fetch_fn is fetch_all_sources_sync:
            return fetch_all_sources_sync(progress_callback=on_progress)
        return self.fetch_fn()

    def _deduplicate(self, jobs: list[JobDict]) -> list[JobDict]:
        return deduplicate(jobs).jobs

    def _store_jobs(self, jobs: list[JobDict]) -> None:
        refresh_fx_rates(self.session)
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
                enrich_job_row(self.session, existing, job_dict)
                continue

            row = Job(
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
            self.session.add(row)
            self.session.flush()
            enrich_job_row(self.session, row, job_dict)
        self.session.flush()

    def _score_for_user(
        self,
        jobs: list[JobDict],
        user: User,
    ) -> tuple[list[ScoredJobDict], int, int]:
        """Score jobs for one user and persist opportunities."""
        if not user_has_active_resume(self.session, user.id):
            log.warning("Skipping scoring for user %s: no active resume", user.email)
            return [], 0, 0

        sync_user_skills_from_resume(self.session, user)
        if not user.parsed_skills:
            log.warning(
                "Scoring user %s with no parsed skills — fit scores may be low",
                user.email,
            )

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
            if scored.get("overall_score", 0) >= DIGEST_MIN_SCORE:
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

    def _apply_legitimacy_flags(self) -> None:
        from db.models import Company

        company_names = {
            name.lower()
            for (name,) in self.session.query(Company.name).all()
            if name
        }
        active_jobs = self.session.query(Job).filter(Job.is_active.is_(True)).all()
        fingerprint_counts: dict[str, int] = {}
        for job in active_jobs:
            if job.dedup_fingerprint:
                fingerprint_counts[job.dedup_fingerprint] = (
                    fingerprint_counts.get(job.dedup_fingerprint, 0) + 1
                )
        for job in active_jobs:
            in_universe = bool(job.company and job.company.lower() in company_names)
            repost_count = fingerprint_counts.get(job.dedup_fingerprint or "", 0)
            job.legitimacy_flags = evaluate_legitimacy(
                job,
                company_in_universe=in_universe,
                repost_count=repost_count,
            )
        self.session.flush()

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
            if job is None or job.repost_of_job_id is not None:
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
        digest = generate_digest_for_user(
            self.session,
            user,
            digest_date=digest_date,
            metrics=metrics,
            opportunities=opportunities,
        )
        from services.notifications.producers import count_overdue_follow_ups, enqueue_digest_notifications

        digest_eligible = len([o for o in opportunities if o.get("overall_score", 0) >= DIGEST_MIN_SCORE])
        overdue = count_overdue_follow_ups(self.session, user)
        enqueue_digest_notifications(
            self.session,
            user,
            digest_date,
            digest,
            digest_eligible_count=digest_eligible,
            overdue_follow_ups=overdue,
        )


def run_nightly_pipeline(session: Session) -> PipelineRun:
    """Load active users and execute the nightly pipeline."""
    users = session.query(User).all()
    pipeline = NightlyPipeline(session, users)
    return pipeline.run_pipeline()
