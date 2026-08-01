"""SFTP：文件浏览 / 上传 / 下载。

每个操作使用独立传输（SSH 每次建连接；local 映射本机文件系统，便于开发验证）。
"""
import os
import stat
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..deps import get_store
from ..store import SessionStore
from ..transports import Transport, build_transport

router = APIRouter(prefix="/api/sessions/{sid}/sftp", tags=["sftp"])
StoreDep = Annotated[SessionStore, Depends(get_store)]

CHUNK = 65536


def _require(store: SessionStore, sid: str) -> dict:
    cfg = store.get(sid)
    if not cfg:
        raise HTTPException(404, "session not found")
    return cfg


async def _ssh_transport(store: SessionStore, sid: str):
    """local 返回 (cfg, None)；SSH 返回 (cfg, 已连接的 transport)。"""
    cfg = _require(store, sid)
    if cfg["transport"] == "local":
        return cfg, None
    transport = build_transport(cfg)
    try:
        await transport.connect()
    except Exception as exc:
        raise HTTPException(502, f"connect failed: {exc}")
    return cfg, transport


def _local_entry(path: Path) -> dict:
    st = path.stat()
    return {"name": path.name, "path": str(path), "size": st.st_size,
            "mtime": int(st.st_mtime), "is_dir": path.is_dir()}


@router.get("/ls")
async def sftp_ls(sid: str, store: StoreDep, path: str = ".") -> list[dict]:
    cfg, transport = await _ssh_transport(store, sid)

    if cfg["transport"] == "local":
        base = Path(path).expanduser()
        if not base.is_dir():
            raise HTTPException(404, "path not a directory")
        return [_local_entry(p) for p in sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))]

    sftp = await transport.conn.start_sftp_client()  # type: ignore[attr-defined]
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
        await transport.close()


@router.get("/download")
async def sftp_download(sid: str, store: StoreDep, path: str) -> StreamingResponse:
    cfg, transport = await _ssh_transport(store, sid)
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

    sftp = await transport.conn.start_sftp_client()  # type: ignore[attr-defined]

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
            await transport.close()

    return StreamingResponse(iter_sftp(), media_type="application/octet-stream",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/upload")
async def sftp_upload(sid: str, store: StoreDep,
                      target_dir: str = Form("."),
                      target_name: str = Form(""),
                      file: UploadFile = File(...)) -> dict:
    cfg, transport = await _ssh_transport(store, sid)
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

    sftp = await transport.conn.start_sftp_client()  # type: ignore[attr-defined]
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
        await transport.close()
