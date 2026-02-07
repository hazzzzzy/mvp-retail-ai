import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db_session
from app.db.models import Coupon

router = APIRouter(prefix="/mock/crm", tags=["mock_crm"])


class CreateCouponRequest(BaseModel):
    name: str
    offer: dict
    duration_days: int = 7


@router.post("/coupons")
async def create_coupon(payload: CreateCouponRequest, session: AsyncSession = Depends(get_db_session)):
    await asyncio.sleep(0.1)
    now = datetime.now()
    coupon = Coupon(
        name=payload.name,
        type=payload.offer.get("type", "full_reduction"),
        threshold=Decimal(str(payload.offer.get("threshold", 0))),
        value=Decimal(str(payload.offer.get("value", 0))),
        start_at=now,
        end_at=now + timedelta(days=payload.duration_days),
        status="draft",
    )
    session.add(coupon)
    await session.commit()
    await session.refresh(coupon)
    return {"coupon_id": coupon.id}


@router.post("/coupons/{coupon_id}/publish")
async def publish_coupon(coupon_id: int, session: AsyncSession = Depends(get_db_session)):
    await asyncio.sleep(0.1)
    result = await session.execute(select(Coupon).where(Coupon.id == coupon_id))
    coupon = result.scalar_one_or_none()
    if coupon is None:
        raise HTTPException(status_code=404, detail="coupon not found")
    coupon.status = "published"
    await session.commit()
    return {"status": "published", "coupon_id": coupon.id}
