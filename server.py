import datetime
import os
import re
import shutil
import sys
import threading
import asyncio
from pathlib import Path

# 1. Detect Host OS
IS_WINDOWS = sys.platform.startswith("win")
IS_ANDROID = "TERMUX_VERSION" in os.environ or "ANDROID_ROOT" in os.environ

# Try importing native Windows ConPTY (pywinpty)
try:
    from winpty import PtyProcess
    HAS_WINPTY = True
except ImportError:
    HAS_WINPTY = False

# Try importing POSIX pty (Only available on Linux / Android Termux / macOS)
try:
    import pty
    import select
    HAS_POSIX_PTY = True
except ImportError:
    HAS_POSIX_PTY = False

from collections import deque
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route, WebSocketRoute
import uvicorn
import json

# Global Session Registry for Surviving Reloads & Disconnects
active_sessions = {}
main_event_loop = None

# 2. Lightweight .env Configuration Loader (Zero extra dependencies)
ENV_FILE = Path(__file__).resolve().parent / ".env"

def load_env():
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")

load_env()
AUTH_PIN = os.environ.get("AGY_AUTH_PIN", "29105")
PORT = int(os.environ.get("AGY_HTTP_PORT") or os.environ.get("PORT") or "8090")


# ------------------------------------------------------------------------------
# 2. Cross-Platform Terminal Session Abstractions
# ------------------------------------------------------------------------------

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


class WindowsConPtySession:
    """
    Native Windows ConPTY via pywinpty.
    Spawns interactive PowerShell and automatically connects to Antigravity CLI.
    """
    def __init__(self, conv_id="default"):
        self.conv_id = conv_id
        self.clients = set()
        self.history_buffer = deque(maxlen=2000)
        
        agy_bin = get_agy_binary()
        if conv_id and conv_id not in ("default", "new"):
            agy_cmd = f"{agy_bin} --conversation {conv_id}"
        else:
            agy_cmd = f"{agy_bin} --continue"

        try:
            print(f"[*] WindowsConPty: Spawning AGY session: {agy_cmd}")
            self.pty = PtyProcess.spawn(agy_cmd)
        except Exception as e:
            print(f"[!] WindowsConPty: Failed to spawn '{agy_cmd}': {e}. Falling back to powershell.")
            self.pty = PtyProcess.spawn("powershell.exe -NoLogo")
        self.alive = True
        self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.reader_thread.start()

    def _read_loop(self):
        while self.alive and self.pty.isalive():
            try:
                data = self.pty.read(1024)
                if data:
                    self.history_buffer.append(data)
                    if main_event_loop and self.clients:
                        for ws in list(self.clients):
                            try:
                                asyncio.run_coroutine_threadsafe(ws.send_text(data), main_event_loop)
                            except Exception:
                                pass
                else:
                    break
            except Exception:
                break
        self.alive = False

    def write(self, data: str):
        if self.alive and self.pty.isalive():
            try:
                self.pty.write(data)
            except Exception:
                self.alive = False

    def resize(self, cols: int, rows: int):
        if self.alive and self.pty.isalive():
            try:
                self.pty.setwinsize(rows, cols)
            except Exception:
                pass

    def is_alive(self):
        return self.alive and self.pty.isalive()

    def close(self):
        self.alive = False
        try:
            self.pty.terminate()
        except Exception:
            pass


class PosixPtySession:
    """
    Linux / Termux / macOS native pseudo-terminal.
    pty.fork() connects child process (bash) to a virtual terminal device.
    Maintains persistent clients set and circular scrollback history buffer.
    """
    def __init__(self, conv_id="default"):
        self.conv_id = conv_id
        self.clients = set()
        shell_cmd = os.environ.get("BASH_PATH") or ("/data/data/com.termux/files/usr/bin/bash" if IS_ANDROID and os.path.exists("/data/data/com.termux/files/usr/bin/bash") else os.environ.get("SHELL", "/bin/bash"))
        
        agy_bin = get_agy_binary()

        if conv_id and conv_id not in ("default", "new"):
            agy_flag = f"--conversation {conv_id}"
        else:
            agy_flag = "--continue"
        
        pid, fd = pty.fork()
        if pid == 0:
            os.environ["TERM"] = "xterm-256color"
            os.environ["COLORTERM"] = "truecolor"
            cmd = f"echo '>> REAGY // Antigravity Terminal Online'; {agy_bin} {agy_flag} || exec {shell_cmd} -l"
            os.execv(shell_cmd, [shell_cmd, "-c", cmd])
        else:
            self.pid = pid
            self.fd = fd
            self.alive = True
            self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.reader_thread.start()

    def _read_loop(self):
        while self.alive:
            try:
                r, _, _ = select.select([self.fd], [], [], 0.1)
                if self.fd in r:
                    data = os.read(self.fd, 2048)
                    if not data:
                        break
                    text = data.decode("utf-8", errors="replace")
                    self.history_buffer.append(text)
                    if main_event_loop and self.clients:
                        for ws in list(self.clients):
                            try:
                                asyncio.run_coroutine_threadsafe(ws.send_text(text), main_event_loop)
                            except Exception:
                                pass
            except Exception:
                break
        self.alive = False

    def write(self, data: str):
        if self.alive:
            try:
                os.write(self.fd, data.encode("utf-8", errors="replace"))
            except Exception:
                self.alive = False

    def resize(self, cols: int, rows: int):
        if HAS_POSIX_PTY and self.fd:
            try:
                import struct
                import fcntl
                import termios
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
            except Exception:
                pass

    def is_alive(self):
        return self.alive

    def close(self):
        self.alive = False
        try:
            os.close(self.fd)
            os.kill(self.pid, 9)
        except Exception:
            pass


def get_or_create_session(conv_id="default"):
    """Fetches an existing running session or spawns a new one if not running."""
    session = active_sessions.get(conv_id)
    if not session or not session.is_alive():
        if IS_WINDOWS and HAS_WINPTY:
            session = WindowsConPtySession(conv_id)
        else:
            session = PosixPtySession(conv_id)
        active_sessions[conv_id] = session
    return session

from flow_agent import categorize_prompt, clean_xml_tags, generate_flow_markdown, parse_transcript_to_steps

# 3. Antigravity Brain Directory (Zero Hardcoding)
BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"

def get_conversations():
    """Reads conversation sessions directly from ~/.gemini/antigravity-cli/brain/"""
    convs = []
    if not BRAIN_DIR.exists():
        return convs
    for item in BRAIN_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            cid = item.name
            title = cid[:8]
            category = "CLI"
            mtime = item.stat().st_mtime
            log_file = item / ".system_generated" / "logs" / "transcript.jsonl"
            if log_file.exists():
                try:
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            d = json.loads(line)
                            if d.get("type") == "USER_INPUT":
                                raw_c = d.get("content", "").strip()
                                c = clean_xml_tags(raw_c)
                                if c:
                                    title = c[:50]
                                    category = categorize_prompt(c)
                                    break
                except Exception:
                    pass
            dt = datetime.datetime.fromtimestamp(mtime)
            formatted_time = dt.strftime("%Y-%m-%d %H:%M")
            convs.append({
                "id": cid,
                "title": title,
                "category": category,
                "mtime": mtime,
                "formatted_time": formatted_time
            })
    convs.sort(key=lambda x: x["mtime"], reverse=True)
    return convs

def get_execution_flowchart(conv_id=None):
    """Parses transcript.jsonl into real-time DAG nodes for visual rendering"""
    nodes = []
    if not conv_id or conv_id in ("default", "new"):
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
                if not line.strip():
                    continue
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
        "total_sessions": len(all_c),
        "python_version": sys.version.split()[0],
        "has_winpty": HAS_WINPTY,
        "has_posix_pty": HAS_POSIX_PTY
    }

# ------------------------------------------------------------------------------
# 4. HTTP & WebSocket Endpoints
# ------------------------------------------------------------------------------

INDEX_HTML_PATH = Path(__file__).resolve().parent / "index.html"

async def serve_index(request):
    if INDEX_HTML_PATH.exists():
        return HTMLResponse(INDEX_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>index.html missing</h1>", status_code=404)

async def api_verify_pin(request):
    token = request.query_params.get("token") or request.query_params.get("pin")
    if token == AUTH_PIN:
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "Invalid PIN"}, status_code=401)

async def api_conversations(request):
    token = request.query_params.get("token") or request.query_params.get("pin")
    if token != AUTH_PIN:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse(get_conversations())

async def api_telemetry(request):
    token = request.query_params.get("token") or request.query_params.get("pin")
    if token != AUTH_PIN:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse(get_telemetry())

async def api_flowchart(request):
    token = request.query_params.get("token") or request.query_params.get("pin")
    if token != AUTH_PIN:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    cid = request.query_params.get("id") or request.query_params.get("conversation")
    return JSONResponse(get_execution_flowchart(cid))

async def api_flow_steps(request):
    token = request.query_params.get("token") or request.query_params.get("pin")
    if token != AUTH_PIN:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    cid = request.query_params.get("id") or request.query_params.get("conversation")
    if not cid or cid in ("default", "new"):
        all_c = get_conversations()
        cid = all_c[0]["id"] if all_c else "default"
    steps = parse_transcript_to_steps(cid)
    return JSONResponse({"conv_id": cid, "steps": steps})

async def api_flow_markdown(request):
    token = request.query_params.get("token") or request.query_params.get("pin")
    if token != AUTH_PIN:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    cid = request.query_params.get("id") or request.query_params.get("conversation")
    if not cid or cid in ("default", "new"):
        all_c = get_conversations()
        cid = all_c[0]["id"] if all_c else "default"
    md = generate_flow_markdown(cid)
    return JSONResponse({"conv_id": cid, "markdown": md})

async def ws_terminal(websocket):
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()

    # Verify PIN token from query parameter: /ws?token=29105
    client_token = websocket.query_params.get("token") or websocket.query_params.get("pin")
    if client_token != AUTH_PIN:
        await websocket.close(code=4001)
        return

    await websocket.accept()

    conv_id = websocket.query_params.get("conversation") or websocket.query_params.get("conv_id") or "default"
    session = get_or_create_session(conv_id)
    session.clients.add(websocket)

    # Replay scrollback history buffer so terminal survives reloads and network reconnects
    for chunk in list(session.history_buffer):
        try:
            await websocket.send_text(chunk)
        except Exception:
            break

    try:
        while True:
            raw_msg = await websocket.receive_text()
            # Support both direct text and structured JSON {type: "input"|"resize", data: ...}
            if raw_msg.startswith("{") and raw_msg.endswith("}"):
                try:
                    payload = json.loads(raw_msg)
                    msg_type = payload.get("type")
                    if msg_type == "input":
                        session.write(payload.get("data", ""))
                    elif msg_type == "resize":
                        if hasattr(session, "resize"):
                            session.resize(payload.get("cols", 80), payload.get("rows", 24))
                    elif msg_type == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                    continue
                except Exception:
                    pass
            session.write(raw_msg)
    except Exception:
        pass
    finally:
        session.clients.discard(websocket)

app = Starlette(
    routes=[
        Route("/", endpoint=serve_index),
        Route("/api/verify-pin", endpoint=api_verify_pin),
        Route("/api/conversations", endpoint=api_conversations),
        Route("/api/telemetry", endpoint=api_telemetry),
        Route("/api/flowchart", endpoint=api_flowchart),
        Route("/api/flow-steps", endpoint=api_flow_steps),
        Route("/api/flow-markdown", endpoint=api_flow_markdown),
        WebSocketRoute("/ws", endpoint=ws_terminal),
    ]
)

if __name__ == "__main__":
    print(f"[*] Starting REAGY Bare Minimum Shell Bridge on http://127.0.0.1:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
