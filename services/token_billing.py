"""Prepaid app-token billing for pipeline runs and platform LLM calls."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import APIError
from db.models import AppBillingConfig, TokenLedger, User

DEFAULT_PIPELINE_RUN_TOKENS = 600
DEFAULT_LLM_CALL_TOKENS = 5
DEFAULT_SIGNUP_GRANT_TOKENS = 1000
DEFAULT_USD_PER_THOUSAND = 1.0

REASON_PIPELINE = "pipeline_run"
REASON_LLM = "llm_call"
REASON_ADMIN_GRANT = "admin_grant"
REASON_SIGNUP = "signup_grant"
REASON_REFUND = "llm_refund"
REASON_PIPELINE_REFUND = "pipeline_refund"


def ensure_billing_config(session: Session) -> AppBillingConfig:
    row = session.get(AppBillingConfig, 1)
    if row is None:
        row = AppBillingConfig(
            id=1,
            pipeline_run_tokens=DEFAULT_PIPELINE_RUN_TOKENS,
            llm_call_tokens=DEFAULT_LLM_CALL_TOKENS,
            signup_grant_tokens=DEFAULT_SIGNUP_GRANT_TOKENS,
            usd_per_thousand_tokens=DEFAULT_USD_PER_THOUSAND,
        )
        session.add(row)
        session.flush()
    return row


def get_rates(session: Session) -> dict[str, Any]:
    cfg = ensure_billing_config(session)
    return {
        "pipeline_run_tokens": int(cfg.pipeline_run_tokens),
        "llm_call_tokens": int(cfg.llm_call_tokens),
        "signup_grant_tokens": int(cfg.signup_grant_tokens),
        "usd_per_thousand_tokens": float(cfg.usd_per_thousand_tokens),
    }


def update_rates(
    session: Session,
    *,
    pipeline_run_tokens: int | None = None,
    llm_call_tokens: int | None = None,
    signup_grant_tokens: int | None = None,
    usd_per_thousand_tokens: float | None = None,
) -> AppBillingConfig:
    cfg = ensure_billing_config(session)
    if pipeline_run_tokens is not None:
        cfg.pipeline_run_tokens = max(0, int(pipeline_run_tokens))
    if llm_call_tokens is not None:
        cfg.llm_call_tokens = max(0, int(llm_call_tokens))
    if signup_grant_tokens is not None:
        cfg.signup_grant_tokens = max(0, int(signup_grant_tokens))
    if usd_per_thousand_tokens is not None:
        cfg.usd_per_thousand_tokens = float(usd_per_thousand_tokens)
    cfg.updated_at = datetime.now(timezone.utc)
    session.flush()
    return cfg


def _locked_user(session: Session, user_id: uuid.UUID) -> User:
    user = (
        session.execute(select(User).where(User.id == user_id).with_for_update())
        .scalar_one_or_none()
    )
    if user is None:
        raise APIError(404, "User not found", "NOT_FOUND")
    return user


def enforce_balance(session: Session, user: User, cost: int) -> None:
    balance = int(getattr(user, "token_balance", 0) or 0)
    if cost > 0 and balance < cost:
        raise APIError(
            402,
            f"Token balance exhausted ({balance} of {cost} needed)",
            "TOKEN_BALANCE_EXCEEDED",
            detail=f"balance={balance};needed={cost}",
        )


def apply_delta(
    session: Session,
    user: User,
    delta: int,
    *,
    reason: str,
    ref_id: str | None = None,
    note: str | None = None,
) -> TokenLedger:
    """Apply a signed delta to the user's balance and append a ledger row."""
    locked = _locked_user(session, user.id)
    new_balance = int(locked.token_balance or 0) + int(delta)
    if new_balance < 0:
        raise APIError(
            402,
            f"Token balance exhausted ({locked.token_balance} available)",
            "TOKEN_BALANCE_EXCEEDED",
            detail=f"balance={locked.token_balance};delta={delta}",
        )
    locked.token_balance = new_balance
    entry = TokenLedger(
        user_id=locked.id,
        delta=int(delta),
        balance_after=new_balance,
        reason=reason,
        ref_id=ref_id,
        note=note,
    )
    session.add(entry)
    session.flush()
    user.token_balance = new_balance
    return entry


def debit(
    session: Session,
    user: User,
    cost: int,
    *,
    reason: str,
    ref_id: str | None = None,
    note: str | None = None,
) -> TokenLedger:
    cost = int(cost)
    if cost <= 0:
        raise ValueError("debit cost must be positive")
    enforce_balance(session, user, cost)
    return apply_delta(session, user, -cost, reason=reason, ref_id=ref_id, note=note)


def credit(
    session: Session,
    user: User,
    amount: int,
    *,
    reason: str,
    ref_id: str | None = None,
    note: str | None = None,
) -> TokenLedger:
    amount = int(amount)
    if amount <= 0:
        raise ValueError("credit amount must be positive")
    return apply_delta(session, user, amount, reason=reason, ref_id=ref_id, note=note)


def charge_pipeline_run(session: Session, user: User, run_id: uuid.UUID | str) -> TokenLedger:
    rates = get_rates(session)
    return debit(
        session,
        user,
        rates["pipeline_run_tokens"],
        reason=REASON_PIPELINE,
        ref_id=str(run_id),
    )


def refund_pipeline_run(
    session: Session,
    user: User,
    run_id: uuid.UUID | str,
    *,
    note: str | None = None,
) -> TokenLedger | None:
    """Refund a prior pipeline charge for this run, if one exists and was not already refunded."""
    from db.models import TokenLedger

    charge = (
        session.query(TokenLedger)
        .filter_by(user_id=user.id, reason=REASON_PIPELINE, ref_id=str(run_id))
        .first()
    )
    if charge is None:
        return None
    already = (
        session.query(TokenLedger)
        .filter_by(user_id=user.id, reason=REASON_PIPELINE_REFUND, ref_id=str(run_id))
        .first()
    )
    if already is not None:
        return None
    amount = abs(int(charge.delta))
    if amount <= 0:
        return None
    return credit(
        session,
        user,
        amount,
        reason=REASON_PIPELINE_REFUND,
        ref_id=str(run_id),
        note=note or "Pipeline failed or was cancelled — tokens refunded",
    )


def maybe_charge_successful_pipeline(
    session: Session,
    user: User,
    run: object,
) -> TokenLedger | None:
    """Charge for a finished pipeline only when status is success or partial."""
    status = getattr(run, "status", None)
    run_id = getattr(run, "id", None)
    if run_id is None or status not in {"success", "partial"}:
        return None
    from db.models import TokenLedger

    already = (
        session.query(TokenLedger)
        .filter_by(user_id=user.id, reason=REASON_PIPELINE, ref_id=str(run_id))
        .first()
    )
    if already is not None:
        return None
    return charge_pipeline_run(session, user, run_id)


def charge_llm_call(session: Session, user: User, purpose: str) -> TokenLedger:
    rates = get_rates(session)
    return debit(
        session,
        user,
        rates["llm_call_tokens"],
        reason=REASON_LLM,
        ref_id=purpose,
    )


def refund_llm_call(session: Session, user: User, purpose: str) -> TokenLedger:
    rates = get_rates(session)
    return credit(
        session,
        user,
        rates["llm_call_tokens"],
        reason=REASON_REFUND,
        ref_id=purpose,
        note="LLM providers unavailable after debit",
    )


def grant_signup_tokens(session: Session, user: User) -> TokenLedger:
    """Set starter balance from config and write a signup ledger entry."""
    rates = get_rates(session)
    grant = int(rates["signup_grant_tokens"])
    user.token_balance = grant
    session.flush()
    return record_signup_grant(session, user)


def record_signup_grant(session: Session, user: User) -> TokenLedger:
    """Write signup ledger entry without changing balance (balance already set)."""
    rates = get_rates(session)
    balance = int(user.token_balance or rates["signup_grant_tokens"])
    entry = TokenLedger(
        user_id=user.id,
        delta=balance,
        balance_after=balance,
        reason=REASON_SIGNUP,
        note="Initial token grant",
    )
    session.add(entry)
    session.flush()
    return entry


def spent_today(session: Session, user_id: uuid.UUID) -> int:
    """Net tokens spent today (debits minus refunds/credits). Never negative."""
    today = date.today()
    total = (
        session.query(func.coalesce(func.sum(-TokenLedger.delta), 0))
        .filter(
            TokenLedger.user_id == user_id,
            func.date(TokenLedger.created_at) == today,
        )
        .scalar()
    )
    return max(0, int(total or 0))


def daily_spend_series(session: Session, user_id: uuid.UUID, days: int = 14) -> list[dict[str, Any]]:
    """Return last N days of net token spend (positive numbers) for charts."""
    since = datetime.now(timezone.utc).date().toordinal() - (days - 1)
    since_date = date.fromordinal(since)
    entries = (
        session.query(TokenLedger)
        .filter(
            TokenLedger.user_id == user_id,
            TokenLedger.created_at
            >= datetime.combine(since_date, datetime.min.time(), tzinfo=timezone.utc),
        )
        .all()
    )
    by_day: dict[str, int] = {}
    for i in range(days):
        d = date.fromordinal(since + i)
        by_day[d.isoformat()] = 0
    for entry in entries:
        created = entry.created_at
        if created is None:
            continue
        day = created.date().isoformat() if hasattr(created, "date") else str(created)[:10]
        if day in by_day:
            by_day[day] += -int(entry.delta)
    return [{"date": day, "spent": max(0, spent)} for day, spent in sorted(by_day.items())]
