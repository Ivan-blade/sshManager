<div align="center">

# sshManager

**人机协作的 SSH 客户端 —— 人和 AI 在同一个共享终端里一起干活**

[English](README.md) · [简体中文](README.zh-CN.md)

</div>

**人机协同的 SSH 会话管理工具**：人和 AI 在**同一个终端会话**里协同工作，可从浏览器或桌面应用访问。AI 既能在后台静默操作一个连接（跑命令、搜文件、管 SFTP），也能向**人正在看的共享终端**注入命令。本质上是 xshell 风格的终端，外加一个能跟你一起敲命令的 AI 助手。

## 演示

**后台会话恢复** —— 关闭 tab 只是 detach 页面；SSH 连接继续在后台运行，输出持续累积。重新打开应用即可一键恢复：

![恢复后台 SSH 会话](ssh_recover.gif)

高清原视频：[recover.mp4](recover.mp4)

## 核心特性

- **人机共享同一个终端** —— 人的输入（WebSocket）与 AI 注入（`write` 接口）走同一把 pty；AI 敲的命令实时出现在人的终端里，其输出进入共享缓冲。
- **AI 双路径执行**
  - *独立路径（默认优先）* —— 非交互 `exec` / 递归 `find`，独立连接、直接返回结果、无并发、不打扰人。
  - *协作路径* —— `write` 注入到人可见的共享终端，`buffer` 增量读取，注入前用 `status` 做空闲检测。
- **AI 能力发现** —— `GET /api/ai/capabilities` 把 39 项能力注册表 + 工作流地图交给 AI agent；`GET /api/ai/capabilities/{name}` 给出单接口参数与调用链。AI 自举发现，无需硬编码。
- **会话 / 分组管理** —— 名称/IP 同时过滤、导入导出（JSON 文件或剪贴板）、xshell 式可折叠分组树。
- **多标签终端** —— 每个 tab 一个独立 SSH 连接；关闭 tab 后 SSH 后台保活不中断，随时可恢复。
- **SFTP 面板** —— 浏览 / 拖拽上传 / 下载 / 编辑 / 删除 / 递归搜索，复用会话连接。
- **快捷命令** —— 分组 + 命令预存，一键发送（只回显或自动执行），支持导入导出，AI 也可通过 run 接口触发。

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│  前端 —— xterm.js + 原生 JS + Electron 壳                     │
│  会话树 │ 多标签终端 │ AI 面板 │ SFTP │ 导入/导出              │
└───────┬──────────────────────────────┬───────────────────────┘
        │ HTTP (REST)                  │ WebSocket
        ▼                              ▼
┌──────────────────────────────────────────────────────────────┐
│  后端 —— Python FastAPI (asyncio)                             │
│  会话 CRUD │ 终端 WS │ AI 双路径 │ SFTP │ 快捷命令              │
│                                                              │
│  SessionManager ── TerminalSession（每个 conn_id 一个）         │
│     环形缓冲 · 单一写锁 · 订阅者扇出                            │
│                          │                                   │
│  传输层抽象：   SSH (asyncssh) │ Local (pty)                   │
└───────┬──────────────────────────────┬───────────────────────┘
        ▼                              ▼
   远端 SSH 主机                本地 pty shell（开发/验证）
```

### 关键设计决策

**1. pty 归 Python 后端持有** —— 前端和 AI 都只是同一个 pty 的客户端。AI 干涉只走后端接口、不碰前端 JS —— 将来可剥掉 Electron 壳退化为纯浏览器形态。

**2. 人机如何共享同一个终端（机制）**

```
人 xterm ──ws input──▶ 后端 ──写锁──▶ pty ──▶ 远端 shell
AI write API ─────────▶ 后端 ──同一把锁──▶ pty         │
                                                     ▼
输出读循环 ◀──── pty ──▶ 环形缓冲（≤256KB）──▶ 扇出给所有 ws 订阅者
```

- **单一写锁** —— 所有来源的输入（人的 WS、AI 的 `write`）在进入 pty 前经过同一把 `asyncio.Lock` 串行化，避免人机协同时字节交错。
- **增量输出缓冲** —— 每个连接维护有界 256KB 环形缓冲。`GET /buffer?since=N` 只返回 `N` 之后的新增输出（`gap=true` 表示偏移已超出窗口）。AI 每次把 `total` 作为下一次 `since`，从不全量重拉历史 —— 大幅节省上下文。
- **空闲检测** —— `GET /api/connections/{conn_id}/status` 返回 `idle` / `idle_ms`（超过 `TERMINAL_IDLE_THRESHOLD_MS` 无输出即为空闲）。AI 注入前先确认 `idle=true`，避免命令和运行中的命令、或未出现的提示符交错。

**3. 独立连接模型 + 后台保活** —— 一份会话配置（`sid`）可产生多个独立连接（`conn_id`）；每个 tab / 每个 AI 连接 = 独立 pty + 缓冲。关闭 WebSocket 只是 *detach*；SSH 继续运行、输出持续累积，`GET /api/connections/background` 跨会话列出所有后台保活连接供一键恢复。

**4. AI 双路径执行**

| 路径 | 接口 | 语义 | 并发 |
|------|------|------|------|
| 协同 | `POST /api/connections/{conn_id}/write` | 注入到指定共享终端；输出进该连接缓冲并回显给人 | 写锁串行化 |
| 独立（默认） | `POST /api/sessions/{sid}/exec` · `POST /api/sessions/{sid}/find` | 非交互、独立连接直接返回结果 | 无 |

**5. 传输层抽象** —— 统一 `Transport` 接口（`connect / close / exec / create_interactive`）。`SSHTransport` 用 asyncssh（exec 走 `conn.run`；交互走 `create_process` + `change_terminal_size`）。`LocalTransport` 用 `pty.fork()` + `loop.add_reader` 非阻塞 master，供开发/验证。终端 WS、AI 执行面、SFTP 完全不知道底层是 SSH 还是本地。

**6. AI 能力发现（自举）** —— 能力注册表驱动整个 AI 集成。每项暴露 `name / method / path / summary / params / returns / example / chain`；body 参数 schema 从**实际校验用的同一个 Pydantic 模型**推导，`chain` 描述多步操作如何编排（OpenAPI 表达不了的信息）。流程：`GET /capabilities`（能做什么）→ `GET /capabilities/{name}`（怎么调）→ 调用 REST 接口。

**7. 存储** —— 纯 JSON 文件（`data/sessions.json`、`data/groups.json`、`data/quick.json`），原子写（tmp + `replace`）。多 token 过滤：每个空白分隔 token 都必须命中「名称 + 主机 + 端口」。

## AI 集成接口

后端暴露 AI 友好的 REST 面（无需界面）。最小 Python 客户端：

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
r = api(f"/api/sessions/{sid}/exec", "POST", {"command": "uptime", "timeout": 20})
print(r["stdout"])

# 4. 协作路径：开连接 → 注入命令 → 增量读输出
conn = api(f"/api/sessions/{sid}/connect", "POST")["conn_id"]
api(f"/api/connections/{conn}/write", "POST", {"data": "echo hello-from-AI\n"})
buf = api(f"/api/connections/{conn}/buffer?since=0")
print(buf["data"][-100:])
api(f"/api/connections/{conn}/disconnect", "POST")
```

完整指南：[docs/usage.md](docs/usage.md) · 接口清单：[docs/features.md](docs/features.md)

## 技术栈

| 层      | 技术                                      |
|---------|-------------------------------------------|
| 终端    | xterm.js · @xterm/addon-fit（本地化，离线可用） |
| 前端    | 原生 JS · WebSocket · Electron 壳          |
| 后端    | Python FastAPI · asyncio · asyncssh       |
| 存储    | JSON 文件（会话 / 分组 / 快捷命令）          |
| AI      | 能力发现接口 · 双路径执行（`/api/ai`、`/api/connections/*`） |

## 项目结构

```
backend/                  # Python FastAPI 后端
  app/main.py             # 应用组装 · /api/health · 静态托管 · lifespan 关闭
  app/sessions.py         # TerminalSession（环形缓冲 · 写锁 · 扇出）+ SessionManager
  app/transports.py       # 传输抽象（SSH asyncssh / Local pty）
  app/capabilities.py     # AI 能力注册表（概述 + 单能力详情）
  app/routes/             # sessions · groups · terminal(WS) · ai · sftp · quick · transfer
  tests/test_smoke.py     # 冒烟测试
frontend/                 # 前端静态资源（由后端托管）
  js/                     # core · tree · terminal(WS) · ctxmenu · modals · bg · quick · sftp
  vendor/                 # xterm.js + addon-fit（本地化，离线可用）
  electron/main.js        # Electron 壳：拉起后端 → 等 /api/health → 加载 UI
docs/                     # architecture · features · implementation · usage
data/                     # 会话 / 分组 / 快捷命令 JSON（gitignored）
```

## 快速开始

### 安装依赖

```bash
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install
```

### 浏览器

```bash
cd backend && .venv/bin/python run.py
# → http://127.0.0.1:8747
```

### 桌面版（Electron）

```bash
cd frontend && npm start
```

### 测试

```bash
cd backend && .venv/bin/python -m pytest tests/ -v
```

## 打包分发（macOS `.app` / `.dmg`）

PyInstaller 把后端（含前端静态资源）冻成 onedir 二进制；electron-builder 再出 `.app` / `.dmg`。在 `feat/packaging` 分支：

```bash
git checkout feat/packaging
cd backend && .venv/bin/pip install "pyinstaller>=6.21"
cd ../frontend && npm install
npm run package:backend && CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --mac
```

打包态后端运行在 `Resources/backend/sshmgr-backend`，自动选空闲端口，用户数据落到系统应用数据目录（macOS 为 `~/Library/Application Support/sshManager/data`）—— 绝不进包内。构建产物（`frontend/dist/*.dmg`、`*.app`）已 gitignore。暂未合并回 `main`。

## 演示文件

| 文件             | 用途                                                   |
|------------------|--------------------------------------------------------|
| `ssh_recover.gif`| 一键恢复后台 SSH 会话的动图演示                          |
| `recover.mp4`    | 同一流程的高清视频                                       |

## 文档

- [使用指南 —— 人类 + AI](docs/usage.md)
- [架构文档](docs/architecture.md)
- [功能文档](docs/features.md)
- [实现文档](docs/implementation.md)

## 路线图

- [ ] AI 后台 WebSocket 回显 →「一起干」模式（AI 把进度流式推到浏览器）
- [ ] 会话 / 分组 / 快捷命令拖拽排序
- [ ] 密码加密存储

## 已验证

- pytest 套件（17 项）—— 会话 CRUD / 过滤 / 导入导出 / exec / find / 终端 WS + AI write / 增量缓冲 / 后台保活 / SFTP 回环，均走 local 传输
- 浏览器 E2E · Electron 冒烟
- 真机 SSH（CentOS 7）—— connect / exec / find / SFTP / 交互终端 全部实测通过

## License

私有项目，授权问题请联系所有者。
