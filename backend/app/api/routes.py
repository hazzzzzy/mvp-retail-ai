import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import get_settings
from app.db.engine import AsyncSessionLocal
from app.graph.graph import ainvoke

router = APIRouter(prefix="/api", tags=["api"])
settings = get_settings()


class ChatRequest(BaseModel):
    query: str


class ExecuteRequest(BaseModel):
    plan: dict[str, Any]


@router.get("/health")
async def health():
    return {"ok": True}


@router.post("/chat")
async def chat(payload: ChatRequest):
    try:
        result = await ainvoke(payload.query)
        return {
            "intent": result.get("intent"),
            "answer": result.get("answer"),
            "report": result.get("report"),
            "plan": result.get("plan"),
            "debug": {**(result.get("debug") or {}), "model": settings.deepseek_model},
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, request: Request):
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def _sse(data: dict[str, Any]) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    async def on_token(token: str) -> None:
        await queue.put({"type": "token", "content": token})

    async def _run_graph() -> dict[str, Any]:
        return await ainvoke(payload.query, stream_cb=on_token)

    task = asyncio.create_task(_run_graph())

    async def event_gen():
        yield _sse({"type": "start"})

        try:
            while True:
                if await request.is_disconnected():
                    task.cancel()
                    break

                if task.done() and queue.empty():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield _sse(event)
                except TimeoutError:
                    continue

            if task.cancelled():
                return

            result = await task
            done_payload = {
                "type": "done",
                "result": {
                    "intent": result.get("intent"),
                    "answer": result.get("answer"),
                    "report": result.get("report"),
                    "plan": result.get("plan"),
                    "debug": {**(result.get("debug") or {}), "model": settings.deepseek_model},
                },
            }
            yield _sse(done_payload)
        except Exception as exc:
            err = {"type": "error", "message": str(exc)}
            yield _sse(err)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/execute")
async def execute(payload: ExecuteRequest):
    try:
        result = await ainvoke("执行上架", plan=payload.plan)
        return {
            "intent": "execute",
            "execution": result.get("execution"),
            "debug": {**(result.get("debug") or {}), "model": settings.deepseek_model},
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/action-logs/summary")
async def action_logs_summary(limit: int = 20):
    n = max(1, min(limit, 100))
    try:
        async with AsyncSessionLocal() as session:
            total = await session.scalar(text("SELECT COUNT(*) FROM action_logs"))
            success_cnt = await session.scalar(text("SELECT COUNT(*) FROM action_logs WHERE status='success'"))
            failed_cnt = await session.scalar(text("SELECT COUNT(*) FROM action_logs WHERE status='failed'"))
            last_created_at = await session.scalar(text("SELECT MAX(created_at) FROM action_logs"))
            latest_rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, idempotency_key, action_type, status, request_json, error_message, created_at
                        FROM action_logs
                        ORDER BY id DESC
                        LIMIT :n
                        """
                    ),
                    {"n": n},
                )
            ).mappings().all()

        total_v = int(total or 0)
        success_v = int(success_cnt or 0)
        failed_v = int(failed_cnt or 0)
        success_rate = round((success_v / total_v) * 100, 2) if total_v > 0 else 0.0
        summary_text = (
            f"累计执行日志 {total_v} 条，其中成功 {success_v} 条，失败 {failed_v} 条，"
            f"成功率 {success_rate:.2f}%。"
        )
        if last_created_at is not None:
            summary_text += f"最近一次执行时间：{last_created_at}。"

        return {
            "summary": summary_text,
            "metrics": {
                "total": total_v,
                "success": success_v,
                "failed": failed_v,
                "success_rate": success_rate,
                "last_created_at": last_created_at,
            },
            "items": [dict(r) for r in latest_rows],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
