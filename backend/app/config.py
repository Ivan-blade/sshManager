"""应用配置：路径、常量。"""
from pathlib import Path

# 仓库根目录（backend/ 的上一级）
REPO_ROOT = Path(__file__).resolve().parents[2]
# 前端静态目录
FRONTEND_DIR = REPO_ROOT / "frontend"
# 数据目录（sessions.json 等），已 gitignore
DATA_DIR = REPO_ROOT / "data"
SESSIONS_FILE = DATA_DIR / "sessions.json"

# 终端输出缓冲上限（字节）。AI 增量获取基于该缓冲，超出后最旧内容被丢弃。
TERMINAL_BUF_LIMIT = 262144  # 256KB

DEFAULT_TERM_SIZE = (24, 80)  # (rows, cols)
