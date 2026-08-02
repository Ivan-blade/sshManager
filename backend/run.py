"""启动后端：python run.py（从 backend/ 目录运行）。
Electron 通过此方式拉起 Python 进程（此时 SSHMANAGER_RELOAD=0 关闭热重载）。

端口：默认 8747（避开常用端口），可用环境变量 SSHMANAGER_PORT 覆盖。

打包态（PyInstaller 冻结）：直接对象导入 app（PyInstaller 才能追踪依赖），
禁用 reload，固定 loop="asyncio"（避开 uvloop C 扩展）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("SSHMANAGER_PORT", "8747"))
    if getattr(sys, "frozen", False):
        from app.main import app  # 对象导入，PyInstaller 可追踪
        uvicorn.run(app, host="127.0.0.1", port=port,
                    reload=False, loop="asyncio")
    else:
        reload = os.environ.get("SSHMANAGER_RELOAD", "1") != "0"
        uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=reload,
                    reload_dirs=["app"])  # 仅监听代码目录，避免数据文件触发重启
