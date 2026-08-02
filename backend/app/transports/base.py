"""传输层抽象基础：统一接口与公共类型。

会话对上层（终端流、AI 执行面、SFTP）只暴露统一接口：
- exec:              非交互式执行，直接返回结果（AI 独立路径）
- create_interactive: 交互式 pty shell（人机共享终端）
"""
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


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


def _local_shell() -> str:
    """本地终端用用户登录 shell（与 macOS「终端」一致）。

    优先取 passwd 数据库的登录 shell（zsh 等），不信任 $SHELL 环境变量——
    GUI 启动的后端可能未设置 $SHELL 或指向旧 bash。兜底 macOS→zsh、其他→bash。
    """
    try:
        import pwd
        shell = pwd.getpwuid(os.getuid()).pw_shell
        if shell:
            return shell
    except Exception:
        pass
    shell = os.environ.get("SHELL")
    if shell:
        return shell
    import sys
    return "/bin/zsh" if sys.platform == "darwin" else "/bin/bash"
