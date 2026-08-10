"""Dashboard API for the HH AI assistant Hedi."""

import asyncio
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.hh_client_factory import get_client
from app.instances import bot


router = APIRouter()
_chat_ids: dict[int, str] = {}
_chat_ids_lock = threading.Lock()


class HediMessage(BaseModel):
    text: str


def _account(idx: int) -> dict:
    acc = bot._get_apply_acc(idx)
    if not acc:
        raise HTTPException(status_code=404, detail="account not found")
    mode = str(acc.get("mode", "")).strip().lower()
    if mode != "mobile":
        raise HTTPException(status_code=400, detail="hedi requires mobile mode")
    return acc


def _mobile_client(idx: int):
    client = get_client(_account(idx))
    return client


async def _start(idx: int, client=None) -> str:
    client = client or _mobile_client(idx)
    # FallbackHHClient intentionally exposes only the shared HHClient ABC;
    # Hedi is mobile-only, so use its mobile half. Test/dedicated clients may
    # expose start_hedi directly.
    starter = getattr(client, "start_hedi", None)
    if starter is None:
        starter = client.mobile.start_hedi
    chat_id = await asyncio.to_thread(starter)
    with _chat_ids_lock:
        _chat_ids[idx] = chat_id
    return chat_id


async def _chat_id(idx: int, client) -> str:
    with _chat_ids_lock:
        chat_id = _chat_ids.get(idx)
    return chat_id or await _start(idx, client)


@router.get("/api/account/{idx}/hedi/start")
async def api_hedi_start(idx: int):
    chat_id = await _start(idx)
    return {"ok": True, "chat_id": chat_id}


@router.get("/api/account/{idx}/hedi/history")
async def api_hedi_history(idx: int, limit: int = 50):
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    client = _mobile_client(idx)
    chat_id = await _chat_id(idx, client)
    thread = await asyncio.to_thread(client.fetch_thread, chat_id)
    if not isinstance(thread, dict):
        thread = {"messages": []}
    if thread.get("error"):
        error = str(thread["error"])
        if "404" in error or "не найден" in error.lower():
            with _chat_ids_lock:
                _chat_ids.pop(idx, None)
            raise HTTPException(status_code=404, detail="hedi chat not found")
    messages = list(thread.get("messages") or [])[-limit:]
    return {"ok": True, "chat_id": chat_id, "messages": messages}


@router.post("/api/account/{idx}/hedi/send")
async def api_hedi_send(idx: int, payload: HediMessage):
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty")
    if len(text) > 4000:
        raise HTTPException(status_code=422, detail="text is too long")
    client = _mobile_client(idx)
    chat_id = await _chat_id(idx, client)
    result = await asyncio.to_thread(client.send_message, chat_id, text)
    if result == "chat_not_found":
        with _chat_ids_lock:
            _chat_ids.pop(idx, None)
        raise HTTPException(status_code=404, detail="hedi chat not found")
    if result is not True:
        raise HTTPException(status_code=502, detail="failed to send message")
    return {"ok": True, "chat_id": chat_id}
