from __future__ import annotations

import json
import re
import time
from typing import Any

from app.core.config import get_settings
from app.db.crud import create_action_log, create_campaign, get_action_log_by_key, make_idempotency_key
from app.db.engine import AsyncSessionLocal
from app.llm.deepseek_client import deepseek_client
from app.llm.prompts import (
    DIAGNOSE_SYSTEM,
    PLAN_EXPLAIN_SYSTEM,
    PLAN_SYSTEM,
    REPORT_SUMMARY_SYSTEM,
    build_route_intent_system,
    build_diagnosis_fallback,
    build_diagnosis_user_prompt,
    build_plan_explain_user_prompt,
    build_plan_markdown,
    build_plan_schema_tip,
    build_plan_user_prompt,
    build_report_summary_user_prompt,
)
from app.graph.tools import kb_query_tool, sql_query_tool
from app.integrations.crm_client import crm_client

settings = get_settings()


def _timer() -> float:
    # 统一计时起点。
    return time.perf_counter()


def _add_timing(state: dict, key: str, start: float) -> None:
    # 将节点耗时写入 debug.timings_ms，便于链路排障。
    debug = state.setdefault("debug", {})
    timings = debug.setdefault("timings_ms", {})
    timings[key] = int((time.perf_counter() - start) * 1000)


def _extract_json_block(s: str) -> dict[str, Any]:
    # 兼容 LLM 返回的 ```json 包裹文本。
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?", "", s).strip()
        s = s.removesuffix("```").strip()

    # 兼容解释文本 + JSON 的混合输出，截取最外层 JSON。
    if "{" in s and "}" in s:
        start = s.find("{")
        end = s.rfind("}")
        s = s[start : end + 1]

    return json.loads(s)


def _extract_budget_duration(query: str) -> tuple[int, int]:
    # 从用户问题解析预算和周期；无法解析时退回配置默认值。
    budget = settings.plan_default_budget
    duration = settings.plan_default_duration_days
    q = query.replace(",", "，")

    # 优先识别“x万”格式。
    m_budget = re.search(r"预算\s*([0-9]+(?:\.[0-9]+)?)\s*万", q)
    if m_budget:
        budget = int(float(m_budget.group(1)) * 10000)
    else:
        # 兜底识别直接金额数字。
        m_budget2 = re.search(r"预算\s*([0-9]+)", q)
        if m_budget2:
            budget = int(m_budget2.group(1))

    # 解析“x天”周期。
    m_duration = re.search(r"([0-9]+)\s*天", q)
    if m_duration:
        duration = int(m_duration.group(1))

    return budget, duration


async def route_intent(state: dict) -> dict:
    # 1) 读取输入上下文。
    start = _timer()
    query = state.get("user_query", "")
    plan = state.get("plan")

    # 2) 若已有结构化 plan，则执行链路优先，避免分类歧义。
    if plan:
        intent = "execute"
        llm_result = "skipped_by_plan"
    else:
        # 3) 纯 LLM 分类：使用包含定义与示例的 few-shot 提示词。
        llm_result = await deepseek_client.chat(system=build_route_intent_system(), user=query, temperature=0)
        llm_result = llm_result.strip().lower()
        intent = llm_result if llm_result in {"report", "diagnose", "plan", "execute"} else "report"

    # 4) 写入调试信息，便于观察分类稳定性。
    state.setdefault("debug", {})["route_intent"] = {"llm": llm_result, "final": intent, "has_plan": bool(plan)}

    _add_timing(state, "route", start)
    return {"intent": intent, "debug": state.get("debug", {})}


async def compose_report_answer(state: dict) -> dict:
    # 1) 组装报表结构。
    start = _timer()
    query = state.get("user_query", "")
    intent = state.get("intent", "report")
    tool_result = await sql_query_tool.ainvoke({"query": query, "intent": intent})
    rows = tool_result.get("rows") or []
    columns = list(rows[0].keys()) if rows else []
    stream_cb = state.get("stream_cb")
    debug = state.setdefault("debug", {})
    debug["tools"] = {
        **(debug.get("tools") or {}),
        "sql_query_tool": tool_result.get("debug", {}),
    }

    # 2) 基于查询结果动态生成自然语言总结，避免固定模板口径。
    sql_error = tool_result.get("error")
    if sql_error:
        answer = f"数据查询执行失败，已自动尝试修复但未成功：{sql_error}。请调整问题口径后重试。"
        if stream_cb is not None:
            await stream_cb(answer)
        _add_timing(state, "compose", start)
        return {
            "answer": answer,
            "report": {"columns": columns, "rows": rows},
            "debug": debug,
        }

    if rows:
        report_prompt = build_report_summary_user_prompt(state.get("user_query", ""), rows)
        if stream_cb is not None:
            answer = await deepseek_client.chat_stream(
                system=REPORT_SUMMARY_SYSTEM,
                user=report_prompt,
                temperature=0.2,
                on_token=stream_cb,
            )
        else:
            answer = await deepseek_client.chat(system=REPORT_SUMMARY_SYSTEM, user=report_prompt, temperature=0.2)
        if not answer.strip():
            answer = f"已返回 {len(rows)} 条数据，请查看下方表格。"
    else:
        answer = "未查到匹配数据。建议调整时间范围、门店范围或指标口径后重试。"
        if stream_cb is not None:
            await stream_cb(answer)

    # 3) 回传 answer + report。
    _add_timing(state, "compose", start)
    return {
        "answer": answer,
        "report": {"columns": columns, "rows": rows},
        "debug": debug,
    }


async def compose_diagnosis_answer(state: dict) -> dict:
    # 1) 准备数据证据与知识证据上下文。
    start = _timer()
    query = state.get("user_query", "")
    intent = state.get("intent", "diagnose")
    sql_result = await sql_query_tool.ainvoke({"query": query, "intent": intent})
    # 诊断口径查不到数据时，自动降级到报表口径再查一次，避免“样本为空”。
    if (not sql_result.get("error")) and not (sql_result.get("rows") or []):
        fallback_sql_result = await sql_query_tool.ainvoke({"query": query, "intent": "report"})
        if fallback_sql_result.get("rows"):
            sql_result = fallback_sql_result
    kb_result = await kb_query_tool.ainvoke({"query": query, "top_k": 5})
    rows = sql_result.get("rows") or []
    knowledge = kb_result.get("knowledge") or []
    stream_cb = state.get("stream_cb")
    user_prompt = build_diagnosis_user_prompt(query, rows, knowledge)
    debug = state.setdefault("debug", {})
    debug["tools"] = {
        **(debug.get("tools") or {}),
        "sql_query_tool": sql_result.get("debug", {}),
        "kb_query_tool": kb_result.get("debug", {}),
    }

    # 2) 根据是否需要流式，选择普通/流式 LLM 调用。
    if stream_cb is not None:
        answer = await deepseek_client.chat_stream(
            system=DIAGNOSE_SYSTEM,
            user=user_prompt,
            temperature=0.2,
            on_token=stream_cb,
        )
    else:
        answer = await deepseek_client.chat(system=DIAGNOSE_SYSTEM, user=user_prompt, temperature=0.2)

    # 3) 若未满足“来源标注”约束，降级为兜底诊断模板。
    if "(data)" not in answer or "(kb)" not in answer:
        answer = build_diagnosis_fallback()

    _add_timing(state, "compose", start)
    return {"answer": answer, "debug": debug}


async def gen_campaign_plan(state: dict) -> dict:
    # 1) 解析预算/周期并准备知识上下文。
    start = _timer()
    query = state.get("user_query", "")
    kb_result = await kb_query_tool.ainvoke({"query": query, "top_k": 5})
    knowledge = kb_result.get("knowledge") or []
    budget, duration = _extract_budget_duration(query)
    kb_text = "\n".join([f"- {k['title']}: {k['content']}" for k in knowledge])
    debug = state.setdefault("debug", {})
    debug["tools"] = {
        **(debug.get("tools") or {}),
        "kb_query_tool": kb_result.get("debug", {}),
    }

    # 2) 生成 schema 约束与用户提示，调用 LLM 产出结构化 plan。
    schema_tip = build_plan_schema_tip(settings, budget=budget, duration=duration)
    user_prompt = build_plan_user_prompt(query, budget, duration, kb_text, schema_tip)
    raw = await deepseek_client.chat(system=PLAN_SYSTEM, user=user_prompt, temperature=0.2)
    plan = _extract_json_block(raw)

    # 3) 兜底补齐关键字段，确保后续可执行。
    plan.setdefault("budget", budget)
    plan.setdefault("duration_days", duration)

    # 4) 基于“用户需求 + 知识 + 结构化 plan”由 LLM 动态生成方案说明。
    explain_user = build_plan_explain_user_prompt(query, knowledge, plan)
    answer = await deepseek_client.chat(system=PLAN_EXPLAIN_SYSTEM, user=explain_user, temperature=0.2)
    if not answer.strip():
        # 5) 若生成异常，退回通用兜底文案（不写死具体促销参数）。
        answer = build_plan_markdown(plan, settings, budget=budget, duration=duration)
    stream_cb = state.get("stream_cb")
    if stream_cb is not None:
        await stream_cb(answer)

    _add_timing(state, "compose", start)
    return {"plan": plan, "answer": answer, "debug": debug}


async def execute_campaign(state: dict) -> dict:
    # 1) 准备执行输入并对 plan 做最小修复。
    start = _timer()
    plan = state.get("plan") or {}
    debug = state.setdefault("debug", {})
    debug.setdefault("plan_fixed", False)

    required_offer_keys = {"type", "threshold", "value", "max_redemptions"}
    if "offer" not in plan or not required_offer_keys.issubset(set(plan.get("offer", {}).keys())):
        plan.setdefault("offer", {})
        plan["offer"].setdefault("type", settings.plan_default_offer_type)
        plan["offer"].setdefault("threshold", settings.plan_default_offer_threshold)
        plan["offer"].setdefault("value", settings.plan_default_offer_value)
        plan["offer"].setdefault("max_redemptions", settings.plan_default_offer_max_redemptions)
        plan.setdefault("duration_days", settings.plan_default_duration_days)
        plan.setdefault("goal", settings.plan_default_goal)
        plan.setdefault("budget", settings.plan_default_budget)
        plan.setdefault("channels", settings.plan_channels)
        plan.setdefault(
            "target_segment",
            {"definition": settings.plan_default_target_definition, "rules": settings.plan_target_rules},
        )
        plan.setdefault(
            "kpi",
            {"primary": settings.plan_default_kpi_primary, "targets": settings.plan_kpi_targets},
        )
        plan.setdefault("risk_controls", settings.plan_risk_controls)
        debug["plan_fixed"] = True

    # 2) 生成幂等键，防止重复执行。
    idem_key = make_idempotency_key(plan)

    async with AsyncSessionLocal() as session:
        # 3) 已成功执行过则直接返回历史结果。
        existing = await get_action_log_by_key(session, idem_key)
        if existing and existing.status == "success":
            execution = json.loads(existing.response_json)
            _add_timing(state, "execute", start)
            return {"execution": execution, "debug": debug}

        try:
            # 4) 先落库 campaign，再调用 CRM 创建并发布券。
            campaign_name = f"campaign-{int(time.time())}"
            await create_campaign(
                session,
                name=campaign_name,
                goal=plan.get("goal", settings.plan_default_goal),
                budget=float(plan.get("budget", settings.plan_default_budget)),
                duration_days=int(plan.get("duration_days", settings.plan_default_duration_days)),
                plan=plan,
            )

            create_payload = {
                "name": campaign_name,
                "offer": plan["offer"],
                "duration_days": int(plan.get("duration_days", settings.plan_default_duration_days)),
            }
            created = await crm_client.create_coupon(create_payload)
            coupon_id = int(created["coupon_id"])
            published = await crm_client.publish_coupon(coupon_id)

            # 5) 记录成功日志并提交事务。
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
            # 6) 记录失败日志，返回失败结构，保证调用方可感知错误。
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
