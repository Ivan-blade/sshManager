"""快捷命令存储（data/quick.json）：分组 + 命令 CRUD。"""
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Optional


class QuickStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._groups: dict[str, dict] = {}
        self._commands: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text("utf-8"))
                self._groups = {g["id"]: g for g in data.get("groups", [])
                                if isinstance(g, dict) and "id" in g}
                self._commands = {c["id"]: c for c in data.get("commands", [])
                                  if isinstance(c, dict) and "id" in c}
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"groups": list(self._groups.values()),
                                   "commands": list(self._commands.values())},
                                  ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self.path)

    # ---------------- 分组 ----------------
    def list_groups(self) -> list[dict]:
        with self._lock:
            return sorted(self._groups.values(),
                          key=lambda g: (g.get("sort", 0), (g.get("name") or "").lower()))

    def create_group(self, name: str) -> dict:
        gid = uuid.uuid4().hex
        rec = {"id": gid, "name": name, "sort": len(self._groups), "created_at": int(time.time())}
        with self._lock:
            self._groups[gid] = rec
            self._save()
        return rec

    def rename_group(self, gid: str, name: str) -> Optional[dict]:
        with self._lock:
            g = self._groups.get(gid)
            if not g:
                return None
            g["name"] = name
            self._save()
            return g

    def delete_group(self, gid: str) -> bool:
        """删除分组；组内命令回到未分组。"""
        with self._lock:
            if gid not in self._groups:
                return False
            del self._groups[gid]
            for c in self._commands.values():
                if c.get("group_id") == gid:
                    c["group_id"] = None
            self._save()
            return True

    # ---------------- 命令 ----------------
    def list_commands(self) -> list[dict]:
        with self._lock:
            return sorted(self._commands.values(),
                          key=lambda c: (c.get("sort", 0), (c.get("name") or "").lower()))

    def create_command(self, group_id: Optional[str], name: str, command: str) -> dict:
        cid = uuid.uuid4().hex
        rec = {"id": cid, "group_id": group_id, "name": name, "command": command,
               "sort": len(self._commands), "created_at": int(time.time())}
        with self._lock:
            self._commands[cid] = rec
            self._save()
        return rec

    def update_command(self, cid: str, patch: dict) -> Optional[dict]:
        """patch 由路由层控制（已处理 group_id 显式置空）。"""
        with self._lock:
            c = self._commands.get(cid)
            if not c:
                return None
            c.update(patch)
            self._save()
            return c

    def delete_command(self, cid: str) -> bool:
        with self._lock:
            if cid not in self._commands:
                return False
            del self._commands[cid]
            self._save()
            return True
