"""SSH 传输（asyncssh）。"""
import asyncio
import os
import time
from typing import Optional

import asyncssh

from .base import ExecResult, InteractiveChannel, Transport


class SSHInteractiveChannel(InteractiveChannel):
    def __init__(self, conn: asyncssh.SSHClientConnection):
        self._conn = conn
        self._proc: Optional[asyncssh.SSHClientProcess] = None

    async def open(self, rows: int, cols: int) -> None:
        # asyncssh 的 term_size / change_terminal_size 均为 (width=cols, height=rows)
        self._proc = await self._conn.create_process(
            term_type="xterm-256color", term_size=(cols, rows)
        )

    async def write(self, data: str) -> None:
        if self._proc:
            self._proc.stdin.write(data)
            await self._proc.stdin.drain()

    async def read(self, n: int) -> str:
        if not self._proc:
            return ""
        data = await self._proc.stdout.read(n)
        return data if data else ""

    async def resize(self, cols: int, rows: int) -> None:
        if self._proc:
            self._proc.change_terminal_size(width=cols, height=rows)

    async def close(self) -> None:
        if self._proc and not self._proc.is_closing():
            self._proc.close()
            try:
                await self._proc.wait_closed()
            except (OSError, asyncssh.Error):
                pass


class SSHTransport(Transport):
    kind = "ssh"

    def __init__(self, host: str, port: int, username: str,
                 auth_type: str, password: Optional[str], key_path: Optional[str]):
        self.host, self.port, self.username = host, port, username
        self.auth_type = auth_type
        self.password = password
        self.key_path = key_path
        self.conn: Optional[asyncssh.SSHClientConnection] = None

    async def connect(self) -> None:
        kwargs: dict = dict(
            host=self.host, port=self.port, username=self.username,
            known_hosts=None,  # 与 xshell 一致：不校验主机密钥
        )
        if self.auth_type == "password":
            kwargs["password"] = self.password or ""
        else:
            key = os.path.expanduser(self.key_path or "~/.ssh/id_rsa")
            kwargs["client_keys"] = [key]
        self.conn = await asyncssh.connect(**kwargs)

    async def close(self) -> None:
        if self.conn and not self.conn.is_closed():
            self.conn.close()
            try:
                await self.conn.wait_closed()
            except (OSError, asyncssh.Error):
                pass
        self.conn = None

    async def exec(self, command: str, timeout: float = 30.0) -> ExecResult:
        if not self.conn:
            raise RuntimeError("ssh not connected")
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self.conn.run(command, check=False, term_type="xterm",
                              term_size=(24, 80)),
                timeout,
            )
            return ExecResult(
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.exit_status,
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
        except asyncio.TimeoutError:
            return ExecResult(stderr=f"command timed out after {timeout:.0f}s",
                              duration_ms=int((time.monotonic() - t0) * 1000),
                              timed_out=True)

    def create_interactive(self) -> InteractiveChannel:
        if not self.conn:
            raise RuntimeError("ssh not connected")
        return SSHInteractiveChannel(self.conn)
