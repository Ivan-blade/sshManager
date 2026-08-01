<div align="center">

# sshManager

**人机协作的 SSH 客户端 —— 人和 AI 在同一个共享终端里一起干活**

[English](README.md) · [简体中文](README.zh-CN.md)

</div>

**人机协同的 SSH 会话管理**：人和 AI 在**同一个终端会话**里协同工作，可从浏览器或桌面应用访问。AI 既能在后台静默操作一个连接（跑命令、搜文件、管 SFTP），也能向**人正在看的共享终端**注入命令。

## 功能特性

- **会话 / 分组管理** —— 按名称/IP 同时过滤、导入导出（JSON 文件或剪贴板）、后台保活 + 一键恢复
- **多标签终端** —— 每个 tab 一个独立 SSH 连接；关闭 tab 后 SSH 后台保活不中断
- **快捷命令** —— 分组 + 命令增删查改，发送到终端（只回显，或末尾带换行自动执行），支持导入导出
- **SFTP 面板** —— 浏览 / 上传（拖拽）/ 下载 / 编辑 / 删除 / 递归搜索
- **AI 能力发现** —— `GET /api/ai/capabilities` 让 AI agent 自举发现并调用后端全部能力
- **AI 双路径执行** —— 独立路径（非交互 `exec`/`find`，无并发）或协作路径（注入到人可见的共享终端）
- **增量输出缓冲** —— AI 通过 `?since=` 偏移只读新增输出（省上下文）

## 快速开始

### 桌面版（Electron）

```bash
cd frontend && npm start
```

### 浏览器

```bash
cd backend && .venv/bin/python run.py
# → http://127.0.0.1:8747
```

### 安装依赖

```bash
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install
```

## 后台会话恢复（演示）

关闭 tab 只是 detach 页面 —— SSH 连接继续在后台运行，输出持续累积。重新打开应用即可一键恢复：

<video src="recover.mp4" controls muted loop style="max-width: 100%; border-radius: 8px;"></video>

- 打开顶栏「◔ Background」—— 这里列出**所有跨会话的后台连接**（含会话名 + 主机）；点击整行即可恢复到 tab。
- **AI 创建的会话同理**：AI 在它创建的会话（或任何会话）上打开的连接，同样会出现在后台列表里，与人创建的会话一样可一键恢复。

## 技术栈

| 层      | 技术                                  |
|---------|---------------------------------------|
| 终端    | xterm.js · @xterm/addon-fit          |
| 桌面    | Electron                             |
| 后端    | Python FastAPI · asyncssh            |
| 存储    | JSON 文件（会话 / 分组 / 快捷命令）    |
| AI      | 能力发现接口（`/api/ai/capabilities*`）|

## 架构（概要）

- **pty 归 Python 后端持有** —— 前端和 AI 都是它的客户端
- **连接模型** —— 一份会话配置可产生多个独立 SSH 连接（`conn_id`），各有独立 pty + 输出缓冲
- **AI 干涉走后端接口，不碰前端 JS** —— 将来可剥掉 Electron 壳退化为纯浏览器形态
- **后台保活** —— 关 tab 只 detach，SSH 不断，可恢复

完整设计见 [docs/architecture.md](docs/architecture.md)。

## 文档

- [使用指南 —— 人类 + AI](docs/usage.md)
- [架构文档](docs/architecture.md)
- [功能文档](docs/features.md)
- [实现文档](docs/implementation.md)

## 路线图

- [ ] AI 后台 WebSocket 回显 →「一起干」模式
- [ ] 会话 / 分组 / 快捷命令拖拽排序
- [ ] 密码加密存储

## 已验证

- pytest 12/12 · 浏览器 E2E · Electron 冒烟
- 真机 SSH（CentOS 7）—— connect / exec / find / SFTP / 交互终端 全部实测通过

## License

私有项目，授权问题请联系所有者。
