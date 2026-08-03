<div align="center">

# sshManager

**AI-assisted SSH client — human & AI collaborate in one shared terminal**

[English](README.md) · [简体中文](README.zh-CN.md)

</div>

A **human-machine collaborative SSH session manager**: a human and an AI work on the **same terminal session**, from a browser or a desktop app. The AI can silently operate a connection in the background (run commands, search files, manage SFTP) — or inject commands into a shared terminal that the human sees live. It is an xshell-style terminal where an AI assistant can also type.

## Demo

**Background session restore** — closing a tab only detaches the page; the SSH connection keeps running in the background and keeps accumulating output. Reopen the app and bring it back with one click:

![Restoring a background SSH session](ssh_recover.gif)

Full-resolution video: [recover.mp4](recover.mp4)

## Key Features

- **Human–AI collaboration on one terminal** — human input (WebSocket) and AI injection (`write` API) share the same backend-owned pty; what the AI types appears live in the human's terminal, and its output enters the shared buffer.
- **AI dual-path execution**
  - *Independent path (default)* — non-interactive `exec` / recursive `find` on a separate connection; results returned directly; no concurrency; the human is not disturbed.
  - *Collaborative path* — `write` into a shared terminal the human sees, incremental `buffer` reads, and `status`-based idle detection before injecting.
- **AI capability discovery** — `GET /api/ai/capabilities` hands an AI agent a 39-entry capability registry plus a workflow map; `GET /api/ai/capabilities/{name}` gives per-endpoint params and call chains. The AI self-bootstraps — nothing is hardcoded.
- **Session & group management** — combined name/IP filtering, import/export (JSON file or clipboard), xshell-style collapsible group tree.
- **Multi-tab terminal** — each tab is an independent SSH connection; closing a tab keeps SSH running in the background, restorable anytime.
- **SFTP panel** — browse / drag-and-drop upload / download / edit / delete / recursive search, reusing the session's connection.
- **Quick commands** — grouped preset commands with one-click send (echo-only or auto-run), import/export, and an AI-triggerable run API.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend — xterm.js + native JS + Electron shell            │
│  session tree │ multi-tab terminal │ AI panel │ SFTP │ I/O   │
└───────┬──────────────────────────────┬───────────────────────┘
        │ HTTP (REST)                  │ WebSocket
        ▼                              ▼
┌──────────────────────────────────────────────────────────────┐
│  Backend — Python FastAPI (asyncio)                          │
│  session CRUD │ terminal WS │ AI dual-path │ SFTP │ quick    │
│                                                              │
│  SessionManager ── TerminalSession (per conn_id)             │
│     ring buffer · single write lock · subscriber fanout      │
│                          │                                   │
│  Transport abstraction:   SSH (asyncssh) │ Local (pty)       │
└───────┬──────────────────────────────┬───────────────────────┘
        ▼                              ▼
   remote SSH host             local pty shell (dev/verify)
```

### Key design decisions

**1. The Python backend owns the pty** — the frontend *and* the AI are both clients of the same pty. AI interference goes through backend APIs only, never frontend JS — so the Electron shell can later be dropped for a pure-browser form.

**2. How human & AI share one terminal (the mechanism)**

```
human xterm ──ws input──▶ backend ──write lock──▶ pty ──▶ remote shell
AI  write API ───────────▶ backend ──same lock──▶ pty         │
                                                             ▼
output read loop ◀──── pty ──▶ ring buffer (≤256 KB) ──▶ fanout to all WS subscribers
```

- **Single write lock** — input from every source (human WS, AI `write`) is serialized through one `asyncio.Lock` before reaching the pty, preventing byte interleaving during human–AI collaboration.
- **Incremental output buffer** — a bounded 256 KB ring buffer per connection. `GET /buffer?since=N` returns only the *new* output after offset `N` (`gap=true` when the offset fell out of the window). The AI passes back `total` as the next `since`, so it never re-pulls history — keeping context usage small.
- **Idle detection** — `GET /api/connections/{conn_id}/status` returns `idle` / `idle_ms` (no output for ≥ `TERMINAL_IDLE_THRESHOLD_MS`). The AI confirms `idle=true` before injecting, so a command never interleaves with a running one or a not-yet-printed prompt.

**3. Independent connection model + background keep-alive** — one session config (`sid`) can spawn many independent connections (`conn_id`); each tab / each AI connection is its own pty + buffer. Closing a WebSocket only *detaches*; the SSH connection keeps running, output keeps accumulating, and `GET /api/connections/background` lists every background connection across all sessions for one-click restore.

**4. AI dual-path execution**

| Path | Endpoint | Semantics | Concurrency |
|------|----------|-----------|-------------|
| Collaborative | `POST /api/connections/{conn_id}/write` | inject into a specific shared terminal; output enters that connection's buffer and is echoed to the human | serialized by write lock |
| Independent (default) | `POST /api/sessions/{sid}/exec` · `POST /api/sessions/{sid}/find` | non-interactive, results returned directly on a separate connection | none |

**5. Transport abstraction** — a unified `Transport` interface (`connect / close / exec / create_interactive`). `SSHTransport` uses asyncssh (`conn.run` for exec; `create_process` + `change_terminal_size` for interactive pty). `LocalTransport` uses `pty.fork()` + `loop.add_reader` with a non-blocking master for development/verification. The terminal WS, AI execution layer, and SFTP never know whether the peer is SSH or local.

**6. AI capability discovery (self-bootstrap)** — the capability registry drives the whole AI integration. Each entry exposes `name / method / path / summary / params / returns / example / chain`; body schemas are derived from the same Pydantic models that validate requests, and `chain` describes how to orchestrate multi-step workflows (things OpenAPI can't express). Workflow: `GET /capabilities` (what can I do?) → `GET /capabilities/{name}` (how do I call it?) → call the REST endpoint.

**7. Storage** — plain JSON files (`data/sessions.json`, `data/groups.json`, `data/quick.json`) with atomic writes (tmp + `replace`). Multi-token filtering matches every whitespace-separated token against `name + host + port`.

## AI integration surface

The backend exposes an AI-friendly REST surface (no UI needed). A minimal Python client:

```python
import json, urllib.request

BASE = "http://127.0.0.1:8747"
def api(p, m="GET", b=None):
    req = urllib.request.Request(BASE + p, method=m,
        data=json.dumps(b).encode() if b else None,
        headers={"Content-Type": "application/json"} if b else {})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

# 1. discover capabilities
print([c["name"] for c in api("/api/ai/capabilities")["capabilities"]])

# 2. find the target session
sid = api("/api/sessions?q=prod")[0]["id"]

# 3. independent path: run a command directly (default)
r = api(f"/api/sessions/{sid}/exec", "POST", {"command": "uptime", "timeout": 20})
print(r["stdout"])

# 4. collaborative path: connect → inject → read new output incrementally
conn = api(f"/api/sessions/{sid}/connect", "POST")["conn_id"]
api(f"/api/connections/{conn}/write", "POST", {"data": "echo hello-from-AI\n"})
buf = api(f"/api/connections/{conn}/buffer?since=0")
print(buf["data"][-100:])
api(f"/api/connections/{conn}/disconnect", "POST")
```

Full guide: [docs/usage.md](docs/usage.md) · API surface: [docs/features.md](docs/features.md)

## Tech Stack

| Layer    | Tech                                     |
|----------|------------------------------------------|
| Terminal | xterm.js · @xterm/addon-fit (local, offline) |
| Frontend | Native JS · WebSocket · Electron shell   |
| Backend  | Python FastAPI · asyncio · asyncssh      |
| Storage  | JSON files (sessions / groups / quick)   |
| AI       | Capability discovery API · dual-path execution (`/api/ai`, `/api/connections/*`) |

## Project Layout

```
backend/                  # Python FastAPI backend
  app/main.py             # app assembly · /api/health · static hosting · lifespan shutdown
  app/sessions.py         # TerminalSession (ring buffer · write lock · fanout) + SessionManager
  app/transports.py       # Transport abstraction (SSH asyncssh / Local pty)
  app/capabilities.py     # AI capability registry (overview + per-capability detail)
  app/routes/             # sessions · groups · terminal(WS) · ai · sftp · quick · transfer
  tests/test_smoke.py     # smoke tests
frontend/                 # static frontend (served by the backend)
  js/                     # core · tree · terminal(WS) · ctxmenu · modals · bg · quick · sftp
  vendor/                 # xterm.js + addon-fit (local, offline-ready)
  electron/main.js        # Electron shell: spawn backend → wait /api/health → load UI
docs/                     # architecture · features · implementation · usage
data/                     # sessions / groups / quick JSON (gitignored)
```

## Quick Start

### Install dependencies

```bash
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install
```

### Browser

```bash
cd backend && .venv/bin/python run.py
# → http://127.0.0.1:8747
```

### Desktop (Electron)

```bash
cd frontend && npm start
```

### Tests

```bash
cd backend && .venv/bin/python -m pytest tests/ -v
```

## Packaging (macOS `.app` / `.dmg`)

PyInstaller freezes the backend (frontend resources included) into an onedir binary; electron-builder wraps it into `.app` / `.dmg`. On the `feat/packaging` branch:

```bash
git checkout feat/packaging
cd backend && .venv/bin/pip install "pyinstaller>=6.21"
cd ../frontend && npm install
npm run package:backend && CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --mac
```

In the packaged app the backend runs from `Resources/backend/sshmgr-backend`, picks a free port automatically, and stores user data in the OS app-data directory (`~/Library/Application Support/sshManager/data` on macOS) — never inside the bundle. Build artifacts (`frontend/dist/*.dmg`, `*.app`) are gitignored. Not merged to `main` yet.

## Demo Assets

| File             | Purpose                                                              |
|------------------|----------------------------------------------------------------------|
| `ssh_recover.gif`| Animated demo of restoring a background SSH session with one click   |
| `recover.mp4`    | Full-resolution video of the same flow                               |

## Documentation

- [Usage Guide — Human & AI](docs/usage.md)
- [Architecture](docs/architecture.md)
- [Features](docs/features.md)
- [Implementation](docs/implementation.md)

## Roadmap

- [ ] AI background WebSocket echo → "work together" mode (AI streams progress into the browser)
- [ ] Drag-and-drop sorting for sessions / groups / quick commands
- [ ] Encrypted credential storage

## Tested Against

- pytest suite (17 tests) — sessions CRUD / filtering / import-export / exec / find / terminal WS + AI write / incremental buffer / background keep-alive / SFTP loopback, all on the local transport
- Browser E2E · Electron smoke test
- Real SSH host (CentOS 7) — connect / exec / find / SFTP / interactive terminal all verified

## License

Private project. Contact the owner for licensing questions.
