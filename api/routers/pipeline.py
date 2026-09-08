"""Pipeline run history and manual trigger routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import APIError, get_current_user, get_db
from api.schemas.pipeline import LLMUsageResponse, PipelineRunListResponse, PipelineRunResponse
from db.models import LLMUsage, PipelineRun, User
from pipeline.pipeline import (
    PipelineAlreadyRunningError,
    PipelineContinueError,
    continue_pipeline_run,
    start_pipeline_run,
)
from pipeline.progress import STAGE_LABELS
from pipeline.cancel import request_pipeline_cancel
from pipeline.runner import is_background_pipeline_running, schedule_pipeline_run
from services.token_billing import get_rates, refund_pipeline_run

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _run_response(run: PipelineRun) -> PipelineRunResponse:
    logs = run.progress_log or []
    return PipelineRunResponse(
        id=str(run.id),
        user_id=str(run.user_id) if run.user_id else None,
        run_date=run.run_date,
        started_at=run.started_at,
        completed_at=run.completed_at,
        status=run.status,
        jobs_discovered=run.jobs_discovered or 0,
        jobs_after_dedup=run.jobs_after_dedup or 0,
        jobs_scored=run.jobs_scored or 0,
        top_opportunities=run.top_opportunities or 0,
        error_stage=run.error_stage,
        error_message=run.error_message,
        current_stage=run.current_stage,
        progress_log=logs,
    )


@router.get("/runs", response_model=PipelineRunListResponse)
def list_pipeline_runs(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelineRunListResponse:
    """Return this user's pipeline run history, newest first."""
    runs = (
        db.query(PipelineRun)
        .filter(PipelineRun.user_id == user.id)
        .order_by(PipelineRun.run_date.desc())
        .limit(30)
        .all()
    )
    return PipelineRunListResponse(runs=[_run_response(run) for run in runs])


@router.post("/run", response_model=PipelineRunResponse)
def trigger_pipeline_run(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelineRunResponse:
    """Manually trigger the pipeline for the authenticated user only.

    Tokens are charged only when the run finishes as success/partial — not on failure.
    """
    from services.token_billing import enforce_balance

    rates = get_rates(db)
    enforce_balance(db, user, int(rates["pipeline_run_tokens"]))
    try:
        run = start_pipeline_run(db, user)
        schedule_pipeline_run(user.id)
    except PipelineAlreadyRunningError:
        raise APIError(409, "Pipeline is already running for your account", "PIPELINE_RUNNING") from None
    return _run_response(run)


@router.post("/continue", response_model=PipelineRunResponse)
def continue_pipeline(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelineRunResponse:
    """Resume today's failed/cancelled pipeline from the stage where it stopped."""
    try:
        run, resume_from = continue_pipeline_run(db, user)
        schedule_pipeline_run(user.id, resume_from=resume_from)
    except PipelineAlreadyRunningError:
        raise APIError(409, "Pipeline is already running for your account", "PIPELINE_RUNNING") from None
    except PipelineContinueError as exc:
        raise APIError(409, str(exc), "PIPELINE_CANNOT_CONTINUE") from None
    return _run_response(run)


@router.post("/cancel", response_model=PipelineRunResponse)
def cancel_pipeline_run(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelineRunResponse:
    """Request cooperative cancellation of today's running pipeline for this user."""
    from datetime import date, datetime, timezone

    run = (
        db.query(PipelineRun)
        .filter_by(run_date=date.today(), user_id=user.id)
        .first()
    )
    if run is None or run.status != "running":
        raise APIError(409, "No pipeline is currently running", "PIPELINE_NOT_RUNNING")
    if not is_background_pipeline_running(user.id):
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc)
        if not run.error_stage:
            run.error_stage = run.current_stage
        if not run.error_message:
            run.error_message = "Run interrupted before completion"
        refund_pipeline_run(db, user, run.id, note="Stale run marked failed — tokens refunded")
        from services.notifications.producers import enqueue_pipeline_status_notification

        enqueue_pipeline_status_notification(db, user, run)
        db.commit()
        db.refresh(run)
        return _run_response(run)
    request_pipeline_cancel(user.id)
    db.refresh(run)
    return _run_response(run)


@router.get("/stages")
def list_pipeline_stages() -> dict[str, str]:
    """Return human-readable labels for pipeline stages."""
    return STAGE_LABELS


@router.get("/llm-usage", response_model=LLMUsageResponse)
def get_llm_usage(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LLMUsageResponse:
    """Legacy endpoint — prefer GET /billing/usage for token balance and charts."""
    from services.token_billing import spent_today

    rows = db.query(LLMUsage).filter(LLMUsage.user_id == user.id).all()
    total_prompt = sum(row.prompt_tokens or 0 for row in rows)
    total_completion = sum(row.completion_tokens or 0 for row in rows)
    rates = get_rates(db)
    balance = int(getattr(user, "token_balance", 0) or 0)
    return LLMUsageResponse(
        total_calls=len(rows),
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        estimated_cost_usd=0.0,
        budget_usd=float(rates["signup_grant_tokens"]) / 1000.0,
        remaining_usd=balance / 1000.0,
        token_balance=balance,
        spent_today_tokens=spent_today(db, user.id),
    )
