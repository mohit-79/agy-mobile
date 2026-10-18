import io
import json
import os
import platform
import re
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

# Resilient DNS fallback for Cloudflare domains
_orig_getaddrinfo = socket.getaddrinfo


def _resilient_getaddrinfo(host, p, *args, **kwargs):
    if "harjani.me" in str(host):
        try:
            return _orig_getaddrinfo(host, p, *args, **kwargs)
        except Exception:
            return _orig_getaddrinfo("104.21.3.143", p, *args, **kwargs)
    return _orig_getaddrinfo(host, p, *args, **kwargs)


socket.getaddrinfo = _resilient_getaddrinfo

# 1. Environment & Platform Detection
IS_WINDOWS = sys.platform.startswith("win")
IS_ANDROID = "TERMUX_VERSION" in os.environ or "ANDROID_ROOT" in os.environ

if IS_WINDOWS:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

# 2. Universal Directory Paths
BASE_DIR = Path(__file__).resolve().parent

# 3. Load Minimal Configurations from .env
pin = "29105"
port = 8090
gateway_url = None

for env_candidate in [BASE_DIR / ".env", Path(".env")]:
    if env_candidate.exists():
        with open(env_candidate, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k == "AGY_AUTH_PIN":
                        pin = v
                    elif k in ["PORT", "AGY_PORT", "AGY_HTTP_PORT"]:
                        try:
                            port = int(v)
                        except ValueError:
                            pass
                    elif k == "AGY_GATEWAY_URL":
                        gateway_url = v
                    elif k == "AGY_DOMAIN" and not gateway_url:
                        gateway_url = f"https://{v}"
        break

if not gateway_url and os.environ.get("AGY_GATEWAY_URL"):
    gateway_url = os.environ.get("AGY_GATEWAY_URL")

ssl_ctx = ssl.create_default_context()


# 4. Universal Cloudflared Binary Locator & Auto-Downloader
def locate_cloudflared():
    found = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
    if found:
        return str(found)

    candidates = []
    if IS_WINDOWS:
        candidates.extend([
            Path.home() / "OneDrive" / "Desktop" / "tasker" / "cloudflared.exe",
            Path.home() / "Desktop" / "tasker" / "cloudflared.exe",
            Path.home() / "AppData" / "Local" / "cloudflared" / "cloudflared.exe",
            BASE_DIR / "cloudflared.exe",
        ])
    elif IS_ANDROID:
        candidates.extend([
            Path("/data/data/com.termux/files/usr/bin/cloudflared"),
            Path("/data/data/com.termux/files/home/cloudflared"),
            Path.home() / "bin" / "cloudflared",
        ])
    else:
        candidates.extend([
            Path("/usr/local/bin/cloudflared"),
            Path("/usr/bin/cloudflared"),
            Path.home() / "bin" / "cloudflared",
        ])

    for c in candidates:
        if c.exists() and os.access(str(c), os.X_OK if not IS_WINDOWS else os.R_OK):
            return str(c)

    return None


def ensure_cloudflared():
    cf_path = locate_cloudflared()
    if cf_path:
        return cf_path

    print("[*] cloudflared not found in PATH or standard paths. Fetching standalone binary...")
    bin_dir = Path.home() / ".cloudflared_bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    arch = platform.machine().lower()
    if IS_WINDOWS:
        dest = bin_dir / "cloudflared.exe"
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    elif IS_ANDROID or "aarch64" in arch or "arm64" in arch:
        dest = bin_dir / "cloudflared"
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
    else:
        dest = bin_dir / "cloudflared"
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"

    if dest.exists():
        return str(dest)

    try:
        print(f"[*] Downloading cloudflared from {url}...")
        urllib.request.urlretrieve(url, dest)
        if not IS_WINDOWS:
            dest.chmod(0o755)
        print(f"[+] Installed cloudflared to {dest}")
        return str(dest)
    except Exception as e:
        print(f"[!] Could not download cloudflared automatically ({e}). Falling back to 'cloudflared' command.")
        return "cloudflared"


# 5. Safe Port Conflict Resolver
def clean_existing_port(p):
    if IS_WINDOWS:
        try:
            res = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                if f":{p} " in line and "LISTENING" in line:
                    parts = line.strip().split()
                    if parts:
                        target_pid = parts[-1]
                        if target_pid.isdigit() and int(target_pid) != os.getpid():
                            subprocess.run(["taskkill", "/F", "/PID", target_pid], capture_output=True)
                            print(f"[CLEANUP] Freed port {p} (terminated PID {target_pid})")
        except Exception:
            pass
    else:
        try:
            res = subprocess.run(["lsof", "-t", f"-i:{p}"], capture_output=True, text=True)
            for pid_str in res.stdout.strip().split():
                if pid_str.isdigit() and int(pid_str) != os.getpid():
                    os.kill(int(pid_str), signal.SIGKILL)
                    print(f"[CLEANUP] Freed port {p} (terminated PID {pid_str})")
        except Exception:
            pass
        try:
            subprocess.run(["fuser", "-k", f"{p}/tcp"], capture_output=True)
        except Exception:
            pass



# 6. Edge Gateway Registration
def register_tunnel(target_gw, tunnel_url):
    if not target_gw:
        return False
    payload = json.dumps({"url": tunnel_url, "pin": pin}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-auth-pin": pin,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }
    req = urllib.request.Request(f"{target_gw}/api/tunnel-url", data=payload, headers=headers)
    for _attempt in range(5):
        try:
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("success"):
                    return True
        except Exception:
            time.sleep(1)
    return False


# 7. Main Engine Supervisor Flow
def main():
    platform_label = "Windows PC" if IS_WINDOWS else ("Android Termux" if IS_ANDROID else "Linux/macOS Host")
    cf_bin = ensure_cloudflared()

    print("==================================================================")
    print(">> REAGY Universal Engine // Cross-Platform Bridge Online")
    print(f"   Platform:        {platform_label}")
    if gateway_url:
        print(f"   Public Gateway:  {gateway_url}")
    print(f"   Local Host:      http://127.0.0.1:{port}")
    print(f"   cloudflared:     {cf_bin}")
    print("==================================================================")

    # 1. Clean port collisions
    clean_existing_port(port)

    # 2. Launch Universal Server
    server_script = BASE_DIR / "server.py"

    print(f"[1/4] Launching server daemon on port {port}...")
    server_env = os.environ.copy()
    server_env["PORT"] = str(port)
    server_env["AGY_HTTP_PORT"] = str(port)
    server_proc = subprocess.Popen(
        [sys.executable, str(server_script)],
        cwd=str(BASE_DIR),
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


    server_log_path = BASE_DIR / "server.log"
    cf_log_path = BASE_DIR / "cloudflared.log"

    def drain_server(proc):
        with open(server_log_path, "a", encoding="utf-8") as f:
            for line in proc.stdout:
                f.write(line)
                f.flush()

    def drain_cf(proc):
        with open(cf_log_path, "a", encoding="utf-8") as f:
            for line in proc.stdout:
                f.write(line)
                f.flush()

    threading.Thread(target=drain_server, args=(server_proc,), daemon=True).start()

    # 3. Healthcheck Server
    print("[2/4] Verifying origin server health...")
    server_ready = False
    for _ in range(15):
        time.sleep(0.5)
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/telemetry?token={pin}")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    server_ready = True
                    break
        except Exception:
            pass

    if not server_ready:
        print("[!] Error: Local origin daemon failed to respond.")
        if server_proc.poll() is not None:
            print(f"Server exited with code: {server_proc.returncode}")
        server_proc.kill()
        sys.exit(1)

    print("[+] Origin server listening and healthy.")

    # 4. Launch Cloudflare Quick Tunnel
    print(f"[3/4] Starting Cloudflare Quick Tunnel to http://127.0.0.1:{port}...")
    cf_proc = subprocess.Popen(
        [cf_bin, "tunnel", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    tunnel_url = None
    start_t = time.time()
    while time.time() - start_t < 25:
        line = cf_proc.stdout.readline()
        if not line:
            if cf_proc.poll() is not None:
                break
            time.sleep(0.1)
            continue
        m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
        if m:
            tunnel_url = m.group(0)
            break

    if not tunnel_url:
        print("[!] Error: Failed to acquire Cloudflare quick tunnel URL.")
        server_proc.kill()
        cf_proc.kill()
        sys.exit(1)

    print(f"[+] Quick Tunnel online: {tunnel_url}")
    threading.Thread(target=drain_cf, args=(cf_proc,), daemon=True).start()

    # 5. Register with Cloudflare Edge Gateway if configured
    registered_gateway = False
    if gateway_url:
        print(f"[4/4] Registering tunnel with Edge Gateway {gateway_url}...")
        if register_tunnel(gateway_url, tunnel_url):
            print("[+] Edge Gateway successfully synchronized!")
            registered_gateway = True
        else:
            print("[!] Edge Gateway registration timed out. Will keep trying in background.")
    else:
        print("[4/4] Ready! (No AGY_GATEWAY_URL configured, using direct tunnel URL).")

    primary_url = gateway_url if (registered_gateway and gateway_url) else tunnel_url
    web_access_url = f"{primary_url}?pin={pin}"

    print("\n" + "=" * 66)
    print(">> REAGY WORKSTATION & COCKPIT IS FULLY ACCESSIBLE!")
    if gateway_url:
        print(f"   Public Edge Gateway:  {gateway_url}")
    print(f"   Cloudflare Tunnel:    {tunnel_url}")
    print(f"   Local Direct Host:    http://127.0.0.1:{port}")
    print(f"   Master PIN:           {pin}")
    print(f"   Direct 1-Click Link:  {web_access_url}")
    print("   Auto-healing supervisor loop ACTIVE (24/7 continuous uptime).")
    print("=" * 66 + "\n")

    # Auto-open browser on desktop if available
    if not IS_ANDROID:
        try:
            webbrowser.open_new_tab(web_access_url)
        except Exception:
            pass

    def handle_sig(sig, frame):
        print("\n[SHUTDOWN] Stopping processes...")
        try:
            cf_proc.terminate()
        except Exception:
            pass
        try:
            server_proc.terminate()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    try:
        while True:
            time.sleep(2)

            # Supervise local origin server
            if server_proc.poll() is not None:
                print(f"[SUPERVISOR] Local server exited (code {server_proc.returncode}). Checking log...")
                if server_log_path.exists():
                    tail = server_log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]
                    for log_line in tail:
                        print(f"  [SERVER LOG] {log_line}")
                print("[SUPERVISOR] Auto-restarting local server...")
                clean_existing_port(port)
                time.sleep(1)
                server_proc = subprocess.Popen(
                    [sys.executable, str(server_script)],
                    cwd=str(BASE_DIR),
                    env=server_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                threading.Thread(target=drain_server, args=(server_proc,), daemon=True).start()
                time.sleep(2)


            # Supervise Cloudflare quick tunnel
            if cf_proc.poll() is not None:
                print(f"[SUPERVISOR] Cloudflare tunnel exited (code {cf_proc.returncode}). Auto-restarting tunnel...")
                cf_proc = subprocess.Popen(
                    [cf_bin, "tunnel", "--url", f"http://127.0.0.1:{port}"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                new_tunnel = None
                start_c = time.time()
                while time.time() - start_c < 25:
                    line = cf_proc.stdout.readline()
                    if not line:
                        if cf_proc.poll() is not None:
                            break
                        time.sleep(0.1)
                        continue
                    m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                    if m:
                        new_tunnel = m.group(0)
                        break
                if new_tunnel:
                    tunnel_url = new_tunnel
                    print(f"[SUPERVISOR] New tunnel online: {tunnel_url}. Re-synchronizing...")
                    if gateway_url:
                        register_tunnel(gateway_url, tunnel_url)
                threading.Thread(target=drain_cf, args=(cf_proc,), daemon=True).start()
    except KeyboardInterrupt:
        handle_sig(None, None)


if __name__ == "__main__":
    main()
