import os
import sys
import re
import json
import asyncio
import datetime
import subprocess
import threading
import shutil
from pathlib import Path
from collections import deque

# 1. Environment & Platform Detection
IS_WINDOWS = sys.platform.startswith("win")
IS_ANDROID = "TERMUX_VERSION" in os.environ or "ANDROID_ROOT" in os.environ

if IS_WINDOWS:
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# Try importing POSIX pty for Linux / macOS / Termux
try:
    import pty
    import select
    import termios
    import tty
    HAS_POSIX_PTY = True
except ImportError:
    HAS_POSIX_PTY = False

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
import uvicorn

# 2. Cross-Platform Directory Paths (Zero Hardcoding)
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
STATIC_DIR = APP_DIR / "static"
UPLOAD_DIR = APP_DIR / "uploads"
AUDIO_DIR = APP_DIR / "audio"
BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"

STATIC_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# 3. Load .env Configuration
def load_env():
    for env_path in [APP_DIR / ".env", ROOT_DIR / ".env", Path(".env")]:
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
            break

load_env()
SECRET_KEY = os.environ.get("AGY_AUTH_PIN", "29105")
PORT = int(os.environ.get("PORT", os.environ.get("AGY_PORT", os.environ.get("AGY_HTTP_PORT", "8090"))))

# Locate Antigravity CLI binary
def get_agy_binary():
    agy_in_path = shutil.which("agy") or shutil.which("agy.exe")
    if agy_in_path:
        return str(agy_in_path)
    if IS_WINDOWS:
        win_candidates = [
            Path.home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe",
            Path.home() / ".gemini" / "antigravity-cli" / "agy.cmd",
            Path.home() / "AppData" / "Roaming" / "npm" / "agy.cmd",
        ]
        for c in win_candidates:
            if c.exists():
                return str(c)
    termux_candidates = [
        Path("/data/data/com.termux/files/usr/bin/agy"),
        Path.home() / "bin" / "agy",
        Path("/usr/local/bin/agy"),
    ]
    for c in termux_candidates:
        if c.exists():
            return str(c)
    return "agy"

# Default interactive shell selection
def get_default_shell():
    if IS_WINDOWS:
        return ["powershell.exe", "-NoLogo", "-NoExit"]
    elif IS_ANDROID:
        termux_bash = "/data/data/com.termux/files/usr/bin/bash"
        if os.path.exists(termux_bash):
            return [termux_bash, "-l"]
        return ["bash", "-l"]
    else:
        return [os.environ.get("SHELL", "/bin/bash"), "-l"]

# Active sessions registry
active_sessions = {}
main_event_loop = None

# 4. Universal Shell & PTY Managers

class WindowsPipedSession:
    """Windows interactive session using subprocess pipes and background UTF-8 reader."""
    def __init__(self, conv_id):
        self.conv_id = conv_id
        self.clients = set()
        self.history_buffer = deque(maxlen=2000)
        self.running = True

        agy_path = get_agy_binary()
        startup_cmd = (
            "$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8; "
            "Write-Host '===================================================' -ForegroundColor DarkGray; "
            "Write-Host '>> AGY 2.0 // Windows Workstation Terminal Online' -ForegroundColor Cyan; "
            "Write-Host '   Platform: Windows | agy CLI: " + agy_path.replace('\\', '\\\\') + "' -ForegroundColor Gray; "
            "Write-Host '   Ready for commands, PowerShell, or 1-Tap Quick Actions.' -ForegroundColor Gray; "
            "Write-Host '===================================================\\n' -ForegroundColor DarkGray;"
        )
        shell_cmd = ["powershell.exe", "-NoLogo", "-NoExit", "-Command", startup_cmd]
        
        self.proc = subprocess.Popen(
            shell_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0
        )

        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _read_loop(self):
        while self.running and self.proc.poll() is None:
            try:
                chunk = self.proc.stdout.read(1024)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                self.history_buffer.append(text)
                if main_event_loop and self.clients:
                    for ws in list(self.clients):
                        try:
                            asyncio.run_coroutine_threadsafe(
                                ws.send_text(json.dumps({"type": "output", "data": text})),
                                main_event_loop
                            )
                        except Exception:
                            pass
            except Exception:
                break

    def write(self, data):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(data.encode("utf-8"))
                self.proc.stdin.flush()
            except Exception:
                pass

    def resize(self, rows, cols):
        pass

    def close(self):
        self.running = False
        if self.proc:
            try:
                self.proc.kill()
            except Exception:
                pass

    def is_alive(self):
        return self.proc and self.proc.poll() is None


class PosixPtySession:
    """POSIX pseudo-terminal emulation for Linux, macOS, and Android (Termux)."""
    def __init__(self, conv_id):
        self.conv_id = conv_id
        self.clients = set()
        self.history_buffer = deque(maxlen=2000)
        self.running = True

        shell = get_default_shell()
        pid, master_fd = pty.fork()

        if pid == 0:
            # Child process
            os.environ["TERM"] = "xterm-256color"
            os.environ["COLORTERM"] = "truecolor"
            try:
                os.execvp(shell[0], shell)
            except Exception as e:
                sys.stderr.write(f"Failed to exec shell: {e}\n")
                sys.exit(1)
        else:
            # Parent process
            self.pid = pid
            self.master_fd = master_fd
            self.reader = threading.Thread(target=self._read_loop, daemon=True)
            self.reader.start()

    def _read_loop(self):
        while self.running:
            try:
                r, _, _ = select.select([self.master_fd], [], [], 0.1)
                if self.master_fd in r:
                    chunk = os.read(self.master_fd, 1024)
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    self.history_buffer.append(text)
                    if main_event_loop and self.clients:
                        for ws in list(self.clients):
                            try:
                                asyncio.run_coroutine_threadsafe(
                                    ws.send_text(json.dumps({"type": "output", "data": text})),
                                    main_event_loop
                                )
                            except Exception:
                                pass
            except Exception:
                break

    def write(self, data):
        if self.running and self.master_fd:
            try:
                os.write(self.master_fd, data.encode("utf-8"))
            except Exception:
                pass

    def resize(self, rows, cols):
        if HAS_POSIX_PTY and self.master_fd:
            try:
                import struct
                import fcntl
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except Exception:
                pass

    def close(self):
        self.running = False
        if self.master_fd:
            try:
                os.close(self.master_fd)
            except Exception:
                pass
        if self.pid:
            try:
                os.kill(self.pid, 9)
            except Exception:
                pass

    def is_alive(self):
        if not self.running:
            return False
        try:
            res, _ = os.waitpid(self.pid, os.WNOHANG)
            return res == 0
        except Exception:
            return False


def get_or_create_session(conv_id):
    if not conv_id or conv_id == "default" or conv_id == "new":
        conv_id = "default"
    
    if conv_id in active_sessions and active_sessions[conv_id].is_alive():
        return active_sessions[conv_id]

    if HAS_POSIX_PTY and not IS_WINDOWS:
        session = PosixPtySession(conv_id)
    else:
        session = WindowsPipedSession(conv_id)

    active_sessions[conv_id] = session
    return session


# 5. Session & Transcript DAG Pipeline
def categorize_session(title):
    t = title.lower()
    if any(k in t for k in ["goal", "autonomous", "overnight", "continuous"]): return "GOAL"
    if any(k in t for k in ["bug", "fix", "error", "crash", "trace", "fail"]): return "DEBUG"
    if any(k in t for k in ["create", "build", "widget", "feature", "app", "ui", "add"]): return "FEATURE"
    if any(k in t for k in ["plan", "design", "interview", "architecture"]): return "PLAN"
    if any(k in t for k in ["research", "search", "explain", "doc"]): return "RESEARCH"
    return "CLI"

def get_conversations():
    convs = []
    if not BRAIN_DIR.exists():
        return convs
    for item in BRAIN_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            cid = item.name
            title = cid[:8]
            mtime = item.stat().st_mtime
            log_file = item / ".system_generated" / "logs" / "transcript.jsonl"
            if log_file.exists():
                try:
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            d = json.loads(line)
                            if d.get("type") == "USER_INPUT":
                                c = d.get("content", "").strip()
                                c = re.sub(r'<[^>]+>', '', c).strip()
                                if c:
                                    title = c[:50]
                                    break
                except Exception:
                    pass
            dt = datetime.datetime.fromtimestamp(mtime)
            formatted_time = dt.strftime("%Y-%m-%d %H:%M")
            convs.append({
                "id": cid,
                "title": title,
                "mtime": mtime,
                "formatted_time": formatted_time,
                "category": categorize_session(title)
            })
    convs.sort(key=lambda x: x["mtime"], reverse=True)
    return convs

def get_execution_flowchart(conv_id=None):
    nodes = []
    if not conv_id or conv_id == "default" or conv_id == "new":
        all_c = get_conversations()
        if all_c:
            conv_id = all_c[0]["id"]
        else:
            return {"conv_id": None, "nodes": []}

    log_file = BRAIN_DIR / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
    if not log_file.exists():
        return {"conv_id": conv_id, "nodes": []}

    idx = 0
    try:
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line.strip(): continue
                d = json.loads(line)
                t = d.get("type")
                content = d.get("content", "")
                tool_calls = d.get("tool_calls", [])

                if t == "USER_INPUT":
                    clean = re.sub(r'<[^>]+>', '', content).strip()
                    nodes.append({
                        "id": f"node-{idx}",
                        "type": "USER_INTENT",
                        "label": clean[:50] + "..." if len(clean) > 50 else clean,
                        "status": "COMPLETED",
                        "details": clean[:250]
                    })
                    idx += 1
                elif tool_calls:
                    for tc in tool_calls:
                        call_name = tc.get("toolAction") or tc.get("toolSummary") or "Tool Call"
                        nodes.append({
                            "id": f"node-{idx}",
                            "type": "TOOL_CALL",
                            "label": call_name,
                            "status": "DONE",
                            "details": json.dumps(tc.get("arguments", {}), indent=2)
                        })
                        idx += 1
                elif t == "PLANNER_RESPONSE" and content:
                    clean = re.sub(r'<[^>]+>', '', content).strip()
                    if clean and len(clean) > 10:
                        nodes.append({
                            "id": f"node-{idx}",
                            "type": "AGENT_STEP",
                            "label": clean[:45] + "...",
                            "status": "DONE",
                            "details": clean[:300]
                        })
                        idx += 1
    except Exception:
        pass

    if len(nodes) > 25:
        nodes = nodes[-25:]
    return {"conv_id": conv_id, "nodes": nodes}

def get_telemetry():
    all_c = get_conversations()
    host_type = "Windows PC" if IS_WINDOWS else ("Android Termux" if IS_ANDROID else "Linux/macOS Host")
    return {
        "status": "ONLINE",
        "host": host_type,
        "active_pty_sessions": len(active_sessions),
        "total_sessions": len(all_c),
        "agy_cli_binary": get_agy_binary(),
        "python_version": sys.version.split()[0],
        "has_posix_pty": HAS_POSIX_PTY,
        "agents": [
            {"name": "Main Orchestrator", "role": "Planning & Autonomous Control", "status": "ACTIVE"},
            {"name": "Subagent: Coder", "role": "Code Generation & Refactoring", "status": "STANDBY"},
            {"name": "Subagent: Researcher", "role": "Codebase Navigation & Web Search", "status": "STANDBY"},
            {"name": "Subagent: Tester", "role": "Verification & Diagnostics", "status": "STANDBY"}
        ]
    }


# 6. HTTP Handlers
async def homepage(request):
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>AGY Universal Workstation Daemon Online</h1>")

async def api_conversations(request):
    token = request.query_params.get("token", "")
    if token != SECRET_KEY:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse(get_conversations())

async def api_flowchart(request):
    token = request.query_params.get("token", "")
    if token != SECRET_KEY:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    cid = request.query_params.get("conversation", None)
    return JSONResponse(get_execution_flowchart(cid))

async def api_telemetry(request):
    token = request.query_params.get("token", "")
    if token != SECRET_KEY:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse(get_telemetry())

async def upload_file(request):
    token = request.query_params.get("token", "")
    if token != SECRET_KEY:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    form = await request.form()
    file_field = form.get("file")
    if file_field:
        filename = getattr(file_field, "filename", "upload.bin")
        content = await file_field.read()
        dest = UPLOAD_DIR / filename
        with open(dest, "wb") as f:
            f.write(content)
        return JSONResponse({"status": "OK", "saved": str(dest)})
    return JSONResponse({"error": "No file uploaded"}, status_code=400)

async def upload_audio(request):
    token = request.query_params.get("token", "")
    if token != SECRET_KEY:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    form = await request.form()
    file_field = form.get("file")
    if file_field:
        filename = getattr(file_field, "filename", f"voice_{int(datetime.datetime.now().timestamp())}.webm")
        content = await file_field.read()
        dest = AUDIO_DIR / filename
        with open(dest, "wb") as f:
            f.write(content)
        return JSONResponse({"status": "OK", "saved": str(dest)})
    return JSONResponse({"error": "No audio uploaded"}, status_code=400)

# 7. WebSocket Stream Endpoint
async def websocket_endpoint(websocket):
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()

    await websocket.accept()
    token = websocket.query_params.get("token", "")
    if token != SECRET_KEY:
        await websocket.send_text(json.dumps({"type": "output", "data": "\r\n[401] Unauthorized: Invalid PIN\r\n"}))
        await websocket.close()
        return

    conv_id = websocket.query_params.get("conversation", "default")
    session = get_or_create_session(conv_id)
    session.clients.add(websocket)

    # Replay buffer history
    for chunk in list(session.history_buffer):
        await websocket.send_text(json.dumps({"type": "output", "data": chunk}))

    try:
        while True:
            msg_text = await websocket.receive_text()
            try:
                msg = json.loads(msg_text)
                mtype = msg.get("type")
                if mtype == "input":
                    session.write(msg.get("data", ""))
                elif mtype == "resize":
                    session.resize(msg.get("rows", 24), msg.get("cols", 80))
                elif mtype == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except Exception:
                pass
    except Exception:
        pass
    finally:
        session.clients.discard(websocket)

# 8. Routes & Application
routes = [
    Route("/", homepage),
    Route("/api/conversations", api_conversations),
    Route("/api/flowchart", api_flowchart),
    Route("/api/telemetry", api_telemetry),
    Route("/upload", upload_file, methods=["POST"]),
    Route("/upload-audio", upload_audio, methods=["POST"]),
    WebSocketRoute("/ws", websocket_endpoint)
]

app = Starlette(routes=routes)

if __name__ == "__main__":
    print(f">> Starting AGY Universal Origin Daemon on port {PORT}...")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
