from __future__ import annotations

from collections.abc import Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    compose_diagnosis_answer,
    compose_report_answer,
    execute_campaign,
    gen_campaign_plan,
    route_intent,
)
from app.graph.state import GraphState


_graph = None


def _intent_router(state: GraphState) -> str:
    return state.get("intent", "report")


def get_graph():
    global _graph
    if _graph is not None:
        return _graph

    workflow = StateGraph(GraphState)
    workflow.add_node("route_intent", route_intent)
    workflow.add_node("compose_report_answer", compose_report_answer)
    workflow.add_node("compose_diagnosis_answer", compose_diagnosis_answer)
    workflow.add_node("gen_campaign_plan", gen_campaign_plan)
    workflow.add_node("execute_campaign", execute_campaign)

    workflow.add_edge(START, "route_intent")
    workflow.add_conditional_edges(
        "route_intent",
        _intent_router,
        {
            "report": "compose_report_answer",
            "diagnose": "compose_diagnosis_answer",
            "plan": "gen_campaign_plan",
            "execute": "execute_campaign",
        },
    )
    workflow.add_edge("compose_report_answer", END)
    workflow.add_edge("compose_diagnosis_answer", END)
    workflow.add_edge("gen_campaign_plan", END)
    workflow.add_edge("execute_campaign", END)

    _graph = workflow.compile()
    return _graph


async def ainvoke(
    query: str,
    plan: dict | None = None,
    stream_cb: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    graph = get_graph()
    initial_state: GraphState = {
        "user_query": query,
        "plan": plan,
        "stream_cb": stream_cb,
        "debug": {},
    }
    return await graph.ainvoke(initial_state)
