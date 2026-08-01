# sshManager

人机协作的 SSH 工具（xshell 增强版）——人和 AI 在同一个浏览器界面里协同操作终端。

## 核心理念

- 人和 AI 各自有**独立执行策略**，共享同一个终端会话
- 人通过界面操作；AI 默认**静默执行**，遇到问题再和人协作
- **AI 干涉走纯后端**（pty 所有权在 Python 后端，AI 往共享 pty 写字节），不依赖前端 JS
- AI 获取终端信息用 `getBuffer` **增量获取**，防止全量拉取占用上下文

## 架构

```
前端: JS + xterm + pty ──打包──> Electron（启动时拉起 Python 后端）
后端: Python FastAPI（持有 pty master，人和 AI 都是其客户端）
AI:   双路径 —— 协同路径（驱动共享界面，有并发问题）/ 独立路径（纯后端，无并发）
```

## 技术栈

| 层 | 技术 |
|----|------|
| 终端前端 | xterm.js |
| 终端尺寸适配 | xterm-resize（@xterm/addon-fit） |
| 桌面壳 | Electron |
| 后端 | Python FastAPI |
| 终端/pty | pty 由 Python 后端持有 |

## 功能规划

- 会话列表管理：按 **IP + 名称同时过滤**
- 会话导入/导出：支持 **JSON 文件 + 剪贴板**
- 快捷命令导入/导出：支持 **JSON 文件 + 剪贴板**
- 快捷命令管理：分组 + 命令**增删查改** + 命令在组间**移动**
- SFTP 管理：**复用 SSH 连接**，文件上传/下载/修改
- 当前路径递归搜索：后端 Python 接口执行 `find` 实现

## 运行

### 方式一：Electron 桌面壳（启动时自动拉起 Python 后端）

```bash
cd frontend && npm start
```

### 方式二：浏览器开发模式

```bash
cd backend && .venv/bin/python run.py
# 打开 http://127.0.0.1:8000
```

首次运行需安装依赖：

```bash
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install
```

## 测试

```bash
cd backend && .venv/bin/python -m pytest tests/ -v
```

冒烟测试聚焦 **local 传输**（与 SSH 共用同一套 exec / 交互通道 / buffer / find / SFTP 代码路径）；SSH 传输需有凭据的测试环境。

## 测试环境

```bash
ssh root@192.168.8.101
```

（私有本地测试 IP，非生产）

## 状态与已知事项

- **已实现**：会话 CRUD/过滤/导入导出、终端 WebSocket 流（含增量 buffer）、AI 双路径（write 写入终端 / exec 独立执行 / find 递归搜索）、SFTP（复用连接）、Electron 壳、冒烟测试。
- **SSH 路径**：asyncssh 连接 + pty 交互已编码，但本仓库测试环境无凭据，需真实主机验证。
- **密码存储**：会话密码明文存于 `data/sessions.json`（与 xshell 同类工具一致）；生产化应加密。

> 详细设计见 [CLAUDE.md](./CLAUDE.md)
