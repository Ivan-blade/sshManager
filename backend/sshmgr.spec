# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把 FastAPI 后端（含前端静态资源）冻成 onedir 二进制。

用法：cd backend && .venv/bin/python -m PyInstaller --clean --noconfirm sshmgr.spec
产物：backend/dist/sshmgr-backend/sshmgr-backend（+ _internal/）

要点：
- 前端资源显式列出（index.html/app.js/style.css/vendor），绝不整个 ../frontend——
  node_modules 250MB（含 Electron 二进制）会被误打进去。
- asyncssh 惰性导入 crypto/sftp 子模块、uvicorn 动态加载协议模块，都需要 collect。
- frozen 分支 run.py 用对象导入 + loop="asyncio"，因此排除 uvloop/watchfiles。
"""
import os
from PyInstaller.utils.hooks import collect_submodules

# SPECPATH 由 PyInstaller 注入，是 spec 所在目录的绝对路径（即 backend/）
BACKEND = os.path.abspath(SPECPATH)
ROOT    = os.path.abspath(os.path.join(BACKEND, ".."))
FRONT   = os.path.join(ROOT, "frontend")

# 前端静态资源（随二进制打进，只读；_MEIPASS/frontend 由 config.py 定位）
datas = [
    (os.path.join(FRONT, "index.html"), "frontend"),
    (os.path.join(FRONT, "js"),         "frontend/js"),
    (os.path.join(FRONT, "style.css"),  "frontend"),
    (os.path.join(FRONT, "vendor"),     "frontend/vendor"),
]

# asyncssh 惰性导入子模块 + uvicorn 动态加载的协议/事件循环实现
hiddenimports = (
    collect_submodules("asyncssh")
    + collect_submodules("uvicorn")
    + [
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
    ]
)

a = Analysis(
    [os.path.join(BACKEND, "run.py")],
    pathex=[BACKEND],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "httpx", "httpcore", "uvloop", "watchfiles"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sshmgr-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 未来 Windows 不弹控制台窗口；macOS 忽略
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="sshmgr-backend",
)
