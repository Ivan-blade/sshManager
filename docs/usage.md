# 使用指南（人类 + AI）

sshManager 支持两种使用者：**人**（浏览器/Electron 界面操作）和 **AI**（纯后端接口调用，不碰界面）。两者可以同时工作、共享同一个会话。

---

## 一、启动

```bash
# 桌面壳（推荐）
cd frontend && npm start

# 浏览器开发模式
cd backend && .venv/bin/python run.py     # → http://127.0.0.1:8747
```

> 端口默认 8747，可用 `SSHMANAGER_PORT=XXXX` 覆盖。前端 ws 自适应端口。

---

## 二、人类使用（Human Guide）

### 会话
- 左侧面板：`+ Session` 新建、`+ Group` 新建分组、搜索框按**名称/IP 同时过滤**
- **单击**选中，**双击**打开终端（同一 IP 可开多个独立 tab）
- hover 会话：`✎` 编辑、`✕` 删除；**右键**：Open / New connection / Move to group… / Rename / Delete
- 分组：右键 Rename / Delete

### 终端
- 多标签，每个 tab 一个**独立 SSH 连接**
- tab 上两个按钮：`✕` 仅关页面（SSH 后台保活）/ `⏻` 断开 SSH 并关闭
- 双击会话：有后台连接则恢复，否则新建

### 快捷命令
- 底部栏：`Default Group ▾` 下拉选分组（含新建/重命名分组）；命令按钮**点一下**发到终端
- **无换行** → 只回显（可编辑后回车执行）；**命令末尾带换行** → 点击直接执行
- 右键命令：Edit / Move to group（二级子菜单）/ Delete；`+` 新建命令
- 顶栏 `Q-Export` / `Q-Import`：快捷命令导入导出（分组+命令可选）

### SFTP
- tab 栏 `📁`：打开/收起 SFTP 面板（跟随当前活动 tab 的会话）
- **双击文件**下载（原生保存框）；**右键文件**：Download / Edit / Delete
- **拖拽文件**到面板 = 上传当前目录
- 搜索框：**递归搜索**（文件+目录），单击结果跳到对应目录
- 文件「Edit」：弹窗改内容 → Save 上传回去

### 导入导出
- 顶栏 `Import` / `Export`：会话+分组，可勾选，输出到剪贴板或文件
- 弹窗右上角 `✕` 或点击非弹框区域可关闭

### 后台连接
- 顶栏 `◔ Background`：列出**所有后台保活 SSH**（跨会话），**整行点击恢复**、右键管理
- 会话列表状态胶囊：`Running`（绿）/ `Background ×N`（黄）/ `Offline`（灰）

---

## 三、AI 使用（AI Guide）

AI **不操作界面**，纯走后端接口。核心是**能力自举发现**：

```
1. GET /api/ai/capabilities             → 后端能做什么（概述）
2. GET /api/ai/capabilities/{name}      → 具体接口怎么调（参数）
3. 调用对应 REST 接口
```

### 关键概念

| 概念 | 含义 | 怎么拿 |
|------|------|--------|
| **sid**（会话） | 一份连接配置（主机/凭据） | `list_sessions` |
| **conn_id**（连接） | 一次真实 SSH 连接（独立 pty+缓冲） | `connect_session` |
| **协作路径** | 往 conn_id 写入命令，人能看到 | `write_terminal` + `read_buffer` |
| **独立路径** | 非交互执行，直接返回，**默认优先** | `exec_command` / `find_files` |

### 推荐 AI 工作流

1. **找会话**：`list_sessions`（可按名称/IP 过滤）
2. **独立干活**（默认优先，无并发）：`exec_command` 跑命令、`find_files` 搜索
3. **需要人协作/被观察**：`connect_session` 拿 conn_id → `write_terminal` 注入命令 → `read_buffer?since=` 增量读结果
4. **收尾**：`disconnect_session` / `connection_disconnect`

### 增量 buffer 协议

- `read_buffer?since=N`：每次把返回的 `total` 当 `since` 传回，**只拿新增内容**（省上下文）
- `gap=true`：偏移已过期（超过 256KB 窗口），需全量重置
- 协作时 AI 与人在同一界面，人全程能看到 AI 注入的命令

### 示例（Python）

```python
import json, urllib.request

BASE = "http://127.0.0.1:8747"
def api(p, m="GET", b=None):
    req = urllib.request.Request(BASE + p, method=m,
        data=json.dumps(b).encode() if b else None,
        headers={"Content-Type": "application/json"} if b else {})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

# 1. 发现能力
print([c["name"] for c in api("/api/ai/capabilities")["capabilities"]])

# 2. 找到目标会话
sid = api("/api/sessions?q=prod")[0]["id"]

# 3. 独立路径：直接执行（默认优先）
r = api(f"/api/sessions/{sid}/exec", "POST",
        {"command": "uptime && free -h | head -2", "timeout": 20})
print(r["stdout"])

# 4. 递归搜索
r = api(f"/api/sessions/{sid}/find", "POST",
        {"path": "/var/log", "pattern": "*.log", "ftype": "f"})
print(r["count"], "files")

# 5. 协作路径：开连接 → 注入命令 → 增量读
conn = api(f"/api/sessions/{sid}/connect", "POST")["conn_id"]
api(f"/api/connections/{conn}/write", "POST", {"data": "echo hello-from-AI\n"})
buf = api(f"/api/connections/{conn}/buffer?since=0")
print(buf["data"][-100:])
api(f"/api/connections/{conn}/disconnect", "POST")
```

---

## 快速对照

| 你想做 | 人 | AI |
|--------|-----|-----|
| 连一台服务器 | 双击会话 | `exec_command`（非交互）或 `connect_session`（交互） |
| 跑命令 | 终端里敲 | `exec_command` |
| 找文件 | SFTP 搜索框 | `find_files` |
| 传文件 | 拖进 SFTP | `sftp_upload` |
| 改文件 | SFTP 右键 Edit | `sftp_download` + `sftp_upload` |
| 让 AI 操作、人看着 | 打开终端看着 | `write_terminal` + `read_buffer` |
