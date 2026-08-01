"""启动后端：python run.py（从 backend/ 目录运行）。
Electron 通过此方式拉起 Python 进程（此时 SSHMANAGER_RELOAD=0 关闭热重载）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn

if __name__ == "__main__":
    reload = os.environ.get("SSHMANAGER_RELOAD", "1") != "0"
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=reload,
                reload_dirs=["app"])  # 仅监听代码目录，避免数据文件触发重启
