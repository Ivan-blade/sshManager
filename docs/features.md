# 功能文档

> 适用版本：核心闭环已实现（2026-08-01）。

## 1. 功能总览

| 功能 | 状态 | 入口 |
|------|------|------|
| 会话列表 + 按 IP/名称同时过滤 | ✅ 已实现 | 左侧面板搜索框 |
| **会话分组树**（xshell 式，可折叠） | ✅ 已实现 | 左侧面板 |
| 会话新建 / 重命名 / 删除 / **移动到分组** | ✅ 已实现 | 左侧面板 + 右键菜单 |
| 分组新建 / 重命名 / 删除 | ✅ 已实现 | 面板「＋」/ 右键菜单 |
| 会话导入 / 导出（JSON 文件 + 剪贴板） | ✅ 已实现 | 顶部「导入」「导出」 |
| **多标签终端**（同时开多个会话） | ✅ 已实现 | 主区标签栏 |
| 终端会话（WebSocket 流 + resize） | ✅ 已实现 | 点击会话 / 标签切换 |
| 终端输出增量获取（AI getBuffer） | ✅ 已实现（服务端） | `GET /buffer` |
| AI 写入终端（协作） | ✅ 已实现 | 后端接口 |
| AI 独立执行（非交互） | ✅ 已实现 | 后端接口 |
| 当前路径递归搜索（find） | ✅ 已实现 | 后端接口 |
| **AI 能力发现**（概述 + 按接口查参数） | ✅ 已实现 | `GET /api/ai/capabilities*` |
| SFTP 文件浏览 / 上传 / 下载 / 编辑 / 删除 / 递归搜索 | ✅ 已实现 | SFTP 面板 + REST API |
| 快捷命令分组 + 增删查改 + 组间移动 + 导入导出 | ✅ 已实现 | 快捷命令栏 + Q-Export/Q-Import |
| AI 后台 WS 长连接回显浏览器（「一起干」） | 🔲 规划中 | — |
| SSH 真机联调验证 | ✅ 已通过（192.168.8.101 实测） | — |

> AI 执行面不提供界面，AI 通过能力发现接口自举后调用后端 API（见 §5）。

## 2. 会话管理

### 2.1 创建会话

支持两种传输：

- **SSH（远程）**：主机、端口、用户名、认证方式（密码 / 密钥路径）。
- **本地 Shell（开发验证）**：无需任何凭据，在本机分配真实 pty 运行 shell，用于不连远程主机时开发/测试。

### 2.2 过滤

过滤框输入可**同时**按名称与 IP 匹配：查询串的每个空白分隔 token 都必须是「名称 + 主机 + 端口」组合串的子串。例如输入 `本地 127` 只匹配名称含「本地」且主机含「127」的会话。

### 2.3 导入 / 导出

- **导出**：一键复制 JSON 到剪贴板，同时下载 JSON 文件。
- **导入**：粘贴剪贴板 JSON 或选择 JSON 文件；已存在的会话按 id 跳过，其余以新 id 合并。

## 3. 终端

- 双击左侧会话打开终端（有后台连接则恢复，否则新建独立连接）。
- **关闭 tab 两个按钮**（hover tab 显示）：
  - `✕` **仅关闭页面**：关闭页面，SSH **后台保活**（进程不断、输出继续累积）。
  - `⏻` **断开 SSH 并关闭**：关闭页面 + 断开 SSH，后台清除。
- **状态胶囊**（统一）：会话列表每项显示统一状态胶囊——`运行中`（绿）/ `后台 ×N`（黄）/ `离线`（灰）。
- **后台连接管理**：面板「◔ 后台连接」按钮 → 弹出列表列出**全部**后台保活 SSH（跨会话，含会话名+主机），每条可「恢复 / 断开」；会话右键也有「恢复到后台连接 / 断开后台连接 / 以新连接打开」。
- 支持实时 I/O、窗口 resize（xterm fit + 服务端 pty resize）。
- 关闭程序时后端 lifespan 终止所有连接。

## 4. AI 能力

AI 面板三种模式：

| 模式 | 做什么 | 结果在哪 |
|------|--------|---------|
| **写入终端（协作）** | 把输入内容注入共享终端，命令在终端里执行 | 终端回显（人能看到，输出进缓冲） |
| **独立执行（非交互）** | 直接执行 shell 命令并返回结果，不打扰终端 | 面板下方输出区 |
| **递归搜索** | 按路径 + 名称模式递归查找文件 | 面板下方输出区 |

使用建议：AI 默认应优先「独立执行」；需要人协作/看到过程时才用「写入终端」。

## 5. SFTP（当前为 API，UI 待接）

- 文件列表：`GET /api/sessions/{id}/sftp/ls?path=`
- 上传：`POST /api/sessions/{id}/sftp/upload`（multipart）
- 下载：`GET /api/sessions/{id}/sftp/download?path=`
- SSH 会话复用连接；local 会话映射本机文件系统。

## 6. API 参考

### 会话

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sessions?q=` | 列表（q 为名称/IP 过滤） |
| POST | `/api/sessions` | 创建 |
| GET | `/api/sessions/{id}` | 单条（不回传密码） |
| PATCH | `/api/sessions/{id}` | 部分更新 |
| DELETE | `/api/sessions/{id}` | 删除（断开运行时） |
| GET | `/api/sessions/export` | 导出全部（含密码，本地工具） |
| POST | `/api/sessions/import` | 导入（JSON 数组） |
| POST | `/api/sessions/{id}/connect` | 建立连接 |
| POST | `/api/sessions/{id}/disconnect` | 断开 |
| GET | `/api/sessions/{id}/status` | 连接状态 |

### 分组

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/groups` | 分组列表 |
| POST | `/api/groups` | 新建分组 |
| PATCH | `/api/groups/{id}` | 重命名 |
| DELETE | `/api/groups/{id}` | 删除（组内会话回到根层级） |

会话移动分组：`PATCH /api/sessions/{id}` 传 `group_id`；传 `group_id: null` 表示移出分组。

### AI 能力发现

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/ai/capabilities` | 后端所有能力概述（名称/方法/路径/一句话说明） |
| GET | `/api/ai/capabilities/{name}` | 按名称查具体调用参数（body schema 从 Pydantic 推导） |

AI 流程：先 `GET /capabilities` 看能做什么 → `GET /capabilities/{name}` 查怎么调 → 调对应 REST 接口。

### 终端 / AI

| 方法 | 路径 | 说明 |
|------|------|------|
| WS | `/ws/terminal/{id}` | 终端流：input/resize（客户端→服务端）；buffer/output/status（服务端→客户端） |
| GET | `/api/connections/background` | 列出全部后台保活连接（跨会话，含会话名/主机） |
| POST | `/api/connections/{conn_id}/write` | AI 协同：写入指定连接（独立终端） |
| GET | `/api/connections/{conn_id}/buffer?since=` | AI 增量获取指定连接输出缓冲 |
| POST | `/api/connections/{conn_id}/disconnect` | 断开指定连接 |
| POST | `/api/sessions/{id}/exec` | AI 独立：非交互执行命令 |
| POST | `/api/sessions/{id}/find` | AI：递归搜索 |

> 连接（conn_id）先通过 `POST /api/sessions/{id}/connect` 获取；每个 tab / 连接是独立终端通道，互不影响。

### SFTP

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/sftp/ls?path=` | 列目录 |
| GET | `/api/sessions/{id}/sftp/download?path=` | 下载文件 |
| POST | `/api/sessions/{id}/sftp/upload` | 上传文件（multipart） |
