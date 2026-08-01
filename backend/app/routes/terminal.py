"""终端 WebSocket 流：浏览器（人）与共享终端之间的通道。

协议（JSON）：
  浏览器 -> 服务端: {"type":"input","data":str} | {"type":"resize","cols":n,"rows":n}
  服务端 -> 浏览器: {"type":"buffer","data":str(历史尾) } |
                    {"type":"output","data":str} |
                    {"type":"status","state":"connected"|"closed"|"error","message":str}
"""
import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..deps import get_manager
from ..sessions import SessionManager

router = APIRouter(tags=["terminal"])
ManagerDep = Annotated[SessionManager, Depends(get_manager)]


async def _attach_safe(manager: SessionManager, sid: str, ws: WebSocket) -> bool:
    """连接会话并给前端发状态。返回是否成功。"""
    ts = manager.get(sid)
    if ts is None:
        await ws.send_json({"type": "status", "state": "error", "message": "session not found"})
        return False
    try:
        await ts.attach(ws)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await ws.send_json({"type": "status", "state": "error",
                            "message": f"connect failed: {exc}"})
        return False
    await ws.send_json({"type": "status", "state": "connected"})
    return True


@router.websocket("/ws/terminal/{sid}")
async def terminal_ws(ws: WebSocket, sid: str, manager: ManagerDep) -> None:
    await ws.accept()
    ok = await _attach_safe(manager, sid, ws)
    if not ok:
        await ws.close(code=1011)
        return
    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            if mtype == "input":
                data = msg.get("data", "")
                if data:
                    await manager.get(sid).write(data)
            elif mtype == "resize":
                cols, rows = int(msg.get("cols", 0)), int(msg.get("rows", 0))
                if cols > 0 and rows > 0:
                    await manager.get(sid).resize(cols, rows)
            elif mtype == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except (ValidationError, KeyError, ValueError):
        pass  # 忽略畸形消息
    finally:
        ts = manager.get(sid)
        if ts:
            ts.detach(ws)
