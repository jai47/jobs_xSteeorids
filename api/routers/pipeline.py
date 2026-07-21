"""Pipeline run history and manual trigger routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import APIError, get_current_user, get_db
from api.schemas.pipeline import LLMUsageResponse, PipelineRunListResponse, PipelineRunResponse
from db.models import LLMUsage, PipelineRun, User
from pipeline.pipeline import PipelineAlreadyRunningError, start_pipeline_run
from pipeline.progress import STAGE_LABELS
from pipeline.cancel import request_pipeline_cancel
from pipeline.runner import is_background_pipeline_running, schedule_pipeline_run

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _run_response(run: PipelineRun) -> PipelineRunResponse:
    logs = run.progress_log or []
    return PipelineRunResponse(
        id=str(run.id),
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
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelineRunListResponse:
    """Return pipeline run history, newest first."""
    runs = db.query(PipelineRun).order_by(PipelineRun.run_date.desc()).limit(30).all()
    return PipelineRunListResponse(runs=[_run_response(run) for run in runs])


@router.post("/run", response_model=PipelineRunResponse)
def trigger_pipeline_run(
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelineRunResponse:
    """Manually trigger the nightly pipeline (runs in background)."""
    try:
        run = start_pipeline_run(db)
        schedule_pipeline_run()
    except PipelineAlreadyRunningError:
        raise APIError(409, "Pipeline is already running", "PIPELINE_RUNNING") from None
    return _run_response(run)


@router.post("/cancel", response_model=PipelineRunResponse)
def cancel_pipeline_run(
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PipelineRunResponse:
    """Request cooperative cancellation of today's running pipeline."""
    from datetime import date, datetime, timezone

    run = db.query(PipelineRun).filter_by(run_date=date.today()).first()
    if run is None or run.status != "running":
        raise APIError(409, "No pipeline is currently running", "PIPELINE_NOT_RUNNING")
    if not is_background_pipeline_running():
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc)
        if not run.error_message:
            run.error_message = "Run interrupted before completion"
        db.commit()
        db.refresh(run)
        return _run_response(run)
    request_pipeline_cancel()
    db.refresh(run)
    return _run_response(run)


@router.get("/stages")
def list_pipeline_stages() -> dict[str, str]:
    """Return human-readable labels for pipeline stages."""
    return STAGE_LABELS


def _estimate_cost_usd(provider: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Rough per-call cost estimate for dashboard display."""
    rates = {
        "anthropic": (3.0 / 1_000_000, 15.0 / 1_000_000),
        "openai": (2.5 / 1_000_000, 10.0 / 1_000_000),
        "opencode": (2.5 / 1_000_000, 10.0 / 1_000_000),
    }
    input_rate, output_rate = rates.get(provider, (3.0 / 1_000_000, 15.0 / 1_000_000))
    return prompt_tokens * input_rate + completion_tokens * output_rate


@router.get("/llm-usage", response_model=LLMUsageResponse)
def get_llm_usage(
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LLMUsageResponse:
    """Return aggregate LLM usage and estimated cost."""
    rows = db.query(LLMUsage).all()
    total_prompt = sum(row.prompt_tokens or 0 for row in rows)
    total_completion = sum(row.completion_tokens or 0 for row in rows)
    estimated = sum(
        _estimate_cost_usd(row.provider or "", row.prompt_tokens or 0, row.completion_tokens or 0)
        for row in rows
    )
    return LLMUsageResponse(
        total_calls=len(rows),
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        estimated_cost_usd=round(estimated, 4),
    )
