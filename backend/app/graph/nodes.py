from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import sqlglot
from sqlglot import exp
from sqlalchemy import text

from app.core.config import get_settings
from app.db.crud import create_action_log, create_campaign, get_action_log_by_key, make_idempotency_key
from app.db.engine import AsyncSessionLocal
from app.llm.deepseek_client import deepseek_client
from app.llm.prompts import DIAGNOSE_SYSTEM, PLAN_SYSTEM, ROUTE_INTENT_SYSTEM, SQL_SYSTEM
from app.rag.chroma_store import chroma_store
from app.integrations.crm_client import crm_client

settings = get_settings()


def _timer() -> float:
    return time.perf_counter()


def _add_timing(state: dict, key: str, start: float) -> None:
    debug = state.setdefault("debug", {})
    timings = debug.setdefault("timings_ms", {})
    timings[key] = int((time.perf_counter() - start) * 1000)


def _extract_json_block(s: str) -> dict[str, Any]:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?", "", s).strip()
        s = s.removesuffix("```").strip()
    if "{" in s and "}" in s:
        start = s.find("{")
        end = s.rfind("}")
        s = s[start : end + 1]
    return json.loads(s)


def _extract_budget_duration(query: str) -> tuple[int, int]:
    budget = 30000
    duration = 7
    q = query.replace(",", "，")

    m_budget = re.search(r"预算\s*([0-9]+(?:\.[0-9]+)?)\s*万", q)
    if m_budget:
        budget = int(float(m_budget.group(1)) * 10000)
    else:
        m_budget2 = re.search(r"预算\s*([0-9]+)", q)
        if m_budget2:
            budget = int(m_budget2.group(1))

    m_duration = re.search(r"([0-9]+)\s*天", q)
    if m_duration:
        duration = int(m_duration.group(1))

    return budget, duration


async def route_intent(state: dict) -> dict:
    start = _timer()
    query = state.get("user_query", "")
    plan = state.get("plan")

    intent = "report"
    if plan and any(k in query for k in ["执行", "上架", "创建", "发布"]):
        intent = "execute"
    else:
        rule_map = [
            ("report", ["报表", "趋势", "gmv", "订单", "客单价"]),
            ("diagnose", ["下降", "原因", "怎么回事", "诊断", "为什么"]),
            ("plan", ["活动", "优惠券", "预算", "策划", "方案"]),
            ("execute", ["执行", "上架", "创建券", "发布券"]),
        ]
        lowered = query.lower()
        rule_hit = None
        for i, words in rule_map:
            if any(w in lowered for w in words):
                rule_hit = i
                break

        if rule_hit:
            intent = rule_hit
            llm_result = "skipped_by_rule"
        else:
            llm_result = await deepseek_client.chat(system=ROUTE_INTENT_SYSTEM, user=query, temperature=0)
            llm_result = llm_result.strip().lower()
            if llm_result in {"report", "diagnose", "plan", "execute"}:
                intent = llm_result

        state.setdefault("debug", {})["route_intent"] = {"llm": llm_result, "rule_hit": rule_hit, "final": intent}

    _add_timing(state, "route", start)
    return {"intent": intent, "debug": state.get("debug", {})}


async def gen_sql(state: dict) -> dict:
    start = _timer()
    query = state.get("user_query", "")
    lowered = query.lower()
    if any(k in lowered for k in ["gmv", "客单价", "订单数", "趋势", "报表"]):
        sql = (
            "SELECT DATE(paid_at) AS dt, store_id, "
            "SUM(CASE WHEN pay_status=1 THEN amount ELSE 0 END) AS gmv, "
            "SUM(CASE WHEN pay_status=1 THEN 1 ELSE 0 END) AS order_cnt, "
            "AVG(CASE WHEN pay_status=1 THEN amount END) AS aov "
            "FROM orders "
            "WHERE paid_at >= DATE_SUB(NOW(), INTERVAL 7 DAY) "
            "GROUP BY DATE(paid_at), store_id "
            "ORDER BY dt DESC, store_id"
        )
    elif any(k in lowered for k in ["复购", "下降", "诊断", "原因"]):
        sql = (
            "WITH w AS ("
            "SELECT member_id, "
            "SUM(CASE WHEN paid_at >= DATE_SUB(NOW(), INTERVAL 7 DAY) AND pay_status=1 THEN 1 ELSE 0 END) AS c7, "
            "SUM(CASE WHEN paid_at >= DATE_SUB(NOW(), INTERVAL 14 DAY) AND paid_at < DATE_SUB(NOW(), INTERVAL 7 DAY) AND pay_status=1 THEN 1 ELSE 0 END) AS c14 "
            "FROM orders WHERE member_id IS NOT NULL GROUP BY member_id"
            ") "
            "SELECT "
            "AVG(CASE WHEN c7>=2 THEN 1 ELSE 0 END) AS repurchase_7d, "
            "AVG(CASE WHEN c14>=2 THEN 1 ELSE 0 END) AS repurchase_prev_7d "
            "FROM w"
        )
    else:
        raw = await deepseek_client.chat(system=SQL_SYSTEM, user=query, temperature=0)
        cleaned = raw.replace("```sql", "").replace("```", "").strip()
        m = re.search(r"(?is)select\\s.+?(?:;|$)", cleaned)
        sql = m.group(0).strip() if m else cleaned
    _add_timing(state, "gen_sql", start)
    return {"sql": sql, "debug": state.get("debug", {})}


async def guard_sql(state: dict) -> dict:
    sql = (state.get("sql") or "").strip()
    guard = {"passed": False, "reason": "", "limit_applied": False}
    parsed_list = sqlglot.parse(sql, read="mysql")
    if len(parsed_list) != 1:
        guard["reason"] = "仅允许单条 SQL"
        state.setdefault("debug", {})["guard"] = guard
        raise ValueError("SQL 必须为单语句")
    parsed = parsed_list[0]
    if not isinstance(parsed, exp.Select):
        guard["reason"] = "仅允许 SELECT"
        state.setdefault("debug", {})["guard"] = guard
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
    debug = state.setdefault("debug", {})
    debug["guard"] = guard
    debug["sql"] = final_sql
    return {"sql": final_sql, "debug": debug}


async def run_sql(state: dict) -> dict:
    start = _timer()
    sql = state.get("sql")

    async def _exec() -> list[dict]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(sql))
            return [dict(r) for r in result.mappings().all()]

    rows = await asyncio.wait_for(_exec(), timeout=settings.sql_timeout_seconds)
    _add_timing(state, "run_sql", start)
    return {"rows": rows, "debug": state.get("debug", {})}


async def retrieve_kb(state: dict) -> dict:
    start = _timer()
    query = state.get("user_query", "")
    knowledge = await chroma_store.query(query, top_k=5)
    _add_timing(state, "retrieve_kb", start)
    return {"knowledge": knowledge, "debug": state.get("debug", {})}


async def compose_report_answer(state: dict) -> dict:
    start = _timer()
    rows = state.get("rows") or []
    columns = list(rows[0].keys()) if rows else []
    answer = "报表已生成。口径说明：GMV 为 pay_status=1 的 amount 汇总；客单价=GMV/成功订单数。"
    stream_cb = state.get("stream_cb")
    if stream_cb is not None:
        await stream_cb(answer)
    _add_timing(state, "compose", start)
    return {
        "answer": answer,
        "report": {"columns": columns, "rows": rows},
        "debug": state.get("debug", {}),
    }


async def compose_diagnosis_answer(state: dict) -> dict:
    start = _timer()
    rows = state.get("rows") or []
    knowledge = state.get("knowledge") or []
    stream_cb = state.get("stream_cb")
    data_sample = json.dumps(rows[:5], ensure_ascii=False, default=str)
    kb_sample = "\n".join([f"- {k['title']}: {k['content']}" for k in knowledge])
    user_prompt = f"用户问题：{state.get('user_query')}\n数据样本：{data_sample}\n知识要点：\n{kb_sample}"
    if stream_cb is not None:
        answer = await deepseek_client.chat_stream(
            system=DIAGNOSE_SYSTEM,
            user=user_prompt,
            temperature=0.2,
            on_token=stream_cb,
        )
    else:
        answer = await deepseek_client.chat(system=DIAGNOSE_SYSTEM, user=user_prompt, temperature=0.2)

    if "(data)" not in answer or "(kb)" not in answer:
        answer = (
            "1. 发现：近7天复购相关指标出现下滑，且部分门店支付成功率下降 (data)\n"
            "2. 原因假设：可能由券到期、触达下降、支付失败上升等导致 (kb)\n"
            "3. 验证：需按老客下单率、支付成功率、渠道占比分解对比近14天 (data)\n"
            "4. 下一步：优先做老客定向券并监控核销与支付链路，设置预算上限 (kb)"
        )
    _add_timing(state, "compose", start)
    return {"answer": answer, "debug": state.get("debug", {})}


async def gen_campaign_plan(state: dict) -> dict:
    start = _timer()
    query = state.get("user_query", "")
    knowledge = state.get("knowledge") or []
    budget, duration = _extract_budget_duration(query)
    kb_text = "\n".join([f"- {k['title']}: {k['content']}" for k in knowledge])
    schema_tip = {
        "goal": "string",
        "duration_days": duration,
        "budget": budget,
        "target_segment": {"definition": "string", "rules": ["..."]},
        "offer": {"type": "full_reduction|discount|points", "threshold": 0, "value": 0, "max_redemptions": 0},
        "channels": ["app_push", "sms", "wechat"],
        "kpi": {"primary": "repeat_rate", "targets": ["..."]},
        "risk_controls": ["..."],
        "sql_preview": "optional string",
    }
    user_prompt = f"用户需求：{query}\n预算默认：{budget}\n周期默认：{duration}\n知识库：\n{kb_text}\n输出schema：{json.dumps(schema_tip, ensure_ascii=False)}"
    raw = await deepseek_client.chat(system=PLAN_SYSTEM, user=user_prompt, temperature=0.2)
    plan = _extract_json_block(raw)
    plan.setdefault("budget", budget)
    plan.setdefault("duration_days", duration)
    target = plan.get("target_segment") or {}
    offer = plan.get("offer") or {}
    kpi = plan.get("kpi") or {}
    risk_controls = plan.get("risk_controls") or []
    channels = plan.get("channels") or []
    rules = target.get("rules") if isinstance(target, dict) else []
    targets = kpi.get("targets") if isinstance(kpi, dict) else []

    rules_md = "\n".join([f"- {x}" for x in rules[:4]]) if isinstance(rules, list) and rules else "- 使用近30天高价值老客标签"
    risk_md = (
        "\n".join([f"- {x}" for x in risk_controls[:4]])
        if isinstance(risk_controls, list) and risk_controls
        else "- 单用户限领1次，预算超 80% 触发预警"
    )
    channels_md = (
        "、".join([str(x) for x in channels if x]) if isinstance(channels, list) and channels else "App Push、短信、企业微信"
    )
    kpi_md = "\n".join([f"- {x}" for x in targets[:3]]) if isinstance(targets, list) and targets else "- 7天复购率提升 2~3 个百分点"

    answer = (
        f"## 促复购活动方案\n\n"
        f"已基于你的要求生成方案，建议周期 **{plan.get('duration_days', duration)} 天**，"
        f"预算 **{plan.get('budget', budget)} 元**，目标是 **{plan.get('goal', '提升复购')}**。\n\n"
        f"### 1. 人群策略\n"
        f"- 人群定义：{target.get('definition', '近30天有消费且客单价较高的老客') if isinstance(target, dict) else '近30天高价值老客'}\n"
        f"{rules_md}\n\n"
        f"### 2. 优惠策略\n"
        f"- 类型：{offer.get('type', 'full_reduction')}\n"
        f"- 门槛：满 {offer.get('threshold', 99)} 元\n"
        f"- 面额/折扣：{offer.get('value', 20)}\n"
        f"- 发放上限：{offer.get('max_redemptions', 1000)}\n"
        f"- 触达渠道：{channels_md}\n\n"
        f"### 3. KPI 目标\n"
        f"- 主指标：{kpi.get('primary', 'repeat_rate') if isinstance(kpi, dict) else 'repeat_rate'}\n"
        f"{kpi_md}\n\n"
        f"### 4. 风险控制\n"
        f"{risk_md}\n\n"
        f"确认后可直接点击 **执行上架（场景D）** 进入发布闭环。"
    )
    stream_cb = state.get("stream_cb")
    if stream_cb is not None:
        await stream_cb(answer)
    _add_timing(state, "compose", start)
    return {"plan": plan, "answer": answer, "debug": state.get("debug", {})}


async def execute_campaign(state: dict) -> dict:
    start = _timer()
    plan = state.get("plan") or {}
    debug = state.setdefault("debug", {})
    debug.setdefault("plan_fixed", False)

    required_offer_keys = {"type", "threshold", "value", "max_redemptions"}
    if "offer" not in plan or not required_offer_keys.issubset(set(plan.get("offer", {}).keys())):
        plan.setdefault("offer", {})
        plan["offer"].setdefault("type", "full_reduction")
        plan["offer"].setdefault("threshold", 99)
        plan["offer"].setdefault("value", 20)
        plan["offer"].setdefault("max_redemptions", 1000)
        plan.setdefault("duration_days", 7)
        plan.setdefault("goal", "提升复购")
        debug["plan_fixed"] = True

    idem_key = make_idempotency_key(plan)

    async with AsyncSessionLocal() as session:
        existing = await get_action_log_by_key(session, idem_key)
        if existing and existing.status == "success":
            execution = json.loads(existing.response_json)
            _add_timing(state, "execute", start)
            return {"execution": execution, "debug": debug}

        try:
            campaign_name = f"campaign-{int(time.time())}"
            await create_campaign(
                session,
                name=campaign_name,
                goal=plan.get("goal", "促复购"),
                budget=float(plan.get("budget", 30000)),
                duration_days=int(plan.get("duration_days", 7)),
                plan=plan,
            )

            create_payload = {
                "name": campaign_name,
                "offer": plan["offer"],
                "duration_days": int(plan.get("duration_days", 7)),
            }
            created = await crm_client.create_coupon(create_payload)
            coupon_id = int(created["coupon_id"])
            published = await crm_client.publish_coupon(coupon_id)

            execution = {
                "idempotency_key": idem_key,
                "coupon_id": coupon_id,
                "publish_status": published.get("status", "unknown"),
                "error": None,
            }
            await create_action_log(
                session,
                idempotency_key=idem_key,
                action_type="publish_coupon",
                request_json=json.dumps(plan, ensure_ascii=False),
                response_json=json.dumps(execution, ensure_ascii=False),
                status="success",
                error_message=None,
            )
            await session.commit()
            _add_timing(state, "execute", start)
            return {"execution": execution, "debug": debug}
        except Exception as exc:
            execution = {
                "idempotency_key": idem_key,
                "coupon_id": None,
                "publish_status": "failed",
                "error": str(exc),
            }
            await create_action_log(
                session,
                idempotency_key=idem_key,
                action_type="publish_coupon",
                request_json=json.dumps(plan, ensure_ascii=False),
                response_json=json.dumps(execution, ensure_ascii=False),
                status="failed",
                error_message=str(exc),
            )
            await session.commit()
            _add_timing(state, "execute", start)
            return {"execution": execution, "debug": debug}

