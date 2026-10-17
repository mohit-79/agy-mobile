# 🚀 AGY 2.0 // Universal Autonomous Agent Cockpit

A high-performance, cross-platform mobile & desktop cockpit for **Google Antigravity (AGY)**. Operates seamlessly on **Windows PC**, **Android (Termux)**, **Linux**, and **macOS**, optionally secured by Cloudflare Zero-Trust Edge Gatekeepers.

---

## ⚡ Quick Start (Zero-Friction 1-Click Setup)

### 🪟 On Windows PC
1. Clone repository:
   ```cmd
   git clone https://github.com/mohit-79/agy-mobile.git
   cd agy-mobile
   ```
2. Double-click **`start.bat`** (or run `start.bat` in Command Prompt / PowerShell).
   - *Auto-initializes configuration (`.env`).*
   - *Auto-installs required Python packages (`requirements.txt`).*
   - *Auto-locates or downloads standalone `cloudflared`.*
   - *Spawns the local daemon, opens Cloudflare Quick Tunnel, and launches your browser directly into the Cockpit!*

---

### 📱 On Android (Termux)
1. Install Termux prerequisites and clone repository:
   ```bash
   pkg update -y && pkg install -y git python python-pip
   git clone https://github.com/mohit-79/agy-mobile.git
   cd agy-mobile
   ```
2. Run universal setup:
   ```bash
   chmod +x start.sh install.sh
   ./start.sh
   ```
3. *(Optional)* **1-Tap Widget Shortcut**:
   Run `bash launcher/install-widget.sh` to install the `AGY` widget into `~/.shortcuts/` for instant home screen launch.

---

### 🐧 On Linux / macOS
```bash
git clone https://github.com/mohit-79/agy-mobile.git
cd agy-mobile
chmod +x start.sh
./start.sh
```

---

## 🏗️ Architecture Blueprint

```
                           [ Client Browser / Mobile / Desktop ]
                                             │
                                             ▼
                          [ Cloudflare Edge Gatekeeper Worker ]
                           (Zero-Trust PIN & Session Cookie)
                                             │
                                             ▼
                                 [ Cloudflare Quick Tunnel ]
                                (*.trycloudflare.com / Named)
                                             │
                         ┌───────────────────┴───────────────────┐
                         │                                       │
                    (HTTP :8090)                            (WS :8090)
                         │                                       │
                         ▼                                       ▼
             [ Starlette Universal Router ]           [ Shell / PTY Manager ]
               ├── / (Cockpit Interface)                ├── Windows: PowerShell UTF-8
               ├── /api/conversations                   └── Linux/Termux: POSIX PTY
               ├── /api/flowchart (DAG Nodes)           └── agy CLI Orchestrator
               ├── /api/telemetry
               └── /upload & /upload-audio
```

---

## 🌟 Core Features

- **Single-Port Architecture**: HTTP, WebSockets (`/ws`), file uploads, and audio streaming all share a single port (default: `8090`), eliminating port collisions and simplifying ingress routing.
- **Cross-Platform Engine**:
  - **Windows**: Interactive piped session using UTF-8 PowerShell or `cmd.exe` with direct access to `agy.exe`.
  - **Linux / Termux / macOS**: Native pseudo-terminal (`pty.fork()`) with true ANSI color streaming.
- **Zero-Config Cloudflare Quick Tunnel**: Automatically opens an HTTPS tunnel with zero Cloudflare account or tunnel credentials required.
- **Optional Zero-Trust Edge Gateway (`cloudflare/edge-gateway`)**: Secure your workstation or phone behind a Cloudflare Edge Worker with master PIN lock and automatic dynamic tunnel synchronization (`/api/tunnel-url`).
- **Real-Time Execution Flowchart**: Live visual DAG parsing sub-agents, tool executions, and user intents straight from `transcript.jsonl`.
- **Touch & Desktop Hybrid Input**: Virtual modifier keys (Ctrl, Shift, Tab) with latching states, full hardware keyboard passthrough, and dismissible file attachment chips.
- **Voice Instruction Streaming**: Built-in HTML5 `MediaRecorder` audio capture streaming voice instructions directly to the agent.
- **Self-Healing Supervisor**: Continuously monitors the local origin server and tunnel process; auto-restarts and re-synchronizes on network disconnects.

---

## ⚙️ Configuration (`.env`)

Copy `.env.example` to `.env` to customize settings:

```env
# Master Unlock PIN
AGY_AUTH_PIN=29105

# Local Origin Port
PORT=8090

# Optional: Cloudflare Edge Gateway URL (start.py auto-syncs its tunnel here)
AGY_GATEWAY_URL=https://agypc.harjani.me
```

---

## 🌐 Deploying the Zero-Trust Edge Gateway (Cloudflare Worker)

If you want a permanent custom domain (e.g. `https://agypc.yourdomain.com` or `https://agy.yourdomain.com`):

1. Enter gateway directory:
   ```bash
   cd cloudflare/edge-gateway
   ```
2. Create a Cloudflare KV namespace for dynamic tunnel registration:
   ```bash
   npx wrangler kv:namespace create TUNNEL_KV
   ```
3. Update `wrangler.toml` with the generated KV ID.
4. Deploy the worker:
   ```bash
   npx wrangler deploy
   ```
5. Set `AGY_GATEWAY_URL=https://your-worker-domain.com` in `.env`.
   Whenever `start.bat` or `./start.sh` launches on your PC or phone, it will automatically register its active tunnel with your Cloudflare Worker!

---

## 📁 Repository Structure

```
agy-mobile/
├── .env.example                # Public environment configuration template
├── .gitignore                  # Ignores local secrets and logs
├── requirements.txt            # Python dependencies (starlette, uvicorn, multipart, websockets)
├── start.bat                   # 1-Click Windows launcher & auto-installer
├── start.sh                    # 1-Click Linux / macOS / Termux launcher
├── start.py                    # Universal Cross-Platform Supervisor Engine
├── install.sh                  # Automated system setup script
├── agy-mobile.sh               # Root convenience launcher
├── agy-mobile-app/             # Origin Backend & Cockpit Assets
│   ├── server.py               # Starlette + Uvicorn universal server
│   ├── requirements.txt        # Local requirements mirror
│   ├── static/
│   │   └── index.html          # Cockpit 2.0 interface & xterm.js terminal
│   ├── audio/                  # Audio input streaming buffer
│   └── uploads/                # File attachments buffer
├── launcher/                   # Mobile launcher suite
│   ├── agy-mobile.sh           # Termux:Widget background launcher
│   └── install-widget.sh       # Widget setup script
├── cloudflare/
│   ├── edge-gateway/           # Zero-Trust Cloudflare Worker Gateway
│   │   ├── wrangler.toml
│   │   ├── package.json
│   │   └── src/index.js
│   └── share-bridge/           # Universal file sharing bridge
└── README.md                   # Full documentation
```
