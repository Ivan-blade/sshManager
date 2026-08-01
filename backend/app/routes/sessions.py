"""会话配置 CRUD / 过滤 / 导入导出 / 运行时连接控制。"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..deps import get_manager, get_store
from ..models import SessionCreate, SessionUpdate
from ..sessions import SessionManager
from ..store import SessionStore

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

StoreDep = Annotated[SessionStore, Depends(get_store)]
ManagerDep = Annotated[SessionManager, Depends(get_manager)]


class ImportRequest(BaseModel):
    sessions: list[dict]


def _public(s: dict) -> dict:
    """列表/单条响应不返回密码。"""
    return {k: v for k, v in s.items() if k != "password"}


@router.get("")
def list_sessions(store: StoreDep, q: str = Query("", description="按名称/IP 同时过滤")) -> list[dict]:
    return [_public(s) for s in store.list_all(q)]


@router.get("/export")
def export_sessions(store: StoreDep) -> list[dict]:
    return store.export()


@router.post("/import")
def import_sessions(body: ImportRequest, store: StoreDep) -> dict:
    return store.import_items(body.sessions)


@router.post("")
def create_session(body: SessionCreate, store: StoreDep) -> dict:
    return store.create(body.model_dump())


@router.get("/{sid}")
def get_session(sid: str, store: StoreDep) -> dict:
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "session not found")
    return _public(s)


@router.patch("/{sid}")
def update_session(sid: str, body: SessionUpdate, store: StoreDep) -> dict:
    patch = body.model_dump(exclude_none=True)
    # 显式传 null 的 group_id 表示移出分组（区别于「未传该字段」）
    if "group_id" in body.model_fields_set:
        patch["group_id"] = body.group_id
    s = store.update(sid, patch)
    if not s:
        raise HTTPException(404, "session not found")
    return _public(s)


@router.delete("/{sid}")
async def delete_session(sid: str, store: StoreDep, manager: ManagerDep) -> dict:
    if not store.get(sid):
        raise HTTPException(404, "session not found")
    await manager.disconnect_sid(sid)  # 断开该会话的全部连接
    store.delete(sid)
    return {"ok": True}


# ---- 运行时连接控制 ----
@router.post("/{sid}/connect")
async def connect_session(sid: str, store: StoreDep, manager: ManagerDep) -> dict:
    """创建一个新的独立连接，返回 conn_id（AI 协作路径先拿 conn_id 再 write/buffer）。"""
    if not store.get(sid):
        raise HTTPException(404, "session not found")
    ts = manager.create(sid)
    try:
        await ts.connect()
    except Exception as exc:
        await manager.remove(ts.id)
        raise HTTPException(502, f"connect failed: {exc}")
    return {"ok": True, "conn_id": ts.id, "state": "connected"}


@router.post("/{sid}/disconnect")
async def disconnect_session(sid: str, manager: ManagerDep) -> dict:
    """断开该会话的全部连接。"""
    await manager.disconnect_sid(sid)
    return {"ok": True, "state": "disconnected"}


@router.get("/{sid}/status")
async def session_status(sid: str, store: StoreDep, manager: ManagerDep) -> dict:
    if not store.get(sid):
        raise HTTPException(404, "session not found")
    return {
        "id": sid,
        "connected": manager.is_connected(sid),
        "active_conns": manager.active_conns(sid),
    }
