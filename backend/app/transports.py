"""传输层抽象：SSH（asyncssh）与 本地 shell（开发/验证）。

核心设计：会话对上层（终端流、AI 执行面、SFTP）只暴露统一接口。
- exec:          非交互式执行，直接返回结果（AI 独立路径）
- create_interactive: 交互式 pty shell（人机共享终端）
- 对 SSH 而言 exec / interactive / SFTP 复用同一个连接（连接复用）。
"""
import asyncio
import os
import signal
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import asyncssh

from . import config


@dataclass
class ExecResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    duration_ms: int = 0
    timed_out: bool = False


class InteractiveChannel(ABC):
    """交互式终端通道（pty）。"""

    @abstractmethod
    async def open(self, rows: int, cols: int) -> None: ...

    @abstractmethod
    async def write(self, data: str) -> None: ...

    @abstractmethod
    async def read(self, n: int) -> str: ...

    @abstractmethod
    async def resize(self, cols: int, rows: int) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...


class Transport(ABC):
    kind: str = ""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def exec(self, command: str, timeout: float = 30.0) -> ExecResult: ...

    @abstractmethod
    def create_interactive(self) -> InteractiveChannel: ...


# --------------------------------------------------------------------------- #
# SSH
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# 本地（开发 / 验证用）
# --------------------------------------------------------------------------- #
def _local_shell() -> str:
    return os.environ.get("SHELL", "/bin/bash")


class LocalInteractiveChannel(InteractiveChannel):
    """基于 pty.fork() 的本地交互终端。

    用事件循环驱动（loop.add_reader + 非阻塞 master）替代读线程：
    避免「读线程阻塞在 os.read，close 时无法唤醒、进程陷入不可中断等待」的经典陷阱。
    close 时先 remove_reader 再关 fd；waitpid 用有界轮询，绝不无限阻塞。
    """

    def __init__(self, shell: Optional[str] = None):
        self._shell = shell or _local_shell()
        self._master: Optional[int] = None
        self._pid: Optional[int] = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def open(self, rows: int, cols: int) -> None:
        import fcntl
        import pty
        import struct
        import termios

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        pid, master = pty.fork()
        if pid == 0:  # 子进程：获得 pty 控制终端，exec shell
            try:
                os.execvpe(self._shell, [self._shell, "-i"], env)
            except Exception:
                os._exit(127)
        self._pid, self._master = pid, master
        try:
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass
        os.set_blocking(master, False)
        self._loop = asyncio.get_running_loop()
        self._loop.add_reader(master, self._on_readable)

    def _on_readable(self) -> None:
        try:
            data = os.read(self._master, 4096)
        except (BlockingIOError, OSError, TypeError):
            return
        if not data:  # EOF
            self._unregister_reader()
            self._queue.put_nowait(None)
        else:
            self._queue.put_nowait(data)

    def _unregister_reader(self) -> None:
        if self._loop is not None and self._master is not None:
            try:
                self._loop.remove_reader(self._master)
            except (KeyError, ValueError, RuntimeError):
                pass

    async def read(self, n: int) -> str:
        chunk = await self._queue.get()
        if chunk is None:
            return ""
        return chunk.decode("utf-8", "replace")

    async def write(self, data: str) -> None:
        if self._master is not None:
            await asyncio.to_thread(os.write, self._master, data.encode("utf-8", "replace"))

    async def resize(self, cols: int, rows: int) -> None:
        if self._master is None:
            return
        import fcntl
        import struct
        import termios

        try:
            fcntl.ioctl(self._master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            if self._pid:
                os.kill(self._pid, signal.SIGWINCH)
        except OSError:
            pass

    async def close(self) -> None:
        import signal as _signal
        self._unregister_reader()
        if self._master is not None:
            try:
                os.close(self._master)
            except OSError:
                pass
            self._master = None
        pid, self._pid = self._pid, None
        if pid:
            try:
                os.kill(pid, _signal.SIGHUP)
            except ProcessLookupError:
                pass
            # 有界轮询等待子进程退出（避免 waitpid 无限阻塞）
            for _ in range(25):
                try:
                    wpid, _ = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    break
                if wpid == pid:
                    break
                await asyncio.sleep(0.1)
            else:
                try:
                    os.kill(pid, _signal.SIGKILL)
                    os.waitpid(pid, os.WNOHANG)
                except (ProcessLookupError, ChildProcessError):
                    pass


class LocalTransport(Transport):
    kind = "local"

    async def connect(self) -> None:
        pass  # 本地无需连接

    async def close(self) -> None:
        pass

    async def exec(self, command: str, timeout: float = 30.0) -> ExecResult:
        t0 = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_shell(
                command, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ExecResult(stderr=f"command timed out after {timeout:.0f}s",
                                  duration_ms=int((time.monotonic() - t0) * 1000),
                                  timed_out=True)
            return ExecResult(
                stdout=out.decode("utf-8", "replace"),
                stderr=err.decode("utf-8", "replace"),
                exit_code=proc.returncode,
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
        except OSError as exc:
            return ExecResult(stderr=str(exc),
                              duration_ms=int((time.monotonic() - t0) * 1000))

    def create_interactive(self) -> InteractiveChannel:
        return LocalInteractiveChannel("/bin/bash")


# --------------------------------------------------------------------------- #
# 构造
# --------------------------------------------------------------------------- #
def build_transport(session: dict) -> Transport:
    if session.get("transport") == "local":
        return LocalTransport()
    return SSHTransport(
        host=session.get("host", "localhost"),
        port=int(session.get("port", 22)),
        username=session.get("username", "root"),
        auth_type=session.get("auth_type", "password"),
        password=session.get("password"),
        key_path=session.get("key_path"),
    )
