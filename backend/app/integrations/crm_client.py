from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings

settings = get_settings()


class CRMClient:
    def __init__(self) -> None:
        self.base_url = settings.crm_base_url

    async def create_coupon(self, payload: dict[str, Any]) -> dict[str, Any]:
        timeout = httpx.Timeout(10.0)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
            resp = await client.post("/coupons", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def publish_coupon(self, coupon_id: int) -> dict[str, Any]:
        timeout = httpx.Timeout(10.0)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
            resp = await client.post(f"/coupons/{coupon_id}/publish", json={})
            resp.raise_for_status()
            return resp.json()


crm_client = CRMClient()
