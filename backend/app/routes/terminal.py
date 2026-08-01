"""终端 WebSocket 流。

- `/ws/terminal/{sid}`      新建一个独立连接（每个 tab / 每次打开）
- `/ws/connection/{conn_id}` 恢复到已有连接（前台恢复后台保活的 SSH）

**关闭语义**：ws 关闭只 detach，不自动断开——连接保持后台保活。
真正断开走 `POST /api/connections/{conn_id}/disconnect`（前端「断开并关闭」）。
关闭程序时由后端 lifespan shutdown 终止所有连接。

协议（JSON）：
  浏览器 -> 服务端: {"type":"input","data":str} | {"type":"resize","cols":n,"rows":n}
  服务端 -> 浏览器: {"type":"status","state","conn_id"?,"message"?} |
                    {"type":"buffer","data":str} | {"type":"output","data":str}
"""
import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..deps import get_manager, get_store
from ..sessions import SessionManager, TerminalSession
from ..store import SessionStore

router = APIRouter(tags=["terminal"])
ManagerDep = Annotated[SessionManager, Depends(get_manager)]
StoreDep = Annotated[SessionStore, Depends(get_store)]


async def _send_error(ws: WebSocket, message: str) -> None:
    await ws.send_json({"type": "status", "state": "error", "message": message})
    await ws.close(code=1011)


async def _attach_and_loop(ws: WebSocket, ts: TerminalSession) -> None:
    """把 ws 挂到连接上，跑消息循环；关闭时仅 detach（连接后台保活）。"""
    await ts.attach(ws)  # 加入 readers + 发送缓冲尾（历史）
    await ws.send_json({"type": "status", "state": "connected", "conn_id": ts.id})
    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            if mtype == "input":
                data = msg.get("data", "")
                if data:
                    await ts.write(data)
            elif mtype == "resize":
                cols, rows = int(msg.get("cols", 0)), int(msg.get("rows", 0))
                if cols > 0 and rows > 0:
                    await ts.resize(cols, rows)
            elif mtype == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except (ValidationError, KeyError, ValueError):
        pass  # 忽略畸形消息
    finally:
        ts.detach(ws)  # 仅关闭页面：连接保活，不自动断开


@router.websocket("/ws/terminal/{sid}")
async def terminal_ws(ws: WebSocket, sid: str, manager: ManagerDep, store: StoreDep) -> None:
    """新建一个独立连接。"""
    await ws.accept()
    if not store.get(sid):
        await _send_error(ws, "session not found")
        return
    ts = manager.create(sid)
    if ts is None:
        await _send_error(ws, "session not found")
        return
    try:
        await ts.connect()
    except asyncio.CancelledError:
        await manager.remove(ts.id)
        raise
    except Exception as exc:
        await manager.remove(ts.id)
        await _send_error(ws, f"connect failed: {exc}")
        return
    await _attach_and_loop(ws, ts)


@router.websocket("/ws/connection/{conn_id}")
async def connection_ws(ws: WebSocket, conn_id: str, manager: ManagerDep) -> None:
    """恢复到已有连接（后台保活的 SSH 拉回前台）。"""
    await ws.accept()
    ts = manager.get(conn_id)
    if not ts or not ts.connected:
        await _send_error(ws, "connection not found or closed")
        return
    await _attach_and_loop(ws, ts)
