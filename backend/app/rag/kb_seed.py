import asyncio

from app.rag.chroma_store import chroma_store

KB_DOCS = [
    {"id": "m1", "title": "GMV口径", "tags": ["metric"], "content": "GMV 指支付成功订单金额总和，建议按 pay_status=1 统计并排除退款。"},
    {"id": "m2", "title": "客单价口径", "tags": ["metric"], "content": "客单价=支付成功订单金额总和/支付成功订单数。"},
    {"id": "m3", "title": "复购率口径", "tags": ["metric"], "content": "复购率可定义为周期内下单次数>=2的会员数占有下单会员数比例。"},
    {"id": "m4", "title": "支付成功率口径", "tags": ["metric"], "content": "支付成功率=支付成功订单数/全部支付尝试订单数。"},
    {"id": "d1", "title": "复购率下降常见原因", "tags": ["diagnosis"], "content": "复购率下降常见原因：券到期、触达下降、供给变化、价格变化、支付失败上升、外卖占比变化。"},
    {"id": "d2", "title": "复购验证路径", "tags": ["diagnosis"], "content": "验证顺序建议：先看老客下单率，再看支付成功率与客单，再看渠道结构变化。"},
    {"id": "c1", "title": "满减券玩法", "tags": ["campaign"], "content": "满减券适合提升客单：设置门槛略高于当前客单价，控制预算上限。"},
    {"id": "c2", "title": "折扣券玩法", "tags": ["campaign"], "content": "折扣券适合拉动转化，需限制人群与核销上限。"},
    {"id": "c3", "title": "会员日玩法", "tags": ["campaign"], "content": "会员日强调高价值老客召回，常配合短信+App Push双通道触达。"},
    {"id": "r1", "title": "预算风险", "tags": ["risk"], "content": "预算风险控制：设置 max_redemptions、单用户限领限核销、券叠加限制。"},
    {"id": "r2", "title": "羊毛党风险", "tags": ["risk"], "content": "防羊毛策略：黑名单、设备指纹、新客券与老客券分离、异常核销预警。"},
]


async def seed_kb() -> None:
    await chroma_store.upsert_docs(KB_DOCS)
    print(f"KB 已写入 {len(KB_DOCS)} 条文档")


if __name__ == "__main__":
    asyncio.run(seed_kb())
