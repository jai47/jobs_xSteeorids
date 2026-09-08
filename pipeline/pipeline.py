"""
Nightly pipeline. Runs all stages in sequence.
Zero LLM calls. Fully deterministic.
One stage failing does not abort the pipeline.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Callable

from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from db.models import Job, PipelineRun, ScoredOpportunity, User
from pipeline.cancel import PipelineCancelled, is_cancel_requested
from pipeline.progress import STAGE_LABELS, append_progress, reset_progress
from pipeline.role_targets import (
    RoleProfile,
    build_role_profile_for_user,
    filter_jobs_by_role,
)
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
from pipeline.stages.overall_scorer import DIGEST_MIN_SCORE, is_digest_eligible
from pipeline.stages.skill_gap import maybe_generate_skill_gap_reports
from pipeline.stages.stale_reconciler import reconcile_stale_jobs
from pipeline.stages.visa_scorer import score_visa
from services.onboarding import (
    sync_user_roles_from_resume,
    sync_user_skills_from_resume,
    user_has_active_resume,
)

log = logging.getLogger(__name__)

ScoredJobDict = dict[str, Any]
_PROGRESS_EVERY_N_JOBS = 25

# Executable stages in order (excludes starting/complete UI labels).
PIPELINE_STAGE_ORDER = [
    "discover",
    "deduplicate",
    "store_jobs",
    "reconcile_stale",
    "score",
    "liveness",
    "company_universe",
    "legitimacy",
    "digest",
    "skill_gap",
]


class PipelineAlreadyRunningError(Exception):
    """Raised when today's pipeline run is already in progress."""


class PipelineContinueError(Exception):
    """Raised when a pipeline cannot be continued."""


def _stage_index(stage: str | None) -> int:
    if not stage:
        return 0
    if stage in PIPELINE_STAGE_ORDER:
        return PIPELINE_STAGE_ORDER.index(stage)
    if stage in {"starting", "complete"}:
        return 0
    return 0


def start_pipeline_run(session: Session, user: User) -> PipelineRun:
    """Create or reset today's run record for a specific user before execution begins."""
    from pipeline.runner import is_background_pipeline_running

    run_date = date.today()
    run = (
        session.query(PipelineRun)
        .filter_by(run_date=run_date, user_id=user.id)
        .first()
    )
    if run is not None and run.status == "running" and run.completed_at is None:
        if is_background_pipeline_running(user.id):
            raise PipelineAlreadyRunningError()
        log.warning("Recovering stale pipeline run for %s user=%s", run_date, user.email)
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc)
        if not run.error_message:
            run.error_message = "Run interrupted before completion"
        session.flush()

    if run is None:
        run = PipelineRun(
            user_id=user.id,
            run_date=run_date,
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        session.add(run)
    else:
        run.user_id = user.id
        run.started_at = datetime.now(timezone.utc)
        run.status = "running"
        run.completed_at = None
        run.error_stage = None
        run.error_message = None
        run.current_stage = None
        run.progress_log = []
    session.commit()
    return run


def continue_pipeline_run(session: Session, user: User) -> tuple[PipelineRun, str]:
    """Resume today's failed/cancelled run from the failed stage. Returns (run, resume_from)."""
    from pipeline.runner import is_background_pipeline_running

    run_date = date.today()
    run = (
        session.query(PipelineRun)
        .filter_by(run_date=run_date, user_id=user.id)
        .first()
    )
    if run is None:
        raise PipelineContinueError("No pipeline run to continue")
    if run.status == "running" and is_background_pipeline_running(user.id):
        raise PipelineAlreadyRunningError()
    if run.status not in {"failed", "cancelled"}:
        raise PipelineContinueError(
            f"Can only continue a failed or cancelled run (status={run.status})"
        )

    resume_from = run.error_stage or run.current_stage or "discover"
    if resume_from not in PIPELINE_STAGE_ORDER:
        resume_from = "discover"

    # If an older version charged before failure, refund before continuing.
    from services.token_billing import refund_pipeline_run

    refund_pipeline_run(
        session,
        user,
        run.id,
        note="Refund before continue — failed run is not billed",
    )

    run.status = "running"
    run.started_at = datetime.now(timezone.utc)
    run.completed_at = None
    run.error_message = None
    # Keep error_stage until a successful finish so UI knows where we resumed.
    session.flush()
    append_progress(
        session,
        run,
        stage=resume_from,
        message=(
            f"Continuing pipeline from "
            f"{STAGE_LABELS.get(resume_from, resume_from)}..."
        ),
    )
    session.commit()
    return run, resume_from


class NightlyPipeline:
    """Orchestrates deterministic nightly job discovery and scoring."""

    def __init__(
        self,
        session: Session,
        users: list[User],
        *,
        fetch_fn: Callable[[], list[JobDict]] | None = None,
        resume_from: str | None = None,
    ) -> None:
        self.session = session
        self.users = users
        self.fetch_fn = fetch_fn or fetch_all_sources_sync
        self.run: PipelineRun | None = None
        self._errors: list[str] = []
        self._cancel_user_id = users[0].id if len(users) == 1 else None
        self.resume_from = resume_from if resume_from in PIPELINE_STAGE_ORDER else None
        self._role_profiles: dict[object, RoleProfile] = {}

    def _role_profile_for(self, user: User) -> RoleProfile:
        """Cache the user's target role universe for the duration of the run."""
        profile = self._role_profiles.get(user.id)
        if profile is None:
            profile = build_role_profile_for_user(self.session, user)
            self._role_profiles[user.id] = profile
        return profile

    def _should_run(self, stage: str) -> bool:
        if self.resume_from is None:
            return True
        return _stage_index(stage) >= _stage_index(self.resume_from)

    def _row_to_jobdict(self, row: Job) -> JobDict:
        return {
            "source": row.source,
            "external_id": row.external_id,
            "url": row.url,
            "company": row.company,
            "title": row.title,
            "country": row.country,
            "city": row.city,
            "remote_type": row.remote_type,
            "salary_display": row.salary_display,
            "visa_keywords": list(row.visa_keywords or []),
            "skills_required": list(row.skills_required or []),
            "experience_min": row.experience_min,
            "description": row.description,
            "posted_at": row.posted_at,
        }

    def _load_jobs_from_db(self) -> list[JobDict]:
        """Rebuild in-memory jobs when resuming after store_jobs."""
        from sqlalchemy import func

        today = date.today()
        rows = (
            self.session.query(Job)
            .filter(Job.is_active.is_(True), func.date(Job.created_at) == today)
            .order_by(Job.created_at.desc())
            .limit(5000)
            .all()
        )
        if not rows:
            limit = 500
            if self.run and self.run.jobs_after_dedup:
                limit = max(50, min(5000, int(self.run.jobs_after_dedup)))
            rows = (
                self.session.query(Job)
                .filter(Job.is_active.is_(True))
                .order_by(Job.created_at.desc())
                .limit(limit)
                .all()
            )
        return [self._row_to_jobdict(row) for row in rows]

    def run_pipeline(self) -> PipelineRun:
        """Execute all pipeline stages and return the run record."""
        if not self.users:
            raise ValueError("NightlyPipeline requires at least one user")
        # Multi-tenant: each pipeline execution is scoped to exactly one user.
        if len(self.users) != 1:
            raise ValueError("NightlyPipeline runs one user at a time")
        user = self.users[0]
        run_date = date.today()
        self.run = (
            self.session.query(PipelineRun)
            .filter_by(run_date=run_date, user_id=user.id)
            .first()
        )
        if self.run is None:
            self.run = PipelineRun(
                user_id=user.id,
                run_date=run_date,
                started_at=datetime.now(timezone.utc),
                status="running",
            )
            self.session.add(self.run)
        else:
            self.run.user_id = user.id
            self.run.started_at = datetime.now(timezone.utc)
            self.run.status = "running"
            self.run.completed_at = None
            if self.resume_from is None:
                self.run.error_stage = None
                self.run.error_message = None
        if self.resume_from is None:
            reset_progress(self.session, self.run)
            append_progress(
                self.session,
                self.run,
                stage="starting",
                message=f"Pipeline run started for {user.email}",
            )
        else:
            append_progress(
                self.session,
                self.run,
                stage=self.resume_from,
                message=(
                    f"Resuming for {user.email} at "
                    f"{STAGE_LABELS.get(self.resume_from, self.resume_from)}"
                ),
            )

        jobs: list[JobDict] = []
        try:
            self._abort_if_cancelled()

            if self._should_run("discover"):
                discovered = self._run_stage("discover", self._discover)
                jobs = discovered if discovered is not None else []
                self.run.jobs_discovered = len(jobs)
                self.session.commit()
                append_progress(
                    self.session,
                    self.run,
                    stage="discover",
                    message=f"Discovered {len(jobs)} jobs from job boards",
                )
            elif self._should_run("deduplicate") or self._should_run("store_jobs") or self._should_run("score"):
                # Resuming mid-pipeline without rediscover — load stored jobs if past store.
                pass

            if self._should_run("deduplicate"):
                if not jobs and not self._should_run("discover"):
                    # Resuming at deduplicate without fresh discover is not useful; rediscover.
                    discovered = self._run_stage("discover", self._discover)
                    jobs = discovered if discovered is not None else []
                    self.run.jobs_discovered = len(jobs)
                jobs = self._run_stage("deduplicate", lambda: self._deduplicate(jobs))
                jobs = jobs if jobs is not None else []
                self.run.jobs_after_dedup = len(jobs)
                self.session.commit()
                append_progress(
                    self.session,
                    self.run,
                    stage="deduplicate",
                    message=f"{len(jobs)} jobs after deduplication",
                )

            if self._should_run("store_jobs"):
                if not jobs:
                    discovered = self._run_stage("discover", self._discover)
                    jobs = discovered if discovered is not None else []
                    self.run.jobs_discovered = len(jobs)
                    jobs = self._run_stage("deduplicate", lambda: self._deduplicate(jobs)) or []
                    self.run.jobs_after_dedup = len(jobs)
                self._run_stage("store_jobs", lambda: self._store_jobs(jobs))
                append_progress(
                    self.session,
                    self.run,
                    stage="store_jobs",
                    message=f"Stored {len(jobs)} jobs in database",
                )

            if self._should_run("reconcile_stale"):
                if jobs:
                    stats = self._run_stage(
                        "reconcile_stale",
                        lambda: reconcile_stale_jobs(self.session, jobs),
                    ) or {"deactivated": 0, "missed": 0, "reactivated": 0}
                    append_progress(
                        self.session,
                        self.run,
                        stage="reconcile_stale",
                        message=(
                            f"Stale check: {stats.get('missed', 0)} missed, "
                            f"{stats.get('deactivated', 0)} deactivated, "
                            f"{stats.get('reactivated', 0)} reactivated"
                        ),
                    )
                else:
                    append_progress(
                        self.session,
                        self.run,
                        stage="reconcile_stale",
                        message="Skipped stale reconcile — no discovery batch in memory",
                    )

            if not jobs and (
                self._should_run("score") or self._should_run("digest")
            ):
                jobs = self._load_jobs_from_db()
                append_progress(
                    self.session,
                    self.run,
                    stage=self.resume_from or "score",
                    message=f"Loaded {len(jobs)} stored jobs to continue",
                )

            total_scored = 0
            total_top = 0
            universe_jobs: list[ScoredJobDict] = []

            if self._should_run("score"):
                for user in self.users:
                    self._abort_if_cancelled()
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
                            if is_digest_eligible(
                                float(opp.get("overall_score") or 0),
                                score_role_match=opp.get("score_role_match"),
                                has_role_preference=self._role_profile_for(user).has_role_preference,
                            )
                        )
                    append_progress(
                        self.session,
                        self.run,
                        stage="score",
                        message=(
                            f"Scored {scored_count} jobs for {user.email} "
                            f"({top_count} digest-eligible)"
                        ),
                    )

                self.run.jobs_scored = total_scored
                self.run.top_opportunities = total_top
                self.session.commit()

            if self._should_run("liveness"):
                append_progress(
                    self.session,
                    self.run,
                    stage="liveness",
                    message="Scheduling background liveness checks on job URLs...",
                )
                schedule_liveness_verification(self.session)

            if self._should_run("company_universe"):
                if not universe_jobs and jobs:
                    # Re-score lightly skipped — build universe from existing high scores if any.
                    pass
                if universe_jobs:
                    self._run_stage(
                        "company_universe",
                        lambda: update_company_universe(universe_jobs, self.session),
                    )

            if self._should_run("legitimacy"):
                self._run_stage("legitimacy", self._apply_legitimacy_flags)

            if self._should_run("digest"):
                if not jobs:
                    jobs = self._load_jobs_from_db()
                for user in self.users:
                    self._abort_if_cancelled()
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

            if self._should_run("skill_gap"):
                self._run_stage(
                    "skill_gap",
                    lambda: maybe_generate_skill_gap_reports(self.session, self.users),
                )

            self.run.status = "partial" if self._errors else "success"
            self.run.error_stage = None
            append_progress(
                self.session,
                self.run,
                stage="complete",
                message=f"Pipeline finished with status: {self.run.status}",
            )
        except PipelineCancelled:
            log.info("Pipeline cancelled by user")
            self.run.status = "cancelled"
            if not self.run.error_stage:
                self.run.error_stage = self.run.current_stage
            append_progress(
                self.session,
                self.run,
                stage="complete",
                message="Pipeline cancelled by user",
            )
        except Exception as exc:
            log.exception("Pipeline failed")
            self.run.status = "failed"
            self.run.error_message = str(exc)
            if not self.run.error_stage:
                self.run.error_stage = self.run.current_stage
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
            if self.run.status in ("failed", "partial") and self.users:
                from services.notifications.producers import enqueue_pipeline_status_notification

                enqueue_pipeline_status_notification(self.session, self.users[0], self.run)
            self.session.commit()

        return self.run

    def _abort_if_cancelled(self) -> None:
        user_id = getattr(self, "_cancel_user_id", None)
        if is_cancel_requested(user_id):
            raise PipelineCancelled()

    def _run_stage(self, stage: str, fn: Callable[[], Any]) -> Any:
        """Run a stage with fail-soft error handling."""
        self._abort_if_cancelled()
        if self.run is not None:
            append_progress(
                self.session,
                self.run,
                stage=stage,
                message=f"Starting {stage}...",
            )
        try:
            return fn()
        except PipelineCancelled:
            raise
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
            self._abort_if_cancelled()
            if self.run is not None:
                append_progress(self.session, self.run, stage="discover", message=message)

        if self.fetch_fn is not fetch_all_sources_sync:
            return self.fetch_fn()

        role_profile = self._role_profile_for(self.users[0])
        if self.run is not None:
            append_progress(
                self.session,
                self.run,
                stage="discover",
                message=f"Targeting roles: {role_profile.describe()}",
            )
        return fetch_all_sources_sync(
            progress_callback=on_progress,
            role_profile=role_profile,
        )

    def _deduplicate(self, jobs: list[JobDict]) -> list[JobDict]:
        return deduplicate(jobs).jobs

    def _store_jobs(self, jobs: list[JobDict]) -> None:
        refresh_fx_rates(self.session)
        total = len(jobs)
        now = datetime.now(timezone.utc)
        for index, job_dict in enumerate(jobs, start=1):
            self._abort_if_cancelled()
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
                existing.is_active = True
                existing.is_stale = False
                existing.consecutive_misses = 0
                existing.last_seen_at = now
                enrich_job_row(self.session, existing, job_dict)
            else:
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
                    is_active=True,
                    is_stale=False,
                    consecutive_misses=0,
                    last_seen_at=now,
                )
                self.session.add(row)
                self.session.flush()
                enrich_job_row(self.session, row, job_dict)

            if (
                self.run is not None
                and total > 0
                and (index == total or index % _PROGRESS_EVERY_N_JOBS == 0)
            ):
                append_progress(
                    self.session,
                    self.run,
                    stage="store_jobs",
                    message=f"Stored {index}/{total} jobs...",
                )
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
        sync_user_roles_from_resume(self.session, user)
        if not user.parsed_skills:
            log.warning(
                "Scoring user %s with no parsed skills — fit scores may be low",
                user.email,
            )

        user_jobs = apply_blacklist(jobs, user)
        role_profile = self._role_profile_for(user)
        on_target = filter_jobs_by_role(user_jobs, role_profile)
        off_target = len(user_jobs) - len(on_target)
        if off_target and self.run is not None:
            append_progress(
                self.session,
                self.run,
                stage="score",
                message=(
                    f"Skipped {off_target} jobs outside {user.email}'s target roles "
                    f"({role_profile.describe()})"
                ),
            )
        user_jobs = on_target

        scored_opportunities: list[ScoredJobDict] = []
        top_count = 0
        digest_date = date.today()
        total = len(user_jobs)

        job_keys = [(job_dict["source"], job_dict["external_id"]) for job_dict in user_jobs]
        jobs_by_key: dict[tuple[str, str], Job] = {}
        if job_keys:
            job_rows = (
                self.session.query(Job)
                .filter(tuple_(Job.source, Job.external_id).in_(job_keys))
                .all()
            )
            jobs_by_key = {(row.source, row.external_id): row for row in job_rows}

        job_ids = [row.id for row in jobs_by_key.values()]
        opps_by_job_id: dict[object, ScoredOpportunity] = {}
        if job_ids:
            existing_opps = (
                self.session.query(ScoredOpportunity)
                .filter_by(user_id=user.id, digest_date=digest_date)
                .filter(ScoredOpportunity.job_id.in_(job_ids))
                .all()
            )
            opps_by_job_id = {opp.job_id: opp for opp in existing_opps}

        for index, job_dict in enumerate(user_jobs, start=1):
            self._abort_if_cancelled()
            scored = dict(job_dict)
            visa_result = score_visa(scored, user)
            scored.update(visa_result)

            fit_result = score_fit(scored, user)
            scored.update(fit_result)

            overall_result = score_overall(fit_result, visa_result)
            scored.update(overall_result)

            job_row = jobs_by_key.get((job_dict["source"], job_dict["external_id"]))
            if job_row is None:
                log.warning(
                    "Skipping score for missing job %s/%s",
                    job_dict["source"],
                    job_dict["external_id"],
                )
                continue

            existing_opp = opps_by_job_id.get(job_row.id)
            if existing_opp:
                self._update_opportunity(existing_opp, scored)
            else:
                opp = self._new_opportunity(job_row.id, user.id, digest_date, scored)
                self.session.add(opp)
                opps_by_job_id[job_row.id] = opp

            scored_opportunities.append(scored)
            if is_digest_eligible(
                float(scored.get("overall_score") or 0),
                score_role_match=scored.get("score_role_match"),
                has_role_preference=role_profile.has_role_preference,
            ):
                top_count += 1

            if self.run is not None and total > 0 and index % _PROGRESS_EVERY_N_JOBS == 0:
                append_progress(
                    self.session,
                    self.run,
                    stage="score",
                    message=f"Scored {index}/{total} jobs for {user.email}...",
                )

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
        for index, job in enumerate(active_jobs, start=1):
            self._abort_if_cancelled()
            in_universe = bool(job.company and job.company.lower() in company_names)
            repost_count = fingerprint_counts.get(job.dedup_fingerprint or "", 0)
            job.legitimacy_flags = evaluate_legitimacy(
                job,
                company_in_universe=in_universe,
                repost_count=repost_count,
            )
            if (
                self.run is not None
                and index % _PROGRESS_EVERY_N_JOBS == 0
            ):
                append_progress(
                    self.session,
                    self.run,
                    stage="legitimacy",
                    message=f"Evaluated legitimacy for {index}/{len(active_jobs)} jobs...",
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
                    "score_role_match": row.score_role_match,
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

        role_profile = self._role_profile_for(user)
        digest_eligible = len(
            [
                o
                for o in opportunities
                if is_digest_eligible(
                    float(o.get("overall_score") or 0),
                    score_role_match=o.get("score_role_match"),
                    has_role_preference=role_profile.has_role_preference,
                )
            ]
        )
        overdue = count_overdue_follow_ups(self.session, user)
        enqueue_digest_notifications(
            self.session,
            user,
            digest_date,
            digest,
            digest_eligible_count=digest_eligible,
            overdue_follow_ups=overdue,
        )


def run_nightly_pipeline(
    session: Session,
    user: User | None = None,
    *,
    resume_from: str | None = None,
) -> PipelineRun:
    """Execute the pipeline for one user (or each user sequentially when ``user`` is None)."""
    from services.token_billing import (
        enforce_balance,
        get_rates,
        maybe_charge_successful_pipeline,
        refund_pipeline_run,
    )

    def _run_one(u: User, *, from_stage: str | None = None) -> PipelineRun:
        rates = get_rates(session)
        # Reserve balance check only for fresh runs (continues are free until success).
        if from_stage is None:
            enforce_balance(session, u, int(rates["pipeline_run_tokens"]))
        pipeline = NightlyPipeline(session, [u], resume_from=from_stage)
        run = pipeline.run_pipeline()
        if run.status in {"failed", "cancelled"}:
            refund_pipeline_run(
                session,
                u,
                run.id,
                note=f"Pipeline {run.status} — tokens refunded",
            )
        else:
            maybe_charge_successful_pipeline(session, u, run)
            try:
                from services.llm_context import rebuild_user_llm_context

                rebuild_user_llm_context(session, u)
            except Exception:
                log.exception("Failed to rebuild LLM context after pipeline for %s", u.email)
        session.commit()
        return run

    if user is not None:
        return _run_one(user, from_stage=resume_from)

    users = session.query(User).order_by(User.created_at.asc()).all()
    if not users:
        raise RuntimeError("No users to run pipeline for")

    last_run: PipelineRun | None = None
    for u in users:
        log.info("Starting per-user pipeline for %s", u.email)
        try:
            last_run = _run_one(u)
        except Exception:
            log.exception("Per-user pipeline failed for %s", u.email)
    if last_run is None:
        raise RuntimeError("Pipeline did not produce a run record")
    return last_run
