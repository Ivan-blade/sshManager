"""Pydantic 请求/响应模型。"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    transport: Literal["ssh", "local"] = "ssh"
    host: str = "localhost"
    port: int = Field(22, ge=1, le=65535)
    username: str = "root"
    auth_type: Literal["password", "key"] = "password"
    password: Optional[str] = None
    key_path: Optional[str] = None
    description: Optional[str] = None
    group_id: Optional[str] = None


class SessionUpdate(BaseModel):
    """部分更新；None 字段表示不修改。"""
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    host: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = None
    auth_type: Optional[Literal["password", "key"]] = None
    password: Optional[str] = None
    key_path: Optional[str] = None
    description: Optional[str] = None
    group_id: Optional[str] = None


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)


class QuickGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class QuickGroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)


class QuickCommandCreate(BaseModel):
    group_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=64)
    command: str = Field(..., min_length=1, max_length=1024)


class QuickCommandUpdate(BaseModel):
    group_id: Optional[str] = None
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    command: Optional[str] = Field(None, min_length=1, max_length=1024)


class TerminalInput(BaseModel):
    """向共享终端写入的数据（AI 干涉 / 注入）。"""
    data: str


class ExecRequest(BaseModel):
    command: str
    timeout: float = Field(30, ge=1, le=600)


class FindRequest(BaseModel):
    path: str = "."
    pattern: str = "*"
    max_depth: Optional[int] = Field(None, ge=1, le=100)
    ftype: Literal["f", "d", "all"] = "f"


class ConnectRequest(BaseModel):
    """创建连接时的可选显示标签；不传则显示所属会话名（UUID 仍是唯一标识）。"""
    label: Optional[str] = Field(None, max_length=64)


class LabelRequest(BaseModel):
    """设置/清除连接的显示名；null 则回落到会话名。与界面 Rename Tab 共用 ts.label。"""
    label: Optional[str] = Field(None, max_length=64)
