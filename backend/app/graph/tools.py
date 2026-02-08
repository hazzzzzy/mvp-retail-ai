from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import sqlglot
from langchain_core.tools import tool
from sqlalchemy import text
from sqlglot import exp

from app.core.config import get_settings
from app.db.engine import AsyncSessionLocal
from app.llm.deepseek_client import deepseek_client
from app.llm.prompts import (
    build_sql_repair_system,
    build_sql_repair_user_prompt,
    build_sql_system,
    build_sql_user_prompt,
)
from app.rag.chroma_store import chroma_store

settings = get_settings()
_SCHEMA_CACHE_TEXT = ""
_SCHEMA_CACHE_AT = 0.0
_SCHEMA_CACHE_TTL_SEC = 60.0


def _extract_select_sql(raw: str) -> str:
    cleaned = (raw or "").replace("```sql", "").replace("```", "").strip()
    m = re.search(r"(?is)select\\s.+?(?:;|$)", cleaned)
    return m.group(0).strip() if m else cleaned


def _build_success_predicate() -> str:
    v = (settings.order_success_value or "").strip()
    if re.fullmatch(r"\d+", v):
        return f"{settings.order_pay_status_col} = {v}"
    safe = v.replace("'", "''")
    return f"{settings.order_pay_status_col} = '{safe}'"


def _build_sql_by_rule(query: str, intent: str) -> str | None:
    q = (query or "").replace("月份", "月")
    table = settings.orders_table
    paid_at = settings.order_paid_at_col
    amount = settings.order_amount_col
    success_pred = _build_success_predicate()

    # 规则1：最近N天汇总（GMV/订单数/客单价）
    m_recent = re.search(r"最近\s*(\d{1,3})\s*天", q)
    ask_gmv = "gmv" in q.lower() or "交易额" in q or "销售额" in q
    ask_order = ("订单" in q) or ("单量" in q)
    ask_aov = ("客单价" in q) or ("aov" in q.lower())
    ask_daily = bool(re.search(r"(按天|每天|日趋势)", q))
    if m_recent and ask_gmv and (ask_order or ask_aov) and not ask_daily and intent == "report":
        n = int(m_recent.group(1))
        return (
            f"SELECT "
            f"COALESCE(SUM({amount}), 0) AS gmv, "
            f"COUNT(*) AS order_count, "
            f"COALESCE(SUM({amount}) / NULLIF(COUNT(*), 0), 0) AS aov "
            f"FROM {table} "
            f"WHERE {success_pred} "
            f"AND {paid_at} >= NOW() - INTERVAL {n} DAY"
        )

    # 规则2：最近N天按天GMV趋势
    if m_recent and ask_gmv and ask_daily and intent == "report":
        n = int(m_recent.group(1))
        return (
            f"SELECT "
            f"DATE({paid_at}) AS dt, "
            f"COALESCE(SUM({amount}), 0) AS gmv "
            f"FROM {table} "
            f"WHERE {success_pred} "
            f"AND {paid_at} >= NOW() - INTERVAL {n} DAY "
            f"GROUP BY DATE({paid_at}) "
            f"ORDER BY dt ASC"
        )

    # 规则3：去年X月 vs 去年Y月 GMV 对比
    m_compare_last_year = re.search(r"去年\s*(\d{1,2})\s*月.*(?:相比|对比|比).*(?:去年)\s*(\d{1,2})\s*月", q)
    if m_compare_last_year and ask_gmv and intent in {"report", "diagnose"}:
        m1 = int(m_compare_last_year.group(1))
        m2 = int(m_compare_last_year.group(2))
        if 1 <= m1 <= 12 and 1 <= m2 <= 12:
            return (
                "SELECT "
                f"SUM(CASE WHEN YEAR({paid_at}) = YEAR(CURDATE()) - 1 AND MONTH({paid_at}) = {m1} THEN {amount} ELSE 0 END) AS month_{m1}_gmv, "
                f"SUM(CASE WHEN YEAR({paid_at}) = YEAR(CURDATE()) - 1 AND MONTH({paid_at}) = {m2} THEN {amount} ELSE 0 END) AS month_{m2}_gmv, "
                f"SUM(CASE WHEN YEAR({paid_at}) = YEAR(CURDATE()) - 1 AND MONTH({paid_at}) = {m1} THEN {amount} ELSE 0 END) - "
                f"SUM(CASE WHEN YEAR({paid_at}) = YEAR(CURDATE()) - 1 AND MONTH({paid_at}) = {m2} THEN {amount} ELSE 0 END) AS diff, "
                "CASE "
                f"WHEN SUM(CASE WHEN YEAR({paid_at}) = YEAR(CURDATE()) - 1 AND MONTH({paid_at}) = {m2} THEN {amount} ELSE 0 END) = 0 "
                "THEN NULL "
                "ELSE ("
                f"SUM(CASE WHEN YEAR({paid_at}) = YEAR(CURDATE()) - 1 AND MONTH({paid_at}) = {m1} THEN {amount} ELSE 0 END) - "
                f"SUM(CASE WHEN YEAR({paid_at}) = YEAR(CURDATE()) - 1 AND MONTH({paid_at}) = {m2} THEN {amount} ELSE 0 END)"
                ") / NULLIF("
                f"SUM(CASE WHEN YEAR({paid_at}) = YEAR(CURDATE()) - 1 AND MONTH({paid_at}) = {m2} THEN {amount} ELSE 0 END), 0"
                ") END AS change_rate "
                f"FROM {table} "
                f"WHERE {success_pred}"
            )

    return None


async def _load_schema_hint_dynamic() -> str:
    global _SCHEMA_CACHE_TEXT, _SCHEMA_CACHE_AT
    now = time.monotonic()
    if _SCHEMA_CACHE_TEXT and now - _SCHEMA_CACHE_AT < _SCHEMA_CACHE_TTL_SEC:
        return _SCHEMA_CACHE_TEXT

    try:
        async with AsyncSessionLocal() as session:
            db_name = await session.scalar(text("SELECT DATABASE()"))
            rows = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT
                        FROM information_schema.COLUMNS
                        WHERE TABLE_SCHEMA = :db
                        ORDER BY TABLE_NAME, ORDINAL_POSITION
                        """
                        ),
                        {"db": db_name},
                    )
                )
                .mappings()
                .all()
            )

        table_map: dict[str, list[str]] = {}
        for r in rows:
            table = r["TABLE_NAME"]
            col = r["COLUMN_NAME"]
            data_type = r["DATA_TYPE"]
            comment = (r["COLUMN_COMMENT"] or "").strip()
            piece = (
                f"{col}:{data_type}" if not comment else f"{col}:{data_type}({comment})"
            )
            table_map.setdefault(table, []).append(piece)

        if not table_map:
            return settings.sql_schema_hint

        hint = "\n".join([f"{t}({', '.join(cols)})" for t, cols in table_map.items()])
        _SCHEMA_CACHE_TEXT = hint
        _SCHEMA_CACHE_AT = now
        return hint
    except Exception:
        return settings.sql_schema_hint


def _enforce_sql_guard(sql: str) -> tuple[str, dict[str, Any]]:
    guard = {"passed": False, "reason": "", "limit_applied": False}
    forbidden_patterns = [
        (r"::", "不允许 PostgreSQL 类型转换(::)"),
        (r"\bILIKE\b", "不允许 ILIKE，MySQL 请使用 LIKE"),
        (r"\bDATE_TRUNC\b", "不允许 DATE_TRUNC，请使用 MySQL 日期函数"),
        (r"\bFILTER\s*\(", "不允许 FILTER 子句"),
        (r"\bINTERVAL\s*'", "INTERVAL 不能使用单引号数字，请使用 INTERVAL 1 DAY"),
        (r"\bUNION\b", "请改为单条 SELECT（可用 CASE WHEN 条件聚合）"),
    ]
    for pattern, reason in forbidden_patterns:
        if re.search(pattern, sql, flags=re.IGNORECASE):
            guard["reason"] = reason
            raise ValueError(reason)

    parsed_list = sqlglot.parse(sql, read="mysql")
    if len(parsed_list) != 1:
        guard["reason"] = "仅允许单条 SQL"
        raise ValueError("SQL 必须为单语句")
    parsed = parsed_list[0]
    if not isinstance(parsed, exp.Select):
        guard["reason"] = "仅允许 SELECT"
        raise ValueError("仅允许 SELECT")

    limit_node = parsed.args.get("limit")
    max_rows = settings.sql_max_rows
    if limit_node is None:
        parsed.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
        guard["limit_applied"] = True
    else:
        current_limit = None
        expr = limit_node.expression
        if isinstance(expr, exp.Literal) and expr.is_int:
            current_limit = int(expr.this)
        if current_limit is None or current_limit > max_rows:
            parsed.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
            guard["limit_applied"] = True

    final_sql = parsed.sql(dialect="mysql")
    guard["passed"] = True
    guard["reason"] = "ok"
    return final_sql, guard


def _extract_compare_month_constraint(query: str) -> dict[str, Any] | None:
    text = (query or "").replace("月份", "月")
    m_same_last_year = re.search(r"去年\s*(\d{1,2})\s*月.*(?:相比|对比|比).*(?:去年)\s*(\d{1,2})\s*月", text)
    if m_same_last_year:
        m1 = int(m_same_last_year.group(1))
        m2 = int(m_same_last_year.group(2))
        if 1 <= m1 <= 12 and 1 <= m2 <= 12:
            return {"type": "same_last_year", "months": {m1, m2}}

    m_cross_year = re.search(r"今年\s*(\d{1,2})\s*月.*(?:相比|对比|比).*(?:去年)\s*(\d{1,2})\s*月", text)
    if m_cross_year:
        m_this = int(m_cross_year.group(1))
        m_last = int(m_cross_year.group(2))
        if 1 <= m_this <= 12 and 1 <= m_last <= 12:
            return {"type": "cross_year", "months": {m_this, m_last}}
    return None


def _enforce_semantic_guard(query: str, sql: str) -> None:
    constraint = _extract_compare_month_constraint(query)
    if constraint:
        sql_text = sql.lower()
        month_literals = set(int(x) for x in re.findall(r"(?<!\d)(?:1[0-2]|[1-9])(?!\d)", sql_text))
        missing = [m for m in constraint["months"] if m not in month_literals]
        if missing:
            raise ValueError(f"SQL 与问题时间口径不一致：缺少目标月份 {missing}")

    text = (query or "").replace("月份", "月")
    sql_lower = sql.lower()

    # 最近N天必须使用 DAY 粒度窗口，避免漂移成 MONTH/YEAR。
    m_recent_days = re.search(r"最近\s*(\d{1,3})\s*天", text)
    if m_recent_days:
        n = m_recent_days.group(1)
        if not re.search(rf"interval\s*'?\s*{n}\s*'?\s*day", sql_lower):
            raise ValueError(f"SQL 与问题时间口径不一致：应使用最近 {n} 天窗口")
        if re.search(rf"interval\s*'?\s*{n}\s*'?\s*(month|year)", sql_lower):
            raise ValueError(f"SQL 与问题时间口径不一致：最近 {n} 天误用了月/年单位")

    # 按天趋势必须按日期分组。
    if re.search(r"(按天|每天|日趋势)", text):
        has_day_expr = ("date(" in sql_lower) or ("date_format(" in sql_lower and "%y-%m-%d" in sql_lower)
        has_group_by = "group by" in sql_lower
        if not (has_day_expr and has_group_by):
            raise ValueError("SQL 与问题语义不一致：按天趋势必须按日期分组")


@tool("sql_query_tool")
async def sql_query_tool(query: str, intent: str = "report") -> dict[str, Any]:
    """根据自然语言查询生成并执行 MySQL SELECT，失败时自动修复 SQL 后重试。"""
    started = time.perf_counter()
    max_retries = 2
    attempts: list[dict[str, Any]] = []
    schema_hint = await _load_schema_hint_dynamic()

    rule_sql = _build_sql_by_rule(query, intent)
    if rule_sql:
        sql = rule_sql
    else:
        raw_sql = await deepseek_client.chat(
            system=build_sql_system(schema_hint),
            user=build_sql_user_prompt(query, intent=intent),
            temperature=0,
        )
        sql = _extract_select_sql(raw_sql)

    for attempt in range(max_retries + 1):
        try:
            guarded_sql, guard = _enforce_sql_guard(sql)
            _enforce_semantic_guard(query, guarded_sql)
            logging.info(f"Guard result: {guard}, SQL after guard: {guarded_sql}")

            async with AsyncSessionLocal() as session:
                result = await asyncio.wait_for(
                    session.execute(text(guarded_sql)),
                    timeout=settings.sql_timeout_seconds,
                )
                rows = [dict(r) for r in result.mappings().all()]
            return {
                "ok": True,
                "sql": guarded_sql,
                "rows": rows,
                "error": None,
                "debug": {
                    "guard": guard,
                    "attempts": attempts,
                    "final_attempt": attempt,
                    "recovered": attempt > 0,
                    "timing_ms": int((time.perf_counter() - started) * 1000),
                },
            }
        except Exception as exc:
            error_text = str(exc)
            attempts.append({"attempt": attempt, "sql": sql, "error": error_text})
            if attempt >= max_retries:
                return {
                    "ok": False,
                    "sql": sql,
                    "rows": [],
                    "error": error_text,
                    "debug": {
                        "attempts": attempts,
                        "final_attempt": attempt,
                        "recovered": False,
                        "timing_ms": int((time.perf_counter() - started) * 1000),
                    },
                }

            repaired_raw = await deepseek_client.chat(
                system=build_sql_repair_system(schema_hint),
                user=build_sql_repair_user_prompt(query, intent, sql, error_text),
                temperature=0,
            )
            sql = _extract_select_sql(repaired_raw)


@tool("kb_query_tool")
async def kb_query_tool(query: str, top_k: int = 5) -> dict[str, Any]:
    """向量检索知识库，返回知识片段列表。"""
    started = time.perf_counter()
    try:
        knowledge = await chroma_store.query(query, top_k=top_k)
        return {
            "ok": True,
            "knowledge": knowledge,
            "error": None,
            "debug": {
                "top_k": top_k,
                "count": len(knowledge),
                "timing_ms": int((time.perf_counter() - started) * 1000),
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "knowledge": [],
            "error": str(exc),
            "debug": {
                "top_k": top_k,
                "count": 0,
                "timing_ms": int((time.perf_counter() - started) * 1000),
            },
        }
