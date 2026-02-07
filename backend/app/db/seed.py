import asyncio
import random
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from faker import Faker
from sqlalchemy import delete, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import AsyncSessionLocal, engine
from app.db.models import ActionLog, Base, Campaign, Coupon, Member, Order, OrderItem, Store

SEED = 42
faker = Faker("zh_CN")
random.seed(SEED)
Faker.seed(SEED)


def _rand_amount(min_v: float, max_v: float) -> Decimal:
    return Decimal(f"{random.uniform(min_v, max_v):.2f}")


async def reset_tables(session: AsyncSession) -> None:
    for model in [ActionLog, Campaign, Coupon, OrderItem, Order, Member, Store]:
        await session.execute(delete(model))
    await session.commit()


async def create_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def seed() -> None:
    await create_schema()
    now = datetime.now()
    ninety_days_ago = now - timedelta(days=90)

    async with AsyncSessionLocal() as session:
        await reset_tables(session)

        stores = [Store(name=f"门店{i+1}", city=random.choice(["上海", "北京", "广州", "深圳", "杭州"])) for i in range(10)]
        session.add_all(stores)
        await session.flush()

        members: list[Member] = []
        member_ids_by_store: dict[int, list[int]] = defaultdict(list)
        for _ in range(3000):
            store = random.choice(stores)
            created_at = faker.date_time_between(start_date="-365d", end_date="-2d")
            m = Member(
                store_id=store.id,
                created_at=created_at,
                level=random.choice([1, 2, 3, 4]),
                total_spent=_rand_amount(100, 25000),
            )
            members.append(m)
        session.add_all(members)
        await session.flush()

        for m in members:
            member_ids_by_store[m.store_id].append(m.id)

        old_member_ids = {m.id for m in members if m.total_spent >= Decimal("3000") or m.level >= 3}

        orders: list[Order] = []
        successful_orders_per_member: dict[int, int] = defaultdict(int)

        for _ in range(40000):
            store = random.choice(stores)
            paid_at = faker.date_time_between(start_date=ninety_days_ago, end_date=now)
            in_recent_week = paid_at >= now - timedelta(days=7)

            is_guest = random.random() < 0.08
            member_id = None if is_guest else random.choice(member_ids_by_store[store.id])

            pay_status = 1
            if store.id == 3 and in_recent_week:
                pay_status = 0 if random.random() < 0.22 else 1
            else:
                pay_status = 0 if random.random() < 0.06 else 1

            if member_id is not None:
                is_old_customer = member_id in old_member_ids
                if in_recent_week and is_old_customer and random.random() < 0.30:
                    continue
            else:
                is_old_customer = False

            base_amount = _rand_amount(25, 320)

            if in_recent_week:
                if member_id is None or not is_old_customer:
                    if random.random() < 0.35:
                        base_amount = (base_amount * Decimal("0.78")).quantize(Decimal("0.01"))
                else:
                    base_amount = (base_amount * Decimal("1.05")).quantize(Decimal("0.01"))

            original_amount = (base_amount * Decimal(str(random.uniform(1.05, 1.25)))).quantize(Decimal("0.01"))

            order = Order(
                store_id=store.id,
                member_id=member_id,
                paid_at=paid_at,
                pay_status=pay_status,
                channel=random.choice(["offline", "online", "delivery"]),
                amount=base_amount,
                original_amount=original_amount,
            )
            orders.append(order)

            if pay_status == 1 and member_id is not None:
                successful_orders_per_member[member_id] += 1

        session.add_all(orders)
        await session.flush()

        items: list[OrderItem] = []
        categories = ["饮料", "零食", "粮油", "日化", "生鲜", "速食"]
        for order in orders:
            for _ in range(random.randint(1, 5)):
                qty = random.randint(1, 3)
                price = _rand_amount(5, 80)
                items.append(
                    OrderItem(
                        order_id=order.id,
                        sku=f"SKU-{random.randint(1000, 9999)}",
                        category=random.choice(categories),
                        qty=qty,
                        price=price,
                    )
                )
        session.add_all(items)
        await session.commit()

        total_orders = await session.scalar(text("SELECT COUNT(*) FROM orders"))
        success_orders = await session.scalar(text("SELECT COUNT(*) FROM orders WHERE pay_status=1"))

        metrics_sql = text(
            """
            SELECT
                SUM(amount) AS gmv,
                COUNT(*) AS order_cnt,
                AVG(amount) AS aov
            FROM orders
            WHERE pay_status=1 AND paid_at >= NOW() - INTERVAL 7 DAY
            """
        )
        metric_row = (await session.execute(metrics_sql)).mappings().first()

        repurchase_sql = text(
            """
            WITH w1 AS (
                SELECT member_id, COUNT(*) AS c
                FROM orders
                WHERE pay_status=1 AND member_id IS NOT NULL
                AND paid_at >= NOW() - INTERVAL 7 DAY
                GROUP BY member_id
            ),
            w2 AS (
                SELECT member_id, COUNT(*) AS c
                FROM orders
                WHERE pay_status=1 AND member_id IS NOT NULL
                AND paid_at >= NOW() - INTERVAL 14 DAY
                AND paid_at < NOW() - INTERVAL 7 DAY
                GROUP BY member_id
            )
            SELECT
                COALESCE((SELECT AVG(CASE WHEN c>=2 THEN 1 ELSE 0 END) FROM w1), 0) AS r1,
                COALESCE((SELECT AVG(CASE WHEN c>=2 THEN 1 ELSE 0 END) FROM w2), 0) AS r2
            """
        )
        repurchase = (await session.execute(repurchase_sql)).mappings().first()

        print(f"SEED={SEED}")
        print(f"总订单数={int(total_orders or 0)}, 成功订单数={int(success_orders or 0)}")
        print(
            "最近7天 GMV={:.2f}, 订单数={}, 客单价={:.2f}".format(
                float(metric_row["gmv"] or 0),
                int(metric_row["order_cnt"] or 0),
                float(metric_row["aov"] or 0),
            )
        )
        print(
            "最近7天复购率={:.4f}, 上一周期复购率={:.4f}".format(
                float(repurchase["r1"] or 0), float(repurchase["r2"] or 0)
            )
        )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
