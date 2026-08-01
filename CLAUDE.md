# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目状态

**核心闭环已实现并可运行**（会话管理、终端流、AI 双路径、SFTP、Electron 壳、冒烟测试）。仍处早期：AI 模型接入、快捷命令、WebSocket 协作回显等尚未实现（见「未实现」）。

## 开发进度快照（2026-08-01 手写记录，防上下文丢失）

**已完成并验证**：后端全链路（会话/分组 CRUD、过滤、导入导出、**独立连接模型**——每 tab 一个独立 pty/缓冲、终端 WS 流 + 增量 buffer、AI 双路径 write/exec/find、SFTP、**AI 能力发现接口**）、前端（**Warp 风深色主题 + xshell 布局 + 分组树 + 多标签终端 + 右键菜单**，双击会话=开新独立 tab，AI 面板已移除）、Electron 壳、pytest 9/9 绿 + 浏览器 E2E 全过。
**当前运行态**：后端跑在 **127.0.0.1:8747**（`backend/.venv/bin/python run.py` 后台启动，日志 `/tmp/sshmgr_server.log`）；数据已清理，仅 1 个「本地开发机」演示会话。
**未验证**：SSH 传输路径（asyncssh 已按 API 编码，但测试环境 `192.168.8.101` 无免密凭据，未真机实测）。
**下一步候选方向**（用户待定）：① 接入 AI 模型（能力发现接口 `/api/ai/capabilities*` 已就绪，把 LLM 接到 exec/write/buffer）② 快捷命令分组 + 增删查改 + 导入导出 ③ SSH 真机联调 ④ AI 后台 WebSocket 长连接回显浏览器的「一起干」模式 ⑤ SFTP 前端 UI。

**本次开发踩坑（重要经验，勿重蹈）**：
- **本地交互终端**：必须用 `pty.fork()` + `loop.add_reader` + 非阻塞 master（见 transports.py）。**绝不要**用读线程 + 阻塞 `os.read` —— 关 fd 无法唤醒读线程，进程陷入不可中断等待（SIGKILL 都杀不掉）。close 顺序：`remove_reader` → 关 fd → SIGHUP → 有界 WNOHANG 轮询 → SIGKILL 兜底。
- **asyncssh 2.24 API**：resize 是 `change_terminal_size(width, height)`（非旧版 `resize_term`）；`create_process` 的 `term_size=(cols, rows)`；SFTP 用 `scandir()`（非 `listdir_attr`），条目是 `SFTPName.filename/.attrs`。
- **同步路由不能 `asyncio.create_task`**（线程池里无事件循环 → "no running event loop"）：需要调 async 代码的路由必须 `async def` 并 await。
- **Python 类体陷阱**：类方法叫 `list` 会遮蔽内置 `list`，导致后续方法注解 `-> list[dict]` 报错 → 方法改名。
- **macOS `/tmp` 是符号链接**：`find /tmp` 默认不穿透（直接跑 shell 也一样），不是代码 bug，用 `/private/tmp` 或真实路径。
- **uvicorn reload_dirs 必须限定 `["app"]`**，否则写 `data/sessions.json` 会触发服务重启。
- **端口**：默认 8747，`SSHMANAGER_PORT` 环境变量覆盖；Electron 与后端读同一环境变量；前端 ws 用 `location.host` 自适应端口。
- **PATCH 无法置空字段**：`model_dump(exclude_none=True)` 会把显式 `null` 也丢掉 → 会话无法移出分组。用 `model_fields_set` 判断「未传」vs「显式置空」，显式 null 单独放行。
- **前端分组树结构**：折叠要生效，children 必须是与行头**兄弟**的 `div.group-children`（CSS 用 `>` 或兄弟选择器），别把 children 嵌进行头里否则点击行头会误触子项。
- **`document.querySelector` 会命中 `display:none` 元素**：E2E 判断可见性要用 `offsetParent === null` 而不是元素是否存在。
- **async 调用漏 `await` 是隐蔽 bug**：`ts.attach(ws)` 忘写 await 时，协程永不执行——readers 没注册、buffer 不发、回显不扇出，表现为"ws 收不到任何后续消息"。排查时用假 reader（FakeWS + `await ts.attach`）隔离验证扇出层。

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
