import asyncio

import httpx

from app.db.engine import engine
from app.graph.graph import ainvoke


async def main() -> None:
    a = await ainvoke("最近7天各门店GMV、客单价、订单数，按天趋势")
    assert a.get("intent") == "report"
    assert a.get("report") and len(a["report"].get("rows", [])) > 0

    b = await ainvoke("这周复购率下降了，可能原因是什么？用数据验证")
    assert b.get("intent") == "diagnose"
    answer = b.get("answer") or ""
    assert "(data)" in answer and "(kb)" in answer

    c = await ainvoke("给高价值老客做一个促复购活动，预算3万，7天")
    assert c.get("intent") == "plan"
    assert int(c.get("plan", {}).get("budget", 0)) == 30000

    plan = c["plan"]
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=20.0) as client:
        d1 = await client.post("/api/execute", json={"plan": plan})
        d1.raise_for_status()
        execution1 = d1.json()["execution"]
        assert execution1["publish_status"] == "published"

        d2 = await client.post("/api/execute", json={"plan": plan})
        d2.raise_for_status()
        execution2 = d2.json()["execution"]
        assert execution2["idempotency_key"] == execution1["idempotency_key"]

    print("A/B/C/D smoke test 全部通过")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
