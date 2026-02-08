from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import Settings


ROUTE_INTENT_SYSTEM = """你是意图分类器，只能输出：report / diagnose / plan / execute（单词，小写）。"""

SQL_SYSTEM = """你是严格的 MySQL 8.0 SQL 生成器。
硬性约束：
1) 仅允许输出一条 SELECT 语句（可含子查询），禁止 INSERT/UPDATE/DELETE/DDL/SET/CALL/EXPLAIN。
2) 只输出 SQL 本体，不要任何解释、注释、Markdown、代码块、前后缀文本。
3) 必须使用 MySQL 语法：日期区间优先使用 CURDATE()/NOW() + DATE_SUB(..., INTERVAL n DAY|MONTH|YEAR)。
4) 禁止 PostgreSQL 风格写法：例如 INTERVAL '1' YEAR、::date、ILIKE、DATE_TRUNC、FILTER 子句等。
5) 优先使用显式 JOIN 条件，避免笛卡尔积；聚合场景保证 GROUP BY 与聚合字段匹配。
6) 语义上应与用户问题一致：时间窗口、分组维度、指标口径必须可解释且不臆造字段。
7) 返回列别名使用简洁英文 snake_case。
8) 若问题是“两个明确时间段对比”（例如去年12月 vs 去年11月），必须只查询这两个时间段，不得扩展到其他月份。
9) 对比型问题优先同时返回：基期值、对比期值、差值(diff)、变化率(change_rate)。
10) INTERVAL 数值禁止单引号，必须使用如 INTERVAL 7 DAY、INTERVAL 1 MONTH。
"""

SQL_REPAIR_SYSTEM = """你是 MySQL 8.0 SQL 修复器。
输入会包含：用户问题、意图、失败SQL、数据库报错、可用schema。
你的任务：只输出一条修复后的可执行 SELECT SQL。
硬性约束：
1) 仅输出 SQL，不要解释、不要注释、不要代码块。
2) 只能使用 MySQL 语法，禁止 PostgreSQL 风格写法。
3) 不得使用非只读语句（INSERT/UPDATE/DELETE/DDL/SET/CALL/EXPLAIN）。
4) 若原 SQL 指标口径明显偏离用户问题，需要在不臆造字段的前提下纠正。
"""

REPORT_SUMMARY_SYSTEM = """你是零售数据解读助手。
请根据用户问题和查询结果，输出简洁的 Markdown 自然语言结论，避免输出 JSON。
要求：
1) 先给出一句总体结论，再给 2-4 条关键发现；
2) 若结果为空，明确说明“未查到匹配数据”，并给出下一步建议；
3) 不要编造数据，数值必须来自输入结果；
4) 语气专业、可读，避免模板化固定口径。"""

DIAGNOSE_SYSTEM = """你是零售经营诊断助手，严格输出四段：
1. 发现（必须引用 data）
2. 原因假设（必须引用 kb）
3. 验证（必须引用 data）
4. 下一步（引用 kb 或 data）
每条结论都必须标注来源：(data) 或 (kb)。"""

PLAN_SYSTEM = """你是营销活动方案生成器，只输出 JSON，且必须符合目标 schema。
从用户输入提取预算与周期；offer 必须包含 type/threshold/value/max_redemptions。"""

EXECUTE_FIX_SYSTEM = """如果 plan 缺字段，请补齐最小默认值，并仅输出 JSON。"""

PLAN_EXPLAIN_SYSTEM = """你是零售增长策略顾问。请根据用户需求、知识要点和结构化 plan，输出面向运营同学的 Markdown 方案说明。
要求：
1) 不要照抄固定模板，要根据输入内容动态组织结构；
2) 重点解释“为什么这样设计”，体现业务逻辑；
3) 输出应包含：目标与人群、策略设计、预算与周期、指标与监控、风险与回滚；
4) 如果 plan 中有字段冲突或信息不足，要明确标注“待确认项”；
5) 语言简洁、可执行，不要输出 JSON。"""


def build_route_intent_system() -> str:
    return """你是零售运营助手的意图分类器。
你的任务：对用户问题进行四分类，只能输出一个单词：report / diagnose / plan / execute（小写）。

分类标准：
- report：用户要看数据报表、趋势、分组统计、指标看板。
- diagnose：用户在问“为什么下降/异常原因/需要验证原因”，强调分析原因与验证。
- plan：用户要“活动方案/策略设计/预算与周期规划”，强调制定方案而非执行。
- execute：用户明确要求“执行/上架/发布/创建券并生效”等落地动作。

判定优先级：
1) 若同时包含“方案设计”和“执行”，以用户最后目标为准；
2) 若表达模糊但更像“看数据”，归类为 report；
3) 绝对不能输出解释，只输出标签单词。

示例：
用户：最近7天各门店GMV、客单价、订单数，按天趋势
输出：report

用户：这周复购率下降了，可能原因是什么？用数据验证
输出：diagnose

用户：给高价值老客做一个促复购活动，预算3万，7天
输出：plan

用户：把这个活动执行上架，直接发券
输出：execute
"""


def build_sql_system(schema_hint: str) -> str:
    return f"""{SQL_SYSTEM}
可用 schema:
{schema_hint}
"""


def build_sql_repair_system(schema_hint: str) -> str:
    return f"""{SQL_REPAIR_SYSTEM}
可用 schema:
{schema_hint}
"""


def build_sql_user_prompt(query: str, intent: str | None = None) -> str:
    label = intent or "unknown"
    compare_hint = build_sql_compare_hint(query)
    return (
        f"用户问题：{query}\n"
        f"上游意图：{label}\n"
        f"{compare_hint}\n"
        "请基于问题自主选择查询口径并生成可执行 MySQL SELECT 语句。"
    )


def build_sql_repair_user_prompt(query: str, intent: str, failed_sql: str, error_text: str) -> str:
    compare_hint = build_sql_compare_hint(query)
    return (
        f"用户问题：{query}\n"
        f"上游意图：{intent}\n"
        f"{compare_hint}\n"
        f"失败SQL：{failed_sql}\n"
        f"数据库错误：{error_text}\n"
        "请输出修复后的 MySQL SELECT SQL。"
    )


def build_sql_compare_hint(query: str) -> str:
    text = (query or "").replace("月份", "月")
    p_same_last_year = re.search(r"去年\s*(\d{1,2})\s*月.*(?:相比|对比|比).*(?:去年)\s*(\d{1,2})\s*月", text)
    if p_same_last_year:
        m1 = int(p_same_last_year.group(1))
        m2 = int(p_same_last_year.group(2))
        if 1 <= m1 <= 12 and 1 <= m2 <= 12:
            return (
                "时间对比约束：这是“去年两个月对比”问题。"
                f"必须只统计去年{m1}月和去年{m2}月；"
                "不要扩展到其他月份；输出请包含两期值、差值和变化率。"
            )

    p_cross_year = re.search(r"今年\s*(\d{1,2})\s*月.*(?:相比|对比|比).*(?:去年)\s*(\d{1,2})\s*月", text)
    if p_cross_year:
        m_this = int(p_cross_year.group(1))
        m_last = int(p_cross_year.group(2))
        if 1 <= m_this <= 12 and 1 <= m_last <= 12:
            return (
                "时间对比约束：这是“今年某月 vs 去年某月”跨年对比。"
                f"必须只统计今年{m_this}月和去年{m_last}月；"
                "不要扩展到其他月份；输出请包含两期值、差值和变化率。"
            )

    p_recent_days = re.search(r"最近\s*(\d{1,3})\s*天", text)
    if p_recent_days:
        n = int(p_recent_days.group(1))
        day_trend = bool(re.search(r"(按天|每天|日趋势)", text))
        if day_trend:
            return (
                f"时间窗口约束：必须严格按最近{n}天统计，使用 INTERVAL {n} DAY。"
                "这是按天趋势问题，必须按日期分组并按日期升序。"
            )
        return f"时间窗口约束：必须严格按最近{n}天统计，使用 INTERVAL {n} DAY，不要擅自改成按月或按年。"

    return "时间口径约束：必须严格对齐用户问题中的时间描述。"


def build_report_summary_user_prompt(user_query: str, rows: list[dict]) -> str:
    data_sample = json.dumps(rows, ensure_ascii=False, default=str)
    return f"用户问题：{user_query}\n查询结果(JSON)：{data_sample}"


def build_diagnosis_user_prompt(user_query: str, rows: list[dict], knowledge: list[dict]) -> str:
    data_sample = json.dumps(rows[:5], ensure_ascii=False, default=str)
    kb_sample = "\n".join([f"- {k['title']}: {k['content']}" for k in knowledge])
    return f"用户问题：{user_query}\n数据样本：{data_sample}\n知识要点：\n{kb_sample}"


def build_diagnosis_fallback() -> str:
    return (
        "1. 发现：近7天复购相关指标出现下滑，且部分门店支付成功率下降 (data)\n"
        "2. 原因假设：可能由券到期、触达下降、支付失败上升等导致 (kb)\n"
        "3. 验证：需按老客下单率、支付成功率、渠道占比分解对比近14天 (data)\n"
        "4. 下一步：优先做老客定向券并监控核销与支付链路，设置预算上限 (kb)"
    )


def build_plan_schema_tip(settings: Settings, budget: int, duration: int) -> dict[str, Any]:
    return {
        "goal": "string",
        "duration_days": duration,
        "budget": budget,
        "target_segment": {"definition": "string", "rules": ["..."]},
        "offer": {"type": "full_reduction|discount|points", "threshold": 0, "value": 0, "max_redemptions": 0},
        "channels": settings.plan_channels,
        "kpi": {"primary": settings.plan_default_kpi_primary, "targets": ["..."]},
        "risk_controls": ["..."],
        "sql_preview": "optional string",
    }


def build_plan_user_prompt(query: str, budget: int, duration: int, kb_text: str, schema_tip: dict[str, Any]) -> str:
    return (
        f"用户需求：{query}\n"
        f"预算默认：{budget}\n"
        f"周期默认：{duration}\n"
        f"知识库：\n{kb_text}\n"
        f"输出schema：{json.dumps(schema_tip, ensure_ascii=False)}"
    )


def build_plan_explain_user_prompt(query: str, knowledge: list[dict], plan: dict[str, Any]) -> str:
    kb_text = "\n".join([f"- {k.get('title', '')}: {k.get('content', '')}" for k in knowledge]) or "- 无"
    return (
        f"用户需求：{query}\n"
        f"知识要点：\n{kb_text}\n"
        f"结构化方案（JSON）：\n{json.dumps(plan, ensure_ascii=False)}\n"
        "请输出可直接给运营同学评审的 Markdown 方案说明。"
    )


def build_plan_markdown(plan: dict[str, Any], settings: Settings, budget: int, duration: int) -> str:
    goal = plan.get("goal", settings.plan_default_goal)
    duration_days = plan.get("duration_days", duration)
    budget_value = plan.get("budget", budget)

    lines = [
        "## 活动方案（兜底）",
        "",
        f"- 目标：{goal}",
        f"- 周期：{duration_days} 天",
        f"- 预算：{budget_value} 元",
        "",
        "### 结构化方案要点",
    ]

    for key, value in plan.items():
        if isinstance(value, (dict, list)):
            lines.append(f"- {key}：`{json.dumps(value, ensure_ascii=False)}`")
        else:
            lines.append(f"- {key}：{value}")

    lines.append("")
    lines.append("### 待确认")
    lines.append("- 请结合门店实时数据与渠道成本，确认最终优惠强度与投放节奏。")
    return "\n".join(lines)
