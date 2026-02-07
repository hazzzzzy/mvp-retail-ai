from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActionLog, Campaign, Coupon


async def get_action_log_by_key(session: AsyncSession, key: str) -> ActionLog | None:
    result = await session.execute(select(ActionLog).where(ActionLog.idempotency_key == key))
    return result.scalar_one_or_none()


async def create_action_log(
    session: AsyncSession,
    *,
    idempotency_key: str,
    action_type: str,
    request_json: str,
    response_json: str,
    status: str,
    error_message: str | None = None,
) -> ActionLog:
    log = ActionLog(
        idempotency_key=idempotency_key,
        action_type=action_type,
        request_json=request_json,
        response_json=response_json,
        status=status,
        error_message=error_message,
    )
    session.add(log)
    await session.flush()
    return log


async def create_campaign(session: AsyncSession, name: str, goal: str, budget: float, duration_days: int, plan: dict) -> Campaign:
    campaign = Campaign(
        name=name,
        goal=goal,
        budget=Decimal(str(budget)),
        duration_days=duration_days,
        plan_json=json.dumps(plan, ensure_ascii=False),
    )
    session.add(campaign)
    await session.flush()
    return campaign


async def create_coupon_from_offer(session: AsyncSession, name: str, offer: dict, duration_days: int) -> Coupon:
    now = datetime.now()
    coupon = Coupon(
        name=name,
        type=offer["type"],
        threshold=Decimal(str(offer["threshold"])),
        value=Decimal(str(offer["value"])),
        start_at=now,
        end_at=now + timedelta(days=duration_days),
        status="draft",
    )
    session.add(coupon)
    await session.flush()
    return coupon


def make_idempotency_key(plan: dict) -> str:
    payload = json.dumps(plan, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
