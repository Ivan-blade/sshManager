"""AI 能力注册表：供 AI agent 自举发现后端能力并了解调用参数。

相比 OpenAPI，这里提供 AI 友好的说明：每个能力有 name/method/path/summary，
body 参数 schema 从 Pydantic 模型推导。AI 流程：
  1. GET /api/ai/capabilities           —— 能力概述（挑用什么）
  2. GET /api/ai/capabilities/{name}    —— 具体参数（怎么调）
  3. 调用对应 REST 接口
"""
from typing import Optional

from .models import ExecRequest, FindRequest, GroupCreate, SessionCreate, TerminalInput


def _body_schema(model) -> dict:
    """从 Pydantic 模型取精简 body schema（properties + required）。"""
    s = model.model_json_schema()
    return {
        "type": "object",
        "properties": s.get("properties", {}),
        "required": s.get("required", []),
    }


def _cap(name: str, method: str, path: str, summary: str,
         params: Optional[list] = None, returns: str = "",
         example: Optional[str] = None) -> dict:
    return {"name": name, "method": method, "path": path, "summary": summary,
            "params": params or [], "returns": returns, "example": example}


SESSION_PATH = {"name": "sid", "in": "path", "type": "string", "required": True,
                "description": "会话 ID（先用 list_sessions 获取）"}

CAPABILITIES: list[dict] = [
    # ---- 会话 ----
    _cap("list_sessions", "GET", "/api/sessions",
         "列出所有会话，可按名称/IP 同时过滤",
         [{"name": "q", "in": "query", "type": "string", "required": False, "default": "",
           "description": "名称/IP 过滤串，多个 token 需同时命中"}],
         "会话对象数组（不含密码）", 'GET /api/sessions?q=prod'),
    _cap("create_session", "POST", "/api/sessions",
         "创建会话（SSH 或本地 shell）",
         [{"name": "body", "in": "body", "required": True, "schema": _body_schema(SessionCreate)}],
         "新建会话对象", '{"name":"prod-web","host":"192.168.8.101","username":"root","auth_type":"password","password":"..."}'),
    _cap("get_session", "GET", "/api/sessions/{sid}",
         "查看单个会话详情（不含密码）", [SESSION_PATH], "会话对象"),
    _cap("update_session", "PATCH", "/api/sessions/{sid}",
         "部分更新会话（改名/改 host/移动到分组 group_id 等）",
         [SESSION_PATH, {"name": "body", "in": "body", "required": True, "schema": _body_schema(SessionCreate)}],
         "更新后的会话对象", '{"group_id":"<gid>","name":"新名字"}'),
    _cap("delete_session", "DELETE", "/api/sessions/{sid}",
         "删除会话并断开其运行时连接", [SESSION_PATH], '{"ok":true}'),
    _cap("export_sessions", "GET", "/api/sessions/export",
         "导出全部会话（JSON 数组，含密码，用于备份/迁移）", [], "会话数组"),
    _cap("import_sessions", "POST", "/api/sessions/import",
         "批量导入会话（JSON 数组），已存在 id 跳过",
         [{"name": "body", "in": "body", "required": True,
           "description": '{"sessions":[{会话对象...}]}'}],
         '{"added":n,"skipped":n,"total":n}'),
    # ---- 连接控制 ----
    _cap("connect_session", "POST", "/api/sessions/{sid}/connect",
         "为会话创建一个新的独立终端连接，返回 conn_id（后续 write/buffer 需要它）",
         [SESSION_PATH], '{"ok":true,"conn_id":"...","state":"connected"}'),
    _cap("disconnect_session", "POST", "/api/sessions/{sid}/disconnect",
         "断开该会话的全部连接", [SESSION_PATH], '{"ok":true,"state":"disconnected"}'),
    _cap("session_status", "GET", "/api/sessions/{sid}/status",
         "查询会话连接状态与活跃连接列表", [SESSION_PATH], '{"id":..,"connected":bool,"active_conns":[...]}'),
    _cap("connection_disconnect", "POST", "/api/connections/{conn_id}/disconnect",
         "断开指定终端连接",
         [{"name": "conn_id", "in": "path", "type": "string", "required": True, "description": "连接 ID（connect_session 返回）"}],
         '{"ok":true,"state":"disconnected"}'),
    # ---- 分组 ----
    _cap("list_groups", "GET", "/api/groups",
         "列出所有会话分组", [], "分组对象数组"),
    _cap("create_group", "POST", "/api/groups",
         "创建会话分组",
         [{"name": "body", "in": "body", "required": True, "schema": _body_schema(GroupCreate)}],
         "新建分组对象", '{"name":"生产环境"}'),
    _cap("rename_group", "PATCH", "/api/groups/{gid}",
         "重命名分组",
         [{"name": "gid", "in": "path", "type": "string", "required": True, "description": "分组 ID"},
          {"name": "body", "in": "body", "required": True, "description": '{"name":"新名字"}'}],
         "分组对象"),
    _cap("delete_group", "DELETE", "/api/groups/{gid}",
         "删除分组（组内会话回到根层级）",
         [{"name": "gid", "in": "path", "type": "string", "required": True, "description": "分组 ID"}],
         '{"ok":true}'),
    # ---- AI 执行面 ----
    _cap("write_terminal", "POST", "/api/connections/{conn_id}/write",
         "协同路径：向指定终端连接写入数据（人会看到，输出进该连接缓冲）。先用 connect_session 拿 conn_id",
         [{"name": "conn_id", "in": "path", "type": "string", "required": True, "description": "连接 ID"},
          {"name": "body", "in": "body", "required": True, "schema": _body_schema(TerminalInput)}],
         '{"ok":true,"written":n}', '{"data":"ls -la\\n"}'),
    _cap("exec_command", "POST", "/api/sessions/{sid}/exec",
         "独立路径：非交互式执行 shell 命令并直接返回结果（独立连接，无并发问题）。默认优先用这个",
         [SESSION_PATH, {"name": "body", "in": "body", "required": True, "schema": _body_schema(ExecRequest)}],
         "stdout/stderr/exit_code/duration_ms/timed_out", '{"command":"ls -la /etc","timeout":30}'),
    _cap("find_files", "POST", "/api/sessions/{sid}/find",
         "在指定路径下按名称模式递归搜索文件",
         [SESSION_PATH, {"name": "body", "in": "body", "required": True, "schema": _body_schema(FindRequest)}],
         '{"results":[...],"count":n}', '{"path":".","pattern":"*.log","max_depth":3,"ftype":"f"}'),
    _cap("read_buffer", "GET", "/api/connections/{conn_id}/buffer",
         "增量读取指定终端连接的输出缓冲。since 传上次返回的 total，只取新增；gap=true 表示需全量同步",
         [{"name": "conn_id", "in": "path", "type": "string", "required": True, "description": "连接 ID"},
          {"name": "since", "in": "query", "type": "integer", "required": False, "default": 0,
           "description": "上次读取的 total 偏移"}],
         '{"since":n,"total":n,"gap":bool,"data":"..."}'),
    # ---- SFTP ----
    _cap("sftp_list", "GET", "/api/sessions/{sid}/sftp/ls",
         "列出远端目录（SSH 复用连接；local 为本机文件系统）",
         [SESSION_PATH, {"name": "path", "in": "query", "type": "string", "required": False, "default": "."}],
         "[{name,path,size,mtime,is_dir}]"),
    _cap("sftp_upload", "POST", "/api/sessions/{sid}/sftp/upload",
         "上传文件到远端目录",
         [SESSION_PATH, {"name": "target_dir", "in": "form", "type": "string", "required": False, "default": "."},
          {"name": "target_name", "in": "form", "type": "string", "required": False, "default": "上传文件名"},
          {"name": "file", "in": "form", "type": "file", "required": True, "description": "multipart 文件"}],
         '{"ok":true,"path":"..","size":n}'),
    _cap("sftp_download", "GET", "/api/sessions/{sid}/sftp/download",
         "下载远端文件（返回文件流）",
         [SESSION_PATH, {"name": "path", "in": "query", "type": "string", "required": True}],
         "文件二进制流"),
]

_BY_NAME = {c["name"]: c for c in CAPABILITIES}


def overview() -> dict:
    return {
        "count": len(CAPABILITIES),
        "note": "先看概述挑能力，再用 GET /api/ai/capabilities/{name} 查参数。会话类接口需先用 list_sessions 拿 sid；write/buffer 这类连接级操作需先 connect_session 拿 conn_id。",
        "capabilities": [{"name": c["name"], "method": c["method"],
                          "path": c["path"], "summary": c["summary"]} for c in CAPABILITIES],
    }


def detail(name: str) -> Optional[dict]:
    return _BY_NAME.get(name)
