import asyncio
import os
import pty
import fcntl
import struct
import termios
import json
import http.server
import socketserver
import threading
import websockets
import re
import urllib.parse
from collections import deque

def load_env(env_path=None):
    if not env_path:
        for p in [os.path.join(os.path.dirname(__file__), ".env"), os.path.join(os.path.dirname(__file__), "..", ".env"), ".env"]:
            if os.path.exists(p):
                env_path = p
                break
    if env_path and os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v

load_env()

HTTP_PORT = int(os.environ.get("AGY_HTTP_PORT", 8080))
WS_PORT = int(os.environ.get("AGY_WS_PORT", 8081))
SECRET_KEY = os.environ.get("AGY_AUTH_PIN", "CHANGE_ME_IN_ENV")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
BRAIN_DIR = os.path.expanduser("~/.gemini/antigravity-cli/brain")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Session manager to keep PTY processes alive across network drops
class PTYSession:
    def __init__(self, conv_id):
        self.conv_id = conv_id
        self.pid = None
        self.master_fd = None
        self.history_buffer = deque(maxlen=2000) # Recent output chunks for instant re-attach
        self.clients = set()
        self.lock = asyncio.Lock()
        self.reader_task = None
        self.spawn_process()

    def spawn_process(self):
        pid, master_fd = pty.fork()
        if pid == 0:
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["COLORTERM"] = "truecolor"
            os.chdir(env.get("HOME", "/data/data/com.termux/files/home"))

            agy_path = "/data/data/com.termux/files/usr/bin/agy"
            if os.path.exists(agy_path):
                if self.conv_id and self.conv_id != "new":
                    os.execvpe(agy_path, [agy_path, "--conversation", self.conv_id], env)
                else:
                    os.execvpe(agy_path, [agy_path], env)
            else:
                os.execvpe("/data/data/com.termux/files/usr/bin/bash", ["bash"], env)
            os._exit(1)

        self.pid = pid
        self.master_fd = master_fd
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def write_input(self, data):
        if self.master_fd:
            try:
                os.write(self.master_fd, data.encode("utf-8"))
            except OSError:
                pass

    def resize(self, rows, cols):
        if self.master_fd:
            try:
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except Exception:
                pass

    def start_reader(self, loop):
        async def pty_reader():
            while True:
                try:
                    data = await loop.run_in_executor(None, lambda: os.read(self.master_fd, 4096))
                    if not data:
                        break
                    text = data.decode("utf-8", errors="replace")
                    self.history_buffer.append(text)
                    
                    # Broadcast to any connected websocket clients
                    dead_clients = set()
                    for ws in list(self.clients):
                        try:
                            await ws.send(json.dumps({"type": "output", "data": text}))
                        except Exception:
                            dead_clients.add(ws)
                    self.clients.difference_update(dead_clients)
                except (OSError, BlockingIOError):
                    await asyncio.sleep(0.01)
                except Exception:
                    break

        self.reader_task = asyncio.create_task(pty_reader())

    def destroy(self):
        if self.reader_task:
            self.reader_task.cancel()
        if self.master_fd:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
        if self.pid:
            try:
                os.kill(self.pid, 9)
                os.waitpid(self.pid, 0)
            except OSError:
                pass

# Global map: conv_key -> PTYSession
active_sessions = {}
sessions_lock = None

def categorize_session(title):
    t = title.lower()
    if any(k in t for k in ["goal", "autonomous", "overnight", "continuous"]):
        return "GOAL"
    if any(k in t for k in ["bug", "fix", "error", "crash", "trace", "fail"]):
        return "DEBUG"
    if any(k in t for k in ["create", "build", "widget", "feature", "app", "ui", "add"]):
        return "FEATURE"
    if any(k in t for k in ["plan", "design", "interview", "architecture"]):
        return "PLAN"
    if any(k in t for k in ["research", "search", "explain", "doc"]):
        return "RESEARCH"
    return "CLI"

def get_conversations():
    convs = []
    if not os.path.isdir(BRAIN_DIR):
        return convs
    
    for cid in os.listdir(BRAIN_DIR):
        cpath = os.path.join(BRAIN_DIR, cid)
        if not os.path.isdir(cpath) or cid.startswith('.'):
            continue
        log_file = os.path.join(cpath, ".system_generated", "logs", "transcript.jsonl")
        title = "Session " + cid[:8]
        mtime = os.path.getmtime(cpath)
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        data = json.loads(line)
                        if data.get("type") == "USER_INPUT":
                            raw = data.get("content", "").strip()
                            clean = re.sub(r'<[^>]+>', '', raw).strip()
                            if clean:
                                title = clean[:60].replace("\n", " ")
                                break
            except Exception:
                pass
        dt = datetime.datetime.fromtimestamp(mtime)
        formatted_time = dt.strftime("%Y-%m-%d %H:%M")
        convs.append({"id": cid, "title": title, "mtime": mtime, "formatted_time": formatted_time, "category": categorize_session(title)})

    convs.sort(key=lambda x: x["mtime"], reverse=True)
    return convs

class CustomHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/conversations":
            query = urllib.parse.parse_qs(parsed.query)
            token = query.get("token", [""])[0]
            if token != SECRET_KEY:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Unauthorized"}')
                return

            convs = get_conversations()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(convs).encode("utf-8"))
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/upload":
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("multipart/form-data"):
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Expected multipart/form-data"}')
                return

            try:
                content_length = int(self.headers.get('Content-Length', 0))
                boundary = content_type.split("boundary=")[1].strip()
                if ";" in boundary:
                    boundary = boundary.split(";")[0].strip()
                boundary_bytes = boundary.encode("utf-8")

                body = self.rfile.read(content_length)
                delimiter = b"--" + boundary_bytes
                parts = body.split(delimiter)
                uploaded_files = []

                for part in parts:
                    if b'filename="' in part:
                        header_part, content_part = part.split(b"\r\n\r\n", 1)
                        if content_part.endswith(b"\r\n"):
                            content_part = content_part[:-2]

                        headers_text = header_part.decode('utf-8', errors='replace')
                        fname = "uploaded_file"
                        for line in headers_text.splitlines():
                            if 'filename="' in line:
                                fname = line.split('filename="')[1].split('"')[0]
                                fname = os.path.basename(fname)

                        saved_path = os.path.join(UPLOAD_DIR, fname)
                        with open(saved_path, "wb") as f:
                            f.write(content_part)
                        uploaded_files.append(saved_path)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response_data = {"success": True, "files": uploaded_files}
                self.wfile.write(json.dumps(response_data).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

def start_http_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", HTTP_PORT), CustomHTTPHandler) as httpd:
        httpd.serve_forever()

async def handle_ws(websocket):
    # Verify auth token
    path = websocket.request.path if hasattr(websocket, 'request') else websocket.path
    parsed = urllib.parse.urlparse(path)
    params = urllib.parse.parse_qs(parsed.query)
    token = params.get("token", [""])[0]

    if token != SECRET_KEY:
        await websocket.close(4001, "Unauthorized")
        return

    conv_id = params.get("conversation", ["default"])[0]
    if not conv_id:
        conv_id = "default"

    loop = asyncio.get_running_loop()

    # Get or create persistent session
    async with sessions_lock:
        if conv_id not in active_sessions:
            sess = PTYSession(conv_id)
            sess.start_reader(loop)
            active_sessions[conv_id] = sess
        else:
            sess = active_sessions[conv_id]

    sess.clients.add(websocket)

    # Immediately replay recent output history to client on reconnect
    if sess.history_buffer:
        joined_history = "".join(sess.history_buffer)
        await websocket.send(json.dumps({"type": "history", "data": joined_history}))

    try:
        async for msg_str in websocket:
            try:
                msg = json.loads(msg_str)
                mtype = msg.get("type")
                if mtype == "input":
                    sess.write_input(msg.get("data", ""))
                elif mtype == "resize":
                    sess.resize(msg.get("rows", 24), msg.get("cols", 80))
                elif mtype == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
            except Exception:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        sess.clients.discard(websocket)

async def main():
    global sessions_lock
    sessions_lock = asyncio.Lock()

    t = threading.Thread(target=start_http_server, daemon=True)
    t.start()

    # Ping interval and ping timeout keep Cloudflare and cellular sockets alive
    async with websockets.serve(
        handle_ws,
        "0.0.0.0",
        WS_PORT,
        ping_interval=15,
        ping_timeout=20,
        max_size=10_000_000
    ):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
