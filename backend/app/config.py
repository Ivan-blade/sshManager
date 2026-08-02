"""应用配置：路径、常量。"""
from pathlib import Path

# 仓库根目录（backend/ 的上一级）
REPO_ROOT = Path(__file__).resolve().parents[2]
# 前端静态目录
FRONTEND_DIR = REPO_ROOT / "frontend"
# 数据目录（sessions.json 等），已 gitignore
DATA_DIR = REPO_ROOT / "data"
SESSIONS_FILE = DATA_DIR / "sessions.json"
GROUPS_FILE = DATA_DIR / "groups.json"
QUICK_FILE = DATA_DIR / "quick.json"

# 终端输出缓冲上限（字节）。AI 增量获取基于该缓冲，超出后最旧内容被丢弃。
TERMINAL_BUF_LIMIT = 262144  # 256KB

# 终端「空闲」判定阈值（毫秒）：超过该时长无输出即视为空闲。
# 供 AI 注入前确认提示符就绪（架构中的「空闲检测」）。
TERMINAL_IDLE_THRESHOLD_MS = 500

DEFAULT_TERM_SIZE = (24, 80)  # (rows, cols)
