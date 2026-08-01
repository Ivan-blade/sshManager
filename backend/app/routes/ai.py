"""AI 执行面 —— 对应「AI 双路径」设计：

- 协同路径: POST /write  注入共享终端（人能看到，输出进缓冲）
- 独立路径: POST /exec   非交互式执行，直接返回结果（不经过共享终端）
- 增量读取: GET  /buffer 基于服务端输出缓冲，?since= 增量获取终端内容
- 递归搜索: POST /find   后端执行 find 命令
"""
import shlex
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_manager, get_store
from ..models import ExecRequest, FindRequest, TerminalInput
from ..sessions import SessionManager
from ..store import SessionStore
from ..transports import build_transport

router = APIRouter(prefix="/api/sessions/{sid}", tags=["ai"])
StoreDep = Annotated[SessionStore, Depends(get_store)]
ManagerDep = Annotated[SessionManager, Depends(get_manager)]


def _require_session(store: SessionStore, sid: str):
    cfg = store.get(sid)
    if not cfg:
        raise HTTPException(404, "session not found")
    return cfg


@router.post("/write")
async def ai_write(sid: str, body: TerminalInput, store: StoreDep, manager: ManagerDep) -> dict:
    """协同路径：向共享终端写入数据（AI 干涉），输出会进入终端缓冲并回显给所有订阅者。"""
    _require_session(store, sid)
    ts = manager.get(sid)
    if not ts or not ts.connected:
        raise HTTPException(409, "session not connected")
    await ts.write(body.data)
    return {"ok": True, "written": len(body.data)}


@router.get("/buffer")
async def ai_buffer(sid: str, store: StoreDep, manager: ManagerDep,
                    since: int = Query(0, ge=0)) -> dict:
    """增量获取终端输出缓冲。since 为上次返回的 total；gap=true 表示 since 已超出缓冲窗口，需全量同步。"""
    _require_session(store, sid)
    ts = manager.get(sid)
    if ts is None:
        return {"since": since, "total": 0, "gap": True, "data": ""}
    return ts.get_buffer(since)


@router.post("/exec")
async def ai_exec(sid: str, body: ExecRequest, store: StoreDep) -> dict:
    """独立路径：非交互式执行 shell 命令，直接返回 stdout/stderr/exit_code。
    SSH 复用会话连接（多路复用通道），与共享终端互不干扰。"""
    cfg = _require_session(store, sid)
    transport = build_transport(cfg)
    try:
        await transport.connect()
    except Exception as exc:
        raise HTTPException(502, f"connect failed: {exc}")
    try:
        result = await transport.exec(body.command, timeout=body.timeout)
    finally:
        await transport.close()
    return {
        "stdout": result.stdout, "stderr": result.stderr,
        "exit_code": result.exit_code, "duration_ms": result.duration_ms,
        "timed_out": result.timed_out,
    }


@router.post("/find")
async def ai_find(sid: str, body: FindRequest, store: StoreDep) -> dict:
    """递归搜索：后端执行 find。参数经过 shlex 安全引用，path 为相对当前路径的基准目录。"""
    cfg = _require_session(store, sid)
    transport = build_transport(cfg)
    try:
        await transport.connect()
    except Exception as exc:
        raise HTTPException(502, f"connect failed: {exc}")
    try:
        parts = ["find", shlex.quote(body.path)]
        if body.max_depth is not None:
            parts += ["-maxdepth", str(body.max_depth)]
        parts += ["-name", shlex.quote(body.pattern)]
        if body.ftype != "all":
            parts += ["-type", body.ftype]
        result = await transport.exec(" ".join(parts), timeout=60)
    finally:
        await transport.close()
    lines = [ln for ln in (result.stdout or "").splitlines() if ln.strip()]
    return {
        "results": lines, "count": len(lines),
        "stderr": result.stderr, "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
    }
