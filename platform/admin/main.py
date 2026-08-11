import datetime
import json
import logging
import os
import shutil
import sqlite3 as _sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import psutil
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import caddy as caddymgr
from db import DB_PATH, get_db, init_db, next_agent_port

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from health import health_payload

START_TIME = time.time()
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_ws_clients: list[WebSocket] = []


async def _broadcast(msg: dict):
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Platform Admin", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    deps = {}
    async with httpx.AsyncClient(timeout=2) as client:
        for name, url in [
            ("ollama", f"{OLLAMA}/api/tags"),
            ("chromadb", "http://localhost:8020/api/v2/collections"),
        ]:
            try:
                await client.get(url)
                deps[name] = "ok"
            except Exception:
                deps[name] = "down"
    return health_payload(START_TIME, "0.1.0", dependencies=deps)


# ── Platform events ───────────────────────────────────────────────────────────

@app.post("/internal/event")
async def internal_event(body: dict, db=Depends(get_db)):
    try:
        db.execute(
            "INSERT INTO platform_events (service, event_type, message, metadata) VALUES (?,?,?,?)",
            (body.get("service", "unknown"), body.get("event_type", "info"),
             body.get("message", ""), json.dumps(body.get("metadata", {}))),
        )
        await _broadcast(body)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/platform-events")
def platform_events_list(limit: int = 50, db=Depends(get_db)):
    try:
        rows = db.execute(
            "SELECT * FROM platform_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(500, str(e))


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats")
def stats():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    temps = _temperatures()
    gpu = _gpu_stats()
    return {
        "cpu_percent": cpu,
        "memory_used_gb": round(mem.used / 1e9, 1),
        "memory_total_gb": round(mem.total / 1e9, 1),
        "memory_percent": mem.percent,
        "temperature_c": temps,
        "gpu": gpu,
    }


def _temperatures() -> dict | None:
    try:
        sensors = psutil.sensors_temperatures()
        if not sensors:
            return None
        result = {}
        for name, entries in sensors.items():
            result[name] = [{"label": e.label or name, "current": e.current} for e in entries]
        return result
    except Exception:
        return None


def _gpu_stats() -> dict | None:
    try:
        r = subprocess.run(["rocm-smi", "--json"], capture_output=True, text=True, timeout=5)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except Exception:
        return None


# ── Service health check ──────────────────────────────────────────────────────

@app.get("/health-check")
async def health_check_all(db=Depends(get_db)):
    registered = [dict(r) for r in db.execute("SELECT * FROM apps ORDER BY name").fetchall()]
    results = []
    async with httpx.AsyncClient(timeout=3) as client:
        for svc in registered:
            if svc["backend_port"]:
                try:
                    r = await client.get(f"http://localhost:{svc['backend_port']}/health")
                    results.append({**svc, "health": r.json()})
                except Exception:
                    results.append({**svc, "health": {"status": "down"}})
            else:
                results.append({**svc, "health": None})
    return results


# ── Apps ──────────────────────────────────────────────────────────────────────

@app.get("/apps")
def list_apps(db=Depends(get_db)):
    try:
        return [dict(r) for r in db.execute("SELECT * FROM apps ORDER BY name").fetchall()]
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/apps", status_code=201)
def register_app(body: dict, db=Depends(get_db)):
    try:
        db.execute(
            "INSERT INTO apps (name, description, route, port, backend_port) VALUES (?,?,?,?,?)",
            (body["name"], body.get("description"), body["route"], body.get("port"), body["backend_port"]),
        )
    except Exception as e:
        raise HTTPException(400, str(e))
    try:
        caddymgr.add_route(body["route"], body["backend_port"])
    except Exception as e:
        log.warning("Caddy update skipped: %s", e)
    return {"status": "ok"}


@app.delete("/apps/{app_id}")
def remove_app(app_id: int, db=Depends(get_db)):
    row = db.execute("SELECT route FROM apps WHERE id=?", (app_id,)).fetchone()
    if not row:
        raise HTTPException(404, "App not found")
    db.execute("DELETE FROM apps WHERE id=?", (app_id,))
    try:
        caddymgr.remove_route(row["route"])
    except Exception as e:
        log.warning("Caddy update skipped: %s", e)
    return {"status": "ok"}


@app.post("/apps/{app_id}/restart")
def restart_app(app_id: int, db=Depends(get_db)):
    row = db.execute("SELECT name FROM apps WHERE id=?", (app_id,)).fetchone()
    if not row:
        raise HTTPException(404, "App not found")
    service = f"platform-{row['name'].lower().replace(' ', '-')}"
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", service],
            check=True, timeout=15,
            capture_output=True, text=True,
        )
        return {"status": "ok", "service": service}
    except subprocess.CalledProcessError as e:
        log.error("systemctl restart %s failed: %s", service, e.stderr or e.stdout or str(e))
        raise HTTPException(500, f"systemctl restart failed: {e.stderr or str(e)}")
    except FileNotFoundError:
        log.warning("systemctl not found — skipping restart (dev/Docker environment)")
        return {"status": "ok", "service": service, "note": "no-op: not a systemd host"}
    except Exception as e:
        log.error("restart %s error: %s", service, e)
        raise HTTPException(500, str(e))


# ── Ollama ────────────────────────────────────────────────────────────────────

@app.get("/ollama/models")
async def ollama_models():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{OLLAMA}/api/tags")
            return r.json()
    except Exception as e:
        raise HTTPException(503, f"Ollama unavailable: {e}")


@app.get("/ollama/running")
async def ollama_running():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{OLLAMA}/api/ps")
            return r.json()
    except Exception as e:
        raise HTTPException(503, f"Ollama unavailable: {e}")


@app.post("/ollama/pull")
async def ollama_pull(body: dict):
    async def stream():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{OLLAMA}/api/pull", json={"name": body["name"]}) as r:
                async for chunk in r.aiter_bytes():
                    yield chunk
    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.delete("/ollama/models/{name:path}")
async def ollama_delete_model(name: str):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.request("DELETE", f"{OLLAMA}/api/delete", json={"name": name})
            return {"status": "ok"} if r.status_code == 200 else {"status": "error", "detail": r.text}
    except Exception as e:
        raise HTTPException(503, str(e))


@app.post("/ollama/unload")
async def ollama_unload():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{OLLAMA}/api/ps")
            models = r.json().get("models", [])
            for m in models:
                await client.post(f"{OLLAMA}/api/generate",
                    json={"model": m["name"], "keep_alive": 0})
        return {"status": "ok", "unloaded": len(models)}
    except Exception as e:
        raise HTTPException(503, str(e))


# ── Tailscale ─────────────────────────────────────────────────────────────────

@app.get("/tailscale/status")
def tailscale_status():
    try:
        r = subprocess.run(["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=5)
        return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr}
    except Exception as e:
        return {"error": str(e)}


# ── Updates ───────────────────────────────────────────────────────────────────

def _do_update_check():
    """Background task: run apt check and cache result in SQLite config table."""
    if not shutil.which("sudo"):
        return  # not a systemd host (Docker dev)
    try:
        subprocess.run(["sudo", "apt-get", "update", "-qq"], timeout=60, capture_output=True)
        r = subprocess.run(["apt", "list", "--upgradable", "--quiet"],
            capture_output=True, text=True, timeout=15)
        lines = [l for l in r.stdout.splitlines() if "/" in l and "upgradable" not in l.lower()]
        result = json.dumps({"packages": lines, "count": len(lines)})
        now = datetime.datetime.utcnow().isoformat()
        conn = _sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('pending_updates_json', ?)", (result,))
        conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('last_update_check', ?)", (now,))
        conn.commit()
        conn.close()
        log.info("Update check: %d package(s) pending", len(lines))
    except Exception as e:
        log.error("Background update check failed: %s", e)


@app.get("/updates/available")
def updates_available(background_tasks: BackgroundTasks, db=Depends(get_db)):
    cached = db.execute("SELECT value FROM config WHERE key='pending_updates_json'").fetchone()
    last_check = db.execute("SELECT value FROM config WHERE key='last_update_check'").fetchone()
    data = json.loads(cached["value"]) if cached else {"packages": [], "count": 0}
    data["last_checked"] = last_check["value"] if last_check else None
    background_tasks.add_task(_do_update_check)
    return data


@app.post("/updates/apply")
def updates_apply(db=Depends(get_db)):
    if _table_exists(db, "sessions"):
        active = db.execute("SELECT id FROM sessions WHERE status='running' LIMIT 1").fetchone()
        if active:
            raise HTTPException(409, "Cannot update during active autocoder session")
    try:
        subprocess.Popen(["sudo", "apt-get", "upgrade", "-y"])
        db.execute(
            "INSERT INTO platform_events (service, event_type, message) VALUES ('system', 'update_applied', 'apt-get upgrade started')"
        )
        return {"status": "ok", "message": "Update started in background"}
    except Exception as e:
        raise HTTPException(500, str(e))


def _table_exists(db, name: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


# ── Agents ────────────────────────────────────────────────────────────────────

@app.get("/agents")
def list_agents(db=Depends(get_db)):
    try:
        return [dict(r) for r in db.execute("SELECT * FROM agents ORDER BY name").fetchall()]
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/apps/{app_id}/agents")
def list_app_agents(app_id: int, db=Depends(get_db)):
    if not db.execute("SELECT 1 FROM apps WHERE id=?", (app_id,)).fetchone():
        raise HTTPException(404, "App not found")
    return [dict(r) for r in db.execute(
        "SELECT * FROM agents WHERE app_id=? ORDER BY name", (app_id,)
    ).fetchall()]


@app.post("/agents", status_code=201)
def create_agent(body: dict, db=Depends(get_db)):
    try:
        db.execute(
            """INSERT INTO agents
               (name, description, model, tools, memory_scope, ui_type, ui_route, system_prompt, app_id, calls)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                body["name"],
                body.get("description"),
                body["model"],
                json.dumps(body.get("tools", [])),
                body.get("memory_scope", "session"),
                body.get("ui_type", "none"),
                body.get("ui_route"),
                body.get("system_prompt"),
                body.get("app_id"),
                json.dumps(body.get("calls", [])),
            ),
        )
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.put("/agents/{agent_id}")
def update_agent(agent_id: int, body: dict, db=Depends(get_db)):
    if not db.execute("SELECT 1 FROM agents WHERE id=?", (agent_id,)).fetchone():
        raise HTTPException(404, "Agent not found")
    allowed = {"name", "description", "model", "tools", "memory_scope", "ui_type", "ui_route", "system_prompt", "app_id", "calls"}
    fields = {k: v for k, v in body.items() if k in allowed}
    if "tools" in fields:
        fields["tools"] = json.dumps(fields["tools"])
    if "calls" in fields:
        fields["calls"] = json.dumps(fields["calls"])
    sets = ", ".join(f"{k}=?" for k in fields)
    db.execute(f"UPDATE agents SET {sets} WHERE id=?", (*fields.values(), agent_id))
    return {"status": "ok"}


@app.delete("/agents/{agent_id}")
def delete_agent(agent_id: int, db=Depends(get_db)):
    if not db.execute("SELECT 1 FROM agents WHERE id=?", (agent_id,)).fetchone():
        raise HTTPException(404, "Agent not found")
    db.execute("DELETE FROM agents WHERE id=?", (agent_id,))
    return {"status": "ok"}


@app.post("/agents/{agent_id}/deploy")
def deploy_agent(agent_id: int, db=Depends(get_db)):
    row = db.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Agent not found")
    agent = dict(row)
    agent["tools"] = json.loads(agent["tools"])
    port = next_agent_port(db)
    try:
        _deploy(agent, port)
        db.execute("UPDATE agents SET backend_port=? WHERE id=?", (port, agent_id))
        if agent.get("ui_route"):
            db.execute(
                "INSERT OR REPLACE INTO apps (name, description, route, backend_port) VALUES (?,?,?,?)",
                (agent["name"], agent.get("description"), agent["ui_route"], port),
            )
            try:
                caddymgr.add_route(agent["ui_route"], port)
            except Exception as e:
                log.warning("Caddy update skipped: %s", e)
        return {"status": "ok", "port": port}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/agents/{agent_id}/stop")
def stop_agent(agent_id: int, db=Depends(get_db)):
    row = db.execute("SELECT name FROM agents WHERE id=?", (agent_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Agent not found")
    service = f"platform-agent-{row['name'].lower().replace(' ', '-')}"
    try:
        subprocess.run(["sudo", "systemctl", "stop", service], check=True, timeout=10)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(500, str(e))


def _deploy(agent: dict, port: int):
    slug = agent["name"].lower().replace(" ", "-")
    base = Path(f"/opt/platform/agents/{slug}")
    base.mkdir(parents=True, exist_ok=True)

    system_prompt = agent.get("system_prompt") or ""
    tools_list = agent.get("tools", [])

    (base / "main.py").write_text(_agent_service_template(agent["model"], system_prompt, tools_list, port))
    (base / "requirements.txt").write_text("fastapi\nuvicorn[standard]\nhttpx\n")

    service_name = f"platform-agent-{slug}"
    unit = (
        f"[Unit]\nDescription=Platform Agent — {agent['name']}\nAfter=network.target\n\n"
        f"[Service]\nType=simple\nUser=ubuntu\nWorkingDirectory={base}\n"
        f"ExecStart={base}/venv/bin/uvicorn main:app --host 0.0.0.0 --port {port}\n"
        f"Restart=always\nRestartSec=5\n\n[Install]\nWantedBy=multi-user.target\n"
    )
    unit_path = f"/etc/systemd/system/{service_name}.service"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".service", delete=False) as f:
        f.write(unit)
        tmp = f.name
    subprocess.run(["sudo", "cp", tmp, unit_path], check=True)
    Path(tmp).unlink(missing_ok=True)

    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    subprocess.run(["sudo", "systemctl", "enable", "--now", service_name], check=True)


def _agent_service_template(model: str, system_prompt: str, tools: list, port: int) -> str:
    # Escape braces for f-string
    sp = system_prompt.replace('"', '\\"')
    return f'''import time
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

START = time.time()
OLLAMA = "http://localhost:11434"
MODEL = "{model}"
SYSTEM_PROMPT = "{sp}"

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {{"status": "ok", "version": "0.1.0", "uptime_seconds": int(time.time() - START)}}


@app.post("/chat")
async def chat(body: dict):
    messages = []
    if SYSTEM_PROMPT:
        messages.append({{"role": "system", "content": SYSTEM_PROMPT}})
    messages.extend(body.get("history", []))
    messages.append({{"role": "user", "content": body["message"]}})

    async def stream():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{{OLLAMA}}/api/chat", json={{"model": MODEL, "messages": messages}}
            ) as r:
                async for chunk in r.aiter_bytes():
                    yield chunk

    return StreamingResponse(stream(), media_type="application/x-ndjson")
'''
