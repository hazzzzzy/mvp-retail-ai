from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_db: str = "mvp_retail_ai"
    mysql_user: str = "root"
    mysql_password: str = "root"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    chroma_dir: str = "./.chroma"
    embed_model_path: str = "./models/bge-base-zh-v1.5"

    sql_max_rows: int = 200
    sql_timeout_seconds: int = 5

    # SQL/schema customization for different environments
    sql_schema_hint: str = (
        "stores(id, name, city)\n"
        "members(id, store_id, created_at, level, total_spent)\n"
        "orders(id, store_id, member_id, paid_at, pay_status, channel, amount, original_amount)\n"
        "order_items(id, order_id, sku, category, qty, price)"
    )
    orders_table: str = "orders"
    order_store_id_col: str = "store_id"
    order_member_id_col: str = "member_id"
    order_paid_at_col: str = "paid_at"
    order_pay_status_col: str = "pay_status"
    order_amount_col: str = "amount"
    order_success_value: str = "1"

    # Intent routing keywords
    intent_report_keywords: str = "报表,趋势,gmv,订单,客单价"
    intent_diagnose_keywords: str = "下降,原因,怎么回事,诊断,为什么"
    intent_plan_keywords: str = "活动,优惠券,预算,策划,方案"
    intent_execute_keywords: str = "执行,上架,创建券,发布券"

    # SQL windows
    report_window_days: int = 7
    diagnose_recent_window_days: int = 7
    diagnose_prev_window_days: int = 14

    # Plan defaults
    plan_default_budget: int = 30000
    plan_default_duration_days: int = 7
    plan_default_goal: str = "提升复购"
    plan_default_channels: str = "app_push,sms,wechat"
    plan_default_offer_type: str = "full_reduction"
    plan_default_offer_threshold: int = 99
    plan_default_offer_value: int = 20
    plan_default_offer_max_redemptions: int = 1000
    plan_default_target_definition: str = "近30天有消费且客单价较高的老客"
    plan_default_target_rules: str = "近30天高价值老客标签"
    plan_default_kpi_primary: str = "repeat_rate"
    plan_default_kpi_targets: str = "7天复购率提升 2~3 个百分点"
    plan_default_risk_controls: str = "单用户限领1次,预算超 80% 触发预警"

    crm_base_url: str = "http://127.0.0.1:8000/mock/crm"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}?charset=utf8mb4"
        )

    @property
    def chroma_dir_abs(self) -> str:
        return str((Path(__file__).resolve().parents[2] / self.chroma_dir).resolve())

    @property
    def embed_model_abs(self) -> str:
        return str((Path(__file__).resolve().parents[2] / self.embed_model_path).resolve())

    @staticmethod
    def split_csv(value: str) -> list[str]:
        text = (value or "").replace("，", ",")
        return [x.strip() for x in text.split(",") if x.strip()]

    @property
    def plan_channels(self) -> list[str]:
        return self.split_csv(self.plan_default_channels)

    @property
    def plan_target_rules(self) -> list[str]:
        return self.split_csv(self.plan_default_target_rules)

    @property
    def plan_kpi_targets(self) -> list[str]:
        return self.split_csv(self.plan_default_kpi_targets)

    @property
    def plan_risk_controls(self) -> list[str]:
        return self.split_csv(self.plan_default_risk_controls)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
