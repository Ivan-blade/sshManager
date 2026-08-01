# 功能文档

> 适用版本：核心闭环已实现（2026-08-01）。

## 1. 功能总览

| 功能 | 状态 | 入口 |
|------|------|------|
| 会话列表 + 按 IP/名称同时过滤 | ✅ 已实现 | 左侧边栏 |
| 会话新建 / 编辑 / 删除 | ✅ 已实现 | 左侧边栏「新建」/ 删除按钮 |
| 会话导入 / 导出（JSON 文件 + 剪贴板） | ✅ 已实现 | 顶部「导入」「导出」 |
| 终端会话（WebSocket 流 + resize） | ✅ 已实现 | 点击会话 |
| 终端输出增量获取（AI getBuffer） | ✅ 已实现（服务端） | `GET /buffer` |
| AI 写入终端（协作） | ✅ 已实现 | AI 面板「写入终端」 |
| AI 独立执行（非交互） | ✅ 已实现 | AI 面板「独立执行」 |
| 当前路径递归搜索（find） | ✅ 已实现 | AI 面板「递归搜索」 |
| SFTP 文件浏览 / 上传 / 下载 | ✅ 已实现 | REST API（UI 待接） |
| 快捷命令分组 + 增删查改 + 组间移动 | 🔲 规划中 | — |
| 快捷命令导入 / 导出 | 🔲 规划中 | — |
| AI 模型接入（意图解析 → 命令） | 🔲 规划中 | — |
| AI 后台 WS 长连接回显浏览器（「一起干」） | 🔲 规划中 | — |
| SSH 真机联调验证 | ⚠️ 待验证 | — |

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

- 点击左侧会话打开终端，建立 WebSocket 连接。
- 支持实时 I/O、窗口 resize（xterm fit + 服务端 pty resize）。
- 连接状态显示在顶部标签栏（已连接 / 已断开 / 错误）。
- 会话关闭页面后保持连接（session 级，非页面级），重新打开可看到历史输出（缓冲尾部）。

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

### 终端 / AI

| 方法 | 路径 | 说明 |
|------|------|------|
| WS | `/ws/terminal/{id}` | 终端流：input/resize（客户端→服务端）；buffer/output/status（服务端→客户端） |
| POST | `/api/sessions/{id}/write` | AI 协同：写入共享终端 |
| GET | `/api/sessions/{id}/buffer?since=` | AI 增量获取终端输出缓冲 |
| POST | `/api/sessions/{id}/exec` | AI 独立：非交互执行命令 |
| POST | `/api/sessions/{id}/find` | AI：递归搜索 |

### SFTP

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/sftp/ls?path=` | 列目录 |
| GET | `/api/sessions/{id}/sftp/download?path=` | 下载文件 |
| POST | `/api/sessions/{id}/sftp/upload` | 上传文件（multipart） |
