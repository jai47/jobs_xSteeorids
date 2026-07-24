"""LinkedIn insights: profile coach + find-network (user opens LinkedIn themselves)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import APIError, get_current_user, get_db
from api.schemas.linkedin_insights import (
    FindNetworkRequest,
    FindNetworkResponse,
    ImportContactsRequest,
    ImportContactsResponse,
    LinkedInProfileAnalyzeRequest,
    LinkedInProfileAnalysisResponse,
)
from db.models import User
from services.linkedin_insights import (
    analyze_and_store_profile,
    find_network_suggestions,
    get_saved_profile_analysis,
    import_network_contacts,
)

router = APIRouter(prefix="/linkedin", tags=["linkedin"])


@router.get("/profile-analysis", response_model=LinkedInProfileAnalysisResponse)
def get_profile_analysis(
    user: Annotated[User, Depends(get_current_user)],
) -> LinkedInProfileAnalysisResponse:
    saved = get_saved_profile_analysis(user)
    if saved is None:
        raise APIError(404, "No LinkedIn profile analysis saved yet", "NOT_FOUND")
    return saved


@router.post("/profile-analysis", response_model=LinkedInProfileAnalysisResponse)
def post_profile_analysis(
    payload: LinkedInProfileAnalyzeRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LinkedInProfileAnalysisResponse:
    """Analyze pasted LinkedIn profile text and suggest updates."""
    return analyze_and_store_profile(db, user, payload)


@router.post("/find-network", response_model=FindNetworkResponse)
def post_find_network(
    payload: FindNetworkRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FindNetworkResponse:
    """Suggest LinkedIn people-search queries for a company/role (no scraping)."""
    return find_network_suggestions(db, user, payload)


@router.post("/import-contacts", response_model=ImportContactsResponse)
def post_import_contacts(
    payload: ImportContactsRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ImportContactsResponse:
    """Bulk-create network contacts from Chrome extension extracts."""
    return import_network_contacts(db, user, payload)
