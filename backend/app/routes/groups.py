"""会话分组 CRUD。删除分组时组内会话回到根层级。"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_store
from ..models import GroupCreate, GroupUpdate
from ..store import SessionStore

router = APIRouter(prefix="/api/groups", tags=["groups"])
StoreDep = Annotated[SessionStore, Depends(get_store)]


@router.get("")
def list_groups(store: StoreDep) -> list[dict]:
    return store.list_groups()


@router.post("")
def create_group(body: GroupCreate, store: StoreDep) -> dict:
    return store.create_group(body.name)


@router.patch("/{gid}")
def rename_group(gid: str, body: GroupUpdate, store: StoreDep) -> dict:
    g = store.rename_group(gid, body.name)
    if not g:
        raise HTTPException(404, "group not found")
    return g


@router.delete("/{gid}")
def delete_group(gid: str, store: StoreDep) -> dict:
    if not store.delete_group(gid):
        raise HTTPException(404, "group not found")
    return {"ok": True}
