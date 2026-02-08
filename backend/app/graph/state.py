from collections.abc import Awaitable, Callable
from typing import Literal, TypedDict


class GraphState(TypedDict, total=False):
    user_query: str
    intent: Literal["report", "diagnose", "plan", "execute"]
    sql: str | None
    rows: list[dict] | None
    sql_error: dict | None
    knowledge: list[dict] | None
    answer: str | None
    report: dict | None
    plan: dict | None
    execution: dict | None
    stream_cb: Callable[[str], Awaitable[None]] | None
    debug: dict
