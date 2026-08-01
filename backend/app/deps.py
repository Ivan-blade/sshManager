"""FastAPI 依赖注入：应用级单例。"""
from functools import lru_cache

from . import config
from .sessions import SessionManager
from .store import SessionStore


@lru_cache
def get_store() -> SessionStore:
    return SessionStore(config.SESSIONS_FILE)


@lru_cache
def get_manager() -> SessionManager:
    return SessionManager(get_store())
