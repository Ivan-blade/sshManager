"""会话配置的持久化存储（data/sessions.json）。

注意：密码以明文存于本地 JSON，与 xshell 同类工具一致。生产化应加密。
"""
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Optional


class SessionStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text("utf-8"))
                if isinstance(data, list):
                    self._sessions = {s["id"]: s for s in data if isinstance(s, dict) and "id" in s}
            except (json.JSONDecodeError, OSError):
                self._sessions = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(list(self._sessions.values()), ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self.path)

    def list_all(self, query: str = "") -> list[dict]:
        """按 IP / 名称 同时过滤：query 的每个空白分隔 token 都必须是
        name/host/port 组合串的子串。空 query 返回全部。"""
        with self._lock:
            items = list(self._sessions.values())
        tokens = [t.lower() for t in query.strip().lower().split() if t]
        if tokens:
            out = []
            for s in items:
                hay = f"{s.get('name','')} {s.get('host','')} {s.get('port','')}".lower()
                if all(t in hay for t in tokens):
                    out.append(s)
            items = out
        return items

    def get(self, sid: str) -> Optional[dict]:
        with self._lock:
            return self._sessions.get(sid)

    def create(self, data: dict) -> dict:
        now = int(time.time())
        sid = uuid.uuid4().hex
        rec = {"id": sid, **data, "created_at": now, "updated_at": now}
        with self._lock:
            self._sessions[sid] = rec
            self._save()
        return rec

    def update(self, sid: str, patch: dict) -> Optional[dict]:
        with self._lock:
            rec = self._sessions.get(sid)
            if not rec:
                return None
            merged = {**rec, **{k: v for k, v in patch.items() if v is not None},
                      "updated_at": int(time.time())}
            self._sessions[sid] = merged
            self._save()
            return merged

    def delete(self, sid: str) -> bool:
        with self._lock:
            if sid not in self._sessions:
                return False
            del self._sessions[sid]
            self._save()
            return True

    def export(self) -> list[dict]:
        with self._lock:
            return list(self._sessions.values())

    def import_items(self, items: list[dict]) -> dict:
        """导入：已存在同 id 则跳过，否则生成新 id 加入。返回导入结果统计。"""
        now = int(time.time())
        added = skipped = 0
        with self._lock:
            for raw in items:
                if not isinstance(raw, dict) or not raw.get("name"):
                    continue
                if raw.get("id") in self._sessions:
                    skipped += 1
                    continue
                rec = {"id": uuid.uuid4().hex, **{k: v for k, v in raw.items() if k != "id"},
                       "created_at": now, "updated_at": now}
                self._sessions[rec["id"]] = rec
                added += 1
            self._save()
        return {"added": added, "skipped": skipped, "total": len(self._sessions)}
