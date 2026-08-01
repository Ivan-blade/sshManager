"""FastAPI 依赖注入：应用级单例。"""
from functools import lru_cache

from . import config
from .quickstore import QuickStore
from .sessions import SessionManager
from .store import SessionStore


@lru_cache
def get_store() -> SessionStore:
    return SessionStore(config.SESSIONS_FILE, config.GROUPS_FILE)


@lru_cache
def get_quick_store() -> QuickStore:
    return QuickStore(config.QUICK_FILE)


@lru_cache
def get_manager() -> SessionManager:
    return SessionManager(get_store())
