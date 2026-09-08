"""User-facing token usage endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from api.schemas.billing import BillingRatesResponse, BillingUsageResponse, UsageDayPoint
from db.models import User
from services.llm_generation_guard import DAILY_GENERATION_LIMIT, count_daily_generations
from services.token_billing import daily_spend_series, get_rates, spent_today

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/usage", response_model=BillingUsageResponse)
def get_billing_usage(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> BillingUsageResponse:
    rates = get_rates(db)
    series = daily_spend_series(db, user.id, days=14)
    return BillingUsageResponse(
        token_balance=int(getattr(user, "token_balance", 0) or 0),
        spent_today=spent_today(db, user.id),
        daily_generation_used=count_daily_generations(db, user.id),
        daily_generation_limit=DAILY_GENERATION_LIMIT,
        rates=BillingRatesResponse(**rates),
        series=[UsageDayPoint(**point) for point in series],
    )
