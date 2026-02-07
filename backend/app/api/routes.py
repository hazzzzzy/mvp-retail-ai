import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import get_settings
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
