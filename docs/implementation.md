# 实现文档

> 适用版本：核心闭环已实现（2026-08-01）。

## 1. 目录结构

```
sshManager/
├── backend/                    # Python FastAPI 后端
│   ├── run.py                  # 启动器（端口 8747，SSHMANAGER_PORT 可覆盖）
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── app/
│   │   ├── main.py             # 应用组装：路由注册 + `GET /api/health` + 静态托管 + lifespan 关闭
│   │   ├── config.py           # 路径/常量（缓冲上限、默认终端尺寸）
│   │   ├── deps.py             # FastAPI 依赖注入（store/manager 单例）
│   │   ├── models.py           # Pydantic 模型
│   │   ├── capabilities.py     # AI 能力注册表（概述 + 详情）
│   │   ├── store.py            # 会话 + 分组 JSON 持久化
│   │   ├── transports.py       # 传输抽象（SSH / Local）
│   │   ├── sessions.py         # 会话运行时（缓冲/写锁/扇出）
│   │   └── routes/
│   │       ├── sessions.py     # 会话 CRUD/过滤/导入导出/连接控制
│   │       ├── groups.py       # 分组 CRUD
│   │       ├── terminal.py     # WS 终端流
│   │       ├── ai.py           # AI 双路径 + 能力发现 /api/ai
│   │       └── sftp.py         # SFTP
│   └── tests/test_smoke.py     # 冒烟测试
├── frontend/                   # 前端（FastAPI 静态托管）
│   ├── index.html              # 单页布局 + 弹窗
│   ├── style.css               # 暗/亮主题（CSS 变量）
│   ├── js/                     # 前端逻辑（按域拆分，index.html 按序加载）
│   │   ├── core.js             #   $/state/api/modal 助手/主题
│   │   ├── tree.js             #   会话/分组树 + 状态刷新
│   │   ├── terminal.js         #   多标签终端 + WebSocket
│   │   ├── ctxmenu.js          #   右键菜单
│   │   ├── modals.js           #   新建/编辑/导入/导出
│   │   ├── bg.js               #   后台连接面板
│   │   ├── quick.js            #   快捷命令
│   │   ├── sftp.js             #   SFTP 面板
│   │   └── main.js             #   事件绑定 + 启动（最后加载）
│   ├── vendor/                 # xterm.js + addon-fit 本地化（离线可用）
│   ├── electron/main.js        # Electron 壳
│   └── package.json
├── data/sessions.json          # 运行数据（gitignored）
└── docs/                       # 本文档目录
```

## 2. 后端实现

### 2.1 传输层（transports.py）

统一接口（ABC）：

```python
class Transport:
    async def connect() -> None
    async def close() -> None
    async def exec(command, timeout) -> ExecResult   # 非交互
    def create_interactive() -> InteractiveChannel    # 交互 pty
```

**SSHTransport（asyncssh）**：
- `connect`：`asyncssh.connect(host, port, username, password|client_keys, known_hosts=None)`。
- `exec`：`await conn.run(cmd, check=False, term_type, term_size)`（异步等待命令完成）。
- 交互：`conn.create_process(term_type="xterm-256color", term_size=(cols, rows))`。
- resize：`proc.change_terminal_size(width, height)`（**注意 asyncssh 2.24 的 API**，非旧版 `resize_term`）。
- 连接复用：exec / interactive / SFTP 共享同一 `SSHClientConnection`（多路复用通道）。

**LocalTransport（开发验证）**：
- `exec`：`asyncio.create_subprocess_shell`。
- 交互：**`pty.fork()` + `loop.add_reader` + 非阻塞 master**（见 3.1，这是经过踩坑修正的实现）。

### 2.2 会话运行时（sessions.py）

**连接模型**：一个会话配置（sid）可产生多个独立 `TerminalSession`（conn_id 唯一），
每个连接有自己的 transport / pty / 缓冲 / 订阅者，互不影响。`SessionManager` 是连接池：
`create(sid)` 新建连接、`get(conn_id)`、`remove(conn_id)`、`is_connected(sid)`、`disconnect_sid(sid)`。

`TerminalSession` 关键成员：

- **环形输出缓冲**：`_parts`（文本片段）、`_chars`（当前缓冲字符数）、`_total`（累计流字符数）、`_start`（缓冲首片流偏移）。
  - `append(text)`：追加并裁剪最旧内容到 ≤256KB。
  - `get_buffer(since)`：返回 `{since, total, gap, data}`——`since` 落在窗口内则只回传新增，否则全量 + `gap=true`。
- **单一写锁**：`_write_lock`，`write()` 中 `async with` 串行写入 pty。
- **订阅者扇出**：`_read_loop` 从 pty 读 → `append` 到缓冲 → 扇出给所有 `readers`（WebSocket）。
- **生命周期**：`connect()` 建传输 + 交互通道 + 启动读循环；`disconnect()` 取消读循环、关通道、关传输。

`SessionManager`：惰性创建 `TerminalSession`（`get()`），`remove()`（async，注意原因见 3.3）、`shutdown()`（lifespan 关闭时调用）。

### 2.3 存储（store.py）

- `SessionStore`：`data/sessions.json`（会话）+ `data/groups.json`（分组），均为列表格式，`threading.Lock` 保护，写时原子替换（tmp 文件 + replace）。
- `list_all(query)`：多 token 过滤（每个 token 都是「名称+主机+端口」子串）。
- 分组方法：`list_groups/create_group/rename_group/delete_group`；**`delete_group` 把组内会话 `group_id` 置空**（回落根层级）。
- `update(sid, patch)`：patch 由路由层控制，已过滤 None；仅显式置空的字段（如 `group_id: null`）会带 None 值，用于「移出分组」。
- 密码明文存储（与 xshell 同类工具一致），`_public()` 出参时剔除密码字段。

### 2.4 路由

**terminal.py — WS 协议**：
- 两个路由：
  - `/ws/terminal/{sid}` 新建独立连接：`manager.create(sid)` → `connect()` → `await attach(ws)`（发缓冲尾）→ `send status`。
  - `/ws/connection/{conn_id}` 恢复到后台保活连接（拉回前台）。
- **关闭语义**：ws 关闭**只 detach，不自动断开**——连接后台保活（SSH 不断、缓冲继续累积）。真正断开走 `POST /api/connections/{conn_id}/disconnect`（前端「断开并关闭」）；关闭程序由 lifespan `manager.shutdown()` 终止所有。
- 客户端 → 服务端：`{"type":"input","data"}`、`{"type":"resize","cols","rows"}`。
- 服务端 → 客户端：`{"type":"status","state","conn_id"}`、`{"type":"buffer","data"}`（历史尾）、`{"type":"output","data"}`。
- 连接失败（如 SSH 认证失败）→ 发 `status:error` 并 close(1011)。
- ⚠️ `attach` 是 async，必须 `await`（漏写会导致 readers 未注册，ws 收不到后续消息）。

**groups.py — 分组 CRUD**：`GET/POST/PATCH/DELETE /api/groups`；删除分组回落组内会话。

**quick.py — 快捷命令**：分组 + 命令 CRUD、导入导出；`POST /commands/{cid}/run` 触发执行——`exec` 独立非交互返回结果，`write` 发送到共享终端（可传 `conn_id` 指定连接）。

**ai.py — AI 双路径（交互/非交互）+ 能力发现**：
- **独立路径（非交互，默认优先）**：`POST /exec`——`build_transport(cfg)` 新建连接执行，返回 `{stdout, stderr, exit_code, duration_ms, timed_out}`；`POST /find`——参数经 `shlex.quote` 安全引用后组 find 命令。
- **协同路径（交互）**：`POST /api/connections/{conn_id}/write`——向共享终端注入（处理需 TTY 的交互命令）；`GET /api/connections/{conn_id}/buffer?since=`——增量读取；`GET /api/connections/{conn_id}/status`——**空闲检测**（`idle/idle_ms`，注入前确认提示符就绪）；`PATCH /api/connections/{conn_id}/label`——连接显示名（`connect_session` 创建时可带 label，界面 Rename Tab 也走这里，统一存 `ts.label`）。
- `GET /api/ai/capabilities` / `GET /api/ai/capabilities/{name}`：能力发现（见 `capabilities.py`）。

**capabilities.py — 能力注册表**：每项 `name/method/path/summary/params/returns/example/chain`；body 参数从 Pydantic 模型 `model_json_schema()` 推导（`_body_schema` 辅助函数）。`chain` 描述调用链（前置/后续），`overview().note` 是「工作流地图」。`overview()` 返回轻量清单，`detail(name)` 返回完整参数。

**sftp.py**：SSH 用 `conn.start_sftp_client()`（`scandir()` 列目录，条目为 `SFTPName.filename/.attrs`）；local 用 `os.scandir`/文件读写。

## 3. 关键实现细节

### 3.1 本地 pty 管理（重要：经踩坑修正）

**背景**：初版用「读线程 + 阻塞 `os.read(master)`」，close 时从另一线程关 fd **无法唤醒**阻塞的读线程，进程陷入不可中断等待（SIGKILL 无效），导致测试整体挂死。

**正解**（当前实现）：
- `pty.fork()` 子进程 exec shell（子进程获得控制终端，job control 正常）。
- `os.set_blocking(master, False)` + `loop.add_reader(master, on_readable)`——由事件循环驱动读取，无读线程。
- `on_readable` 读到的数据 `put_nowait` 进 asyncio 队列；EOF 时 `remove_reader` 并推 `None` 信号。
- `close()` 顺序：`remove_reader` → 关 fd → SIGHUP → **有界 WNOHANG 轮询**（2.5s）→ SIGKILL 兜底。绝不无限 `waitpid` 阻塞。

### 3.2 增量缓冲算法

```
append(text):  parts += [text]; total += len(text)
              while chars > 256KB: 从头部裁剪（片段级/字符级），start 前移

get_buffer(since):
  end = start + len("".join(parts))
  if start <= since <= end:  return {since, total, gap:False, data: text[since-start:]}
  else:                      return {since, total, gap:True,  data: text}   # 全量 + 标记 gap
```

调用方（AI）每次把返回的 `total` 作为下次的 `since`，即实现增量获取。

### 3.3 同步路由不得 `asyncio.create_task`

FastAPI 的同步路由跑在线程池线程里，**没有运行中的事件循环**，`asyncio.create_task` 会报 `no running event loop`。需要调 async 逻辑的路由（如删除会话要断开运行时）必须声明 `async def` 并 `await`。

### 3.4 启动与 Electron 集成

- `run.py`：`uvicorn.run(..., reload=True, reload_dirs=["app"])`——`reload_dirs` 限定代码目录，避免写 `data/sessions.json` 触发服务重启。
- `electron/main.js`：`spawn(python run.py, {detached:true, env:SSHMANAGER_RELOAD=0})` → 轮询 `/api/sessions` 等后端就绪 → `BrowserWindow.loadURL` → `will-quit` 时 `process.kill(-pid, SIGTERM)` 整树终止。

## 4. 前端实现

- 原生 JS（Electron 友好），xterm.js + addon-fit **本地化在 `vendor/`**，离线可用。
- **布局**：左侧边栏（会话列表 + 过滤 + 新建/导入/导出）+ 主区（终端标签栏 + 终端容器 + AI 面板）。
- **终端**：`Terminal` + `FitAddon`，`term.onData` → WS input，`term.onResize` → WS resize，`ResizeObserver` 触发 `fit()`。
- **WS 自适应端口**：用 `location.host` 拼 ws 地址，换端口无需改前端。
- **AI 面板**：三种模式切换（写入终端 / 独立执行 / 递归搜索），输出区展示 exec/find 结果。
- **导入导出**：导出=剪贴板 + 下载 JSON；导入=粘贴文本或选文件。

## 5. 测试

```bash
cd backend && .venv/bin/python -m pytest tests/ -v
```

覆盖：会话 CRUD/过滤/导入导出、exec、find、终端 WS 流 + AI write + 增量 buffer、SFTP 上传/下载回环。均走 **local 传输**（与 SSH 共用上层代码路径）；SSH 需凭据环境，未自动化。

## 6. 已知问题与待办

### 已知问题
- ~~SSH 传输路径未真机验证~~ → 已实测（192.168.8.101，connect/exec/find/SFTP/交互终端全通过）。
- SFTP 无前端 UI（仅 API）。
- 密码明文存储（生产化需加密）。
- `known_hosts=None` 不校验主机密钥（与 xshell 一致，安全权衡）。
- SSH 交互终端注入命令前需等登录横幅/提示符（启动时序）——**空闲检测已实现**（`GET /api/connections/{conn_id}/status` 的 `idle`），AI 注入前先确认 `idle=true`。

### 待办
- [ ] AI 后台 WebSocket 长连接 + 回显浏览器的「一起干」模式
- [ ] 拖拽排序（会话/分组/快捷命令）
- [ ] 密码加密存储
