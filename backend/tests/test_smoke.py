"""后端核心链路冒烟测试。

运行：cd backend && .venv/bin/python -m pytest tests/ -v

SSH 传输在无凭据环境无法验证；本套件聚焦 local 传输（与 SSH 共用同一套
exec / 交互通道 / buffer / find / SFTP 代码路径）。
"""
import json
import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def local_session(client):
    r = client.post("/api/sessions", json={
        "name": f"smoke-local-{int(time.time()*1000)}", "transport": "local", "host": "127.0.0.1",
    })
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    yield sid
    client.delete(f"/api/sessions/{sid}")


def test_session_crud_and_filter(client):
    name = f"smoke-{int(time.time()*1000)}"
    r = client.post("/api/sessions", json={
        "name": name, "host": "10.1.2.3", "port": 22, "username": "admin",
        "auth_type": "password", "password": "secret",
    })
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    # 按 IP 过滤
    assert any(s["id"] == sid for s in client.get("/api/sessions", params={"q": "10.1.2.3"}).json())
    # 按名称过滤
    assert any(s["id"] == sid for s in client.get("/api/sessions", params={"q": name}).json())
    # 密码绝不回传
    assert "password" not in client.get(f"/api/sessions/{sid}").json()
    # 更新
    assert client.patch(f"/api/sessions/{sid}", json={"username": "root2"}).json()["username"] == "root2"
    # 导入 / 导出
    exp = client.get("/api/sessions/export").json()
    assert any(s["id"] == sid for s in exp)
    imp_name = f"imp-{int(time.time()*1000)}"
    r = client.post("/api/sessions/import", json={"sessions": [{"name": imp_name, "host": "1.1.1.1"}]})
    assert r.json()["added"] >= 1
    # 删除（含测试导入的会话，避免污染持久化文件）
    for s in client.get("/api/sessions", params={"q": imp_name}).json():
        client.delete(f"/api/sessions/{s['id']}")
    assert client.delete(f"/api/sessions/{sid}").json()["ok"] is True


def test_exec_local(client, local_session):
    r = client.post(f"/api/sessions/{local_session}/exec", json={"command": "echo hi; exit 3"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["stdout"].strip() == "hi"
    assert d["exit_code"] == 3


def test_find_local(client, local_session):
    r = client.post(f"/api/sessions/{local_session}/find", json={
        "path": ".", "pattern": "*.py", "max_depth": 1, "ftype": "f",
    })
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 1


def test_terminal_ws_and_ai_write(client, local_session):
    with client.websocket_connect(f"/ws/terminal/{local_session}") as ws:
        # 初始：读到 buffer 尾 + status（status 带 conn_id）
        seen = {}
        while not ({"buffer", "status"} <= seen.keys()):
            m = ws.receive_json()
            seen[m["type"]] = m
        assert "buffer" in seen and "status" in seen
        conn_id = seen["status"].get("conn_id")
        assert conn_id, "ws 应返回 conn_id"

        # 人的输入 → 终端回显
        ws.send_json({"type": "input", "data": "echo WS_TEST_OK\n"})
        got = ""
        while "WS_TEST_OK" not in got:
            got += ws.receive_json().get("data", "")
        assert "WS_TEST_OK" in got

        # resize
        ws.send_json({"type": "resize", "cols": 100, "rows": 30})

        # AI 协同路径：向该连接 write 注入
        r = client.post(f"/api/connections/{conn_id}/write", json={"data": "echo AI_WRITE_OK\n"})
        assert r.status_code == 200, r.text
        time.sleep(0.8)

        # 增量 buffer
        b = client.get(f"/api/connections/{conn_id}/buffer", params={"since": 0}).json()
        assert "AI_WRITE_OK" in b["data"] and b["gap"] is False
        total = b["total"]
        b2 = client.get(f"/api/connections/{conn_id}/buffer", params={"since": total - 5}).json()
        assert b2["total"] == total and b2["gap"] is False
        b3 = client.get(f"/api/connections/{conn_id}/buffer", params={"since": 10**9}).json()
        assert b3["gap"] is True

    # ws 关闭后该连接应已释放
    time.sleep(0.3)
    st = client.get(f"/api/sessions/{local_session}/status").json()
    assert st["active_conns"] == []


def test_session_id_unique_per_host(client):
    """同一 host 建多个会话，id 必须互不相同（uuid4）。"""
    host = "10.9.9.9"
    ids = []
    for i in range(5):
        r = client.post("/api/sessions", json={"name": f"dup-{i}", "host": host, "username": "root"})
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
    assert len(ids) == len(set(ids)), "会话 id 出现重复"
    for sid in ids:
        client.delete(f"/api/sessions/{sid}")


def test_groups_crud_and_move(client):
    """分组 CRUD + 会话移入/移出 + 删除分组回落根层级。失败也清理。"""
    gid = sid = None
    try:
        g = client.post("/api/groups", json={"name": f"grp-{int(time.time()*1000)}"})
        assert g.status_code == 200, g.text
        gid = g.json()["id"]

        s = client.post("/api/sessions", json={"name": "in-group", "host": "1.2.3.4", "group_id": gid})
        assert s.status_code == 200, s.text
        sid = s.json()["id"]
        assert s.json()["group_id"] == gid

        # 列表包含分组
        assert any(x["id"] == gid for x in client.get("/api/groups").json())

        # 移出分组（group_id 置空）
        s2 = client.patch(f"/api/sessions/{sid}", json={"group_id": None})
        assert s2.json().get("group_id") is None

        # 移回分组
        s3 = client.patch(f"/api/sessions/{sid}", json={"group_id": gid})
        assert s3.json().get("group_id") == gid

        # 重命名
        assert client.patch(f"/api/groups/{gid}", json={"name": "renamed"}).json()["name"] == "renamed"

        # 删除分组 → 组内会话回落根层级
        assert client.delete(f"/api/groups/{gid}").json()["ok"] is True
        gid = None
        assert client.get(f"/api/sessions/{sid}").json().get("group_id") is None
    finally:
        if sid:
            client.delete(f"/api/sessions/{sid}")
        if gid:
            client.delete(f"/api/groups/{gid}")


def test_independent_connections(client, local_session):
    """同一会话可建多个独立连接：conn_id 不同、缓冲互不共享。"""
    r1 = client.post(f"/api/sessions/{local_session}/connect")
    r2 = client.post(f"/api/sessions/{local_session}/connect")
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    c1, c2 = r1.json()["conn_id"], r2.json()["conn_id"]
    assert c1 != c2

    # AI write 到 conn1 → 只进 conn1 的缓冲
    assert client.post(f"/api/connections/{c1}/write", json={"data": "echo ONLY_C1\n"}).status_code == 200
    time.sleep(0.8)
    b1 = client.get(f"/api/connections/{c1}/buffer", params={"since": 0}).json()
    b2 = client.get(f"/api/connections/{c2}/buffer", params={"since": 0}).json()
    assert "ONLY_C1" in b1["data"]
    assert "ONLY_C1" not in b2["data"]

    # 状态返回活跃连接数
    st = client.get(f"/api/sessions/{local_session}/status").json()
    assert c1 in st["active_conns"] and c2 in st["active_conns"]

    # 清理
    client.post(f"/api/connections/{c1}/disconnect")
    client.post(f"/api/connections/{c2}/disconnect")


def test_ai_capabilities(client):
    """AI 能力发现：概述 + 详情 + 未知 404。"""
    o = client.get("/api/ai/capabilities").json()
    assert o["count"] >= 10
    names = {c["name"] for c in o["capabilities"]}
    assert {"list_sessions", "exec_command", "write_terminal", "find_files", "read_buffer"} <= names

    d = client.get("/api/ai/capabilities/exec_command").json()
    assert d["method"] == "POST"
    body = next(p for p in d["params"] if p["in"] == "body")
    assert "command" in body["schema"]["properties"]
    assert "timeout" in body["schema"]["properties"]

    assert client.get("/api/ai/capabilities/nope").status_code == 404


def test_sftp_local(client, local_session):
    target = tempfile.mkdtemp()
    payload = b"sftp-test-content"
    # 上传
    r = client.post(
        f"/api/sessions/{local_session}/sftp/upload",
        files={"file": ("up.txt", payload, "text/plain")},
        data={"target_dir": target},
    )
    assert r.status_code == 200, r.text
    # 列表
    entries = client.get(f"/api/sessions/{local_session}/sftp/ls", params={"path": target}).json()
    assert any(e["name"] == "up.txt" for e in entries)
    # 下载回环
    r = client.get(f"/api/sessions/{local_session}/sftp/download",
                   params={"path": os.path.join(target, "up.txt")})
    assert r.status_code == 200 and r.content == payload
