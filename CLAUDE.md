# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目状态

**核心闭环已实现并可运行**（会话管理、终端流、AI 双路径、SFTP、Electron 壳、冒烟测试）。仍处早期：AI 模型接入、快捷命令、WebSocket 协作回显等尚未实现（见「未实现」）。

## 常用命令

```bash
# 后端（浏览器开发模式，端口默认 8747，可用 SSHMANAGER_PORT 覆盖）
cd backend && .venv/bin/python run.py            # http://127.0.0.1:8747

# 桌面壳（自动拉起 Python 后端）
cd frontend && npm start

# 测试（冒烟，聚焦 local 传输）
cd backend && .venv/bin/python -m pytest tests/ -v

# 依赖安装
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install
```

## 项目是什么

`sshManager` —— **人机协作的 xshell**：人和 AI 在同一个浏览器界面里协同操作 SSH 终端。人和 AI 各自有独立执行策略，共享同一个终端会话。

## 架构（已落地）

### pty 所有权在 Python 后端（关键决策）

- **Python 后端（FastAPI）拥有 pty**；前端（xterm.js）和 AI 都只是它的客户端。
- **AI 干涉走纯后端接口**（向共享 pty 写字节），不依赖前端 JS —— Electron 壳将来可剥掉变为纯浏览器形态。
- 前端由 FastAPI 直接静态托管（`frontend/`）。

```
人（浏览器/xterm）
   │  ① ws input → 后端
   ▼
Python 后端 ──▶ PTY ──▶ 远端 shell/SSH（local 传输则是本地 pty shell）
   │
   │  ② AI 干涉接口：POST /api/sessions/{id}/write（写同一 pty）
   │
   └──③ 输出统一由后端读取 → 扇出给 ws 订阅者 + 写入增量缓冲
```

### 传输层抽象（backend/app/transports.py）

- `Transport` 统一接口：`connect/close/exec/create_interactive`。
- `SSHTransport`（asyncssh）：exec 用 `conn.run`；交互用 `create_process(term_type, term_size=(cols, rows))`；resize 用 `change_terminal_size`（注意 asyncssh 2.24 API，不是旧版 `resize_term`）。
- `LocalTransport`（开发/验证）：exec 用子进程；交互用 **`pty.fork()` + `loop.add_reader` 非阻塞 master**（不要用读线程 + blocking `os.read` —— 会导致 close 时进程陷入不可中断等待）。close 时先 `remove_reader` 再关 fd，waitpid 用有界轮询。

### 运行时（backend/app/sessions.py）

- `TerminalSession`：输出环形缓冲（上限 256KB，`config.TERMINAL_BUF_LIMIT`）+ **增量读取**（`get_buffer(since)`，返回 `since/total/gap/data`；`gap=True` 表示调用方偏移已超出缓冲窗口）。这是「AI 增量获取、避免全量拉取撑爆上下文」的实现。
- **单一写锁**：所有来源（人 ws / AI write 接口）的输入串行进 pty，缓解并发交错。
- `SessionManager` 惰性建运行时；`remove()`/`delete` 路由必须是 async（避免 sync 线程里 `create_task` 报 "no running event loop"）。

### API 路由（backend/app/routes/）

| 文件 | 职责 |
|------|------|
| `sessions.py` | 会话 CRUD + IP/名称同时过滤 + JSON 导入导出 + connect/disconnect/status |
| `terminal.py` | `WS /ws/terminal/{id}` 终端流（input/resize → 服务端；buffer/output/status ← 服务端） |
| `ai.py` | **AI 双路径**：`POST /write`（协同，写共享终端）/ `POST /exec`（独立，非交互直接返回）/ `GET /buffer`（增量）/ `POST /find`（递归搜索，`shlex.quote` 防注入） |
| `sftp.py` | SFTP ls/upload/download；SSH 复用会话连接，local 映射本机文件系统 |

## AI 设计

- **协同路径**（`/write`）：AI 注入共享终端，输出进缓冲并对所有订阅者回显。有并发问题，靠写锁 + 空闲注入缓解。
- **独立路径**（`/exec`、`/find`）：非交互执行直接返回，不经过共享终端，无并发问题，**默认优先**。
- 待实现：AI 模型接入（把意图/输出理解接到这些接口上）；三种后台操作形态（非交互 / 交互 / WebSocket 长连接回显浏览器实现「一起干」）。

## 前端（frontend/）

- 原生 JS（Electron 友好），xterm.js + addon-fit **本地化在 `vendor/`**（离线可用）。
- 左侧会话列表（过滤 / 新建 / 删除 / 导入导出），主区终端 + AI 执行面板（写入终端 / 独立执行 / 递归搜索三种模式）。
- `window.__term` 为 E2E 调试钩子。

## 未实现（规划中）

- 快捷命令分组 + 增删查改 + 组间移动；快捷命令导入导出（JSON + 剪贴板）
- AI 模型接入与 agent 循环（把 LLM 接到 exec/write/buffer 接口上）
- AI 后台 WebSocket 长连接 + 回显浏览器的「一起干」协作模式
- SSH 真机验证（测试环境无凭据，SSH 路径已编码未实测）

## 已知事项

- 密码明文存于 `data/sessions.json`（gitignored；与 xshell 同类工具一致），生产化应加密。
- `known_hosts=None`：不校验主机密钥（与 xshell 一致）。
- 本地测试主机 `ssh root@192.168.8.101`（私有本地 IP，无免密凭据）。
