"""应用配置：路径、常量。

路径分两态：
- 开发态（源码树）：前端/数据都在仓库内，靠 parents[2] 定位仓库根。
- 打包态（PyInstaller 冻结，sys.frozen 为真）：前端静态资源随后端打进
  _MEIPASS（只读）；用户数据落到系统应用数据目录（可写、跨版本保留）。
"""
import os
import sys
from pathlib import Path

IS_FROZEN = getattr(sys, "frozen", False)


def _data_dir() -> Path:
    """打包态返回可写的用户数据目录并确保存在；开发态返回仓库 data/。"""
    if not IS_FROZEN:
        return Path(__file__).resolve().parents[2] / "data"
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / "sshManager"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))) / "sshManager"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))) / "sshManager"
    d = base / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


if IS_FROZEN:
    # 打包态：前端静态资源随二进制打进 _MEIPASS（只读）
    FRONTEND_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "frontend"
else:
    # 开发态：前端静态目录
    FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

# 数据目录（sessions.json 等），已 gitignore
DATA_DIR = _data_dir()
SESSIONS_FILE = DATA_DIR / "sessions.json"
GROUPS_FILE = DATA_DIR / "groups.json"
QUICK_FILE = DATA_DIR / "quick.json"

# 终端输出缓冲上限（字节）。AI 增量获取基于该缓冲，超出后最旧内容被丢弃。
TERMINAL_BUF_LIMIT = 262144  # 256KB

# 终端「空闲」判定阈值（毫秒）：超过该时长无输出即视为空闲。
# 供 AI 注入前确认提示符就绪（架构中的「空闲检测」）。
TERMINAL_IDLE_THRESHOLD_MS = 500

DEFAULT_TERM_SIZE = (24, 80)  # (rows, cols)
