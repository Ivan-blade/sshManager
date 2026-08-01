"""快捷命令：分组 + 命令 CRUD + 导入导出。"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import get_quick_store
from ..models import (QuickCommandCreate, QuickCommandUpdate,
                      QuickGroupCreate, QuickGroupUpdate)
from ..quickstore import QuickStore

router = APIRouter(prefix="/api/quick", tags=["quick"])
QuickDep = Annotated[QuickStore, Depends(get_quick_store)]


class QuickExportRequest(BaseModel):
    group_ids: list[str] = []
    command_ids: list[str] = []


class QuickImportRequest(BaseModel):
    groups: list[dict] = []
    commands: list[dict] = []


@router.post("/export")
def export_bundle(body: QuickExportRequest, store: QuickDep) -> dict:
    """按选择导出分组与命令；空选择=全部。"""
    return store.export_bundle(body.group_ids, body.command_ids)


@router.post("/import")
def import_bundle(body: QuickImportRequest, store: QuickDep) -> dict:
    """统一导入 {groups, commands}；分组按名称去重复用，命令重写 group_id。"""
    return store.import_bundle(body.groups, body.commands)


# ---- 分组 ----
@router.get("/groups")
def list_groups(store: QuickDep) -> list[dict]:
    return store.list_groups()


@router.post("/groups")
def create_group(body: QuickGroupCreate, store: QuickDep) -> dict:
    return store.create_group(body.name)


@router.patch("/groups/{gid}")
def rename_group(gid: str, body: QuickGroupUpdate, store: QuickDep) -> dict:
    g = store.rename_group(gid, body.name)
    if not g:
        raise HTTPException(404, "group not found")
    return g


@router.delete("/groups/{gid}")
def delete_group(gid: str, store: QuickDep) -> dict:
    if not store.delete_group(gid):
        raise HTTPException(404, "group not found")
    return {"ok": True}


# ---- 命令 ----
@router.get("/commands")
def list_commands(store: QuickDep) -> list[dict]:
    return store.list_commands()


@router.post("/commands")
def create_command(body: QuickCommandCreate, store: QuickDep) -> dict:
    return store.create_command(body.group_id, body.name, body.command)


@router.patch("/commands/{cid}")
def update_command(cid: str, body: QuickCommandUpdate, store: QuickDep) -> dict:
    patch = body.model_dump(exclude_none=True)
    if "group_id" in body.model_fields_set:
        patch["group_id"] = body.group_id  # 显式 null = 移到未分组
    c = store.update_command(cid, patch)
    if not c:
        raise HTTPException(404, "command not found")
    return c


@router.delete("/commands/{cid}")
def delete_command(cid: str, store: QuickDep) -> dict:
    if not store.delete_command(cid):
        raise HTTPException(404, "command not found")
    return {"ok": True}
