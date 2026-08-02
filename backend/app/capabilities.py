"""AI 能力注册表：供 AI agent 自举发现后端能力并了解「怎么调 + 怎么编排」。

相比 OpenAPI，这里提供 AI 友好的说明：
  - 每个能力有 name/method/path/summary，body 参数 schema 从 Pydantic 模型推导；
  - chain 字段描述该能力的调用链（前置依赖 / 后续步骤）——这些不是 OpenAPI 能表达的；
  - overview().note 是完整的「工作流地图」。

AI 流程：
  1. GET /api/ai/capabilities           —— 能力概述 + 工作流地图（挑什么、怎么编排）
  2. GET /api/ai/capabilities/{name}    —— 具体参数与 chain（怎么调）
  3. 按 note 的链条编排调用对应 REST 接口
"""
from typing import Optional

from .models import (ExecRequest, FindRequest, GroupCreate, QuickCommandCreate,
                     QuickCommandUpdate, QuickGroupCreate, SessionCreate,
                     TerminalInput)


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
         example: Optional[str] = None, chain: Optional[str] = None) -> dict:
    """chain: 该能力的调用链/前置与后续，供 AI 编排多步操作（非 OpenAPI 信息）。"""
    return {"name": name, "method": method, "path": path, "summary": summary,
            "params": params or [], "returns": returns, "example": example,
            "chain": chain}


SESSION_PATH = {"name": "sid", "in": "path", "type": "string", "required": True,
                "description": "会话 ID（先用 list_sessions 获取）"}

CAPABILITIES: list[dict] = [
    # ---- 会话 ----
    _cap("list_sessions", "GET", "/api/sessions",
         "列出所有会话，可按名称/IP 同时过滤",
         [{"name": "q", "in": "query", "type": "string", "required": False, "default": "",
           "description": "名称/IP 过滤串，多个 token 需同时命中"}],
         "会话对象数组（不含密码）", 'GET /api/sessions?q=prod',
         chain="起点：几乎所有操作的 sid 都来自这里（或 create_session 新建）。"),
    _cap("create_session", "POST", "/api/sessions",
         "创建会话（SSH 或本地 shell）",
         [{"name": "body", "in": "body", "required": True, "schema": _body_schema(SessionCreate)}],
         "新建会话对象", '{"name":"prod-web","host":"192.168.8.101","username":"root","auth_type":"password","password":"..."}',
         chain="产出 sid，可直接 connect / exec / find / SFTP。"),
    _cap("get_session", "GET", "/api/sessions/{sid}",
         "查看单个会话详情（不含密码）", [SESSION_PATH], "会话对象"),
    _cap("update_session", "PATCH", "/api/sessions/{sid}",
         "部分更新会话（改名/改 host/移动到分组 group_id 等）",
         [SESSION_PATH, {"name": "body", "in": "body", "required": True, "schema": _body_schema(SessionCreate)}],
         "更新后的会话对象", '{"group_id":"<gid>","name":"新名字"}',
         chain="group_id 传 null 可把会话移出分组（显式置空有效）。"),
    _cap("delete_session", "DELETE", "/api/sessions/{sid}",
         "删除会话并断开其运行时连接", [SESSION_PATH], '{"ok":true}'),
    _cap("export_sessions", "GET", "/api/sessions/export",
         "导出全部会话（JSON 数组，含密码，用于备份/迁移）", [], "会话数组"),
    _cap("import_sessions", "POST", "/api/sessions/import",
         "批量导入会话（JSON 数组），已存在 id 跳过",
         [{"name": "body", "in": "body", "required": True,
           "description": '{"sessions":[{会话对象...}]}'}],
         '{"added":n,"skipped":n,"total":n}'),
    _cap("export_bundle", "POST", "/api/export",
         "按选择导出分组与会话（空选择=全部），返回 {groups, sessions}",
         [{"name": "body", "in": "body", "required": True,
           "description": '{"group_ids":[...],"session_ids":[...]}，空数组表示全部'}],
         '{"groups":[...],"sessions":[...]}'),
    _cap("import_bundle", "POST", "/api/import",
         "统一导入 {groups, sessions}；分组按名称去重复用，会话 group_id 自动映射",
         [{"name": "body", "in": "body", "required": True,
           "description": '{"groups":[...],"sessions":[...]}'}],
         '{"groups_added":n,"added":n,"skipped":n,"total":n}'),
    # ---- 连接控制 ----
    _cap("connect_session", "POST", "/api/sessions/{sid}/connect",
         "为会话创建一个新的独立终端连接，返回 conn_id（后续 write/buffer 需要它）",
         [SESSION_PATH], '{"ok":true,"conn_id":"...","state":"connected"}',
         chain="产出 conn_id，供 write_terminal / read_buffer / connection_disconnect 使用。"),
    _cap("disconnect_session", "POST", "/api/sessions/{sid}/disconnect",
         "断开该会话的全部连接", [SESSION_PATH], '{"ok":true,"state":"disconnected"}'),
    _cap("session_status", "GET", "/api/sessions/{sid}/status",
         "查询会话连接状态与活跃连接列表", [SESSION_PATH], '{"id":..,"connected":bool,"active_conns":[...]}',
         chain="先查再动：判断会话是否已连接、有几个后台连接。"),
    _cap("connection_disconnect", "POST", "/api/connections/{conn_id}/disconnect",
         "断开指定终端连接",
         [{"name": "conn_id", "in": "path", "type": "string", "required": True, "description": "连接 ID（connect_session 返回）"}],
         '{"ok":true,"state":"disconnected"}',
         chain="只断指定 conn_id（对应用户某个 tab）；要断全部用 disconnect_session。"),
    _cap("list_background_connections", "GET", "/api/connections/background",
         "列出全部后台保活连接（跨会话，含会话名/主机/conn_id）",
         [], "[{conn_id,sid,name,host,port,transport}]",
         chain="后台保活 = 关 tab 不断线。接管输出用 read_buffer 增量拉取；终止用 connection_disconnect。"),
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
         '{"ok":true,"written":n}', '{"data":"ls -la\\n"}',
         chain="前置 connect_session 拿 conn_id。人共用同一 pty——建议终端空闲时注入；输出用 read_buffer 增量拉取。"),
    _cap("exec_command", "POST", "/api/sessions/{sid}/exec",
         "独立路径：非交互式执行 shell 命令并直接返回结果（独立连接，无并发问题）。默认优先用这个",
         [SESSION_PATH, {"name": "body", "in": "body", "required": True, "schema": _body_schema(ExecRequest)}],
         "stdout/stderr/exit_code/duration_ms/timed_out", '{"command":"ls -la /etc","timeout":30}',
         chain="独立路径，无需 connect，不经共享终端（人不被打扰）。默认优先于 write_terminal。"),
    _cap("find_files", "POST", "/api/sessions/{sid}/find",
         "在指定路径下按名称模式递归搜索文件",
         [SESSION_PATH, {"name": "body", "in": "body", "required": True, "schema": _body_schema(FindRequest)}],
         '{"results":[...],"count":n}', '{"path":".","pattern":"*.log","max_depth":3,"ftype":"f"}',
         chain="独立路径。SFTP 递归搜索也用它（传 path 基准目录）。"),
    _cap("read_buffer", "GET", "/api/connections/{conn_id}/buffer",
         "增量读取指定终端连接的输出缓冲。since 传上次返回的 total，只取新增；gap=true 表示需全量同步",
         [{"name": "conn_id", "in": "path", "type": "string", "required": True, "description": "连接 ID"},
          {"name": "since", "in": "query", "type": "integer", "required": False, "default": 0,
           "description": "上次读取的 total 偏移"}],
         '{"since":n,"total":n,"gap":bool,"data":"..."}',
         chain="配合 write_terminal：每次把 since 设为上次返回的 total；gap=true 表示偏移已超出缓冲窗口（256KB），需从 0 重拉。"),
    _cap("connection_status", "GET", "/api/connections/{conn_id}/status",
         "查询连接状态：connected / idle / idle_ms。idle=true 表示终端已空闲（N 毫秒无输出），可确认提示符就绪",
         [{"name": "conn_id", "in": "path", "type": "string", "required": True, "description": "连接 ID"}],
         '{"conn_id":..,"connected":bool,"idle":bool,"idle_ms":n,"buffer_total":n}',
         chain="配合 write_terminal：写之前先查 idle=true（空闲）再注入，避免和正在运行的命令交错；写完用 read_buffer 增量取输出。"),
    # ---- SFTP ----
    _cap("sftp_list", "GET", "/api/sessions/{sid}/sftp/ls",
         "列出远端目录（SSH 复用连接；local 为本机文件系统）",
         [SESSION_PATH, {"name": "path", "in": "query", "type": "string", "required": False, "default": "."}],
         "[{name,path,size,mtime,is_dir}]",
         chain="先 list_sessions 拿 sid。浏览用这个，递归搜索用 find_files。"),
    _cap("sftp_upload", "POST", "/api/sessions/{sid}/sftp/upload",
         "上传文件到远端目录",
         [SESSION_PATH, {"name": "target_dir", "in": "form", "type": "string", "required": False, "default": "."},
          {"name": "target_name", "in": "form", "type": "string", "required": False, "default": "上传文件名"},
          {"name": "file", "in": "form", "type": "file", "required": True, "description": "multipart 文件"}],
         '{"ok":true,"path":"..","size":n}',
         chain="每次操作独立建连。SSH 每次建连接；local 映射本机文件系统。"),
    _cap("sftp_download", "GET", "/api/sessions/{sid}/sftp/download",
         "下载远端文件（返回文件流）",
         [SESSION_PATH, {"name": "path", "in": "query", "type": "string", "required": True}],
         "文件二进制流",
         chain="先 sftp_list 确认路径再下载。"),
    _cap("sftp_delete", "POST", "/api/sessions/{sid}/sftp/delete",
         "删除远端文件（目录仅限空目录；local 端目录则递归删除）",
         [SESSION_PATH, {"name": "body", "in": "body", "required": True,
                         "description": '{"path":"要删除的文件路径"}'}],
         '{"ok":true,"path":"..."}',
         chain="先 sftp_list 确认路径与 is_dir 再删。"),
    # ---- 快捷命令 ----
    _cap("quick_list_groups", "GET", "/api/quick/groups",
         "列出快捷命令分组", [], "分组对象数组",
         chain="快捷命令 = 预存命令串。执行时取出 command 字段用 exec_command（独立）或 write_terminal（协同）发送。"),
    _cap("quick_create_group", "POST", "/api/quick/groups",
         "创建快捷命令分组",
         [{"name": "body", "in": "body", "required": True, "schema": _body_schema(QuickGroupCreate)}],
         "新建分组对象", '{"name":"运维"}'),
    _cap("quick_rename_group", "PATCH", "/api/quick/groups/{gid}",
         "重命名快捷命令分组",
         [{"name": "gid", "in": "path", "type": "string", "required": True, "description": "分组 ID"},
          {"name": "body", "in": "body", "required": True, "description": '{"name":"新名字"}'}],
         "分组对象"),
    _cap("quick_delete_group", "DELETE", "/api/quick/groups/{gid}",
         "删除快捷命令分组（组内命令一并删除）",
         [{"name": "gid", "in": "path", "type": "string", "required": True, "description": "分组 ID"}],
         '{"ok":true}'),
    _cap("quick_list_commands", "GET", "/api/quick/commands",
         "列出全部快捷命令（含所属分组）", [], "[{id,group_id,name,command,...}]"),
    _cap("quick_create_command", "POST", "/api/quick/commands",
         "创建快捷命令",
         [{"name": "body", "in": "body", "required": True, "schema": _body_schema(QuickCommandCreate)}],
         "新命令对象", '{"group_id":"<gid>","name":"查看磁盘","command":"df -h"}'),
    _cap("quick_update_command", "PATCH", "/api/quick/commands/{cid}",
         "更新快捷命令（改名/改命令/移分组）",
         [{"name": "cid", "in": "path", "type": "string", "required": True, "description": "命令 ID"},
          {"name": "body", "in": "body", "required": True, "schema": _body_schema(QuickCommandUpdate)}],
         "更新后的命令对象",
         chain="group_id 传 null 可移到未分组（显式置空有效）。"),
    _cap("quick_delete_command", "DELETE", "/api/quick/commands/{cid}",
         "删除快捷命令",
         [{"name": "cid", "in": "path", "type": "string", "required": True, "description": "命令 ID"}],
         '{"ok":true}'),
    _cap("quick_export", "POST", "/api/quick/export",
         "按选择导出快捷命令分组与命令（空选择=全部）",
         [{"name": "body", "in": "body", "required": True,
           "description": '{"group_ids":[...],"command_ids":[...]}，空数组表示全部'}],
         '{"groups":[...],"commands":[...]}'),
    _cap("quick_import", "POST", "/api/quick/import",
         "统一导入快捷命令 {groups, commands}；分组按名称去重复用，命令 group_id 自动映射",
         [{"name": "body", "in": "body", "required": True,
           "description": '{"groups":[...],"commands":[...]}'}],
         '{"groups_added":n,"added":n,"skipped":n,"total":n}'),
]

_BY_NAME = {c["name"]: c for c in CAPABILITIES}


def overview() -> dict:
    return {
        "count": len(CAPABILITIES),
        "note": (
            "工作流地图（怎么编排多步操作）：\n"
            "1. 一切从 list_sessions 拿 sid 开始。\n"
            "2. 独立执行（默认优先，不打扰人）：list_sessions → exec_command / find_files。\n"
            "3. 协同注入（人要看到）：list_sessions → connect_session 拿 conn_id → write_terminal\n"
            "   → read_buffer 轮询增量 → 结束用 connection_disconnect。\n"
            "4. SFTP：list_sessions → sftp_list 浏览 → sftp_upload / sftp_download / sftp_delete；\n"
            "   递归搜索用 find_files。\n"
            "5. 后台连接：list_background_connections 看后台保活 → read_buffer 接管输出 / connection_disconnect 终止。\n"
            "6. 快捷命令：quick_* 管理预存命令串，执行时用 exec_command 或 write_terminal 发送。\n"
            "每个能力的详细参数与调用链用 GET /api/ai/capabilities/{name} 查。"
        ),
        "capabilities": [{"name": c["name"], "method": c["method"],
                          "path": c["path"], "summary": c["summary"]} for c in CAPABILITIES],
    }


def detail(name: str) -> Optional[dict]:
    return _BY_NAME.get(name)
