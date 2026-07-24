"""Job Search Autopilot routes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from api.deps import APIError, get_current_user, get_db
from api.schemas.autopilot import (
    ApplyPacketResponse,
    AutoPipelineRequest,
    AutoPipelineResponse,
    ChatRequest,
    ChatResponse,
    CompanyResearchRequest,
    CompanyResearchResponse,
    FormAnswersRequest,
    FormAnswersResponse,
    InterviewPackResponse,
    MasterResumeListResponse,
    MasterResumeUpdate,
    MasterResumeItem,
    MessagePackResponse,
    OfferCompareRequest,
    OfferCompareResponse,
    PatternsResponse,
    ProjectScoreRequest,
    ProjectScoreResponse,
    ReplyCoachRequest,
    ReplyCoachResponse,
    ResumeScoreResponse,
    TodayQueueResponse,
    TrainingScoreRequest,
    TrainingScoreResponse,
    WeeklyPlanResponse,
)
from db.models import User
from services.autopilot.apply_packet import build_apply_packet, ensure_apply_packet
from services.autopilot.auto_pipeline import run_auto_pipeline
from services.autopilot.calendar_ics import build_calendar_ics
from services.autopilot.chat import run_chat
from services.autopilot.company_research import research_company
from services.autopilot.form_answers import generate_and_store_form_answers, get_form_answers
from services.autopilot.interview_pack import (
    generate_and_store_interview_pack,
    get_interview_pack,
)
from services.autopilot.master_resumes import list_master_resumes, update_master_resume
from services.autopilot.message_pack import (
    generate_and_store_message_pack,
    get_message_pack,
)
from services.autopilot.offer_compare import compare_offers
from services.autopilot.patterns import build_patterns
from services.autopilot.project_score import score_project
from services.autopilot.reply_coach import run_reply_coach
from services.autopilot.resume_score import (
    analyze_and_store_resume_score,
    get_saved_resume_score,
)
from services.autopilot.today import build_today_queue
from services.autopilot.training_score import score_training
from services.autopilot.weekly_plan import (
    generate_and_store_weekly_plan,
    get_saved_weekly_plan,
)
from services.health_summary import build_health_summary
from api.schemas.network import HealthSummaryResponse

router = APIRouter(prefix="/autopilot", tags=["autopilot"])


@router.post("/auto-pipeline", response_model=AutoPipelineResponse)
def post_auto_pipeline(
    payload: AutoPipelineRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AutoPipelineResponse:
    """Paste a JD → score → optional track/approve+tailor. Never auto-submits."""
    return run_auto_pipeline(db, user, payload)


@router.post("/company-research", response_model=CompanyResearchResponse)
def post_company_research(
    payload: CompanyResearchRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CompanyResearchResponse:
    return research_company(db, user, payload)


@router.get("/applications/{application_id}/form-answers", response_model=FormAnswersResponse)
def get_app_form_answers(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FormAnswersResponse:
    result = get_form_answers(db, user, application_id)
    if result is None:
        raise APIError(404, "No form answers yet", "NOT_FOUND")
    return result


@router.post("/applications/{application_id}/form-answers", response_model=FormAnswersResponse)
def post_app_form_answers(
    application_id: uuid.UUID,
    payload: FormAnswersRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FormAnswersResponse:
    return generate_and_store_form_answers(db, user, application_id, payload)


@router.get("/patterns", response_model=PatternsResponse)
def get_patterns(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    refresh: bool = False,
) -> PatternsResponse:
    return build_patterns(db, user, refresh_summary=refresh)


@router.post("/training/score", response_model=TrainingScoreResponse)
def post_training_score(
    payload: TrainingScoreRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TrainingScoreResponse:
    return score_training(db, user, payload)


@router.post("/project/score", response_model=ProjectScoreResponse)
def post_project_score(
    payload: ProjectScoreRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectScoreResponse:
    return score_project(db, user, payload)


@router.get("/today", response_model=TodayQueueResponse)
def get_today(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TodayQueueResponse:
    return build_today_queue(db, user)


@router.get("/health-summary", response_model=HealthSummaryResponse)
def get_health_summary(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> HealthSummaryResponse:
    """360° job-search health snapshot for the extension and Today page."""
    return build_health_summary(db, user)


@router.get("/calendar.ics")
def get_calendar_ics(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    body = build_calendar_ics(db, user)
    return Response(
        content=body,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="career-copilot-autopilot.ics"'},
    )


@router.get("/applications/{application_id}/packet", response_model=ApplyPacketResponse)
def get_packet(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ApplyPacketResponse:
    return build_apply_packet(db, user, application_id)


@router.post("/applications/{application_id}/packet/ensure", response_model=ApplyPacketResponse)
def post_ensure_packet(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ApplyPacketResponse:
    return ensure_apply_packet(db, user, application_id)


@router.get("/applications/{application_id}/message-pack", response_model=MessagePackResponse)
def get_msg_pack(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MessagePackResponse:
    pack = get_message_pack(db, user, application_id)
    if pack is None:
        raise APIError(404, "Message pack not generated yet", "NOT_FOUND")
    return pack


@router.post("/applications/{application_id}/message-pack", response_model=MessagePackResponse)
def post_msg_pack(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MessagePackResponse:
    return generate_and_store_message_pack(db, user, application_id)


@router.get("/applications/{application_id}/interview-pack", response_model=InterviewPackResponse)
def get_int_pack(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InterviewPackResponse:
    pack = get_interview_pack(db, user, application_id)
    if pack is None:
        raise APIError(404, "Interview pack not generated yet", "NOT_FOUND")
    return pack


@router.post("/applications/{application_id}/interview-pack", response_model=InterviewPackResponse)
def post_int_pack(
    application_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> InterviewPackResponse:
    return generate_and_store_interview_pack(db, user, application_id)


@router.post("/reply-coach", response_model=ReplyCoachResponse)
def post_reply_coach(
    payload: ReplyCoachRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ReplyCoachResponse:
    return run_reply_coach(db, user, payload)


@router.post("/offers/compare", response_model=OfferCompareResponse)
def post_offer_compare(
    payload: OfferCompareRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> OfferCompareResponse:
    return compare_offers(db, user, payload)


@router.get("/resume-score", response_model=ResumeScoreResponse)
def get_resume_score(
    user: Annotated[User, Depends(get_current_user)],
) -> ResumeScoreResponse:
    saved = get_saved_resume_score(user)
    if saved is None:
        raise APIError(404, "No resume score yet", "NOT_FOUND")
    return saved


@router.post("/resume-score", response_model=ResumeScoreResponse)
def post_resume_score(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ResumeScoreResponse:
    return analyze_and_store_resume_score(db, user)


@router.get("/weekly-plan", response_model=WeeklyPlanResponse)
def get_weekly_plan(
    user: Annotated[User, Depends(get_current_user)],
) -> WeeklyPlanResponse:
    saved = get_saved_weekly_plan(user)
    if saved is None:
        raise APIError(404, "No weekly plan yet", "NOT_FOUND")
    return saved


@router.post("/weekly-plan", response_model=WeeklyPlanResponse)
def post_weekly_plan(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WeeklyPlanResponse:
    return generate_and_store_weekly_plan(db, user)


@router.post("/chat", response_model=ChatResponse)
def post_chat(
    payload: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatResponse:
    return run_chat(db, user, payload)


@router.get("/master-resumes", response_model=MasterResumeListResponse)
def get_master_resumes(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MasterResumeListResponse:
    return list_master_resumes(db, user)


@router.patch("/master-resumes/{resume_id}", response_model=MasterResumeItem)
def patch_master_resume(
    resume_id: uuid.UUID,
    payload: MasterResumeUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MasterResumeItem:
    return update_master_resume(db, user, resume_id, payload)
