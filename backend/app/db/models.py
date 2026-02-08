from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Store(Base):
    __tablename__ = "stores"
    __table_args__ = {"comment": "门店主数据表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="门店ID，主键自增")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="门店名称，例如：门店1")
    city: Mapped[str] = mapped_column(String(50), nullable=False, comment="所在城市，例如：上海、北京")


class Member(Base):
    __tablename__ = "members"
    __table_args__ = {"comment": "会员主数据表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="会员ID，主键自增")
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, comment="归属门店ID，关联 stores.id")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="会员创建时间")
    level: Mapped[int] = mapped_column(Integer, nullable=False, comment="会员等级，示例：1=普通，2=银卡，3=金卡，4=黑金")
    total_spent: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=0,
        comment="历史累计消费金额（元）",
    )


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = {"comment": "订单主表（含支付状态与订单金额）"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="订单ID，主键自增")
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, comment="门店ID，关联 stores.id")
    member_id: Mapped[int | None] = mapped_column(
        ForeignKey("members.id"),
        nullable=True,
        comment="会员ID，关联 members.id；为空表示游客单",
    )
    paid_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="支付时间")
    pay_status: Mapped[int] = mapped_column(Integer, nullable=False, comment="支付状态，示例：1=支付成功，0=支付失败")
    channel: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="下单渠道，示例：offline=门店，online=线上，delivery=外卖",
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, comment="实付金额（元）")
    original_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, comment="原价金额（元）")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = {"comment": "订单明细表（按商品行）"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="明细ID，主键自增")
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, comment="订单ID，关联 orders.id")
    sku: Mapped[str] = mapped_column(String(50), nullable=False, comment="商品编码，例如：SKU-1024")
    category: Mapped[str] = mapped_column(String(50), nullable=False, comment="商品品类，例如：饮料、零食、生鲜")
    qty: Mapped[int] = mapped_column(Integer, nullable=False, comment="购买数量，例如：1、2、3")
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, comment="成交单价（元）")


class Coupon(Base):
    __tablename__ = "coupons"
    __table_args__ = {"comment": "优惠券主表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="优惠券ID，主键自增")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="优惠券名称")
    type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="券类型，示例：full_reduction=满减，discount=折扣，points=积分券",
    )
    threshold: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, comment="使用门槛金额（元）")
    value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, comment="优惠值（元或折扣值）")
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="生效开始时间")
    end_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="生效结束时间")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        comment="券状态，示例：draft=草稿，published=已发布，expired=已过期",
    )


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = {"comment": "营销活动表（保存活动目标、预算、方案）"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="活动ID，主键自增")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="活动名称")
    goal: Mapped[str] = mapped_column(String(200), nullable=False, comment="活动目标，例如：提升复购率")
    budget: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, comment="活动预算（元）")
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, comment="活动周期（天）")
    plan_json: Mapped[str] = mapped_column(Text, nullable=False, comment="活动方案JSON（字符串）")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")


class ActionLog(Base):
    __tablename__ = "action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="日志ID，主键自增")
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, comment="幂等键（同一动作唯一）")
    action_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="动作类型，示例：publish_coupon",
    )
    request_json: Mapped[str] = mapped_column(Text, nullable=False, comment="请求体JSON（字符串）")
    response_json: Mapped[str] = mapped_column(Text, nullable=False, comment="响应体JSON（字符串）")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="执行状态，示例：success=成功，failed=失败",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="错误信息；成功时通常为空",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")

    __table_args__ = (
        Index("uq_action_logs_idem_key", "idempotency_key", unique=True),
        {"comment": "执行动作日志表（含幂等控制）"},
    )
