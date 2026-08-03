"""本地 shell 传输（开发/验证用）。"""
import asyncio
import os
import signal
import time
from typing import Optional

from .base import ExecResult, InteractiveChannel, Transport, _local_shell


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
                # -il = 登录 + 交互：与 macOS「终端」一致，先 source ~/.zprofile 再 ~/.zshrc。
                # 只 -i 时 GUI 启动的后端 PATH 最小，~/.zshrc 里 pyenv 等初始化会因找不到
                # 命令而失败（如 python 丢失）；-l 让 .zprofile 的 brew shellenv 先补 PATH。
                os.execvpe(self._shell, [self._shell, "-il"], env)
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
        return LocalInteractiveChannel(_local_shell())
