"""终端 WebSocket 流。

每个 ws 连接都会为会话配置创建**一个独立的终端连接**（自己的 pty/SSH 通道 + 缓冲）。
同一会话可同时存在多个独立连接（多 tab / 多 AI 连接互不影响）。

协议（JSON）：
  浏览器 -> 服务端: {"type":"input","data":str} | {"type":"resize","cols":n,"rows":n}
  服务端 -> 浏览器: {"type":"status","state","conn_id"?, "message"?} |
                    {"type":"buffer","data":str} |
                    {"type":"output","data":str}
"""
import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..deps import get_manager, get_store
from ..sessions import SessionManager
from ..store import SessionStore

router = APIRouter(tags=["terminal"])
ManagerDep = Annotated[SessionManager, Depends(get_manager)]
StoreDep = Annotated[SessionStore, Depends(get_store)]


@router.websocket("/ws/terminal/{sid}")
async def terminal_ws(ws: WebSocket, sid: str, manager: ManagerDep, store: StoreDep) -> None:
    await ws.accept()
    if not store.get(sid):
        await ws.send_json({"type": "status", "state": "error", "message": "session not found"})
        await ws.close(code=1011)
        return

    ts = manager.create(sid)  # 每次连接建一个独立终端实例
    if ts is None:
        await ws.send_json({"type": "status", "state": "error", "message": "session not found"})
        await ws.close(code=1011)
        return

    try:
        await ts.connect()
    except asyncio.CancelledError:
        await manager.remove(ts.id)
        raise
    except Exception as exc:
        await ws.send_json({"type": "status", "state": "error", "message": f"connect failed: {exc}"})
        await manager.remove(ts.id)
        await ws.close(code=1011)
        return

    await ts.attach(ws)  # 加入 readers + 发送当前缓冲尾
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
        ts.detach(ws)
        await manager.remove(ts.id)  # 连接结束即释放该独立实例
