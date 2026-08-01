"""导入 / 导出（支持分组 + 会话，按选择筛选，文件/剪贴板）。"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..deps import get_store
from ..store import SessionStore

router = APIRouter(tags=["transfer"])
StoreDep = Annotated[SessionStore, Depends(get_store)]


class ExportRequest(BaseModel):
    group_ids: list[str] = []
    session_ids: list[str] = []


class ImportRequest(BaseModel):
    groups: list[dict] = []
    sessions: list[dict] = []


@router.post("/api/export")
def export_data(body: ExportRequest, store: StoreDep) -> dict:
    """按选择导出分组与会话；空选择 = 全部。返回 {groups, sessions}。"""
    groups = store.list_groups()
    sessions = store.export()
    if body.group_ids:
        groups = [g for g in groups if g["id"] in body.group_ids]
    if body.session_ids:
        sessions = [s for s in sessions if s["id"] in body.session_ids]
    return {"groups": groups, "sessions": sessions}


@router.post("/api/import")
def import_data(body: ImportRequest, store: StoreDep) -> dict:
    """统一导入 {groups, sessions}；分组按名称去重复用，会话重写 group_id。"""
    return store.import_bundle(body.groups, body.sessions)
