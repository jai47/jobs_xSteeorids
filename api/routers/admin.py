"""Admin panel APIs: billing rates, token grants, platform LLM status."""

from __future__ import annotations

from typing import Annotated
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import APIError, get_db, require_admin
from api.schemas.billing import (
    AdminByokProvider,
    AdminUserDetailResponse,
    AdminUserListResponse,
    AdminUserRow,
    BillingRatesResponse,
    BillingRatesUpdate,
    GrantTokensRequest,
    GrantTokensResponse,
    SetAdminRequest,
    SetAdminResponse,
)
from api.schemas.user import LLMStatusResponse
from db.models import User
from llm.providers import build_status_payload
from services.token_billing import REASON_ADMIN_GRANT, credit, get_rates, update_rates
from services.user_llm_keys import list_user_keys

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/billing-rates", response_model=BillingRatesResponse)
def admin_get_rates(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> BillingRatesResponse:
    return BillingRatesResponse(**get_rates(db))


@router.patch("/billing-rates", response_model=BillingRatesResponse)
def admin_patch_rates(
    payload: BillingRatesUpdate,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> BillingRatesResponse:
    update_rates(
        db,
        pipeline_run_tokens=payload.pipeline_run_tokens,
        llm_call_tokens=payload.llm_call_tokens,
        signup_grant_tokens=payload.signup_grant_tokens,
        usd_per_thousand_tokens=payload.usd_per_thousand_tokens,
    )
    return BillingRatesResponse(**get_rates(db))


@router.get("/users", response_model=AdminUserListResponse)
def admin_list_users(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> AdminUserListResponse:
    rows = db.execute(select(User).order_by(User.created_at.asc())).scalars().all()
    return AdminUserListResponse(
        users=[
            AdminUserRow(
                id=str(u.id),
                name=u.name,
                email=u.email,
                token_balance=int(getattr(u, "token_balance", 0) or 0),
                is_admin=bool(getattr(u, "is_admin", False)),
            )
            for u in rows
        ]
    )


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
def admin_get_user(
    user_id: uuid.UUID,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> AdminUserDetailResponse:
    """User detail for admin modal — BYOK status only (never plaintext keys)."""
    target = db.get(User, user_id)
    if target is None:
        raise APIError(404, "User not found", "NOT_FOUND")
    providers = [
        AdminByokProvider(
            id=row["id"],
            label=row["label"],
            configured=bool(row["configured"]),
            key_hint=row.get("key_hint"),
        )
        for row in list_user_keys(db, target)
        if row.get("byok_supported")
    ]
    return AdminUserDetailResponse(
        id=str(target.id),
        name=target.name,
        email=target.email,
        token_balance=int(getattr(target, "token_balance", 0) or 0),
        is_admin=bool(getattr(target, "is_admin", False)),
        preferred_llm_provider=getattr(target, "preferred_llm_provider", None) or "auto",
        byok_providers=providers,
    )


@router.post("/users/{user_id}/grant-tokens", response_model=GrantTokensResponse)
def admin_grant_tokens(
    user_id: uuid.UUID,
    payload: GrantTokensRequest,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> GrantTokensResponse:
    target = db.get(User, user_id)
    if target is None:
        raise APIError(404, "User not found", "NOT_FOUND")
    credit(
        db,
        target,
        payload.amount,
        reason=REASON_ADMIN_GRANT,
        note=payload.note,
    )
    db.refresh(target)
    return GrantTokensResponse(
        user_id=str(target.id),
        token_balance=int(target.token_balance or 0),
        granted=payload.amount,
    )


@router.patch("/users/{user_id}/admin", response_model=SetAdminResponse)
def admin_set_admin(
    user_id: uuid.UUID,
    payload: SetAdminRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> SetAdminResponse:
    """Promote or demote a user as admin. Cannot remove the last admin."""
    target = db.get(User, user_id)
    if target is None:
        raise APIError(404, "User not found", "NOT_FOUND")

    if not payload.is_admin and bool(getattr(target, "is_admin", False)):
        from sqlalchemy import func

        admin_count = (
            db.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(True)))
            or 0
        )
        if admin_count <= 1:
            raise APIError(
                400,
                "Cannot remove the last admin",
                "LAST_ADMIN",
            )
        if target.id == admin.id:
            raise APIError(
                400,
                "You cannot remove your own admin access",
                "CANNOT_DEMOTE_SELF",
            )

    target.is_admin = bool(payload.is_admin)
    db.flush()
    return SetAdminResponse(
        user_id=str(target.id),
        email=target.email,
        is_admin=bool(target.is_admin),
    )


@router.get("/llm-platform-status", response_model=LLMStatusResponse)
def admin_llm_platform_status(
    _admin: Annotated[User, Depends(require_admin)],
) -> LLMStatusResponse:
    """Server .env provider configuration (not shown to regular users)."""
    return LLMStatusResponse(**build_status_payload())
