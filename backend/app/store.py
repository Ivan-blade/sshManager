"""会话与分组的持久化存储（data/sessions.json、data/groups.json）。

注意：密码以明文存于本地 JSON，与 xshell 同类工具一致。生产化应加密。
"""
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Optional


class SessionStore:
    def __init__(self, path: Path, groups_path: Optional[Path] = None):
        self.path = path
        self.groups_path = groups_path or (path.parent / "groups.json")
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._groups: dict[str, dict] = {}
        self._load()
        self._load_groups()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text("utf-8"))
                if isinstance(data, list):
                    self._sessions = {s["id"]: s for s in data if isinstance(s, dict) and "id" in s}
            except (json.JSONDecodeError, OSError):
                self._sessions = {}

    def _load_groups(self) -> None:
        if self.groups_path.exists():
            try:
                data = json.loads(self.groups_path.read_text("utf-8"))
                if isinstance(data, list):
                    self._groups = {g["id"]: g for g in data if isinstance(g, dict) and "id" in g}
            except (json.JSONDecodeError, OSError):
                self._groups = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(list(self._sessions.values()), ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self.path)

    def _save_groups(self) -> None:
        self.groups_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.groups_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(list(self._groups.values()), ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self.groups_path)

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
        """patch 由路由层控制：已过滤 None，仅显式置空的字段（如 group_id）会带 None。"""
        with self._lock:
            rec = self._sessions.get(sid)
            if not rec:
                return None
            merged = {**rec, **patch, "updated_at": int(time.time())}
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

    def import_bundle(self, groups: list[dict], sessions: list[dict]) -> dict:
        """统一导入：分组按名称去重/复用，会话重写 group_id 映射到实际分组 id。"""
        gid_map: dict[str, str] = {}
        group_added = 0
        for g in groups:
            if not isinstance(g, dict) or not g.get("name"):
                continue
            existing = next(
                (x for x in self.list_groups() if (x.get("name") or "").lower() == g["name"].lower()),
                None,
            )
            if existing:
                gid_map[g.get("id")] = existing["id"]
            else:
                ng = self.create_group(g["name"])
                gid_map[g.get("id")] = ng["id"]
                group_added += 1
        added = skipped = 0
        now = int(time.time())
        with self._lock:
            for raw in sessions:
                if not isinstance(raw, dict) or not raw.get("name"):
                    continue
                if raw.get("id") in self._sessions:
                    skipped += 1
                    continue
                rec = {"id": uuid.uuid4().hex,
                       **{k: v for k, v in raw.items() if k != "id"},
                       "created_at": now, "updated_at": now}
                old_gid = raw.get("group_id")
                if old_gid and old_gid in gid_map:
                    rec["group_id"] = gid_map[old_gid]
                self._sessions[rec["id"]] = rec
                added += 1
            self._save()
        return {"groups_added": group_added, "added": added, "skipped": skipped,
                "total": len(self._sessions)}

    # ---------------- 分组 ----------------
    def list_groups(self) -> list[dict]:
        with self._lock:
            return sorted(self._groups.values(), key=lambda g: (g.get("name") or "").lower())

    def get_group(self, gid: str) -> Optional[dict]:
        with self._lock:
            return self._groups.get(gid)

    def create_group(self, name: str) -> dict:
        now = int(time.time())
        gid = uuid.uuid4().hex
        rec = {"id": gid, "name": name, "created_at": now, "updated_at": now}
        with self._lock:
            self._groups[gid] = rec
            self._save_groups()
        return rec

    def rename_group(self, gid: str, name: str) -> Optional[dict]:
        with self._lock:
            rec = self._groups.get(gid)
            if not rec:
                return None
            rec["name"] = name
            rec["updated_at"] = int(time.time())
            self._save_groups()
            return rec

    def delete_group(self, gid: str) -> bool:
        """删除分组；组内会话回到根层级（group_id 置空）。"""
        with self._lock:
            if gid not in self._groups:
                return False
            del self._groups[gid]
            changed = False
            for s in self._sessions.values():
                if s.get("group_id") == gid:
                    s["group_id"] = None
                    s["updated_at"] = int(time.time())
                    changed = True
            self._save_groups()
            if changed:
                self._save()
            return True
