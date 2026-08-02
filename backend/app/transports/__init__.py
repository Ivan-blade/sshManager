"""传输层：统一入口（公共 API 与工厂）。

保持旧 `transports.py` 的外部接口不变：
- `build_transport(session)`  工厂（local → LocalTransport，否则 SSH）
- `Transport` / `ExecResult` / `InteractiveChannel`  公共类型
"""
from .base import ExecResult, InteractiveChannel, Transport
from .local import LocalTransport
from .ssh import SSHTransport


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


__all__ = ["Transport", "build_transport", "ExecResult", "InteractiveChannel"]
