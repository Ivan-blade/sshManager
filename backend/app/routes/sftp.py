"""SFTP：文件浏览 / 上传 / 下载。

SSH 会话复用共享连接（`复用 ssh 连接`）；local 传输映射到本机文件系统，便于开发验证。
"""
import os
import stat
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..deps import get_manager, get_store
from ..sessions import SessionManager
from ..store import SessionStore

router = APIRouter(prefix="/api/sessions/{sid}/sftp", tags=["sftp"])
StoreDep = Annotated[SessionStore, Depends(get_store)]
ManagerDep = Annotated[SessionManager, Depends(get_manager)]

CHUNK = 65536


def _require(store: SessionStore, sid: str) -> dict:
    cfg = store.get(sid)
    if not cfg:
        raise HTTPException(404, "session not found")
    return cfg


async def _connected(manager: SessionManager, store: SessionStore, sid: str):
    """确保会话已连接，返回 (cfg, TerminalSession)。local 会返回 ts 以便走文件系统。"""
    cfg = _require(store, sid)
    ts = manager.get(sid)
    if not ts.connected:
        try:
            await ts.connect()
        except Exception as exc:
            raise HTTPException(502, f"connect failed: {exc}")
    return cfg, ts


def _local_entry(path: Path) -> dict:
    st = path.stat()
    return {"name": path.name, "path": str(path), "size": st.st_size,
            "mtime": int(st.st_mtime), "is_dir": path.is_dir()}


@router.get("/ls")
async def sftp_ls(sid: str, store: StoreDep, manager: ManagerDep,
                  path: str = ".") -> list[dict]:
    cfg, ts = await _connected(manager, store, sid)
    if cfg["transport"] == "local":
        base = Path(path).expanduser()
        if not base.is_dir():
            raise HTTPException(404, "path not a directory")
        entries = []
        for child in sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            entries.append(_local_entry(child))
        return entries

    conn = ts.transport.conn  # type: ignore[attr-defined]
    sftp = await conn.start_sftp_client()
    try:
        out = []
        async for name in sftp.scandir(path):
            a = name.attrs
            mode = a.permissions if a.permissions is not None else 0
            out.append({"name": name.filename, "path": os.path.join(path, name.filename),
                        "size": a.size or 0, "mtime": a.mtime or 0,
                        "is_dir": bool(stat.S_ISDIR(mode))})
        out.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        return out
    except Exception as exc:
        raise HTTPException(502, f"sftp ls failed: {exc}")
    finally:
        sftp.exit()
        await sftp.wait_closed()


@router.get("/download")
async def sftp_download(sid: str, store: StoreDep, manager: ManagerDep,
                        path: str) -> StreamingResponse:
    cfg, ts = await _connected(manager, store, sid)
    fname = os.path.basename(path.rstrip("/")) or "download"

    if cfg["transport"] == "local":
        p = Path(path).expanduser()
        if not p.is_file():
            raise HTTPException(404, "not a file")

        def iter_local():
            with open(p, "rb") as f:
                while chunk := f.read(CHUNK):
                    yield chunk
        return StreamingResponse(iter_local(), media_type="application/octet-stream",
                                 headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    conn = ts.transport.conn  # type: ignore[attr-defined]
    sftp = await conn.start_sftp_client()

    async def iter_sftp():
        try:
            f = await sftp.open(path, "rb")
            try:
                while True:
                    chunk = await f.read(CHUNK)
                    if not chunk:
                        break
                    yield chunk
            finally:
                await f.close()
        finally:
            sftp.exit()
            await sftp.wait_closed()

    return StreamingResponse(iter_sftp(), media_type="application/octet-stream",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/upload")
async def sftp_upload(sid: str, store: StoreDep, manager: ManagerDep,
                      target_dir: str = Form("."),
                      target_name: str = Form(""),
                      file: UploadFile = File(...)) -> dict:
    cfg, ts = await _connected(manager, store, sid)
    name = target_name or file.filename or "upload"

    if cfg["transport"] == "local":
        dest = Path(target_dir).expanduser() / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(dest, "wb") as out:
                while chunk := await file.read(CHUNK):
                    out.write(chunk)
        except OSError as exc:
            raise HTTPException(502, f"upload failed: {exc}")
        return {"ok": True, "path": str(dest), "size": dest.stat().st_size}

    conn = ts.transport.conn  # type: ignore[attr-defined]
    sftp = await conn.start_sftp_client()
    try:
        dest = os.path.join(target_dir, name)
        f = await sftp.open(dest, "wb")
        try:
            while chunk := await file.read(CHUNK):
                await f.write(chunk)
        finally:
            await f.close()
        attrs = await sftp.stat(dest)
        return {"ok": True, "path": dest, "size": attrs.size}
    except Exception as exc:
        raise HTTPException(502, f"sftp upload failed: {exc}")
    finally:
        sftp.exit()
        await sftp.wait_closed()
