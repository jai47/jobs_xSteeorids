"""Pipeline run history and manual trigger routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.pipeline import PipelineRunListResponse, PipelineRunResponse
from db.models import PipelineRun, User
from pipeline.pipeline import run_nightly_pipeline

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _run_response(run: PipelineRun) -> PipelineRunResponse:
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
    """Manually trigger the nightly pipeline."""
    run = run_nightly_pipeline(db)
    return _run_response(run)
