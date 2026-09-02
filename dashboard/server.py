"""
WOS-Bot Dashboard Server
FastAPI backend providing REST API + SSE log streaming for the bot.
"""

import asyncio
import json
import os
import signal
import httpx
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Logging setup for dashboard server
import logging as _logging
_logging.getLogger("ppocr").setLevel(_logging.ERROR)
_logging.getLogger("uvicorn").setLevel(_logging.WARNING)
_logging.getLogger("uvicorn.access").setLevel(_logging.ERROR)

logger = _logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
DB_DIR = PROJECT_ROOT / "db"
ACCOUNT_FILE = DB_DIR / "account.json"
COMPLETION_LOG = DB_DIR / "completion_log.txt"
SETTINGS_FILE = DB_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "ocr_capture_tool": "adb",
    "sudo_password": "",
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup/shutdown: kill subprocesses and cancel SSE listeners."""
    yield  # --- app runs ---
    # Shutdown: terminate any running subprocesses
    for proc, label in [(_bot_process, "Bot"), (_ocr_process, "OCR")]:
        if proc and proc.poll() is None:
            logger.info("[Shutdown] Terminating %s process (PID %d)", label, proc.pid)
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
    # Cancel all SSE listeners so their coroutines exit
    for q in _log_listeners:
        try:
            q.put_nowait(None)  # sentinel to unblock awaiting consumers
        except asyncio.QueueFull:
            pass
    for q in _ocr_log_listeners:
        try:
            q.put_nowait(None)
        except asyncio.QueueFull:
            pass
    _log_listeners.clear()
    _ocr_log_listeners.clear()
    logger.info("[Shutdown] Cleanup complete.")


def _read_project_version() -> str:
    """Read version from pyproject.toml."""
    toml_path = PROJECT_ROOT / "pyproject.toml"
    try:
        import tomllib
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        return data.get("project", {}).get("version", "0.0.0")
    except Exception:
        pass
    # Fallback: regex parse
    try:
        import re
        text = toml_path.read_text()
        m = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "0.0.0"


APP_VERSION = _read_project_version()

app = FastAPI(title="WOS-Bot Dashboard", version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Bot Process State ---
_bot_process: Optional[subprocess.Popen] = None
_log_lines: list[str] = []
_log_listeners: list[asyncio.Queue] = []
_bot_status: str = "stopped"  # stopped | starting | running | stopping
_current_task: str = ""
_current_player: str = ""
_selected_tasks: list[str] = []
_selected_accounts: list[str] = []  # email filter for bot runs

# --- OCR Server Process State ---
_ocr_process: Optional[subprocess.Popen] = None
_ocr_status: str = "stopped"  # stopped | starting | running | error
_ocr_log_lines: list[str] = []
_ocr_log_listeners: list[asyncio.Queue] = []

MAX_LOG_LINES = 500


# --- Models ---
class TaskSelection(BaseModel):
    tasks: list[str]
    accounts: Optional[list[str]] = None  # optional email filter
    characters: Optional[dict[str, list[str]]] = None  # email -> [player_ids] filter


class AccountUpdate(BaseModel):
    email: str
    priority: int
    players: list[dict]


class PlayerUpdate(BaseModel):
    name: str
    id: str


class NewAccount(BaseModel):
    email: str
    priority: int = 999
    players: list[dict] = []


# --- Helpers ---
def _load_accounts() -> dict:
    if not ACCOUNT_FILE.exists():
        return {}
    with open(ACCOUNT_FILE) as f:
        return json.load(f)


def _save_accounts(data: dict):
    with open(ACCOUNT_FILE, "w") as f:
        json.dump(data, f, indent=4)


def _load_completion_log() -> list[dict]:
    records = []
    if not COMPLETION_LOG.exists():
        return records
    with open(COMPLETION_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            records.append({
                "player_id": parts[0].strip(),
                "timestamp": float(parts[1].strip()),
                "datetime": parts[2].strip(),
            })
    return records


def _discover_tasks() -> list[dict]:
    """Parse TASK_METADATA from usecases/ via AST — no imports, no side effects."""
    import ast
    usecases_dir = PROJECT_ROOT / "usecases"
    tasks = []
    seen_keys: set[str] = set()

    for pyfile in sorted(usecases_dir.glob("*.py")):
        if pyfile.name.startswith("_"):
            continue
        try:
            tree = ast.parse(pyfile.read_text())
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not (isinstance(target, ast.Name) and target.id == "TASK_METADATA"):
                    continue
                try:
                    entries = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue
                for entry in entries:
                    key = entry.get("key")
                    if not key or key in seen_keys:
                        continue
                    seen_keys.add(key)
                    tasks.append({
                        "key": key,
                        "title": entry.get("title", key),
                        "description": entry.get("description", ""),
                    })

    return tasks


async def _broadcast_log(line: str):
    """Send log line to all SSE listeners."""
    dead = []
    for q in _log_listeners:
        try:
            q.put_nowait(line)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _log_listeners.remove(q)


def _parse_bot_output(line: str):
    """Parse bot stdout for status updates."""
    global _current_task, _current_player

    line_lower = line.lower()

    if "running tasks for:" in line_lower:
        _current_player = line.split("Running tasks for:")[-1].strip()
    elif "running" in line_lower and any(t["title"].lower() in line_lower for t in _discover_tasks()):
        for t in _discover_tasks():
            if t["title"].lower() in line_lower:
                _current_task = t["title"]
                break
    elif "marked completed:" in line_lower:
        _current_task = "Completed"
    elif "skipping" in line_lower:
        _current_player = line.split("Skipping")[-1].split("-")[0].strip()
        _current_task = "Skipped"


async def _read_bot_stream(process: subprocess.Popen):
    """Read bot process stdout line by line."""
    global _bot_status
    loop = asyncio.get_event_loop()

    while True:
        line = await loop.run_in_executor(None, process.stdout.readline)
        if not line:
            break
        text = line.decode("utf-8", errors="replace").rstrip()
        if text:
            _log_lines.append(text)
            if len(_log_lines) > MAX_LOG_LINES:
                _log_lines.pop(0)
            _parse_bot_output(text)
            await _broadcast_log(text)

    process.wait()
    _bot_status = "stopped"
    _current_task = ""
    _current_player = ""
    await _broadcast_log("[Dashboard] Bot process exited.")


# --- API Routes ---

def _get_adb_devices() -> dict:
    """Check ADB device connectivity."""
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.strip().split("\n")[1:]
        devices = []
        for line in lines:
            if line.strip():
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append({"id": parts[0], "state": "connected"})
                elif len(parts) >= 2:
                    devices.append({"id": parts[0], "state": parts[1]})
        return {"connected": len(devices) > 0, "devices": devices}
    except FileNotFoundError:
        return {"connected": False, "devices": [], "error": "ADB not found"}
    except subprocess.TimeoutExpired:
        return {"connected": False, "devices": [], "error": "ADB timeout"}
    except Exception as e:
        return {"connected": False, "devices": [], "error": str(e)}


def _get_ocr_module_versions() -> dict:
    """Get OCR-related module versions."""
    info = {}
    try:
        import paddleocr
        info["paddleocr"] = getattr(paddleocr, "__version__", "unknown")
    except ImportError:
        info["paddleocr"] = "not installed"
    try:
        import paddle
        info["paddlepaddle"] = getattr(paddle, "__version__", "unknown")
    except ImportError:
        info["paddlepaddle"] = "not installed"
    try:
        import cv2
        info["opencv"] = cv2.__version__
    except ImportError:
        info["opencv"] = "not installed"
    try:
        import rapidfuzz
        info["rapidfuzz"] = getattr(rapidfuzz, "__version__", "unknown")
    except ImportError:
        info["rapidfuzz"] = "not installed"
    return info


def _get_total_characters() -> int:
    """Count total characters across all accounts."""
    data = _load_accounts()
    total = 0
    for acc in data.values():
        players = acc.get("player", [])
        total += len(players)
    return total


@app.get("/api/status")
async def get_status():
    adb_info = _get_adb_devices()
    ocr_modules = _get_ocr_module_versions()
    accounts = _load_accounts()
    total_chars = sum(len(acc.get("player", [])) for acc in accounts.values())

    # Determine readiness — collect all blocking issues
    issues: list[str] = []
    if not adb_info.get("connected"):
        err = adb_info.get("error", "No device detected")
        issues.append(f"ADB: {err}")
    if not accounts:
        issues.append("No accounts configured")

    return {
        "status": _bot_status,
        "current_player": _current_player,
        "current_task": _current_task,
        "selected_tasks": _selected_tasks,
        "selected_accounts": _selected_accounts,
        "ocr_status": _ocr_status,
        "uptime": time.time() if _bot_status == "running" else None,
        "version": APP_VERSION,
        "adb": adb_info,
        "ocr_modules": ocr_modules,
        "total_accounts": len(accounts),
        "total_characters": total_chars,
        "ready": len(issues) == 0,
        "issues": issues,
    }


@app.get("/api/tasks")
async def get_tasks():
    return _discover_tasks()


@app.post("/api/bot/start")
async def start_bot(selection: TaskSelection):
    global _bot_process, _bot_status, _selected_tasks, _selected_accounts, _log_lines

    if _bot_status in ("running", "starting"):
        raise HTTPException(400, "Bot is already running")

    if not selection.tasks:
        raise HTTPException(400, "No tasks selected")

    _selected_tasks = selection.tasks
    _selected_accounts = selection.accounts or []
    _log_lines.clear()
    _bot_status = "starting"

    # Auto-start OCR server if not running
    if _ocr_status not in ("running", "starting"):
        try:
            _start_ocr_process()
            await _broadcast_log("[Dashboard] Auto-started OCR server.")
        except Exception as e:
            await _broadcast_log(f"[Dashboard] ⚠️ OCR auto-start failed: {e}")

    # Wait for OCR server to be ready before starting bot
    ocr_ready = False
    port_file = PROJECT_ROOT / "system" / ".ocr_port"
    for attempt in range(60):  # up to 60 seconds
        try:
            ocr_port = int(port_file.read_text().strip())
            async with httpx.AsyncClient(timeout=2) as client:
                resp = await client.get(f"http://127.0.0.1:{ocr_port}/health")
                if resp.status_code == 200:
                    ocr_ready = True
                    break
        except Exception:
            pass
        await asyncio.sleep(1)
    if ocr_ready:
        await _broadcast_log("[Dashboard] ✅ OCR server is ready.")
    else:
        await _broadcast_log("[Dashboard] ⚠️ OCR server not ready after 60s, bot may fail OCR requests.")

    # Send task keys + optional account/character filter as JSON via stdin
    payload: dict = {"tasks": selection.tasks}
    if _selected_accounts:
        payload["accounts"] = _selected_accounts
    if selection.characters:
        payload["characters"] = selection.characters
    task_json = json.dumps(payload) + "\n"

    try:
        _bot_process = subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / "Main" / "main.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )

        # Send JSON task selection to bot's stdin
        _bot_process.stdin.write(task_json.encode())
        _bot_process.stdin.flush()
        _bot_process.stdin.close()

        _bot_status = "running"
        asyncio.create_task(_read_bot_stream(_bot_process))
        await _broadcast_log(f"[Dashboard] Bot started with tasks: {', '.join(selection.tasks)}")

        return {"status": "started", "tasks": selection.tasks}

    except Exception as e:
        _bot_status = "stopped"
        raise HTTPException(500, f"Failed to start bot: {e}")


@app.post("/api/bot/stop")
async def stop_bot():
    global _bot_process, _bot_status, _ocr_process, _ocr_status

    if _bot_status != "running":
        raise HTTPException(400, "Bot is not running")

    _bot_status = "stopping"
    await _broadcast_log("[Dashboard] Stopping bot...")

    if _bot_process and _bot_process.poll() is None:
        _bot_process.terminate()
        try:
            _bot_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _bot_process.kill()

    _bot_process = None
    _bot_status = "stopped"
    _current_task = ""
    _current_player = ""

    # Stop OCR engine together with the bot — always, regardless of tracked state
    await _broadcast_log("[Dashboard] Stopping OCR engine...")
    if _ocr_process and _ocr_process.poll() is None:
        _ocr_process.terminate()
        try:
            _ocr_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _ocr_process.kill()
    # Kill any orphan OCR process using the dynamic port
    try:
        _port_file = PROJECT_ROOT / "system" / ".ocr_port"
        _ocr_port = int(_port_file.read_text().strip()) if _port_file.exists() else None
        if _ocr_port is None:
            logger.info("[Stop] No .ocr_port file found, skipping orphan check")
        else:
            result = subprocess.run(
                ["lsof", "-ti", f":{_ocr_port}"], capture_output=True, text=True, timeout=5
            )
            for pid_str in result.stdout.strip().split():
                pid = int(pid_str)
                if pid != os.getpid():
                    logger.info("[Stop] Killing orphan OCR process PID %d", pid)
                    os.kill(pid, signal.SIGTERM)
    except Exception as e:
        logger.warning("[Stop] Failed to check orphan OCR: %s", e)
    _ocr_process = None
    _ocr_status = "stopped"

    await _broadcast_log("[Dashboard] Bot stopped.")
    return {"status": "stopped"}


@app.get("/api/logs")
async def get_logs():
    return {"lines": _log_lines[-200:]}


@app.get("/api/logs/stream")
async def stream_logs():
    async def event_generator():
        queue = asyncio.Queue(maxsize=100)
        _log_listeners.append(queue)
        try:
            # Send recent history first
            for line in _log_lines[-50:]:
                yield f"data: {json.dumps({'line': line})}\n\n"
            # Stream new lines
            while True:
                line = await queue.get()
                if line is None:  # shutdown sentinel
                    break
                yield f"data: {json.dumps({'line': line})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in _log_listeners:
                _log_listeners.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/accounts")
async def get_accounts():
    data = _load_accounts()
    accounts = []
    for email, info in sorted(data.items(), key=lambda x: x[1].get("priority", 999)):
        accounts.append({
            "email": email,
            "priority": info.get("priority", 999),
            "players": info.get("player", []),
        })
    return accounts


@app.put("/api/accounts/{email:path}")
async def update_account(email: str, update: AccountUpdate):
    data = _load_accounts()
    data[email] = {
        "priority": update.priority,
        "player": update.players,
    }
    _save_accounts(data)
    return {"status": "updated", "email": email}


@app.delete("/api/accounts/{email:path}")
async def delete_account(email: str):
    data = _load_accounts()
    if email not in data:
        raise HTTPException(404, "Account not found")
    del data[email]
    _save_accounts(data)
    return {"status": "deleted", "email": email}


@app.get("/api/completion")
async def get_completion():
    records = _load_completion_log()
    accounts = _load_accounts()

    # Build player name lookup
    player_names = {}
    for email, info in accounts.items():
        for p in info.get("player", []):
            player_names[p["id"]] = {"name": p["name"], "email": email}

    result = []
    for r in records:
        pid = r["player_id"]
        info = player_names.get(pid, {})
        age_hours = (time.time() - r["timestamp"]) / 3600
        result.append({
            "player_id": pid,
            "player_name": info.get("name", "Unknown"),
            "email": info.get("email", "Unknown"),
            "last_completed": r["datetime"],
            "hours_ago": round(age_hours, 1),
            "in_cooldown": age_hours < 3.0,
        })

    return sorted(result, key=lambda x: x["hours_ago"])


# --- OCR Server Management ---

async def _read_ocr_stream(process: subprocess.Popen):
    """Read OCR server stdout line by line."""
    global _ocr_status
    loop = asyncio.get_event_loop()

    while True:
        line = await loop.run_in_executor(None, process.stdout.readline)
        if not line:
            break
        text = line.decode("utf-8", errors="replace").rstrip()
        if text:
            _ocr_log_lines.append(text)
            if len(_ocr_log_lines) > MAX_LOG_LINES:
                _ocr_log_lines.pop(0)
            # Broadcast to OCR log listeners
            dead = []
            for q in _ocr_log_listeners:
                try:
                    q.put_nowait(text)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                _ocr_log_listeners.remove(q)

    process.wait()
    if _ocr_status != "stopped":
        _ocr_status = "stopped"


@app.get("/api/ocr/status")
async def ocr_status():
    return {"status": _ocr_status}


def _start_ocr_process():
    """Internal helper to launch OCR subprocess. Raises on failure."""
    global _ocr_process, _ocr_status, _ocr_log_lines

    if _ocr_status in ("running", "starting"):
        return  # already running

    _ocr_log_lines.clear()
    _ocr_status = "starting"

    # Let OCR server pick its own dynamic port (written to system/.ocr_port)
    _ocr_process = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "core" / "ocr.py")],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        cwd=str(PROJECT_ROOT),
        env={
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "OCR_CAPTURE_TOOL": _load_settings().get("ocr_capture_tool", "adb"),
            "OCR_SUDO_PASSWORD": _load_settings().get("sudo_password", ""),
        },
    )
    _ocr_status = "running"
    asyncio.create_task(_read_ocr_stream(_ocr_process))


@app.post("/api/ocr/start")
async def ocr_start():
    try:
        _start_ocr_process()
        return {"status": "started"}
    except Exception as e:
        _ocr_status = "error"
        raise HTTPException(500, f"Failed to start OCR server: {e}")


@app.post("/api/ocr/stop")
async def ocr_stop():
    global _ocr_process, _ocr_status

    if _ocr_status != "running":
        raise HTTPException(400, "OCR server is not running")

    _ocr_status = "stopping"
    if _ocr_process and _ocr_process.poll() is None:
        _ocr_process.terminate()
        try:
            _ocr_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _ocr_process.kill()

    _ocr_process = None
    _ocr_status = "stopped"
    return {"status": "stopped"}


@app.get("/api/ocr/logs/stream")
async def ocr_stream_logs():
    async def event_generator():
        queue = asyncio.Queue(maxsize=100)
        _ocr_log_listeners.append(queue)
        try:
            for line in _ocr_log_lines[-50:]:
                yield f"data: {json.dumps({'line': line})}\n\n"
            while True:
                line = await queue.get()
                if line is None:  # shutdown sentinel
                    break
                yield f"data: {json.dumps({'line': line})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in _ocr_log_listeners:
                _ocr_log_listeners.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# --- Enhanced Account/Character Editing ---

@app.post("/api/accounts")
async def create_account(new: NewAccount):
    data = _load_accounts()
    if new.email in data:
        raise HTTPException(409, "Account already exists")
    data[new.email] = {
        "priority": new.priority,
        "player": new.players,
    }
    _save_accounts(data)
    return {"status": "created", "email": new.email}


@app.put("/api/accounts/{email:path}/players/{player_id}")
async def update_player(email: str, player_id: str, update: PlayerUpdate):
    data = _load_accounts()
    if email not in data:
        raise HTTPException(404, "Account not found")

    players = data[email].get("player", [])
    found = False
    for p in players:
        if str(p.get("id")) == str(player_id):
            p["name"] = update.name
            p["id"] = update.id
            found = True
            break

    if not found:
        raise HTTPException(404, f"Player {player_id} not found in account {email}")

    _save_accounts(data)
    return {"status": "updated", "email": email, "player_id": update.id}


@app.post("/api/accounts/{email:path}/players")
async def add_player(email: str, player: PlayerUpdate):
    data = _load_accounts()
    if email not in data:
        raise HTTPException(404, "Account not found")

    players = data[email].get("player", [])
    # Check for duplicate ID
    for p in players:
        if str(p.get("id")) == str(player.id):
            raise HTTPException(409, f"Player with ID {player.id} already exists")

    players.append({"name": player.name, "id": player.id})
    data[email]["player"] = players
    _save_accounts(data)
    return {"status": "added", "email": email, "player_id": player.id}


@app.delete("/api/accounts/{email:path}/players/{player_id}")
async def delete_player(email: str, player_id: str):
    data = _load_accounts()
    if email not in data:
        raise HTTPException(404, "Account not found")

    players = data[email].get("player", [])
    original_len = len(players)
    data[email]["player"] = [p for p in players if str(p.get("id")) != str(player_id)]

    if len(data[email]["player"]) == original_len:
        raise HTTPException(404, f"Player {player_id} not found")

    _save_accounts(data)
    return {"status": "deleted", "email": email, "player_id": player_id}


@app.put("/api/accounts/{email:path}")
async def update_account(email: str, update: AccountUpdate):
    """Update an existing account's email, priority, and full player list."""
    data = _load_accounts()
    if email not in data:
        raise HTTPException(404, "Account not found")

    # If email changed, migrate the entry
    if update.email != email:
        if update.email in data:
            raise HTTPException(409, f"Account {update.email} already exists")
        data[update.email] = {
            "priority": update.priority,
            "player": update.players,
        }
        del data[email]
    else:
        data[email]["priority"] = update.priority
        data[email]["player"] = update.players

    _save_accounts(data)
    return {"status": "updated", "email": update.email}


@app.delete("/api/accounts/{email:path}")
async def delete_account(email: str):
    data = _load_accounts()
    if email not in data:
        raise HTTPException(404, "Account not found")
    del data[email]
    _save_accounts(data)
    return {"status": "deleted", "email": email}


# --- Settings ---
def _load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return {**DEFAULT_SETTINGS}
    with open(SETTINGS_FILE) as f:
        data = json.load(f)
    # Merge with defaults for any missing keys
    merged = {**DEFAULT_SETTINGS}
    merged.update(data)
    return merged


def _save_settings(data: dict):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=4)


class SettingsUpdate(BaseModel):
    ocr_capture_tool: Optional[str] = None
    sudo_password: Optional[str] = None


@app.get("/api/settings")
async def get_settings():
    return _load_settings()


@app.put("/api/settings")
async def update_settings(update: SettingsUpdate):
    data = _load_settings()
    if update.ocr_capture_tool is not None:
        if update.ocr_capture_tool not in ("adb", "scrcpy"):
            raise HTTPException(400, "ocr_capture_tool must be 'adb' or 'scrcpy'")
        data["ocr_capture_tool"] = update.ocr_capture_tool
    if update.sudo_password is not None:
        data["sudo_password"] = update.sudo_password
    _save_settings(data)
    return {"status": "updated", "settings": data}


# --- Debug / Test Endpoints ---

def _get_ocr_port() -> Optional[int]:
    """Read current OCR server port from .ocr_port file."""
    port_file = PROJECT_ROOT / "system" / ".ocr_port"
    if not port_file.exists():
        return None
    try:
        return int(port_file.read_text().strip())
    except (ValueError, OSError):
        return None


class DebugOcrRequest(BaseModel):
    image_base64: str  # base64-encoded PNG/JPEG
    rois: Optional[list[list[float]]] = None  # percentage-based ROIs [x1,y1,x2,y2]
    name: Optional[str] = None
    expected_text: Optional[str] = None


class DebugTemplateRequest(BaseModel):
    image_base64: str  # screenshot to match against
    template_base64: Optional[str] = None  # cropped template (if not using saved)
    template_name: Optional[str] = None  # saved template name
    threshold: float = 0.8
    rois: Optional[list[list[float]]] = None


class DebugSaveCoordRequest(BaseModel):
    key: str  # e.g. "Home.NewButton"
    text: Optional[str] = None
    score: Optional[float] = None
    box: list[float]  # [x1, y1, x2, y2] in percentage
    target_file: Optional[str] = None  # specific file or None for merged


@app.post("/api/debug/screenshot")
async def debug_screenshot():
    """Capture live screen from ADB and return as base64 PNG."""
    import base64
    import cv2
    import numpy as np
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from cmd_program.screen_action import take_screenshot
        img = take_screenshot(save=False)
        _, buf = cv2.imencode(".png", img)
        b64 = base64.b64encode(buf.tobytes()).decode()
        return {"success": True, "image_base64": b64, "width": img.shape[1], "height": img.shape[0]}
    except Exception as e:
        raise HTTPException(500, f"Screenshot failed: {e}")


@app.post("/api/debug/ocr")
async def debug_ocr(req: DebugOcrRequest):
    """Run OCR on an uploaded/captured image via the OCR server."""
    import base64
    import tempfile
    ocr_port = _get_ocr_port()
    if not ocr_port:
        raise HTTPException(503, "OCR server not running")

    # Decode base64 image to temp file
    try:
        img_data = base64.b64decode(req.image_base64)
    except Exception as e:
        raise HTTPException(400, f"Invalid base64 image: {e}")

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=str(PROJECT_ROOT / "cache"))
    tmp.write(img_data)
    tmp.close()

    try:
        # Convert percentage ROIs to pixel ROIs if provided
        pixel_rois = None
        if req.rois:
            import cv2
            import numpy as np
            img_arr = np.frombuffer(img_data, np.uint8)
            img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
            if img is not None:
                h, w = img.shape[:2]
                pixel_rois = []
                for roi in req.rois:
                    pixel_rois.append([
                        int(roi[0] / 100 * w),
                        int(roi[1] / 100 * h),
                        int(roi[2] / 100 * w),
                        int(roi[3] / 100 * h),
                    ])

        payload = {
            "img_path": tmp.name,
            "save_result": True,
            "rois": pixel_rois,
            "name": req.name,
            "expected_text": req.expected_text,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"http://127.0.0.1:{ocr_port}/ocr", json=payload)
            data = resp.json()

        return data
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@app.post("/api/debug/template")
async def debug_template(req: DebugTemplateRequest):
    """Run template matching on an uploaded/captured image."""
    import base64
    import tempfile
    import cv2
    import numpy as np

    ocr_port = _get_ocr_port()
    if not ocr_port:
        raise HTTPException(503, "OCR server not running")

    # Decode screenshot
    try:
        screen_data = base64.b64decode(req.image_base64)
    except Exception as e:
        raise HTTPException(400, f"Invalid screenshot base64: {e}")

    screen_tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=str(PROJECT_ROOT / "cache"))
    screen_tmp.write(screen_data)
    screen_tmp.close()

    try:
        if req.template_base64:
            # User-cropped template: save it temporarily and use custom matching
            tmpl_data = base64.b64decode(req.template_base64)
            tmpl_tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=str(PROJECT_ROOT / "cache"))
            tmpl_tmp.write(tmpl_data)
            tmpl_tmp.close()

            try:
                # Run OpenCV template matching directly in dashboard server
                screen_img = cv2.imdecode(np.frombuffer(screen_data, np.uint8), cv2.IMREAD_COLOR)
                tmpl_img = cv2.imdecode(np.frombuffer(tmpl_data, np.uint8), cv2.IMREAD_COLOR)

                if screen_img is None or tmpl_img is None:
                    raise HTTPException(400, "Failed to decode images")

                gray_screen = cv2.cvtColor(screen_img, cv2.COLOR_BGR2GRAY)
                gray_tmpl = cv2.cvtColor(tmpl_img, cv2.COLOR_BGR2GRAY)

                result = cv2.matchTemplate(gray_screen, gray_tmpl, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

                h, w = tmpl_img.shape[:2]
                sh, sw = screen_img.shape[:2]

                matches = []
                threshold = req.threshold
                locations = np.where(result >= threshold)
                for pt in zip(*locations[::-1]):
                    matches.append({
                        "box": [
                            round(pt[0] / sw * 100, 2),
                            round(pt[1] / sh * 100, 2),
                            round((pt[0] + w) / sw * 100, 2),
                            round((pt[1] + h) / sh * 100, 2),
                        ],
                        "score": round(float(result[pt[1], pt[0]]), 4),
                        "pixel_box": [int(pt[0]), int(pt[1]), int(pt[0] + w), int(pt[1] + h)],
                    })

                # Deduplicate overlapping matches (NMS-like)
                matches.sort(key=lambda m: m["score"], reverse=True)
                filtered = []
                for m in matches:
                    overlap = False
                    for f in filtered:
                        if abs(m["box"][0] - f["box"][0]) < 2 and abs(m["box"][1] - f["box"][1]) < 2:
                            overlap = True
                            break
                    if not overlap:
                        filtered.append(m)

                return {"success": True, "results": filtered, "best_score": round(max_val, 4)}
            finally:
                try:
                    os.unlink(tmpl_tmp.name)
                except OSError:
                    pass

        elif req.template_name:
            # Use saved template via OCR server's /template endpoint
            payload = {
                "name": req.template_name,
                "threshold": req.threshold,
                "save_result": True,
                "rois": None,
            }
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(f"http://127.0.0.1:{ocr_port}/template", json=payload)
                return resp.json()
        else:
            raise HTTPException(400, "Provide either template_base64 or template_name")
    finally:
        try:
            os.unlink(screen_tmp.name)
        except OSError:
            pass


@app.get("/api/debug/templates")
async def debug_list_templates():
    """List all saved template names from references/icon/."""
    icon_dir = PROJECT_ROOT / "references" / "icon"
    templates = []
    if icon_dir.exists():
        for f in sorted(icon_dir.glob("*.png")):
            templates.append(f.stem)
    # Also include entries from template_config.json
    config_file = icon_dir / "template_config.json"
    if config_file.exists():
        try:
            with open(config_file) as fh:
                config = json.load(fh)
            for key in config:
                if key != "_demo" and key not in templates:
                    templates.append(key)
        except Exception:
            pass
    return {"templates": templates}


@app.get("/api/debug/coords")
async def debug_list_coords():
    """List all text_area coord keys."""
    text_area_dir = PROJECT_ROOT / "references" / "TextArea"
    coords = {}
    if text_area_dir.exists():
        for f in sorted(text_area_dir.glob("*.json")):
            if f.name.startswith("_"):
                continue
            try:
                with open(f) as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    for key, val in data.items():
                        coords[key] = {
                            "box": val.get("box"),
                            "text": val.get("text"),
                            "source_file": f.name,
                        }
            except Exception:
                pass
    return {"count": len(coords), "coords": coords}


@app.post("/api/debug/save-coord")
async def debug_save_coord(req: DebugSaveCoordRequest):
    """Save a new coord entry to the TextArea JSON files."""
    text_area_dir = PROJECT_ROOT / "references" / "TextArea"
    text_area_dir.mkdir(exist_ok=True)

    # Determine target file
    if req.target_file:
        target = text_area_dir / req.target_file
    else:
        # Auto-determine from key prefix: Home.X -> Home.json, World.X -> World.json
        parts = req.key.split(".")
        prefix = parts[0] if parts else "Global"
        target = text_area_dir / f"{prefix}.json"

    # Load existing or create new
    data = {}
    if target.exists():
        try:
            with open(target) as f:
                data = json.load(f)
        except Exception:
            data = {}

    data[req.key] = {
        "text": req.text or "",
        "score": req.score or 0.0,
        "box": req.box,
    }

    with open(target, "w") as f:
        json.dump(data, f, indent=4)

    return {"success": True, "saved_to": str(target.name), "key": req.key}


@app.post("/api/debug/save-template")
async def debug_save_template(req: DebugSaveCoordRequest):
    """Save a cropped region as a template image."""
    import base64
    # This expects image_base64 in the request body alongside the coord info
    # We reuse DebugSaveCoordRequest but the actual image comes from the frontend
    # The frontend will POST the cropped image separately
    raise HTTPException(501, "Use /api/debug/save-template-image instead")


class SaveTemplateImageRequest(BaseModel):
    name: str
    image_base64: str
    threshold: float = 0.8


@app.post("/api/debug/save-template-image")
async def debug_save_template_image(req: SaveTemplateImageRequest):
    """Save a cropped template image to references/icon/."""
    import base64
    icon_dir = PROJECT_ROOT / "references" / "icon"
    icon_dir.mkdir(exist_ok=True)

    try:
        img_data = base64.b64decode(req.image_base64)
    except Exception as e:
        raise HTTPException(400, f"Invalid base64: {e}")

    filepath = icon_dir / f"{req.name}.png"
    filepath.write_bytes(img_data)

    # Update template_config.json
    config_file = icon_dir / "template_config.json"
    config = {}
    if config_file.exists():
        try:
            with open(config_file) as f:
                config = json.load(f)
        except Exception:
            config = {}

    config[req.name] = {"threshold": req.threshold}

    with open(config_file, "w") as f:
        json.dump(config, f, indent=4)

    return {"success": True, "saved_to": str(filepath), "name": req.name}


# --- Static Files ---
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8081)
    args, _ = parser.parse_known_args()
    uvicorn.run(app, host="0.0.0.0", port=args.port)
