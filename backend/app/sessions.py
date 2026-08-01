"""运行时会话管理器。

每个 TerminalSession 持有：
- transport + interactive channel（人机共享的 pty 终端）
- 输出缓冲（环形，上限见 config）与增量读取：AI 通过 ?since= 增量获取，避免全量拉取
- 写锁：所有来源（人 via ws / AI via write 接口）的输入串行进入终端，缓解并发交错
- 订阅者集合：WebSocket 连接，输出扇出给每个订阅者
"""
import asyncio
import time
import uuid
from typing import Optional

from fastapi import WebSocket

from . import config
from .store import SessionStore
from .transports import Transport, build_transport


class TerminalSession:
    """一个独立的终端连接（自己的 transport + 通道 + 缓冲）。

    一个会话配置（sid）可产生多个独立连接；每个 tab / 每个 AI 连接 = 一个 TerminalSession。
    """

    MAX_BUF = config.TERMINAL_BUF_LIMIT

    def __init__(self, conn_id: str, session_cfg: dict):
        self.id = conn_id          # 连接唯一 id
        self.sid = session_cfg.get("id", "")
        self.cfg = session_cfg
        self.transport: Optional[Transport] = None
        self._channel = None
        self.connected = False
        self.readers: set[WebSocket] = set()
        # 输出缓冲（文本片段列表）
        self._parts: list[str] = []
        self._chars = 0          # 当前缓冲总字符数
        self._total = 0          # 累计流字符数（用于增量 since 定位）
        self._start = 0          # 缓冲首片对应的流偏移
        self._write_lock = asyncio.Lock()
        self._read_task: Optional[asyncio.Task] = None

    # ---------------- 缓冲 / 增量获取 ----------------
    def append(self, text: str) -> None:
        if not text:
            return
        self._parts.append(text)
        self._chars += len(text)
        self._total += len(text)
        # 裁剪最旧内容，保持有界
        while self._chars > self.MAX_BUF and self._parts:
            head = self._parts[0]
            if len(head) <= self._chars - self.MAX_BUF:
                self._parts.pop(0)
                self._start += len(head)
                self._chars -= len(head)
            else:
                keep = self._chars - self.MAX_BUF
                self._parts[0] = head[keep:]
                self._start += keep
                self._chars -= keep

    def get_buffer(self, since: int) -> dict:
        """增量读取。since 为调用方上次看到的累计长度。
        若 since 落在缓冲窗口内，返回其后新增文本；否则返回全部并标记 gap。"""
        text = "".join(self._parts)
        end = self._start + len(text)
        if self._start <= since <= end:
            return {"since": since, "total": self._total, "gap": False,
                    "data": text[since - self._start:]}
        return {"since": since, "total": self._total, "gap": True, "data": text}

    # ---------------- 生命周期 ----------------
    async def connect(self) -> None:
        if self.connected:
            return
        self.transport = build_transport(self.cfg)
        await self.transport.connect()
        self._channel = self.transport.create_interactive()
        await self._channel.open(*config.DEFAULT_TERM_SIZE)
        self.connected = True
        self._read_task = asyncio.create_task(self._read_loop())

    async def disconnect(self) -> None:
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except (asyncio.CancelledError, Exception):
                pass
            self._read_task = None
        if self._channel:
            try:
                await self._channel.close()
            except Exception:
                pass
            self._channel = None
        if self.transport:
            try:
                await self.transport.close()
            except Exception:
                pass
            self.transport = None
        self.connected = False

    async def _read_loop(self) -> None:
        try:
            while self._channel:
                data = await self._channel.read(4096)
                if not data:
                    break
                self.append(data)
                await self._fanout({"type": "output", "data": data})
        except (asyncio.CancelledError, Exception):
            pass
        finally:
            self.connected = False
            await self._fanout({"type": "status", "state": "closed"})

    async def _fanout(self, payload: dict) -> None:
        for ws in list(self.readers):
            try:
                await ws.send_json(payload)
            except Exception:
                self.readers.discard(ws)

    # ---------------- 输入路径（统一写锁） ----------------
    async def write(self, data: str) -> None:
        if not self.connected or not self._channel:
            raise RuntimeError("session not connected")
        async with self._write_lock:
            await self._channel.write(data)

    async def resize(self, cols: int, rows: int) -> None:
        if self._channel:
            await self._channel.resize(cols, rows)

    # ---------------- WebSocket 订阅 ----------------
    async def attach(self, ws: WebSocket) -> None:
        self.readers.add(ws)
        if not self.connected:
            await self.connect()  # 连接失败会向上抛
        buf = self.get_buffer(0)
        await ws.send_json({"type": "buffer", "data": buf["data"]})

    def detach(self, ws: WebSocket) -> None:
        self.readers.discard(ws)


class SessionManager:
    """运行时连接池：按 conn_id 管理。一个会话配置可产生多个独立连接。"""

    def __init__(self, store: SessionStore):
        self.store = store
        self._sessions: dict[str, TerminalSession] = {}  # conn_id -> TerminalSession

    def create(self, sid: str) -> Optional[TerminalSession]:
        """为会话配置创建一个新的独立连接。"""
        cfg = self.store.get(sid)
        if not cfg:
            return None
        conn_id = uuid.uuid4().hex
        ts = TerminalSession(conn_id, cfg)
        self._sessions[conn_id] = ts
        return ts

    def get(self, conn_id: str) -> Optional[TerminalSession]:
        return self._sessions.get(conn_id)

    async def remove(self, conn_id: str) -> None:
        ts = self._sessions.pop(conn_id, None)
        if ts:
            await ts.disconnect()

    def is_connected(self, sid: str) -> bool:
        return any(ts.connected for ts in self._sessions.values() if ts.sid == sid)

    def active_conns(self, sid: str) -> list[str]:
        """全部存活连接（含挂在页面上的 + 后台保活的）。"""
        return [ts.id for ts in self._sessions.values() if ts.sid == sid and ts.connected]

    def background_conns(self, sid: str) -> list[str]:
        """后台保活连接：SSH 存活但没有页面/ws 挂着。"""
        return [ts.id for ts in self._sessions.values()
                if ts.sid == sid and ts.connected and not ts.readers]

    def background_all(self) -> list[TerminalSession]:
        """全部会话的后台保活连接（跨会话）。"""
        return [ts for ts in self._sessions.values() if ts.connected and not ts.readers]

    async def disconnect_sid(self, sid: str) -> None:
        for ts in list(self._sessions.values()):
            if ts.sid == sid:
                await self.remove(ts.id)

    async def shutdown(self) -> None:
        for ts in list(self._sessions.values()):
            await ts.disconnect()
        self._sessions.clear()
